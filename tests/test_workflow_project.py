"""Actual portable spatial-model persistence, authority and failure recovery."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.subsurface import project_package as package
from basinlens_ccs.subsurface.model_workflow import UNITS, WorkflowCase
from basinlens_ccs.subsurface.workflow_project import (
    WORKFLOW_ASSET_PATH, open_workflow_project, save_workflow_project,
    verify_workflow_project_roundtrip,
)
from basinlens_ccs.subsurface.schema import DataAsset, Quantity


def case_data():
    """Different property supports and every supported forcing across two periods."""
    materials, assignments = [], []
    for layer in range(2):
        for row in range(2):
            mid = f"m{layer}{row}"
            materials.append({"id": mid, "name": f"assumed material {mid}",
                "kx_m_day": 1.0 + row, "ky_m_day": 3.0,
                "kz_m_day": 0.1 + layer * 0.1, "ss_per_m": 1e-5 * (layer + 1),
                "porosity": 0.2 + row * 0.1})
            assignments.append({"material_id": mid, "stratum_id": f"s{layer}",
                                "cells": [[layer, row, col] for col in range(3)]})
    boundaries = []
    for period in range(2):
        records = [("CHD", [0, 0, 0], {"head_m": 12.0 + period}),
                   ("WEL", [0, 1, 1], {"rate_m3_day": -1.0 if period == 0 else 2.0}),
                   ("GHB", [1, 0, 2], {"head_m": 11.0, "conductance_m2_day": 2.0}),
                   ("DRN", [1, 1, 2], {"elevation_m": 11.0, "conductance_m2_day": 2.0}),
                   ("RIV", [0, 0, 2], {"stage_m": 12.0, "conductance_m2_day": 0.5, "bottom_m": 10.0})]
        if period == 0:
            records.append(("RCH", [0, 1, 0], {"rate_m_day": 0.002}))
        boundaries.extend({"kind": kind, "period": period, "cell": cell,
                           "values": values, "label": f"b{period}{kind}"}
                          for kind, cell, values in records)
    return {"schema": "basinlens-model-workflow-v1",
        "project": {"id": "portable_review", "name": "Own synthetic layered case",
            "domain": "ccs", "flow_role": "background_water", "units": dict(UNITS),
            "crs": "unknown", "vertical_datum": "unknown",
            "provenance": ["Authored synthetic persistence test", "No field or original GMS observation"]},
        "grid": {"nrow": 2, "ncol": 3, "dx_m": 7.0, "dy_m": 11.0,
            "x_origin_m": 345000.0, "y_origin_m": 4100000.0, "rotation_degrees": 0.0,
            "row_axis": "south_to_north", "layer_surfaces_m": [0.0, -10.0, -25.0]},
        "strata": [{"id": f"s{k}", "name": f"named synthetic stratum {k}",
                    "layer_indices": [k]} for k in range(2)],
        "materials": materials, "assignments": assignments,
        "initial_head_m": [12.0 + index * 0.01 for index in range(12)],
        "periods": [{"duration_day": 0.75, "nsteps": 2, "steady": True},
                    {"duration_day": 2.5, "nsteps": 3, "steady": False}],
        "boundaries": boundaries}


class WorkflowProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workflow-project-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case = WorkflowCase.from_dict(case_data())
        self.view = {"selected_layer": 1, "selected_field": "porosity",
                     "chart_mode": "3d", "show_wells": False}
        self.archive = save_workflow_project(self.case, self.root / "source.blproj",
                                             view_state=self.view)

    def generic(self):
        return package.open_project_package(self.archive, self.root / "generic")

    def test_actual_relocation_preserves_complete_case_and_view(self):
        loaded = open_workflow_project(self.archive, self.root / "relocated")
        self.assertEqual(loaded.case.to_dict(), self.case.to_dict())
        self.assertEqual(loaded.view_state, self.view)
        self.assertEqual(loaded.case.to_dict()["boundaries"], case_data()["boundaries"])
        self.assertEqual(loaded.project.geometry.origin_y_m, 4100000.0)
        self.assertEqual(loaded.project.spatial_reference.crs, "unknown")
        self.assertEqual(loaded.project.spatial_reference.vertical_datum, "unknown")
        self.assertEqual(loaded.project.provenance.assumptions,
                         tuple(case_data()["project"]["provenance"]))
        self.assertEqual(loaded.project.model.engine_id, "modflow6_spatial")
        self.assertEqual(loaded.project.model.role, "background_water")
        self.assertEqual(loaded.project.wells, ())  # Forcing remains period-specific in the asset.
        self.assertTrue(loaded.receipt["workflow_shared_project_consistent"])
        self.assertTrue(loaded.receipt["boundary_periods_preserved"])
        self.assertFalse(loaded.receipt["solver_executed"])
        self.assertFalse(loaded.receipt["gms_parity_established"])
        self.assertEqual(loaded.root, self.root / "relocated")
        self.assertEqual(loaded.asset_root, loaded.root / "assets")

    def test_global_layer_and_cell_fields_retain_exact_support_and_values(self):
        project = open_workflow_project(self.archive, self.root / "opened").project
        props = {item.name: item for item in project.rock_properties}
        self.assertEqual(len(props), 5)
        self.assertEqual(props["hydraulic_conductivity_y"].support.kind, "global")
        self.assertEqual(props["hydraulic_conductivity_y"].quantity.value, 3.0)
        self.assertEqual(props["hydraulic_conductivity_z"].support.kind, "layer")
        self.assertEqual(props["hydraulic_conductivity_z"].quantity.value, (0.1, 0.2))
        self.assertEqual(props["specific_storage"].quantity.value, (1e-5, 2e-5))
        self.assertEqual(props["hydraulic_conductivity_x"].support.kind, "cell")
        self.assertEqual(props["hydraulic_conductivity_x"].support.indices,
                         tuple((k, r, c) for k in range(2) for r in range(2) for c in range(3)))
        self.assertEqual(props["hydraulic_conductivity_x"].quantity.value,
                         (1., 1., 1., 2., 2., 2., 1., 1., 1., 2., 2., 2.))
        self.assertTrue(all(item.source_asset_ids == ("workflow_model",) for item in props.values()))
        self.assertTrue(all(item.basis == "assumed" for item in props.values()))

    def test_roundtrip_really_opens_repacks_reopens_and_compares(self):
        before = self.archive.read_bytes()
        receipt = verify_workflow_project_roundtrip(self.archive)
        for key in ("roundtrip_verified", "workflow_case_equal", "project_semantics_equal",
                    "view_state_equal", "asset_bytes_equal", "source_unchanged", "archive_bytes_equal"):
            self.assertTrue(receipt[key], key)
        self.assertFalse(receipt["gms_project_roundtrip"])
        self.assertFalse(receipt["gms_parity_established"])
        self.assertEqual(self.archive.read_bytes(), before)

    def test_coherently_rehashed_outer_metadata_contradictions_are_rejected(self):
        loaded = self.generic()
        properties = list(loaded.project.rock_properties)
        properties[0] = replace(properties[0], quantity=Quantity((3.0,) * 12, "m/day"))
        variations = [replace(loaded.project, name="contradictory name"),
            replace(loaded.project, geometry=replace(loaded.project.geometry, origin_y_m=5.0)),
            replace(loaded.project, spatial_reference=replace(loaded.project.spatial_reference, crs="different")),
            replace(loaded.project, rock_properties=tuple(properties)),
            replace(loaded.project, stratigraphy=(replace(loaded.project.stratigraphy[0], name="wrong"),
                                                  loaded.project.stratigraphy[1]))]
        for index, project in enumerate(variations):
            path = package.save_project_package(project, self.root / f"contradiction{index}.blproj",
                                                asset_root=loaded.asset_root)
            target = self.root / f"rejected{index}"
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "contradicts"):
                open_workflow_project(path, target)
            self.assertFalse(target.exists())

    def test_asset_must_be_canonical_even_when_generic_hashes_are_consistent(self):
        loaded = self.generic()
        target = loaded.asset_root / WORKFLOW_ASSET_PATH
        target.write_text(json.dumps(self.case.to_dict(), indent=3), encoding="utf-8")
        asset = replace(loaded.project.assets[0], sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        project = replace(loaded.project, assets=(asset,))
        path = package.save_project_package(project, self.root / "noncanonical.blproj",
                                            asset_root=loaded.asset_root)
        with self.assertRaisesRegex(ValueError, "canonical"):
            open_workflow_project(path, self.root / "rejected")
        self.assertFalse((self.root / "rejected").exists())

    def test_invalid_authoritative_case_is_not_accepted_as_opaque_asset(self):
        loaded = self.generic()
        data = self.case.to_dict()
        data["project"]["units"]["length"] = "ft"
        target = loaded.asset_root / WORKFLOW_ASSET_PATH
        target.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        asset = replace(loaded.project.assets[0], sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        project = replace(loaded.project, assets=(asset,))
        path = package.save_project_package(project, self.root / "wrongunits.blproj",
                                            asset_root=loaded.asset_root)
        with self.assertRaisesRegex(ValueError, "units"):
            open_workflow_project(path, self.root / "rejected")
        self.assertFalse((self.root / "rejected").exists())

    def test_undeclared_bridge_asset_and_wrong_engine_options_are_rejected(self):
        loaded = self.generic()
        extra = loaded.asset_root / "extra.txt"
        extra.write_bytes(b"own synthetic extra")
        asset = DataAsset("extra", "extra.txt", hashlib.sha256(extra.read_bytes()).hexdigest(),
                          "text/plain", "CC0", "synthetic test")
        variants = [replace(loaded.project, assets=(*loaded.project.assets, asset)),
                    replace(loaded.project, model=replace(loaded.project.model, options={"workflow_asset_id": "other"}))]
        for index, project in enumerate(variants):
            path = package.save_project_package(project, self.root / f"extra{index}.blproj",
                                                asset_root=loaded.asset_root)
            target = self.root / f"refused{index}"
            with self.subTest(index=index), self.assertRaises(ValueError):
                open_workflow_project(path, target)
            self.assertFalse(target.exists())

    def test_existing_destinations_are_preserved_and_refused(self):
        original = self.archive.read_bytes()
        with self.assertRaises(FileExistsError):
            save_workflow_project(self.case, self.archive)
        target = self.root / "existing"
        target.mkdir()
        (target / "sentinel").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            open_workflow_project(self.archive, target)
        self.assertEqual((target / "sentinel").read_bytes(), b"keep")
        self.assertEqual(self.archive.read_bytes(), original)

    def test_failed_final_promotion_cleans_staging_and_retry_succeeds(self):
        target = self.root / "recovered"
        promote = package._promote_directory
        def fail_final(staging, output):
            if output == target:
                raise OSError("simulated final promotion failure")
            return promote(staging, output)
        with patch.object(package, "_promote_directory", side_effect=fail_final):
            with self.assertRaisesRegex(OSError, "simulated"):
                open_workflow_project(self.archive, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".recovered*")))
        self.assertEqual(open_workflow_project(self.archive, target).case.to_dict(), self.case.to_dict())

    def test_persistence_calls_never_execute_a_solver(self):
        with patch("basinlens_ccs.subsurface.model_workflow.run_native_simulation",
                   side_effect=AssertionError("unexpected solver action")):
            self.assertTrue(verify_workflow_project_roundtrip(self.archive)["roundtrip_verified"])

    def test_source_change_after_generic_open_blocks_final_publication(self):
        from basinlens_ccs.subsurface import workflow_project as bridge
        original = self.archive.read_bytes()
        validate = bridge._load_authoritative_case
        def mutate_after_validation(loaded):
            result = validate(loaded)
            self.archive.write_bytes(original + b"changed")
            return result
        target = self.root / "changedsource"
        with patch.object(bridge, "_load_authoritative_case", side_effect=mutate_after_validation):
            with self.assertRaisesRegex(ValueError, "changed"):
                open_workflow_project(self.archive, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".changedsource*")))
        self.archive.write_bytes(original)
        self.assertEqual(open_workflow_project(self.archive, target).case.to_dict(), self.case.to_dict())

    def test_wrong_case_type_and_invalid_view_leave_no_file(self):
        for index, case in enumerate((self.case.to_dict(), WorkflowCase("{}"))):
            target = self.root / f"invalid{index}.blproj"
            with self.subTest(index=index), self.assertRaises(ValueError):
                save_workflow_project(case, target)
            self.assertFalse(target.exists())
        target = self.root / "invalidview.blproj"
        with self.assertRaises(ValueError):
            save_workflow_project(self.case, target, view_state={"selected_layer": True})
        self.assertFalse(target.exists())

    def test_wider_compiler_case_is_explicitly_refused_by_shared_geometry(self):
        data = case_data()
        data["grid"].update(nrow=1, ncol=501, layer_surfaces_m=[0.0, -10.0])
        data["strata"] = data["strata"][:1]
        data["materials"] = data["materials"][:1]
        data["assignments"] = [{"material_id": data["materials"][0]["id"],
                               "stratum_id": data["strata"][0]["id"],
                               "cells": [[0, 0, col] for col in range(501)]}]
        data["initial_head_m"] = [12.0] * 501
        data["boundaries"] = [b for b in data["boundaries"] if b["kind"] == "CHD"]
        case = WorkflowCase.from_dict(data)
        target = self.root / "too-wide.blproj"
        with self.assertRaisesRegex(ValueError, "ncol"):
            save_workflow_project(case, target)
        self.assertFalse(target.exists())
