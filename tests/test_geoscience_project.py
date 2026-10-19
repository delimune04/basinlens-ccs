"""Portable typed objects and rehashed semantic-adversary checks, not GMS parity."""
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from basinlens_ccs.subsurface import project_package as package
from basinlens_ccs.subsurface.geoscience_project import (
    AnalysisArchive, MANIFEST_ID, MANIFEST_PATH, ProjectObject, archive_analysis_bundle,
    main, open_geoscience_project, save_geoscience_project, verify_geoscience_project_roundtrip,
)
from basinlens_ccs.subsurface.schema import DataAsset, SubsurfaceProject, load_project
from basinlens_ccs.subsurface.geology import load_geology, GeologyProject
from basinlens_ccs.subsurface.scatter import load_scatter, ScatterDataset
from basinlens_ccs.subsurface.features import load_coverage
from basinlens_ccs.subsurface.mesh import structured_mesh
from basinlens_ccs.subsurface.raster import load_raster, RasterGrid
from basinlens_ccs.subsurface.pointcloud import load_pointcloud, PointCloud
from basinlens_ccs.subsurface.surfaces import load_surfaces, SurfaceModel
from basinlens_ccs.subsurface.analysis import AnalysisVolume, write_analysis_bundle
from basinlens_ccs.subsurface.model_workflow import load_workflow_case, WorkflowCase

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/geoscience_project"


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class GeoscienceProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "sources"; self.source.mkdir()
        shutil.copytree(ROOT / "examples/geology/assets", self.source / "assets")
        self.base = load_project(EXAMPLE / "project.json", check_assets=False)
        self.geology = load_geology(ROOT / "examples/geology/synthetic_boreholes.json", asset_root=self.source).project
        self.scatter = load_scatter(EXAMPLE / "scatter.json")
        self.features = load_coverage(ROOT / "examples/features/local_coverage.json")
        self.mesh = structured_mesh([0., 1., 3.], [0., 2., 5.], crs="unknown")
        self.items = [ProjectObject("geology", "boreholes", self.geology),
                      ProjectObject("scatter", "samples", self.scatter),
                      ProjectObject("features", "coverage", self.features),
                      ProjectObject("mesh", "mesh", self.mesh)]
        self.archive = self.root / "mixed.blproj"
        self.counter = 0

    def save(self, *, objects=None, project=None, output=None, **kwargs):
        roots = kwargs.pop("object_asset_roots", {"boreholes": self.source} if objects is None else None)
        return save_geoscience_project(project or self.base, self.items if objects is None else objects,
            output or self.archive, object_asset_roots=roots, **kwargs)

    def loaded(self):
        if not self.archive.exists(): self.save()
        self.counter += 1
        return package.open_project_package(self.archive, self.root / f"generic-{self.counter}")

    def repack(self, mutate):
        """Produce a valid generic package whose inner typed semantics are adversarial."""
        loaded = self.loaded()
        data = loaded.project.to_dict()
        payloads = {a.relative_path: (loaded.asset_root / a.relative_path).read_bytes() for a in loaded.project.assets}
        manifest = json.loads(payloads[MANIFEST_PATH])
        mutate(data, manifest, payloads)
        # Resign generic package hashes, so rejection must be a typed semantic gate.
        by_id = {a["asset_id"]: a for a in data["assets"]}
        for asset in manifest["managed_assets"]:
            if asset["asset_id"] in by_id:
                asset.update(by_id[asset["asset_id"]])
                asset["sha256"] = digest(payloads[asset["relative_path"]])
                by_id[asset["asset_id"]]["sha256"] = asset["sha256"]
        payloads[MANIFEST_PATH] = canonical(manifest)
        by_id[MANIFEST_ID]["sha256"] = digest(payloads[MANIFEST_PATH])
        for relative, raw in payloads.items():
            path = loaded.asset_root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        output = self.root / f"rehashed-{self.counter}.blproj"
        package.save_project_package(SubsurfaceProject.from_dict(data), output,
                                     asset_root=loaded.asset_root, view_state=loaded.view_state)
        return output

    def reject(self, source):
        self.counter += 1
        output = self.root / f"refused-{self.counter}"
        with self.assertRaises(ValueError): open_geoscience_project(source, output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.' + output.name + '.geoscience-partial-*')))

    def test_portable_save_relocate_reopen_resave_exact_objects_and_original_assets(self):
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        view = {"selected_layer": 1, "selected_field": "porosity", "chart_mode": "3d", "show_wells": False}
        self.save(view_state=view)
        unchanged = self.archive.read_bytes()
        moved = self.root / "relocated.blproj"; shutil.copyfile(self.archive, moved)
        shutil.rmtree(self.source)
        loaded = open_geoscience_project(moved, self.root / "restored")
        self.assertEqual([(x.kind, x.object_id, x.value.to_dict()) for x in loaded.objects],
                         [(x.kind, x.object_id, x.value.to_dict()) for x in self.items])
        self.assertEqual(loaded.view_state, view)
        self.assertEqual(loaded.object_asset_roots, {"boreholes": loaded.asset_root})
        for relative, raw in before.items(): self.assertEqual((loaded.asset_root / relative).read_bytes(), raw)
        repacked = save_geoscience_project(loaded.project, loaded.objects, self.root / "again.blproj",
                                          asset_root=loaded.asset_root, view_state=loaded.view_state)
        self.assertEqual(repacked.read_bytes(), unchanged)
        self.assertEqual(moved.read_bytes(), unchanged)
        self.assertFalse(loaded.receipt["solver_executed"])
        self.assertFalse(loaded.receipt["object_to_model_mapping_performed"])
        self.assertFalse(loaded.receipt["gms_parity_established"])

    def test_actual_roundtrip_checks_objects_views_assets_and_source_identity(self):
        self.save()
        before = self.archive.read_bytes()
        result = verify_geoscience_project_roundtrip(self.archive)
        for key in ("roundtrip_verified", "typed_objects_equal", "project_metadata_equal",
                    "registered_asset_bytes_equal", "view_state_equal", "source_unchanged", "archive_bytes_equal"):
            self.assertTrue(result[key])
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(result["source_archive_sha256"], digest(before))
        self.assertEqual(result["object_count"], 4)

    def test_explicit_collection_edit_replaces_managed_assets_and_preserves_base(self):
        self.save()
        first = open_geoscience_project(self.archive, self.root / "editing")
        data = self.scatter.to_dict(); data["points"][0]["value"] = 7.
        changed = ProjectObject("scatter", "samples", ScatterDataset.from_dict(data))
        rewritten = save_geoscience_project(first.project, [changed], self.root / "edited.blproj", asset_root=first.asset_root)
        second = open_geoscience_project(rewritten, self.root / "edited-open")
        self.assertEqual(len(second.objects), 1)
        self.assertEqual(second.objects[0].value.to_dict(), data)
        self.assertNotIn("bl_geo_obj_boreholes", {a.asset_id for a in second.project.assets})
        generic = second.project.to_dict(); generic["assets"] = []
        self.assertEqual(generic, self.base.to_dict())
        self.assertEqual(self.scatter.to_dict()["points"][0]["value"], 1.)

    def test_generic_metadata_options_observations_and_opaque_asset_preserved(self):
        raw = b"opaque original bytes\x00\xff\n"
        (self.source / "opaque.bin").write_bytes(raw)
        asset = DataAsset("original", "opaque.bin", digest(raw), "application/octet-stream", "CC0 authored fixture", "Authored opaque data; never interpreted")
        data = self.base.to_dict(); data["assets"] = [asset.__dict__]
        data["model"]["options"]["owner_note"] = {"unchanged": [1, True, None]}
        project = SubsurfaceProject.from_dict(data)
        self.save(project=project, asset_root=self.source)
        loaded = open_geoscience_project(self.archive, self.root / "metadata")
        actual = loaded.project.to_dict()
        actual["assets"] = [a for a in actual["assets"] if a["asset_id"] == "original"]
        self.assertEqual(actual, project.to_dict())
        self.assertEqual((loaded.asset_root / "opaque.bin").read_bytes(), raw)

    def test_new_spatial_types_preserve_own_canonical_fields_in_matching_projects(self):
        sources = [("raster", load_raster(ROOT / "examples/raster/linear_head.json")),
                   ("pointcloud", load_pointcloud(ROOT / "examples/pointcloud/synthetic_points.json")),
                   ("surfaces", load_surfaces(ROOT / "examples/surfaces/tilted_planes.json"))]
        for kind, value in sources:
            obj = value.to_dict()
            # Each project uses the object's actual metadata; no object is retagged.
            metadata = obj["metadata"] if kind == "pointcloud" else obj
            data = self.base.to_dict(); data["spatial_reference"].update(crs=metadata["crs"], vertical_datum=metadata["vertical_datum"])
            project = SubsurfaceProject.from_dict(data)
            path = self.root / (kind + ".blproj")
            self.save(project=project, objects=[ProjectObject(kind, "authored", value)], output=path)
            loaded = open_geoscience_project(path, self.root / (kind + "-open"))
            self.assertEqual(loaded.objects[0].value.to_dict(), obj)
            self.assertTrue(verify_geoscience_project_roundtrip(path)["archive_bytes_equal"])
            if kind == "pointcloud":
                self.assertEqual(loaded.objects[0].value.prefix, value.prefix)
                self.assertEqual(loaded.objects[0].value.records, value.records)
                self.assertEqual(loaded.objects[0].value.identities, value.identities)

    def test_inert_analysis_archive_preserves_exact_original_files_without_run_reconstruction(self):
        case_data = load_workflow_case(ROOT / "examples/workflow/layered_background_water.json").to_dict()
        project_data = self.base.to_dict()
        project_data["spatial_reference"].update(crs=case_data["project"]["crs"], vertical_datum=case_data["project"]["vertical_datum"])
        project = SubsurfaceProject.from_dict(project_data)
        case = WorkflowCase.from_dict(case_data)
        volume = AnalysisVolume.from_arrays(case, [1.], np.ones((1, *case.shape))*12., provenance="Authored portable archive fixture")
        bundle = write_analysis_bundle(volume.clip(), self.root / "analysis")
        archived = archive_analysis_bundle(bundle)
        expected = archived.files
        path = self.save(project=project, objects=[ProjectObject("analysis_archive", "results", archived)])
        shutil.rmtree(bundle)
        loaded = open_geoscience_project(path, self.root / "archive-open")
        restored = loaded.objects[0].value
        self.assertEqual(restored.files, expected)
        self.assertFalse(restored.to_dict()["live_engine_state_restored"])
        self.assertIn("no numerical recomputation", restored.to_dict()["verification_scope"])
        self.assertTrue(verify_geoscience_project_roundtrip(path)["archive_bytes_equal"])

    def test_unknown_labels_are_literal_metadata_and_incompatible_types_fail(self):
        self.save()
        loaded = open_geoscience_project(self.archive, self.root / "unknown")
        self.assertEqual(loaded.project.spatial_reference.crs, "unknown")
        self.assertTrue(loaded.receipt["unknown_spatial_labels_preserved"])
        self.assertFalse(loaded.receipt["object_to_model_mapping_performed"])
        for item in (ProjectObject("scatter", "bad", self.scatter.to_dict()),
                     ProjectObject("dynamic_import", "bad", self.scatter),
                     ProjectObject("scatter", "../bad", self.scatter),
                     ProjectObject("scatter", "CON.", self.scatter)):
            with self.assertRaises(ValueError): self.save(objects=[item], output=self.root / "bad.blproj")

    def test_duplicate_collection_ids_including_casefold_are_rejected(self):
        for second in ("samples", "SAMPLES"):
            with self.assertRaises(ValueError):
                self.save(objects=[ProjectObject("scatter", "samples", self.scatter), ProjectObject("mesh", second, self.mesh)])
        self.assertFalse(self.archive.exists())

    def test_crs_datum_units_contradictions_and_wrong_dependency_roots_fail(self):
        for key, value in (("crs", "EPSG:32652"), ("vertical_datum", "MSL")):
            data = self.scatter.to_dict(); data[key] = value
            with self.assertRaises(ValueError): self.save(objects=[ProjectObject("scatter", "mismatch", ScatterDataset.from_dict(data))])
        cloud = load_pointcloud(ROOT / "examples/pointcloud/synthetic_points.json").to_dict()
        cloud["metadata"].update(crs="unknown", vertical_datum="unknown", horizontal_unit="unknown")
        with self.assertRaises(ValueError): self.save(objects=[ProjectObject("pointcloud", "cloud", PointCloud.from_dict(cloud))])
        with self.assertRaises(ValueError): self.save(objects=[ProjectObject("mesh", "mesh", self.mesh)], object_asset_roots={"bogus": self.source})

    def test_missing_altered_symlink_and_fifo_original_dependencies_fail(self):
        target = self.source / "assets/synthetic_notes.txt"
        original = target.read_bytes()
        for mutation in ("missing", "changed", "symlink", "fifo"):
            if target.exists() or target.is_symlink(): target.unlink()
            if mutation == "changed": target.write_bytes(b"changed")
            elif mutation == "symlink":
                other = self.source / "elsewhere"; other.write_bytes(original); target.symlink_to(other)
            elif mutation == "fifo":
                if not hasattr(os, "mkfifo"): continue
                os.mkfifo(target)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.save()
            self.assertFalse(self.archive.exists())
        target.unlink(); target.write_bytes(original)

    def test_generic_reserved_paths_ids_and_casefold_aliases_fail(self):
        for aid, relative in (("owner", "geoscience/user.json"), ("bl_geo_obj_samples", "owner.txt")):
            raw = b"owner"; path = self.source / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            data = self.base.to_dict(); data["assets"] = [DataAsset(aid,relative,digest(raw),"text/plain","CC0","Authored").__dict__]
            with self.assertRaises(ValueError): self.save(project=SubsurfaceProject.from_dict(data), asset_root=self.source)

    def test_conflicting_dependency_bytes_media_license_and_casefold_paths_fail(self):
        dependency = self.geology.to_dict()["assets"][0]
        for kind in ("checksum", "license", "case_path", "case_id"):
            data = self.base.to_dict(); relative = dependency["relative_path"]
            if kind == "case_path": relative = relative.replace("assets", "ASSETS")
            asset = DataAsset("original" if kind != "case_id" else "BL_GEO_DEP_boreholes_0", relative,
                              "0"*64 if kind == "checksum" else dependency["sha256"],
                              dependency["media_type"], "different" if kind == "license" else dependency["license"], "Authored generic reference")
            data["assets"] = [asset.__dict__]
            if kind == "case_path":
                (self.source / "ASSETS").mkdir(exist_ok=True)
                (self.source / relative).write_bytes((self.source / dependency["relative_path"]).read_bytes())
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.save(project=SubsurfaceProject.from_dict(data), asset_root=self.source)

    def test_rehashed_outer_metadata_contradiction_is_rejected(self):
        self.reject(self.repack(lambda data, manifest, payloads: data.update(name="Contradictory outer metadata")))

    def test_rehashed_object_kind_spatial_or_document_identity_is_rejected(self):
        for field, value in (("kind", "mesh"), ("document_id", "other"), ("spatial_reference", {"crs":"wrong","coordinate_unit":"m","vertical_datum":None})):
            self.reject(self.repack(lambda data, manifest, payloads, field=field, value=value: manifest["objects"][1].update({field:value})))

    def test_rehashed_object_asset_metadata_and_path_are_rejected(self):
        for field, value in (("media_type", "text/plain"), ("license", "invented"), ("source", "relabelled"), ("relative_path", "elsewhere/object.json")):
            def mutate(data, manifest, payloads, field=field, value=value):
                asset = next(a for a in data["assets"] if a["asset_id"] == "bl_geo_obj_samples")
                if field == "relative_path": payloads[value] = payloads[asset["relative_path"]]
                asset[field] = value
            self.reject(self.repack(mutate))

    def test_rehashed_original_geology_reference_metadata_is_rejected(self):
        for field, value in (("license", "relicensed"), ("source", "unrelated origin")):
            def mutate(data, manifest, payloads, field=field, value=value):
                next(a for a in data["assets"] if a["asset_id"] == "bl_geo_dep_boreholes_0")[field] = value
            self.reject(self.repack(mutate))

    def test_rehashed_unsupported_or_invalid_object_payload_never_executes(self):
        marker = self.root / "executed"
        def mutate(data, manifest, payloads):
            record = manifest["objects"][1]
            value = json.loads(payloads[record["relative_path"]])
            value["__class__"] = f"__import__('pathlib').Path({str(marker)!r}).touch()"
            payloads[record["relative_path"]] = canonical(value)
            record["sha256"] = digest(payloads[record["relative_path"]])
        self.reject(self.repack(mutate)); self.assertFalse(marker.exists())

    def test_rehashed_missing_extra_duplicate_or_reordered_dependency_fails(self):
        for mutation in ("missing", "duplicate", "unknown", "ordering"):
            def mutate(data, manifest, payloads, mutation=mutation):
                record = manifest["objects"][0]
                if mutation == "missing": record["dependencies"] = []
                elif mutation == "duplicate": record["dependencies"] *= 2
                elif mutation == "unknown": record["dependencies"] = ["not_registered"]
                else: manifest["managed_assets"].reverse()
            self.reject(self.repack(mutate))

    def test_rehashed_duplicate_ids_and_unmanaged_reserved_namespace_fail(self):
        self.reject(self.repack(lambda data, manifest, payloads: manifest["objects"].append(copy.deepcopy(manifest["objects"][0]))))
        def mutate(data, manifest, payloads):
            raw = b"unmanaged source"
            asset = DataAsset("owner-extra", "geoscience/unmanaged.txt", digest(raw), "text/plain", "CC0", "Authored test")
            data["assets"].insert(0, asset.__dict__); payloads[asset.relative_path] = raw
            managed = {a["asset_id"] for a in manifest["managed_assets"]} | {MANIFEST_ID}
            base = copy.deepcopy(data); base["assets"] = [a for a in base["assets"] if a["asset_id"] not in managed]
            manifest["base_project_sha256"] = digest(canonical(base))
        self.reject(self.repack(mutate))

    def test_source_mutation_during_save_removes_only_new_published_package(self):
        writer = package.save_project_package
        def changed(*args, **kwargs):
            result = writer(*args, **kwargs)
            (self.source / "assets/synthetic_notes.txt").write_bytes(b"changed during publication")
            return result
        with patch.object(package, "save_project_package", side_effect=changed), self.assertRaises(ValueError): self.save()
        self.assertFalse(self.archive.exists())

    def test_missing_or_symlinked_source_after_publication_removes_new_output(self):
        writer = package.save_project_package
        for mutation in ("missing", "symlink", "fifo"):
            target = self.source / "assets/synthetic_notes.txt"
            if target.exists() or target.is_symlink(): target.unlink()
            target.write_bytes((ROOT / "examples/geology/assets/synthetic_notes.txt").read_bytes())
            def changed(*args, **kwargs):
                result = writer(*args, **kwargs); target.unlink()
                if mutation == "symlink": target.symlink_to(self.source / "missing-source")
                elif mutation == "fifo": os.mkfifo(target)
                return result
            if mutation == "fifo" and not hasattr(os, "mkfifo"): continue
            with self.subTest(mutation=mutation), patch.object(package, "save_project_package", side_effect=changed), self.assertRaises(ValueError): self.save()
            self.assertFalse(self.archive.exists())

    def test_changed_destination_is_preserved_on_postpublication_source_failure(self):
        reader = package._read_file
        source = self.source / "assets/synthetic_notes.txt"
        sentinel = b"owner replacement; preserve this"
        def changed(path, maximum):
            if Path(path) == source and self.archive.exists():
                self.archive.unlink(); self.archive.write_bytes(sentinel)
                source.unlink()
            return reader(path, maximum)
        with patch.object(package, "_read_file", side_effect=changed), self.assertRaisesRegex(ValueError, "replacement preserved"):
            self.save()
        self.assertEqual(self.archive.read_bytes(), sentinel)

    def test_aggregate_budget_rejects_before_reading_later_known_large_source(self):
        data = self.base.to_dict(); data["assets"] = []
        for name in ("first.bin", "second.bin"):
            raw = name.encode().ljust(40, b"x"); (self.source / name).write_bytes(raw)
            data["assets"].append(DataAsset(name, name, digest(raw), "application/octet-stream", "CC0", "Authored budget fixture").__dict__)
        project = SubsurfaceProject.from_dict(data)
        reader = package._read_file
        with patch.object(package, "MAX_TOTAL_BYTES", 60), patch.object(package, "_read_file", wraps=reader) as observed:
            with self.assertRaisesRegex(ValueError, "before next capture"):
                self.save(objects=[ProjectObject("mesh", "mesh", self.mesh)], project=project, asset_root=self.source)
        paths = [Path(call.args[0]) for call in observed.call_args_list]
        self.assertIn(self.source / "first.bin", paths)
        self.assertNotIn(self.source / "second.bin", paths)
        self.assertFalse(self.archive.exists())

    def test_source_archive_mutation_before_open_publication_leaves_no_output(self):
        from basinlens_ccs.subsurface import geoscience_project as module
        self.save(); reader = module._read_objects
        def changed(*args, **kwargs):
            result = reader(*args, **kwargs)
            with self.archive.open("ab") as stream: stream.write(b"changed")
            return result
        with patch.object(module, "_read_objects", side_effect=changed): self.reject(self.archive)

    def test_fresh_output_existing_destination_and_unsupported_budgets(self):
        self.save()
        original = self.archive.read_bytes()
        with self.assertRaises(FileExistsError): self.save()
        self.assertEqual(self.archive.read_bytes(), original)
        output = self.root / "existing"; output.mkdir(); (output / "owner.txt").write_text("keep")
        with self.assertRaises(FileExistsError): open_geoscience_project(self.archive, output)
        self.assertEqual((output / "owner.txt").read_text(), "keep")
        from basinlens_ccs.subsurface import geoscience_project as module
        with patch.object(module, "MAX_OBJECT_BYTES", 100), self.assertRaises(ValueError):
            self.save(objects=[ProjectObject("scatter", "samples", self.scatter)], output=self.root / "too-big.blproj")
        with self.assertRaises(ValueError): self.save(objects=[ProjectObject("mesh", f"m{i}", self.mesh) for i in range(65)], output=self.root / "too-many.blproj")

    def test_cli_open_roundtrip_and_invalid_archive_failure_recovery(self):
        self.save()
        main(["open", str(self.archive), "--output", str(self.root / "cli-open")])
        main(["roundtrip", str(self.archive)])
        broken = self.root / "broken.blproj"; broken.write_bytes(b"broken")
        with self.assertRaises(SystemExit) as error: main(["open", str(broken), "--output", str(self.root / "cli-failed")])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root / "cli-failed").exists())
        main(["open", str(self.archive), "--output", str(self.root / "cli-recovered")])


if __name__ == "__main__": unittest.main()
