"""Independent scalar formulas and invalid/portable scatter operation checks."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.subsurface.scatter import (
    SCHEMA, ScatterDataset, ScatterError, dataset_math, edit_values,
    interpolate_idw, interpolate_nearest, interpolate_tin,
    load_scatter, save_scatter, verify_scatter_roundtrip,
)


def sample(dim=2, values=(1, 3, 4, 6)):
    coords = [[0, 0], [1, 0], [0, 1], [1, 1]]
    if dim == 3:
        coords = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
    return {"schema": SCHEMA, "id": "synthetic-plane", "dimension": dim,
            "coordinate_unit": "m", "crs": "LOCAL_CARTESIAN_METRES",
            "vertical_datum": "synthetic arbitrary origin", "vertical_axis": "positive_up" if dim == 3 else "not_applicable",
            "quantity": "hydraulic_head", "value_unit": "m", "basis": "synthetic",
            "provenance": ["Authored synthetic fixture; not field measurements"],
            "duplicate_coordinate_policy": "reject",
            "points": [{"id": f"p{i}", "coordinates_m": c, "value": v,
                        "missing_reason": None if v is not None else "unobserved synthetic value"}
                       for i, (c, v) in enumerate(zip(coords, values))]}


class ScatterContractTests(unittest.TestCase):
    def test_json_csv_portable_roundtrip_preserves_missing_and_literal_ids(self):
        obj = sample(values=(1, None, 4, 6))
        obj["points"][0]["id"] = "001, literal quote \" value"
        obj["provenance"].append("한글 synthetic provenance")
        dataset = ScatterDataset.from_dict(obj)
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".csv"):
                p = Path(directory)/("original"+suffix)
                save_scatter(dataset, p)
                raw = p.read_bytes()
                relocated = Path(directory)/("relocated"+suffix)
                relocated.write_bytes(raw)
                self.assertEqual(load_scatter(relocated).to_dict(), dataset.to_dict())
                receipt = verify_scatter_roundtrip(relocated)
                self.assertTrue(receipt["semantic_equal"])
                self.assertEqual(receipt["dataset_sha256"], dataset.sha256)
                self.assertEqual(p.read_bytes(), raw)

    def test_deterministic_fresh_publication_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ("json", "csv"):
                a, b = Path(directory)/("a."+suffix), Path(directory)/("b."+suffix)
                save_scatter(ScatterDataset.from_dict(sample()), a)
                save_scatter(ScatterDataset.from_dict(sample()), b)
                self.assertEqual(a.read_bytes(), b.read_bytes())
                before = a.read_bytes()
                with self.assertRaises(ScatterError):
                    save_scatter(ScatterDataset.from_dict(sample()), a)
                self.assertEqual(a.read_bytes(), before)
            self.assertFalse(list(Path(directory).glob(".scatter-*")))

    def test_duplicate_ids_and_coordinates_rejected_even_if_missing(self):
        for mutate in (lambda o: o["points"][1].update(id="p0"),
                       lambda o: o["points"][1].update(coordinates_m=[0, 0], value=None, missing_reason="missing")):
            obj = sample()
            mutate(obj)
            with self.assertRaises(ScatterError):
                ScatterDataset.from_dict(obj)

    def test_strict_units_datum_values_missing_and_unknown_keys(self):
        changes = [("coordinate_unit", "ft"), ("dimension", True), ("dimension", 4),
                   ("vertical_axis", "positive_down"), ("duplicate_coordinate_policy", "average"),
                   ("crs", ""), ("vertical_datum", None), ("basis", "real"), ("provenance", [])]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ScatterError):
                ScatterDataset.from_dict({**sample(), key: value})
        for value in (float("nan"), float("inf"), True, "3", 10**1000):
            obj = sample()
            obj["points"][0]["value"] = value
            with self.assertRaises(ScatterError):
                ScatterDataset.from_dict(obj)
        obj = sample()
        obj["points"][0]["value"] = None
        with self.assertRaises(ScatterError):
            ScatterDataset.from_dict(obj)
        obj = sample()
        obj["unknown"] = "not silently dropped"
        with self.assertRaises(ScatterError):
            ScatterDataset.from_dict(obj)
        with self.assertRaises(ScatterError):
            ScatterDataset(False).to_dict()

    def test_json_duplicate_nonfinite_and_csv_ragged_unversioned_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/"bad.json"
            for raw in ('{"schema":1,"schema":2}', '{"value":NaN}', '[[[[[[[['):
                p.write_text(raw)
                with self.assertRaises(ScatterError):
                    load_scatter(p)
            csvfile = Path(directory)/"bad.csv"
            csvfile.write_text("id,x,y,value\np0,0,0,1\n")
            with self.assertRaises(ScatterError):
                load_scatter(csvfile)
            save_scatter(ScatterDataset.from_dict(sample()), Path(directory)/"good.csv")
            lines = (Path(directory)/"good.csv").read_text().splitlines()
            csvfile.write_text("\n".join(lines[:2]+["p0,0,0,1,,extra"]))
            with self.assertRaises(ScatterError):
                load_scatter(csvfile)

    def test_fifo_symlink_directory_and_read_budget_fail_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            regular = path/"data.json"
            save_scatter(ScatterDataset.from_dict(sample()), regular)
            symlink = path/"alias.json"
            symlink.symlink_to(regular)
            with self.assertRaises(ScatterError):
                load_scatter(symlink)
            with self.assertRaises(ScatterError):
                load_scatter(path)
            if hasattr(os, "mkfifo"):
                fifo = path/"fifo.json"
                os.mkfifo(fifo)
                with self.assertRaises(ScatterError):
                    load_scatter(fifo)
            with patch("basinlens_ccs.subsurface.scatter.MAX_BYTES", 100):
                with self.assertRaises(ScatterError):
                    load_scatter(regular)
                with self.assertRaises(ScatterError):
                    save_scatter(ScatterDataset.from_dict(sample()), path/"large.json")

    def test_explicit_edit_is_immutable_traceable_and_missing(self):
        original = ScatterDataset.from_dict(sample())
        result = edit_values(original, {"p0": 9, "p1": None}, missing_reason="explicitly removed")
        self.assertEqual(original.to_dict()["points"][0]["value"], 1)
        self.assertEqual(result.to_dict()["points"][0]["value"], 9)
        self.assertEqual(result.to_dict()["points"][1]["missing_reason"], "explicitly removed")
        self.assertIn(original.sha256, result.to_dict()["provenance"][-1])
        self.assertEqual(result.to_dict()["basis"], "interpreted")
        for edits in ({}, {"unknown": 0}, {"p0": "invalid"}):
            with self.assertRaises(ScatterError):
                edit_values(original, edits)
        obj = sample()
        obj["provenance"] *= 32
        with self.assertRaises(ScatterError):
            edit_values(ScatterDataset.from_dict(obj), {"p0": 0})


class ScatterMathTests(unittest.TestCase):
    def test_add_subtract_and_ratio_shared_support_order_independent(self):
        a = ScatterDataset.from_dict(sample())
        obj = sample(values=(2, 6, 8, 12))
        obj["points"].reverse()
        b = ScatterDataset.from_dict(obj)
        for op, expected, quantity, unit in (("+", [3, 9, 12, 18], "hydraulic_head", "m"),
                                              ("-", [-1, -3, -4, -6], "hydraulic_head", "m"),
                                              ("/", [.5]*4, "ratio", "1")):
            result = dataset_math(a, op, b, result_id="computed", result_quantity=quantity, result_unit=unit)
            self.assertEqual([p["value"] for p in result.to_dict()["points"]], expected)
            self.assertIn(a.sha256, result.to_dict()["provenance"][0])

    def test_dimensionless_multiplication_and_division(self):
        a = ScatterDataset.from_dict(sample())
        factor = sample(values=(2, 2, 2, 2))
        factor.update(quantity="factor", value_unit="1")
        b = ScatterDataset.from_dict(factor)
        for left, right, op, values in ((a, b, "*", [2, 6, 8, 12]), (b, a, "*", [2, 6, 8, 12]), (a, b, "/", [.5, 1.5, 2, 3])):
            got = dataset_math(left, op, right, result_id="scaled", result_quantity="hydraulic_head", result_unit="m")
            self.assertEqual([p["value"] for p in got.to_dict()["points"]], values)

    def test_missing_propagates_and_invalid_units_support_operator_zero_fail(self):
        a = ScatterDataset.from_dict(sample())
        missing = ScatterDataset.from_dict(sample(values=(None, 2, 3, 4)))
        result = dataset_math(a, "+", missing, result_id="missing", result_quantity="hydraulic_head", result_unit="m")
        self.assertIsNone(result.to_dict()["points"][0]["value"])
        for obj in (dict(sample(), crs="EPSG:9999"), dict(sample(), value_unit="ft")):
            with self.assertRaises(ScatterError):
                dataset_math(a, "+", ScatterDataset.from_dict(obj), result_id="bad", result_quantity="hydraulic_head", result_unit="m")
        obj = sample()
        obj["points"][0]["coordinates_m"] = [0, .1]
        with self.assertRaises(ScatterError):
            dataset_math(a, "+", ScatterDataset.from_dict(obj), result_id="bad", result_quantity="hydraulic_head", result_unit="m")
        for op, right in (("__import__", a), ("*", a), ("/", ScatterDataset.from_dict(sample(values=(0, 1, 1, 1))))):
            with self.assertRaises(ScatterError):
                dataset_math(a, op, right, result_id="bad", result_quantity="hydraulic_head", result_unit="m")
        with self.assertRaises(ScatterError):
            dataset_math(a, "+", a, result_id="bad", result_quantity="pressure", result_unit="Pa")
        large = ScatterDataset.from_dict(sample(values=(1e100,)*4))
        with self.assertRaises(ScatterError):
            dataset_math(large, "+", large, result_id="bad", result_quantity="hydraulic_head", result_unit="m")


class ScatterInterpolationTests(unittest.TestCase):
    def test_idw_exact_constant_and_hand_weighted_two_point_case(self):
        ds = ScatterDataset.from_dict(sample())
        self.assertEqual(interpolate_idw(ds, [[0, 0]])["rows"][0]["value"], 1)
        constant = ScatterDataset.from_dict(sample(values=(17,)*4))
        rows = interpolate_idw(constant, [[.2, .7], [.5, .5]])["rows"]
        for row in rows:
            self.assertAlmostEqual(row["value"], 17)
        obj = sample(values=(0, 10, 0, 0))
        obj["points"] = obj["points"][:2]
        result = interpolate_idw(ScatterDataset.from_dict(obj), [[.25, 0]], power=2, max_neighbors=2)
        # Distances .25 and .75 => weights 16 and 16/9 => value exactly 1.
        self.assertAlmostEqual(result["rows"][0]["value"], 1)
        self.assertFalse(result["receipt"]["uncertainty_estimated"])

    def test_nearest_ties_radius_and_truncation(self):
        ds = ScatterDataset.from_dict(sample())
        row = interpolate_nearest(ds, [[.5, 0]])["rows"][0]
        self.assertEqual(row["value"], 1)
        self.assertEqual(row["source_ids"], ["p0"])
        self.assertTrue(row["truncated"])
        row = interpolate_idw(ds, [[.5, .5]], radius_m=.1)["rows"][0]
        self.assertFalse(row["supported"])
        self.assertEqual(row["reason"], "insufficient_neighbors_within_radius")
        row = interpolate_idw(ds, [[.1, 0]], radius_m=.11, min_neighbors=2)["rows"][0]
        self.assertFalse(row["supported"])
        self.assertEqual(row["source_ids"], ["p0"])
        row = interpolate_idw(ds, [[.5, .5]], max_neighbors=2)["rows"][0]
        self.assertTrue(row["truncated"])
        self.assertEqual(len(row["source_ids"]), 2)

    def test_3d_vertical_anisotropy_changes_weights_and_radius_in_scaled_metric(self):
        obj = sample(3, values=(0, 10, 0, 0))
        obj["points"] = obj["points"][:2]
        obj["points"][0]["coordinates_m"] = [0, 0, 1]
        obj["points"][1]["coordinates_m"] = [2, 0, 0]
        ds = ScatterDataset.from_dict(obj)
        one = interpolate_idw(ds, [[0, 0, 0]], vertical_scale=1, bounds_policy="allow")["rows"][0]
        two = interpolate_idw(ds, [[0, 0, 0]], vertical_scale=2, bounds_policy="allow")["rows"][0]
        self.assertAlmostEqual(one["value"], 2)
        self.assertAlmostEqual(two["value"], 5)
        masked = interpolate_nearest(ds, [[0, 0, 0]], vertical_scale=2, radius_m=1.5, bounds_policy="allow")["rows"][0]
        self.assertFalse(masked["supported"])

    def test_missing_exact_and_outside_masks_are_not_filled(self):
        ds = ScatterDataset.from_dict(sample(values=(None, 3, 4, 6)))
        row = interpolate_idw(ds, [[0, 0]])["rows"][0]
        self.assertIsNone(row["value"])
        self.assertEqual(row["reason"], "exact_source_value_missing")
        row = interpolate_idw(ds, [[.5, .5]])["rows"][0]
        self.assertNotIn("p0", row["source_ids"])
        self.assertEqual(len(row["source_ids"]), 3)
        masked = interpolate_idw(ds, [[2, 2]])["rows"][0]
        allowed = interpolate_idw(ds, [[2, 2]], bounds_policy="allow")["rows"][0]
        self.assertFalse(masked["supported"])
        self.assertTrue(allowed["supported"])
        self.assertTrue(allowed["outside_source_bounds"])
        all_missing = ScatterDataset.from_dict(sample(values=(None,)*4))
        self.assertFalse(interpolate_idw(all_missing, [[.5, .5]])["rows"][0]["supported"])

    def test_invalid_parameters_query_shape_and_pair_budget(self):
        ds = ScatterDataset.from_dict(sample())
        for kwargs in ({"power": 0}, {"power": float("nan")}, {"max_neighbors": True},
                       {"min_neighbors": 9, "max_neighbors": 8}, {"radius_m": 0},
                       {"vertical_scale": 2}, {"bounds_policy": "hidden_extrapolation"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ScatterError):
                interpolate_idw(ds, [[.5, .5]], **kwargs)
        for points in ([], [[.5]], [[.5, .5, 1]], [[True, 0]], [[1e20, 0]]):
            with self.assertRaises(ScatterError):
                interpolate_idw(ds, points)
        with patch("basinlens_ccs.subsurface.scatter.MAX_PAIRS", 3):
            with self.assertRaises(ScatterError):
                interpolate_idw(ds, [[.5, .5]])
        obj = sample(3)
        obj["points"] = obj["points"][:1]
        obj["points"][0]["coordinates_m"] = [0, 0, 1e-320]
        with self.assertRaisesRegex(ScatterError, "underflow"):
            interpolate_idw(ScatterDataset.from_dict(obj), [[0, 0, 0]], vertical_scale=1e-10, bounds_policy="allow")

    def test_large_input_bounded_query_evaluates_and_overbudget_rejected(self):
        obj = sample()
        obj["points"] = [{"id": f"s{i:05}", "coordinates_m": [float(i), 0.0], "value": 7.0, "missing_reason": None} for i in range(20000)]
        ds = ScatterDataset.from_dict(obj)
        result = interpolate_idw(ds, [[.5, 0.0]], max_neighbors=8)
        self.assertAlmostEqual(result["rows"][0]["value"], 7)
        with self.assertRaises(ScatterError):
            interpolate_idw(ds, [[.5, 0.0]]*101)

    def test_linear_tin_independent_affine_plane_and_outside_gap(self):
        ds = ScatterDataset.from_dict(sample())  # z=1+2*x+3*y
        queries = [[0, 0], [.2, .3], [.9, .8], [.5, .5], [2, 2]]
        result = interpolate_tin(ds, queries, [["p0", "p1", "p2"], ["p1", "p3", "p2"]])
        for point, row in zip(queries[:4], result["rows"][:4]):
            self.assertAlmostEqual(row["value"], 1+2*point[0]+3*point[1], places=12)
            self.assertAlmostEqual(sum(row["barycentric_weights"]), 1)
        self.assertFalse(result["rows"][-1]["supported"])
        self.assertEqual(result["rows"][-1]["reason"], "outside_explicit_tin")
        incomplete = interpolate_tin(ds, [[.9, .9]], [["p0", "p1", "p2"]])
        self.assertFalse(incomplete["rows"][0]["supported"])

    def test_tin_orientation_missing_exact_and_boundary_values(self):
        ds = ScatterDataset.from_dict(sample(values=(1, 3, None, 6)))
        result = interpolate_tin(ds, [[0, 0], [.5, 0], [.1, .1], [.25, 1e-13]], [["p2", "p1", "p0"]])
        self.assertEqual(result["rows"][0]["value"], 1)
        self.assertEqual(result["rows"][1]["value"], 2)
        self.assertFalse(result["rows"][2]["supported"])
        self.assertEqual(result["rows"][2]["reason"], "triangle_source_value_missing")
        self.assertTrue(result["rows"][3]["supported"])
        self.assertEqual(result["rows"][3]["barycentric_weights"][0], 0)
        self.assertAlmostEqual(result["rows"][3]["value"], 1.5)

    def test_tin_invalid_degenerate_duplicate_crossing_overlap_and_nonmanifold(self):
        ds = ScatterDataset.from_dict(sample())
        for triangles in ([], [["p0", "p1", "missing"]], [["p0", "p0", "p1"]],
                          [["p0", "p1", "p2"], ["p2", "p0", "p1"]],
                          [["p0", "p1", "p2"], ["p0", "p1", "p3"]]):
            with self.subTest(triangles=triangles), self.assertRaises(ScatterError):
                interpolate_tin(ds, [[.5, .5]], triangles)
        obj = sample()
        obj["points"][2]["coordinates_m"] = [.5, 0]
        with self.assertRaisesRegex(ScatterError, "degenerate"):
            interpolate_tin(ScatterDataset.from_dict(obj), [[.5, 0]], [["p0", "p1", "p2"]])
        crossing = sample()
        coordinates = [[-2,0],[2,0],[0,2],[-2,1],[2,1],[0,-1]]
        crossing["points"] = [{"id": f"c{i}", "coordinates_m": c, "value": 1, "missing_reason": None} for i,c in enumerate(coordinates)]
        with self.assertRaisesRegex(ScatterError, "overlap"):
            interpolate_tin(ScatterDataset.from_dict(crossing), [[0,0]], [["c0","c1","c2"],["c3","c4","c5"]])
        with self.assertRaises(ScatterError):
            interpolate_tin(ScatterDataset.from_dict(sample(3)), [[0, 0, 0]], [["p0", "p1", "p2"]])
        obj = sample()
        obj["points"] += [{"id": "p4", "coordinates_m": [.5, -1], "value": 0, "missing_reason": None}]
        with self.assertRaisesRegex(ScatterError, "non-manifold"):
            interpolate_tin(ScatterDataset.from_dict(obj), [[.1, .1]], [["p0", "p1", "p2"], ["p0", "p1", "p3"], ["p0", "p1", "p4"]])

    def test_tin_large_coordinate_translation_preserves_affine_interpolation(self):
        obj = sample()
        for p in obj["points"]:
            p["coordinates_m"] = [p["coordinates_m"][0]+350000, p["coordinates_m"][1]+4100000]
        result = interpolate_tin(ScatterDataset.from_dict(obj), [[350000.25, 4100000.25]], [["p0", "p1", "p2"]])
        self.assertAlmostEqual(result["rows"][0]["value"], 2.25)


class ScatterCLITests(unittest.TestCase):
    def test_actual_cli_export_roundtrip_query_math_and_failure_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, queries = root/"points.json", root/"queries.json"
            save_scatter(ScatterDataset.from_dict(sample()), source)
            queries.write_text("[[0.5,0.5],[2,2]]")
            triangles = root/"triangles.json"
            triangles.write_text('[["p0","p1","p2"],["p1","p3","p2"]]')
            commands = [
                ["load", str(source), "--output", str(root/"points.csv")],
                ["roundtrip", str(root/"points.csv"), "--output", str(root/"receipt.json")],
                ["query", str(source), str(queries), "--neighbors", "2", "--output", str(root/"query.json")],
                ["query", str(source), str(queries), "--method", "nearest", "--output", str(root/"nearest.json")],
                ["query", str(source), str(queries), "--method", "tin", "--triangles", str(triangles), "--output", str(root/"tin.json")],
                ["math", str(source), "+", str(source), "--id", "sum", "--quantity", "hydraulic_head", "--unit", "m", "--output", str(root/"sum.csv")],
            ]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]/"src")
            for args in commands:
                result = subprocess.run([sys.executable, "-m", "basinlens_ccs.subsurface.scatter", *args], capture_output=True, text=True, env=env, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads((root/"receipt.json").read_text())["semantic_equal"])
            self.assertEqual([p["value"] for p in load_scatter(root/"sum.csv").to_dict()["points"]], [2, 6, 8, 12])
            result = subprocess.run([sys.executable, "-m", "basinlens_ccs.subsurface.scatter", "query", str(source), str(queries), "--power", "0", "--output", str(root/"failed.json")], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((root/"failed.json").exists())
            self.assertTrue((root/"query.json").is_file())


if __name__ == "__main__":
    unittest.main()
