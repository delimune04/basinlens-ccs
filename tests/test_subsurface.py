"""Project contracts and actual adapter behavior; unavailable physics fails closed."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.groundwater import demo_case, verify_bundle
from basinlens_ccs.subsurface import (DataAsset, EngineAvailability, EngineDescriptor,
    EngineUnavailableError, FieldSupport,
    ProjectValidationError, Quantity, RockProperty, SubsurfaceProject,
    UnsupportedPhysicsError, default_registry, load_project, project_from_groundwater,
    save_project, verify_assets, verify_project_bundle)

FLOPY = importlib.util.find_spec("flopy") is not None
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


class SubsurfaceContractTests(unittest.TestCase):
    def setUp(self):
        self.project = project_from_groundwater(demo_case(), domain="ccs")
        self.registry = default_registry()

    def changed(self, change):
        data = copy.deepcopy(self.project.to_dict())
        change(data)
        return SubsurfaceProject.from_dict(data)

    def test_deterministic_serialization_and_immutable_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_project(self.project, Path(tmp) / "project.json")
            loaded = load_project(path)
            self.assertEqual(loaded, self.project)
            self.assertEqual(path.read_bytes(), loaded.to_json().encode("utf-8"))
            self.assertEqual(loaded.model.role, "background_water")
            with self.assertRaises(FileExistsError):
                save_project(loaded, path)

    def test_units_support_and_geological_bounds_are_strict(self):
        for change in (
            lambda d: d["spatial_reference"].update(length_unit="ft"),
            lambda d: d["rock_properties"][0]["quantity"].update(unit="m2"),
            lambda d: d["geometry"].update(nrow=True),
            lambda d: d["geometry"].update(layer_bottoms_m=[-10, -5, -50]),
            lambda d: d["rock_properties"][0]["support"].update(indices=[0, 0, 2]),
            lambda d: d["rock_properties"][0]["quantity"].update(value=[1, float("nan"), 3]),
        ):
            with self.subTest(change=change), self.assertRaises(ProjectValidationError):
                self.changed(change)
        with self.assertRaises(ProjectValidationError):
            RockProperty("porosity", Quantity(1.1, "1"), FieldSupport("global"))

    def test_booleans_are_not_numeric_quantities_indices_or_capability_flags(self):
        for change in (
            lambda d: d["geometry"].update(delr_m=True),
            lambda d: d["geometry"].update(origin_x_m=False),
            lambda d: d["rock_properties"][0]["quantity"].update(value=[True, 1.0, 2.0]),
            lambda d: d["rock_properties"][0]["support"].update(indices=[False, 1, 2]),
            lambda d: d["wells"][0]["rate"].update(value=True),
            lambda d: d["wells"][0].update(cell=[False, 10, 20]),
            lambda d: d.update(schema_version=True),
        ):
            with self.subTest(change=change), self.assertRaises(ProjectValidationError):
                self.changed(change)
        with self.assertRaises(ProjectValidationError):
            Quantity(True, "m")
        with self.assertRaises(ProjectValidationError):
            EngineAvailability(1, True, "bad marker")
        with self.assertRaises(ProjectValidationError):
            EngineDescriptor(True, "invalid", "IMPLEMENTED", ("x",), ("x",), ("x",), ("x",), ("x",))

    def test_returned_mapping_cannot_mutate_the_engine_property_contract(self):
        mapping = self.registry.validate(self.project)
        mapping["property_mapping"]["hydraulic_conductivity_x"] = "corrupted"
        self.assertEqual(self.registry.validate(self.project)["property_mapping"]["hydraulic_conductivity_x"], "kx_m_per_day")

    def test_native_engine_options_reject_booleans_as_numbers(self):
        for change in (
            lambda d: d["model"]["options"]["boundaries"].update(left_head_m=True),
            lambda d: d["model"]["options"].update(recharge_m_per_day=False),
            lambda d: d["model"]["options"]["periods"][0].update(length_days=True),
            lambda d: d["model"]["options"]["periods"][0].update(steps=True),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.registry.validate(self.changed(change))

    def test_unknown_fields_duplicate_json_keys_and_native_projects_refused(self):
        with self.assertRaises(ProjectValidationError):
            self.changed(lambda d: d.update(mystery=1))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ProjectValidationError):
                load_project(path)
            with self.assertRaises(ProjectValidationError):
                save_project(self.project, Path(tmp) / "project.gpr")

    def test_property_layer_order_is_mapped_explicitly(self):
        def reorder(data):
            prop = data["rock_properties"][0]
            prop["support"]["indices"] = [2, 0, 1]
            prop["quantity"]["value"] = [5.0, 10.0, 0.05]
        project = self.changed(reorder)
        from basinlens_ccs.subsurface import Modflow6Adapter
        mapped, _ = Modflow6Adapter().prepare(project)
        self.assertEqual(mapped.properties["kx_m_per_day"], [10.0, 0.05, 5.0])

    def test_cell_properties_and_nonwater_wells_are_not_silently_approximated(self):
        cell_property = self.changed(lambda d: d["rock_properties"][0].update(
            support={"kind": "cell", "indices": [[0, 0, 1]]}, quantity={"value": [10.0], "unit": "m/day"}))
        co2_well = self.changed(lambda d: d["wells"][0].update(fluid="co2"))
        for project in (cell_property, co2_well):
            with self.assertRaises(UnsupportedPhysicsError):
                self.registry.validate(project)

    def test_background_water_role_cannot_masquerade_as_ccs_or_oil_simulation(self):
        for change in (
            lambda d: d["model"].update(physics="co2_brine_multiphase"),
            lambda d: d["model"].update(role="co2_storage"),
            lambda d: d["model"].update(role="groundwater_flow"),
            lambda d: d["model"].update(engine_id="unknown"),
        ):
            with self.subTest(change=change), self.assertRaises(UnsupportedPhysicsError):
                self.registry.validate(self.changed(change))
        oil = project_from_groundwater(demo_case(), domain="oil_exploration")
        self.assertEqual(self.registry.validate(oil)["role"], "background_water")

    def test_unsupported_axis_orientation_is_rejected_and_origin_is_preserved(self):
        reversed_axes = self.changed(lambda d: d["spatial_reference"].update(local_axes="x increases west; y increases north; z increases downward"))
        with self.assertRaises(UnsupportedPhysicsError):
            self.registry.validate(reversed_axes)
        origin = self.changed(lambda d: d["geometry"].update(origin_x_m=350000.0, origin_y_m=4100000.0))
        mapping = self.registry.validate(origin)
        self.assertEqual(mapping["project_grid_origin_m"], {"x": 350000.0, "y": 4100000.0})

    def test_unimplemented_descriptors_fail_before_output_creation(self):
        records = {r["engine_id"]: r for r in self.registry.engines()}
        for engine_id, physics, role, domain in (
            ("opm_flow_co2", "co2_brine_multiphase", "co2_storage", "ccs"),
            ("opm_flow_blackoil", "black_oil", "petroleum_reservoir", "oil_exploration"),
            ("seismic_interpretation", "seismic_interpretation", "observation_interpretation", "ccs"),
        ):
            self.assertEqual(records[engine_id]["implementation_status"], "NOT_AVAILABLE")
            self.assertFalse(records[engine_id]["availability"]["run_available"])
            project = self.changed(lambda d: (d.update(domain=domain), d["model"].update(engine_id=engine_id, physics=physics, role=role)))
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "run"
                with self.assertRaises(EngineUnavailableError):
                    self.registry.run(project, output)
                self.assertFalse(output.exists())

    def test_missing_solver_and_dependency_do_not_create_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            with self.assertRaises(EngineUnavailableError):
                self.registry.run(self.project, output, exe_name="/nonexistent/basinlens-no-mf6")
            self.assertFalse(output.exists())
            with patch("basinlens_ccs.subsurface.registry.importlib.util.find_spec", return_value=None):
                record = next(r for r in self.registry.engines() if r["engine_id"] == "modflow6")
                self.assertFalse(record["availability"]["export_available"])
                with self.assertRaises(EngineUnavailableError):
                    self.registry.export(self.project, output)
            self.assertFalse(output.exists())

    def test_asset_paths_hashes_and_symbolic_links(self):
        for path in ("../secret", "/tmp/a", "a/./b", "C:/x", "a\\b", "a//b"):
            with self.subTest(path=path), self.assertRaises(ProjectValidationError):
                DataAsset("a", path, "0" * 64, "text/csv", "CC0", "test")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset_path = root / "properties.csv"
            asset_path.write_bytes(b"synthetic,10\n")
            digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            project = self.changed(lambda d: d.update(assets=[{
                "asset_id": "props", "relative_path": "properties.csv", "sha256": digest,
                "media_type": "text/csv", "license": "CC0-1.0", "source": "synthetic fixture"}]))
            self.assertEqual(verify_assets(project, root), {"props": digest})
            saved = save_project(project, root / "project.json")
            self.assertEqual(load_project(saved), project)
            if FLOPY:
                output = root / "export"
                with self.assertRaises(ProjectValidationError):
                    self.registry.export(project, output)
                self.assertFalse(output.exists())
                exported = self.registry.export(project, output, asset_root=root)
                self.assertEqual(exported.summary["assets_verified"], {"props": digest})
                self.assertEqual(verify_project_bundle(output)["status"], "exported")
                self.assertEqual(load_project(output / "project.json", check_assets=False), project)
            asset_path.write_bytes(b"modified")
            with self.assertRaises(ProjectValidationError):
                load_project(saved)
            asset_path.unlink()
            asset_path.symlink_to(root / "project.json")
            with self.assertRaises(ProjectValidationError):
                verify_assets(project, root)

    def test_observations_and_extra_rock_fields_remain_explicitly_unused(self):
        def extras(data):
            data["rock_properties"].append({"name": "porosity", "quantity": {"value": 0.2, "unit": "1"},
                "support": {"kind": "global", "indices": []}, "basis": "assumed", "source_asset_ids": []})
            data["observations"] = [{"observation_id": "synthetic-head", "kind": "head",
                "quantity": {"value": [11.0], "unit": "m"}, "support": {"kind": "cell", "indices": [[0, 10, 20]]},
                "time": {"value": 0.0, "unit": "day"}, "basis": "synthetic", "source_asset_ids": []}]
        mapping = self.registry.validate(self.changed(extras))
        self.assertEqual(mapping["unused_rock_properties"], ["porosity"])
        self.assertEqual(mapping["observation_count"], 1)
        self.assertFalse(mapping["observations_assimilated"])

    @unittest.skipUnless(FLOPY, "FloPy is optional")
    def test_export_preserves_exact_provenance_and_valid_inner_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            result = self.registry.export(self.project, output)
            mapped = json.loads((output / "engine/case.json").read_text())
            self.assertEqual(mapped["provenance"]["source"], self.project.provenance.source)
            self.assertEqual(mapped["provenance"]["crs"], self.project.spatial_reference.crs)
            self.assertEqual(mapped["provenance"]["vertical_datum"], self.project.spatial_reference.vertical_datum)
            self.assertEqual(mapped["provenance"]["assumptions"], list(self.project.provenance.assumptions))
            self.assertEqual(load_project(output / "project.json"), self.project)
            self.assertEqual(result.role, "background_water")
            self.assertEqual(verify_bundle(output / "engine")["status"], "exported")
            manifest = json.loads((output / "project_run_metadata.json").read_text())
            self.assertIn("mapping.json", manifest["files"])
            self.assertIn("project.json", manifest["files"])
            for relative, record in manifest["files"].items():
                self.assertEqual(hashlib.sha256((output / relative).read_bytes()).hexdigest(), record["sha256"])
            self.assertEqual(verify_project_bundle(output)["status"], "exported")
            (output / "mapping.json").write_text("{}")
            with self.assertRaises(ProjectValidationError):
                verify_project_bundle(output)

    @unittest.skipUnless(FLOPY and SOLVER, "MF6_EXE and FloPy are required for actual physics execution")
    def test_registry_invokes_actual_groundwater_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            result = self.registry.run(self.project, output, exe_name=SOLVER)
            self.assertEqual(result.engine_result.heads.shape, (13, 3, 21, 41))
            self.assertEqual(result.summary["status"], "completed")
            self.assertEqual(result.summary["domain"], "ccs")
            self.assertEqual(result.summary["physics"], "single_phase_confined_groundwater")
            self.assertEqual(result.summary["role"], "background_water")
            self.assertEqual(verify_bundle(output / "engine")["status"], "completed")
            self.assertEqual(verify_project_bundle(output)["status"], "completed")


@unittest.skipUnless(FLOPY, "FloPy is optional")
class ProjectBundleHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "export"
        self.registry = default_registry()
        self.project = project_from_groundwater(demo_case(), domain="ccs")
        self.registry.export(self.project, self.root)

    def manifest(self):
        return json.loads((self.root / "project_run_metadata.json").read_text())

    def write_manifest(self, data):
        (self.root / "project_run_metadata.json").write_text(json.dumps(data), encoding="utf-8")

    def rewrite_checksummed(self, relative, data):
        path = self.root / relative
        path.write_text(json.dumps(data), encoding="utf-8")
        manifest = self.manifest()
        manifest["files"][relative] = {"size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self.write_manifest(manifest)

    def test_malformed_manifest_shapes_paths_and_boolean_sizes_are_rejected(self):
        original = self.manifest()
        records = [[], None, {}, {**original, "schema_version": True}, {**original, "engine_id": []},
            {**original, "files": []}, {**original, "files": {}}, {**original, "status": "running"}]
        bad_size = copy.deepcopy(original)
        bad_size["files"]["mapping.json"]["size_bytes"] = True
        records.append(bad_size)
        bad_path = copy.deepcopy(original)
        bad_path["files"]["../outside"] = {"size_bytes": 0, "sha256": "0" * 64}
        records.append(bad_path)
        for record in records:
            with self.subTest(record=record):
                self.write_manifest(record)
                with self.assertRaises(ProjectValidationError):
                    verify_project_bundle(self.root)
        self.write_manifest(original)
        path = self.root / "project_run_metadata.json"
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(ProjectValidationError):
            verify_project_bundle(self.root)

    def test_checksummed_malformed_summary_is_normalized(self):
        original = json.loads((self.root / "project_summary.json").read_text())
        for summary in ([], None, True, {}, {**original, "assets_verified": []},
                {**original, "observations_assimilated": 0}, {**original, "engine_summary": {}},
                {**original, "limitations": True}, {**original, "source_asset_policy": "raw assets copied"}):
            with self.subTest(summary=summary):
                self.rewrite_checksummed("project_summary.json", summary)
                with self.assertRaises(ProjectValidationError):
                    verify_project_bundle(self.root)

    def test_checksummed_mapping_cannot_change_physics_or_boolean_version(self):
        original = json.loads((self.root / "mapping.json").read_text())
        for mapping in ([], {}, {**original, "physics": "co2_brine_multiphase"},
                {**original, "mapping_schema_version": True}, {**original, "observations_assimilated": True}):
            with self.subTest(mapping=mapping):
                self.rewrite_checksummed("mapping.json", mapping)
                with self.assertRaises(ProjectValidationError):
                    verify_project_bundle(self.root)

    def test_reopened_project_asset_markers_must_match_registered_hashes(self):
        source = Path(__file__).resolve().parents[1] / "examples/subsurface/ccs_background_water.json"
        project = load_project(source)
        output = Path(self.temp.name) / "with-assets"
        self.registry.export(project, output, asset_root=source.parent)
        self.root = output
        self.assertEqual(verify_project_bundle(output)["status"], "exported")
        summary = json.loads((output / "project_summary.json").read_text())
        self.assertTrue(summary["assets_verified"])
        self.rewrite_checksummed("project_summary.json", {**summary, "assets_verified": {}})
        with self.assertRaises(ProjectValidationError):
            verify_project_bundle(output)

    def test_native_case_must_match_the_preserved_project(self):
        # A different, internally valid engine export must not be substituted.
        from basinlens_ccs.groundwater import export_case
        changed = demo_case()
        changed.boundaries["left_head_m"] = 20.0
        replacement = Path(self.temp.name) / "replacement"
        export_case(changed, replacement)
        shutil.rmtree(self.root / "engine")
        shutil.copytree(replacement, self.root / "engine")
        manifest = self.manifest()
        manifest["files"] = {
            path.relative_to(self.root).as_posix(): {"size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in self.root.rglob("*") if path.is_file() and path.name != "project_run_metadata.json"}
        self.write_manifest(manifest)
        with self.assertRaises(ProjectValidationError):
            verify_project_bundle(self.root)

    def test_added_files_and_symbolic_links_are_rejected(self):
        extra = self.root / "extra.txt"
        extra.write_text("unregistered")
        with self.assertRaises(ProjectValidationError):
            verify_project_bundle(self.root)
        extra.unlink()
        extra.symlink_to(self.root / "project.json")
        with self.assertRaises(ProjectValidationError):
            verify_project_bundle(self.root)


if __name__ == "__main__":
    unittest.main()
