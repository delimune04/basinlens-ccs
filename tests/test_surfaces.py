"""Independent explicit-plane, wedge-volume, topology and IO checks."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from basinlens_ccs.subsurface.surfaces import (
    SurfaceError, SurfaceModel, edit_vertices, export_surface_tables,
    extrude_solids, import_surface_tables, load_surfaces, query_surface,
    save_surfaces, section_surfaces, smooth_horizon, verify_surface_roundtrip,
)


def plane():
    # Rectangle area 8 m2. Upper z=10+x+2y; lower z=5+x+y.
    # Thickness=5+y; integral=(5+1)*8 = 48 m3.
    return {"schema": "basinlens-surfaces-v1", "id": "synthetic-planes", "name": "Authored tilted planes", "units": {"length": "m", "elevation": "m", "volume": "m3"}, "crs": "LOCAL:explicit synthetic XY metres", "vertical_datum": "LOCAL:authored z=0", "provenance": ["Authored synthetic analytical planes; no field measurements"], "vertices": [{"id": "A", "x_m": 0, "y_m": 0}, {"id": "B", "x_m": 4, "y_m": 0}, {"id": "C", "x_m": 4, "y_m": 2}, {"id": "D", "x_m": 0, "y_m": 2}], "triangles": [{"id": "T0", "vertex_ids": ["A", "B", "C"]}, {"id": "T1", "vertex_ids": ["A", "C", "D"]}], "horizons": [{"id": "top", "name": "Top interpreted horizon", "elevations_m": [10, 14, 18, 14]}, {"id": "base", "name": "Base interpreted horizon", "elevations_m": [5, 9, 11, 7]}], "layers": [{"id": "layer-0", "name": "Synthetic wedge", "material_id": "synthetic-sand"}], "history": []}


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.model = SurfaceModel.from_dict(plane())

    def test_planar_interpolation_boundary_mask_and_metadata(self):
        result = query_surface(self.model, "top", [[1, 0.5], [0, 0], [4, 2], [2, 1], [4.1, 1]])
        for row, expected in zip(result["points"][:4], [12, 10, 18, 14]):
            self.assertTrue(row["supported"])
            self.assertAlmostEqual(row["elevation_m"], expected)
            self.assertAlmostEqual(sum(row["weights"]), 1)
        self.assertFalse(result["points"][4]["supported"])
        self.assertIsNone(result["points"][4]["elevation_m"])
        self.assertEqual(result["points"][3]["triangle_id"], "T0")
        self.assertEqual(result["source_sha256"], self.model.sha256)
        self.assertEqual(result["crs"], plane()["crs"])

    def test_exact_wedge_volumes_closed_faces_and_orientation(self):
        result = extrude_solids(self.model)
        self.assertEqual(result["total_volume_m3"], 48)
        self.assertEqual(len(result["solids"]), 2)
        self.assertAlmostEqual(result["solids"][0]["volume_m3"], 4 * (5 + 5 + 7) / 3)
        for prism in result["solids"]:
            self.assertEqual(prism["material_id"], "synthetic-sand")
            # Each oriented closed-shell edge occurs twice in opposite directions.
            oriented = []
            for face in prism["faces"]:
                oriented.extend(zip(face, face[1:] + face[:1]))
            for a, b in oriented:
                self.assertEqual(oriented.count((b, a)), 1)
            # Independent signed tetrahedron integral from triangulated outward faces.
            volume = 0
            xyz = prism["vertices_xyz_m"]
            for face in prism["faces"]:
                a = xyz[face[0]]
                for j in range(1, len(face) - 1):
                    b, c = xyz[face[j]], xyz[face[j + 1]]
                    volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) + a[1] * (b[2] * c[0] - b[0] * c[2]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
            self.assertAlmostEqual(volume, prism["volume_m3"])

    def test_prism_ids_cannot_collide_when_literal_ids_contain_separators(self):
        data = plane()
        data["triangles"][0]["id"] = "b:c"
        data["triangles"][1]["id"] = "c"
        data["horizons"].append({"id": "deep", "name": "Deep plane", "elevations_m": [0, 0, 0, 0]})
        data["layers"][0]["id"] = "a"
        data["layers"].append({"id": "a:b", "name": "Second layer", "material_id": "second"})
        solids = extrude_solids(SurfaceModel.from_dict(data))["solids"]
        self.assertEqual(len({s["id"] for s in solids}), 4)
        self.assertEqual({s["layer_id"] for s in solids}, {"a", "a:b"})

    def test_polyline_section_clips_domain_and_uses_true_distances(self):
        result = section_surfaces(self.model, [[-1, 1], [5, 1], [5, 3]])
        self.assertEqual(result["total_polyline_length_m"], 8)
        self.assertEqual(len(result["pieces"]), 2)
        intervals = [p["distance_m"] for p in result["pieces"]]
        self.assertEqual(intervals, [[1, 3], [3, 5]])
        for p in result["pieces"]:
            self.assertEqual(p["segment_index"], 0)
            for xy, z in zip(p["endpoints_xy_m"], p["horizons"][0]["elevations_m"]):
                self.assertAlmostEqual(z, 10 + xy[0] + 2 * xy[1])
            self.assertEqual(p["bands"][0]["material_id"], "synthetic-sand")
        self.assertEqual(result["source_sha256"], self.model.sha256)

    def test_shared_edge_section_not_double_counted(self):
        result = section_surfaces(self.model, [[0, 0], [4, 2]])
        self.assertEqual(len(result["pieces"]), 1)
        self.assertEqual(result["pieces"][0]["triangle_id"], "T0")
        self.assertAlmostEqual(result["pieces"][0]["distance_m"][1], math.sqrt(20))

    def test_distant_component_never_expands_small_triangle_query_support(self):
        data = plane()
        coordinates = [(0, 0), (2, 0), (0, 1), (1e6, 0), (1e6 + 2, 0), (1e6, 2)]
        data["vertices"] = [{"id": str(i), "x_m": x, "y_m": y} for i, (x, y) in enumerate(coordinates)]
        data["triangles"] = [{"id": "small", "vertex_ids": ["0", "1", "2"]}, {"id": "distant", "vertex_ids": ["3", "4", "5"]}]
        data["horizons"][0]["elevations_m"] = [10] * 6
        data["horizons"][1]["elevations_m"] = [0] * 6
        model = SurfaceModel.from_dict(data)
        result = query_surface(model, "top", [[-0.1, 0.2], [0, 0.2]])
        self.assertFalse(result["points"][0]["supported"])
        self.assertTrue(result["points"][1]["supported"])
        self.assertEqual(section_surfaces(model, [[-0.1, 0.1], [-0.1, 0.5]])["pieces"], [])

    def test_hole_and_disconnected_domain_are_not_filled(self):
        data = plane()
        data["vertices"] = [{"id": str(i), "x_m": x, "y_m": y} for i, (x, y) in enumerate([(0, 0), (1, 0), (0, 1), (2, 0), (3, 0), (3, 1)])]
        data["triangles"] = [{"id": "left", "vertex_ids": ["0", "1", "2"]}, {"id": "right", "vertex_ids": ["3", "4", "5"]}]
        data["horizons"][0]["elevations_m"] = [10] * 6
        data["horizons"][1]["elevations_m"] = [0] * 6
        model = SurfaceModel.from_dict(data)
        self.assertFalse(query_surface(model, "top", [[1.5, 0.25]])["points"][0]["supported"])
        intervals = [p["distance_m"] for p in section_surfaces(model, [[0, 0.25], [3, 0.25]])["pieces"]]
        self.assertEqual(intervals, [[0, 0.75], [2.25, 3]])

    def test_traceable_edit_preserves_original_and_rejects_crossing(self):
        before = self.model.to_dict()
        edited = edit_vertices(self.model, horizon_id="top", elevations={"A": 11}, reason="explicit synthetic alternative")
        self.assertEqual(self.model.to_dict(), before)
        self.assertEqual(edited.to_dict()["horizons"][0]["elevations_m"][0], 11)
        self.assertEqual(edited.to_dict()["history"][-1]["source_sha256"], self.model.sha256)
        with self.assertRaisesRegex(SurfaceError, "cross"):
            edit_vertices(self.model, horizon_id="top", elevations={"A": 4}, reason="invalid crossing")
        with self.assertRaises(SurfaceError):
            edit_vertices(self.model, xy={"B": [0, 0]}, reason="invalid duplicate XY")

    def test_fixed_boundary_jacobi_smoothing_independent_average(self):
        data = plane()
        data["vertices"].append({"id": "E", "x_m": 2, "y_m": 1})
        data["triangles"] = [{"id": str(i), "vertex_ids": tri} for i, tri in enumerate([["A", "B", "E"], ["B", "C", "E"], ["C", "D", "E"], ["D", "A", "E"]])]
        data["horizons"][0]["elevations_m"].append(30)
        data["horizons"][1]["elevations_m"].append(8)
        model = SurfaceModel.from_dict(data)
        smoothed = smooth_horizon(model, "top", iterations=1, weight=0.5, reason="synthetic editing example")
        z = smoothed.to_dict()["horizons"][0]["elevations_m"]
        self.assertEqual(z[:4], [10, 14, 18, 14])
        self.assertEqual(z[4], 22)  # 0.5*30 + 0.5*mean(10,14,18,14)
        self.assertEqual(smoothed.to_dict()["history"][-1]["parameters"]["fixed_boundary_vertex_ids"], ["A", "B", "C", "D"])
        self.assertEqual(model.to_dict()["horizons"][0]["elevations_m"][4], 30)

    def test_orientation_degenerate_overlap_tjunction_and_nonmanifold_rejected(self):
        variants = []
        a = plane(); a["triangles"][0]["vertex_ids"] = ["C", "B", "A"]; variants.append(a)
        a = plane(); a["vertices"][2].update(x_m=2, y_m=0); variants.append(a)
        a = plane(); a["triangles"].append({"id": "duplicate", "vertex_ids": ["A", "B", "C"]}); variants.append(a)
        a = plane(); a["vertices"].extend([{"id": "E", "x_m": 1, "y_m": 0.2}, {"id": "F", "x_m": 2, "y_m": 0.2}, {"id": "G", "x_m": 1, "y_m": 0.4}]); a["triangles"].append({"id": "inside", "vertex_ids": ["E", "F", "G"]}); variants.append(a)
        a = plane(); a["vertices"].extend([{"id": "E", "x_m": 2, "y_m": 0}, {"id": "F", "x_m": 1, "y_m": -1}]); a["triangles"].append({"id": "T-junction", "vertex_ids": ["A", "F", "E"]}); variants.append(a)
        a = plane(); a["vertices"].append({"id": "E", "x_m": 2, "y_m": -1}); a["triangles"].append({"id": "crossing", "vertex_ids": ["E", "C", "D"]}); variants.append(a)
        for data in variants:
            # Match horizon lengths so rejection exercises topology, not length.
            for h in data["horizons"]:
                h["elevations_m"].extend([h["elevations_m"][0]] * (len(data["vertices"]) - len(h["elevations_m"])))
            with self.subTest(triangles=data["triangles"]), self.assertRaises(SurfaceError):
                SurfaceModel.from_dict(data)

    def test_contract_rejects_unknown_units_missing_metadata_and_nonfinite(self):
        mutations = [("units", {"length": "ft", "elevation": "m", "volume": "m3"}), ("crs", ""), ("history", [{}])]
        for key, value in mutations:
            data = plane(); data[key] = value
            with self.subTest(key=key), self.assertRaises(SurfaceError):
                SurfaceModel.from_dict(data)
        for value in [True, float("nan"), float("inf"), 10 ** 1000]:
            data = plane(); data["vertices"][0]["x_m"] = value
            with self.subTest(value=str(value)[:20]), self.assertRaises(SurfaceError):
                SurfaceModel.from_dict(data)
        for value in [b"{}", b"not JSON", "{}", b'{"schema":1,"schema":2}']:
            with self.assertRaises(SurfaceError):
                SurfaceModel(value).to_dict()

    def test_nonmanifold_vertex_fans_and_hidden_table_values_rejected(self):
        data = plane()
        data["vertices"].extend([{"id": "E", "x_m": -2, "y_m": 0}, {"id": "F", "x_m": 0, "y_m": -2}])
        data["triangles"].append({"id": "separate-fan", "vertex_ids": ["A", "E", "F"]})
        for h in data["horizons"]:
            h["elevations_m"].extend([h["elevations_m"][0]] * 2)
        with self.assertRaisesRegex(SurfaceError, "nonmanifold vertex"):
            SurfaceModel.from_dict(data)
        with tempfile.TemporaryDirectory() as td:
            tables = export_surface_tables(self.model, Path(td) / "tables")
            manifest_path = tables / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["metadata"]["horizons"][0]["elevations_m"] = [999] * 4
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(SurfaceError, "table horizon metadata"):
                import_surface_tables(tables)

    def test_real_json_csv_roundtrip_relocation_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = save_surfaces(self.model, root / "source.json")
            before = source.read_bytes()
            receipt = verify_surface_roundtrip(source, root / "roundtrip")
            self.assertTrue(receipt["source_unchanged"])
            self.assertTrue(receipt["json_and_csv_semantics_equal"])
            self.assertEqual(receipt["original_gms_comparison"], "NOT_OBSERVED")
            self.assertEqual(source.read_bytes(), before)
            moved = root / "relocated"; (root / "roundtrip" / "tables").rename(moved)
            self.assertEqual(import_surface_tables(moved).to_dict(), self.model.to_dict())
            with self.assertRaises(SurfaceError):
                save_surfaces(self.model, source)
            with self.assertRaises(SurfaceError):
                verify_surface_roundtrip(source, root / "roundtrip")
            with self.assertRaises(SurfaceError):
                export_surface_tables(self.model, moved)

    def test_modified_missing_extra_table_and_symlinks_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tables = export_surface_tables(self.model, root / "tables")
            original = (tables / "vertices.csv").read_bytes()
            (tables / "vertices.csv").write_bytes(original.replace(b"0.0", b"9.0", 1))
            with self.assertRaisesRegex(SurfaceError, "changed table"):
                import_surface_tables(tables)
            (tables / "vertices.csv").write_bytes(original)
            (tables / "extra").write_text("unknown")
            with self.assertRaises(SurfaceError):
                import_surface_tables(tables)
            (tables / "extra").unlink()
            (tables / "vertices.csv").unlink(); (tables / "vertices.csv").symlink_to(root / "external")
            (root / "external").write_bytes(original)
            with self.assertRaises(SurfaceError):
                import_surface_tables(tables)
            source = root / "source.json"; source.symlink_to(root / "external")
            with self.assertRaises(SurfaceError):
                load_surfaces(source)

    def test_duplicate_json_and_fifo_rejected_without_wait(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "bad.json"; bad.write_text('{"schema":1,"schema":2}')
            with self.assertRaisesRegex(SurfaceError, "duplicate JSON"):
                load_surfaces(bad)
            if hasattr(os, "mkfifo"):
                fifo = root / "pipe"; os.mkfifo(fifo)
                with self.assertRaises(SurfaceError):
                    load_surfaces(fifo)

    def test_cli_actual_query_section_extrusion_roundtrip_and_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = save_surfaces(self.model, root / "source.json")
            points = root / "points.json"; points.write_text("[[1,0.5],[8,8]]")
            for command, extra in [("check", []), ("query", ["--horizon", "top", "--values", str(points)]), ("section", ["--values", str(points)]), ("extrude", []), ("roundtrip", [])]:
                args = [sys.executable, "-m", "basinlens_ccs.subsurface.surfaces", command, str(source), *extra]
                if command != "check":
                    args.extend(["--output", str(root / command)])
                run = subprocess.run(args, capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 0, run.stderr)
            bad = subprocess.run([sys.executable, "-m", "basinlens_ccs.subsurface.surfaces", "query", str(source), "--horizon", "missing", "--values", str(points), "--output", str(root / "missing")], capture_output=True, text=True, timeout=15)
            self.assertEqual(bad.returncode, 2)
            self.assertIn("unknown horizon", bad.stderr)
            self.assertFalse((root / "missing").exists())


if __name__ == "__main__":
    unittest.main()
