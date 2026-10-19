"""Independent support/formula checks and actual source-bound MF6 analysis."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from basinlens_ccs.subsurface.analysis import (
    AnalysisError, AnalysisVolume, load_analysis_run, main,
    verify_analysis_bundle, write_analysis_bundle,
)
from basinlens_ccs.subsurface.model_workflow import (
    WorkflowCase, UNITS, load_workflow_case, run_workflow,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/workflow/layered_background_water.json"
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


def fixture():
    shape = (2, 3, 4)
    data = {"schema": "basinlens-model-workflow-v1", "project": {
        "id": "analytical", "name": "Authored affine field", "domain": "groundwater",
        "flow_role": "background_water", "units": dict(UNITS), "crs": "local analytical XY",
        "vertical_datum": "local synthetic z=0 m", "provenance": ["Authored analytical array; not solver or field evidence."]},
        "grid": {"nrow": 3, "ncol": 4, "dx_m": 2., "dy_m": 3.,
                 "x_origin_m": 100., "y_origin_m": 200., "rotation_degrees": 0.,
                 "row_axis": "south_to_north", "layer_surfaces_m": [0., -10., -30.]},
        "strata": [{"id": "aquifer", "name": "Synthetic aquifer", "layer_indices": [0, 1]}],
        "materials": [{"id": "sand", "name": "Synthetic sand", "kx_m_day": 2., "ky_m_day": 3.,
                       "kz_m_day": 4., "ss_per_m": 1e-5, "porosity": .25}],
        "assignments": [{"material_id": "sand", "stratum_id": "aquifer",
                         "cells": [list(cell) for cell in np.ndindex(shape)]}],
        "initial_head_m": [10.] * math.prod(shape),
        "periods": [{"duration_day": 3., "nsteps": 2, "steady": True}],
        "boundaries": [{"kind": "CHD", "period": 0, "cell": [0, 0, 0],
                        "values": {"head_m": 10.}, "label": "synthetic_anchor"}]}
    case = WorkflowCase.from_dict(data)
    # Independently generated from hand-defined centre coordinates, without preview_grid.
    x = np.array([101., 103., 105., 107.])[None, None, :]
    y = np.array([201.5, 204.5, 207.5])[None, :, None]
    z = np.array([-5., -20.])[:, None, None]
    heads = np.asarray([2*x + 3*y - 4*z + 7*t for t in (1., 3.)])
    return AnalysisVolume.from_arrays(case, [1., 3.], heads, provenance="Authored affine analytical fixture")


def observations(volume, records=None):
    data = volume.case.to_dict()
    if records is None:
        records = [{"id": "synthetic-1", "time_day": 1., "cell": [0, 0, 0], "head_m": 832.5,
                    "sigma_m": 1., "basis": "synthetic", "provenance": "Authored known residual"}]
    return {"schema": "basinlens-head-observations-v1", "project_id": data["project"]["id"],
            "case_sha256": volume.case_sha256, "crs": data["project"]["crs"],
            "vertical_datum": data["project"]["vertical_datum"], "units": {"head": "m", "time": "day"},
            "observations": records}


class VolumeSamplingTests(unittest.TestCase):
    def test_captured_arrays_and_metadata_are_immutable_independent_copies(self):
        volume = fixture()
        original = volume.case.to_dict()
        returned = volume.case.to_dict(); returned["project"]["id"] = "other"
        volume.times_day[0] = 100
        source = volume.source; source["case_sha256"] = "0" * 64
        volume._preview["cells"][0]["kx_m_day"] = 999
        self.assertEqual(volume.case.to_dict(), original)
        self.assertEqual(volume.times_day.tolist(), [1., 3.])
        self.assertNotEqual(volume.source["case_sha256"], "0" * 64)
        self.assertEqual(volume.source["kind"], "AUTHORED_ARRAYS")
        self.assertEqual(volume.query([[101., 201.5, -5.]], field="kx_m_day")["rows"][0]["value"], 2.)
        with self.assertRaises(AttributeError):
            volume._case_json = b"{}"
        with self.assertRaises(ValueError):
            volume._heads.flags.writeable = True

    def test_piecewise_constant_cell_ownership_and_unclamped_exterior(self):
        result = fixture().query([[100., 200., 0.], [102., 203., -10.],
                                  [108., 204., -5.], [101., 209., -5.],
                                  [101., 201., -30.], [99.999, 201., -5.] ], time_day=1.)
        self.assertEqual([r["supported"] for r in result["rows"]], [True, True, False, False, False, False])
        self.assertEqual(result["rows"][0]["value"], 833.5)
        self.assertEqual([result["rows"][1][k] for k in ("layer", "row", "column")], [1, 1, 1])
        self.assertEqual(result["rows"][1]["value"], 906.5)
        self.assertTrue(all(r["value"] is None for r in result["rows"][2:]))

    def test_trilinear_interpolation_reproduces_independent_affine_field(self):
        points = np.array([[101., 201.5, -5.], [107., 207.5, -20.], [104.2, 205.3, -12.4]])
        result = fixture().query(points, spatial_method="linear_centres", time_day=2., temporal_method="linear")
        expected = 2 * points[:, 0] + 3 * points[:, 1] - 4 * points[:, 2] + 14
        np.testing.assert_allclose([r["value"] for r in result["rows"]], expected, rtol=0, atol=2e-13)
        self.assertEqual(result["temporal_support"]["saved_indices"], [0, 1])
        self.assertEqual(result["temporal_support"]["upper_weight"], .5)

    def test_linear_centres_masks_between_edge_and_first_centre(self):
        rows = fixture().query([[100.9, 204.5, -10.], [103., 207.6, -10.], [103., 204.5, -20.1]],
                               spatial_method="linear_centres")["rows"]
        self.assertTrue(all(not r["supported"] and r["value"] is None for r in rows))
        self.assertTrue(all(r["layer"] is not None for r in rows))

    def test_singleton_interpolation_axis_only_supports_its_centre(self):
        case = load_workflow_case(EXAMPLE)
        heads = np.ones((1, *case.shape)) * 12
        volume = AnalysisVolume.from_arrays(case, [1.], heads, provenance="Authored singleton-axis fixture")
        rows = volume.query([[115., 210., -10.], [115., 210.01, -10.]], spatial_method="linear_centres")["rows"]
        self.assertEqual([r["supported"] for r in rows], [True, False])
        self.assertEqual(rows[0]["value"], 12.)

    def test_material_queries_are_static_and_do_not_accept_time_relabelling(self):
        volume = fixture()
        result = volume.query([[101., 201.5, -5.]], field="kx_m_day")
        self.assertEqual(result["rows"][0]["value"], 2.)
        self.assertEqual(result["value_unit"], "m/day")
        with self.assertRaises(AnalysisError):
            volume.query([[101., 201.5, -5.]], field="porosity", time_day=1.)

    def test_time_exact_and_linear_support_reject_extrapolation(self):
        volume = fixture()
        for time, method in ((2., "exact"), (0., "linear"), (4., "linear"), (True, "exact")):
            with self.subTest(time=time, method=method), self.assertRaises(AnalysisError):
                volume.query([[101., 201.5, -5.]], time_day=time, temporal_method=method)
        self.assertEqual(volume.query([[101., 201.5, -5.]])["temporal_support"]["time_day"], 3.)

    def test_invalid_queries_and_large_arrays_fail(self):
        volume = fixture()
        for points in ([], [[True, 201., -5.]], [[float("nan"), 201., -5.]], [["101", 201., -5.]],
                       [[101., 201.]], np.zeros((100001, 3)), [[10**1000, 0, 0]]):
            with self.subTest(points=str(points)[:60]), self.assertRaises(AnalysisError):
                volume.query(points)
        with self.assertRaises(AnalysisError):
            volume.query([[101., 201.5, -5.]], field="pressure")
        with self.assertRaises(AnalysisError):
            volume.query([[101., 201.5, -5.]], spatial_method="nearest_outside")

    def test_polyline_chainage_keeps_corners_endpoint_and_mask(self):
        result = fixture().section([[101., 201.5], [104., 201.5], [104., 205.5]], [-5., -20.], 2., time_day=1.)
        rows = result["rows"]
        self.assertEqual([r["chainage_m"] for r in rows[::2]], [0., 2., 3., 4., 6., 7.])
        self.assertEqual([(r["x_m"], r["y_m"]) for r in rows[::2]],
                         [(101., 201.5), (103., 201.5), (104., 201.5), (104., 202.5), (104., 204.5), (104., 205.5)])
        self.assertEqual(rows[2]["value"], 837.5)
        outside = fixture().section([[99., 201.5], [101., 201.5]], [-5.], 1.)
        self.assertEqual([r["supported"] for r in outside["rows"]], [False, True, True])

    def test_section_and_frame_budgets_and_declared_moving_frames(self):
        volume = fixture()
        for line, z, spacing in (([[101., 201.], [101., 201.]], [-5.], 1.),
                                 ([[100., 200.], [108., 209.]], [-5.], 1e-6),
                                 ([[100., 200.], [108., 209.]], [], 1.)):
            with self.assertRaises(AnalysisError):
                volume.section(line, z, spacing)
        frames = [{"polyline_xy_m": [[101., 201.5 + i], [107., 201.5 + i]],
                   "z_m": [-5.], "spacing_m": 2., "time_day": time} for i, time in enumerate((1., 3.))]
        result = volume.section_frames(frames)
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual(result["sample_count"], 8)
        self.assertEqual(result["frames"][1]["rows"][0]["y_m"], 202.5)
        self.assertFalse(result["gms_parity_established"])
        with self.assertRaises(AnalysisError):
            volume.section_frames(frames * 51)

    def test_combined_plane_scalar_and_boolean_visibility_is_logical_and(self):
        volume = fixture()
        mask = np.ones(volume.case.shape, dtype=bool)
        mask[0, 1, 2] = False
        result = volume.clip(time_day=1., scalar_min=840., scalar_max=860., plane=[1., 0., 0., -104.], visibility=mask)
        expected = []
        for row in result["rows"]:
            show = row["value"] >= 840 and row["value"] <= 860 and row["x_m"] >= 104 and mask[row["layer"], row["row"], row["column"]]
            expected.append(bool(show))
        self.assertEqual([r["visible"] for r in result["rows"]], expected)
        self.assertEqual(result["visible_cells"], sum(expected))
        self.assertTrue(any(expected))
        self.assertFalse(result["rows"][6]["visible"])

    def test_invalid_clipping_is_not_silently_coerced(self):
        volume = fixture()
        for options in ({"plane": [0., 0., 0., 1.]}, {"plane": [1., 0., 0.]},
                        {"visibility": [1] * 24}, {"visibility": [True]},
                        {"scalar_min": 3., "scalar_max": 2.}, {"scalar_min": float("inf")}):
            with self.subTest(options=str(options)[:80]), self.assertRaises(AnalysisError):
                volume.clip(**options)


class ManualComparisonTests(unittest.TestCase):
    def test_independent_known_residual_bias_weighted_rmse_and_objective(self):
        volume = fixture()
        records = [{"id": "one", "time_day": 1., "cell": [0, 0, 0], "head_m": 832.5,
                    "sigma_m": 1., "basis": "synthetic", "provenance": "Authored residual +1 m"},
                   {"id": "two", "time_day": 3., "cell": [0, 0, 0], "head_m": 850.5,
                    "sigma_m": 2., "basis": "synthetic", "provenance": "Authored residual -3 m"}]
        result = volume.compare_observations(observations(volume, records))
        self.assertEqual([r["residual_m"] for r in result["rows"]], [1., -3.])
        metrics = result["metrics"]
        self.assertEqual(metrics["bias_m"], -1.)
        self.assertAlmostEqual(metrics["rmse_m"], math.sqrt(5))
        self.assertAlmostEqual(metrics["weighted_rmse_m"], math.sqrt(2.6))
        self.assertEqual(metrics["objective_chi_square"], 3.25)
        self.assertAlmostEqual(metrics["normalized_rmse"], math.sqrt(1.625))
        self.assertFalse(result["parameter_fit_performed"])
        self.assertFalse(result["field_validation_established"])

    def test_linear_temporal_comparison_is_explicit_in_each_row(self):
        volume = fixture()
        document = observations(volume)
        document["observations"][0].update(time_day=2., head_m=840.5)
        with self.assertRaises(AnalysisError):
            volume.compare_observations(document)
        result = volume.compare_observations(document, temporal_method="linear")
        self.assertEqual(result["rows"][0]["residual_m"], 0.)
        self.assertEqual(result["rows"][0]["temporal_support_kind"], "declared_linear_temporal_interpolation")
        self.assertEqual(result["observation_temporal_support"][0]["saved_times_day"], [1., 3.])

    def test_mismatched_units_crs_datum_and_other_case_are_rejected(self):
        volume = fixture()
        for key, value in (("units", {"head": "ft", "time": "day"}), ("crs", "EPSG:4326"),
                           ("vertical_datum", "MSL"), ("case_sha256", "0" * 64), ("project_id", "other")):
            document = observations(volume); document[key] = value
            with self.subTest(key=key), self.assertRaises(AnalysisError):
                volume.compare_observations(document)

    def test_unknown_labels_are_preserved_without_claiming_known_georeferencing(self):
        case = load_workflow_case(EXAMPLE)
        volume = AnalysisVolume.from_arrays(case, [1.], np.ones((1, *case.shape)) * 12, provenance="Authored unknown CRS example")
        result = volume.compare_observations(observations(volume))
        self.assertEqual(result["crs"], "unknown")
        self.assertIn("unknown label remains unknown", result["metadata_scope"])

    def test_invalid_missing_duplicate_outside_and_oversized_observations_fail(self):
        volume = fixture()
        changes = [lambda d: d["observations"][0].update(sigma_m=0),
                   lambda d: d["observations"][0].update(time_day=None),
                   lambda d: d["observations"][0].update(time_day=True),
                   lambda d: d["observations"][0].update(cell=[0, 3, 0]),
                   lambda d: d["observations"][0].update(cell=[False, 0, 0]),
                   lambda d: d["observations"][0].update(time_day=10),
                   lambda d: d["observations"][0].pop("provenance"),
                   lambda d: d["observations"][0].update(basis="truth"),
                   lambda d: d["observations"].append(copy.deepcopy(d["observations"][0])),
                   lambda d: d.update(observations=d["observations"] * 5001)]
        for change in changes:
            document = observations(volume); change(document)
            with self.assertRaises(AnalysisError):
                volume.compare_observations(document)


class AnalysisBundleTests(unittest.TestCase):
    def test_csv_json_manifest_roundtrip_and_existing_output_refusal(self):
        result = fixture().section([[101., 201.5], [107., 201.5]], [-5.], 1.)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = write_analysis_bundle(result, root / "section")
            manifest = verify_analysis_bundle(folder)
            self.assertEqual(manifest["source"], result["source"])
            self.assertEqual(json.loads((folder / "analysis.json").read_text()), result)
            with self.assertRaises(FileExistsError):
                write_analysis_bundle(result, folder)
            with (folder / "samples.csv").open("a") as stream:
                stream.write("altered\n")
            with self.assertRaises(AnalysisError):
                verify_analysis_bundle(folder)

    def test_missing_extra_symlink_and_nonfinite_bundle_fail(self):
        result = fixture().clip()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for mutation in ("missing", "extra", "symlink"):
                folder = write_analysis_bundle(result, root / mutation)
                if mutation == "missing":
                    (folder / "samples.csv").unlink()
                elif mutation == "extra":
                    (folder / "extra.txt").write_text("extra")
                else:
                    target = root / "elsewhere.csv"
                    (folder / "samples.csv").rename(target)
                    (folder / "samples.csv").symlink_to(target)
                with self.assertRaises(AnalysisError):
                    verify_analysis_bundle(folder)
            bad = copy.deepcopy(result); bad["rows"][0]["value"] = float("nan")
            with self.assertRaises(AnalysisError):
                write_analysis_bundle(bad, root / "bad")
            self.assertFalse((root / "bad").exists())

    def test_malformed_manifest_or_json_types_report_analysis_error(self):
        result = fixture().clip()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = write_analysis_bundle(result, root / "manifest-list")
            path = folder / "manifest.json"
            manifest = json.loads(path.read_text()); manifest["files"] = ["analysis.json", "samples.csv"]
            path.write_text(json.dumps(manifest))
            with self.assertRaises(AnalysisError):
                verify_analysis_bundle(folder)
            folder = write_analysis_bundle(result, root / "result-list")
            raw = b"[]\n"; (folder / "analysis.json").write_bytes(raw)
            path = folder / "manifest.json"; manifest = json.loads(path.read_text())
            manifest["files"]["analysis.json"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            path.write_text(json.dumps(manifest))
            with self.assertRaises(AnalysisError):
                verify_analysis_bundle(folder)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO special files unavailable")
    def test_fifo_input_is_rejected_without_blocking(self):
        from basinlens_ccs.subsurface.analysis import _read
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "fifo.json"; os.mkfifo(fifo)
            with self.assertRaises(AnalysisError):
                _read(fifo)


@unittest.skipUnless(SOLVER, "Actual MF6 executable required")
class ActualRunAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.case = load_workflow_case(EXAMPLE)
        cls.native_run = run_workflow(cls.case, cls.root / "run", exe_name=SOLVER)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_mf6_exact_cell_query_and_known_manual_residual(self):
        before = {p.relative_to(self.native_run.workspace): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.native_run.workspace.rglob("*") if p.is_file()}
        volume = load_analysis_run(self.native_run.workspace)
        self.assertEqual(volume.source["kind"], "VERIFIED_WORKFLOW_RUN")
        self.assertEqual(volume.case, self.case)
        # Captured CHD support is exactly 12 m at the first western boundary.
        self.assertAlmostEqual(volume.query([[105., 210., -5.]], time_day=1.)["rows"][0]["value"], 12., places=12)
        document = observations(volume)
        document["observations"][0].update(head_m=11.5, sigma_m=.25)
        result = volume.compare_observations(document)
        self.assertAlmostEqual(result["metrics"]["rmse_m"], .5)
        self.assertAlmostEqual(result["metrics"]["objective_chi_square"], 4.)
        folder = write_analysis_bundle(result, self.root / "actual-comparison")
        self.assertEqual(verify_analysis_bundle(folder)["source"], volume.source)
        after = {p.relative_to(self.native_run.workspace): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.native_run.workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        with self.assertRaises(AnalysisError):
            write_analysis_bundle(result, self.native_run.workspace / "analysis")

    def test_cli_actual_section_clip_query_compare_and_bad_input(self):
        root = self.root / "cli"; root.mkdir()
        base = [str(self.native_run.workspace)]
        main(["section", *base, "--polyline", "[[105,210],[145,210]]", "--z", "[-5,-20]", "--spacing", "5", "--output", str(root / "section")])
        main(["clip", *base, "--plane", "[1,0,0,-120]", "--scalar-min", "10", "--output", str(root / "clip")])
        main(["query", *base, "--points", "[[105,210,-5],[145,210,-20]]", "--output", str(root / "query")])
        document = observations(load_analysis_run(self.native_run.workspace))
        path = root / "observations.json"; path.write_text(json.dumps(document))
        main(["compare", *base, str(path), "--output", str(root / "compare")])
        for name in ("section", "clip", "query", "compare"):
            verify_analysis_bundle(root / name)
        with self.assertRaises(SystemExit) as error:
            main(["query", *base, "--points", "[[true,210,-5]]", "--output", str(root / "bad")])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((root / "bad").exists())

    def test_modified_captured_run_is_rejected_and_snapshot_not_relabelled(self):
        copied = self.root / "altered"; shutil.copytree(self.native_run.workspace, copied)
        volume = load_analysis_run(copied)
        result = volume.clip()
        with (copied / "native/flow.hds").open("ab") as stream:
            stream.write(b"altered")
        with self.assertRaises((ValueError, RuntimeError)):
            load_analysis_run(copied)
        with self.assertRaises((ValueError, RuntimeError)):
            write_analysis_bundle(result, self.root / "refused-altered-analysis")
        self.assertFalse((self.root / "refused-altered-analysis").exists())


if __name__ == "__main__":
    unittest.main()
