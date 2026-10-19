"""Independent geometry/topology/operational checks; no original GMS assertions."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from basinlens_ccs.subsurface.mesh import (
    MeshError, PlanarMesh, extrude_mesh, read_mesh, refine_quadtree,
    render_data, structured_mesh, to_disv, topology, verify_mesh_roundtrip, write_mesh,
)

FLOPY = importlib.util.find_spec("flopy") is not None
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


def explicit(points, rings):
    return {"schema": "basinlens-planar-mesh-v1", "length_unit": "m", "crs": "LOCAL:synthetic meters, no geodetic registration",
            "vertices": [{"id": i, "x_m": x, "y_m": y} for i, (x, y) in enumerate(points)],
            "cells": [{"id": i, "vertices": ring, "material_id": f"unit-{i}"} for i, ring in enumerate(rings)],
            "provenance": ["Independently authored synthetic test fixture"]}


def signed_face_volume(nodes, faces):
    # Independent divergence-theorem calculation with a translated origin.
    origin = nodes[faces[0][0]]
    xyz = {i: [node[k] - origin[k] for k in ("x_m", "y_m", "z_m")] for i, node in enumerate(nodes)}
    total = []
    for face in faces:
        a = xyz[face[0]]
        for j in range(1, len(face) - 1):
            b, c = xyz[face[j]], xyz[face[j + 1]]
            cross = (b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0])
            total.append(sum(a[k] * cross[k] for k in range(3)) / 6)
    return math.fsum(total)


class MeshGeometryTests(unittest.TestCase):
    def test_nonuniform_frame_all_cell_areas_centres_orientation(self):
        mesh = structured_mesh([350000, 350002, 350005], [4100000, 4100001, 4100004], crs="EPSG:32652", material_id="sand")
        report = topology(mesh)
        self.assertEqual(report["areas_m2"], [2, 3, 6, 9])
        self.assertEqual(report["centres_m"], [(350001, 4100000.5), (350003.5, 4100000.5), (350001, 4100002.5), (350003.5, 4100002.5)])
        self.assertEqual((report["cells"], report["vertices"], report["area_m2"]), (4, 9, 20))
        self.assertEqual((len(report["boundary_edges"]), len(report["interior_edges"])), (8, 4))
        self.assertFalse(report["crs_transform_performed"])

    def test_both_explicit_diagonals_cover_same_area_and_distinct_connectivity(self):
        a = structured_mesh([0, 4], [0, 3], crs="LOCAL", triangulate="sw_ne")
        b = structured_mesh([0, 4], [0, 3], crs="LOCAL", triangulate="nw_se")
        for mesh in (a, b):
            self.assertEqual(topology(mesh)["areas_m2"], [6, 6])
            self.assertEqual(len(topology(mesh)["interior_edges"]), 1)
        self.assertNotEqual(render_data(a)["cells"][0]["ring_m"], render_data(b)["cells"][0]["ring_m"])

    def test_oblique_convex_polygon_centroid_area(self):
        mesh = PlanarMesh.from_dict(explicit([(0, 0), (4, 0), (3, 2), (1, 2)], [[0, 1, 2, 3]]))
        report = topology(mesh)
        self.assertEqual(report["areas_m2"], [6])
        self.assertAlmostEqual(report["centres_m"][0][0], 2)
        self.assertAlmostEqual(report["centres_m"][0][1], 8 / 9)

    def test_interface_hanging_node_is_rejected_then_explicit_shared_node_is_accepted(self):
        points = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (1, .5), (0, 1), (2, .5)]
        bad = explicit(points, [[0, 1, 4, 6], [1, 2, 7, 5], [5, 7, 3, 4]])
        with self.assertRaisesRegex(MeshError, "Nonconforming"):
            PlanarMesh.from_dict(bad)
        bad["cells"][0]["vertices"] = [0, 1, 5, 4, 6]
        mesh = PlanarMesh.from_dict(bad)
        self.assertEqual(topology(mesh)["area_m2"], 2)
        self.assertEqual(len(topology(mesh)["interior_edges"]), 3)

    def test_partial_and_contained_overlap_rejected(self):
        for points in (
            [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1), (3, 1), (3, 3), (1, 3)],
            [(0, 0), (4, 0), (4, 4), (0, 4), (1, 1), (2, 1), (2, 2), (1, 2)],
        ):
            with self.assertRaisesRegex(MeshError, "overlap"):
                PlanarMesh.from_dict(explicit(points, [[0, 1, 2, 3], [4, 5, 6, 7]]))

    def test_self_cross_clockwise_concave_and_degenerate_rejected(self):
        fixtures = [([(0, 0), (2, 2), (0, 2), (2, 0)], [0, 1, 2, 3]),
                    ([(0, 0), (0, 1), (1, 1), (1, 0)], [0, 1, 2, 3]),
                    ([(0, 0), (2, 0), (.5, .5), (2, 2), (0, 2)], [0, 1, 2, 3, 4]),
                    ([(0, 0), (1, 0), (2, 0)], [0, 1, 2])]
        for points, ring in fixtures:
            with self.subTest(points=points), self.assertRaises(MeshError):
                PlanarMesh.from_dict(explicit(points, [ring]))

    def test_strict_schema_ids_units_nonfinite_and_duplicate_vertex_fail(self):
        base = structured_mesh([0, 1], [0, 1], crs="LOCAL").to_dict()
        mutations = [lambda x: x.update(length_unit="feet"), lambda x: x.update(crs=""), lambda x: x.update(crs="EPSG:4326"),
                     lambda x: x.update(unknown=True), lambda x: x["vertices"][0].update(id=True),
                     lambda x: x["vertices"][0].update(x_m=float("nan")), lambda x: x["vertices"][0].update(x_m="0"), lambda x: x["vertices"][0].update(x_m=10**10000),
                     lambda x: x["cells"][0].update(material_id=""), lambda x: x["cells"][0].update(vertices=[0, 1, 99]),
                     lambda x: x["cells"][0].update(vertices=[0, 1, 2, 0]),
                     lambda x: x["vertices"][1].update(x_m=0, y_m=0)]
        for mutation in mutations:
            changed = deepcopy(base)
            mutation(changed)
            with self.assertRaises(MeshError):
                PlanarMesh.from_dict(changed)

    def test_unused_vertex_and_duplicate_cell_rejected(self):
        base = structured_mesh([0, 1], [0, 1], crs="LOCAL").to_dict()
        base["vertices"].append({"id": 4, "x_m": 2, "y_m": 2})
        with self.assertRaisesRegex(MeshError, "Unused"):
            PlanarMesh.from_dict(base)
        base["vertices"].pop()
        cell = deepcopy(base["cells"][0]); cell["id"] = 1; base["cells"].append(cell)
        with self.assertRaises(MeshError):
            PlanarMesh.from_dict(base)

    def test_generation_budget_precision_and_invalid_controls(self):
        for xs, ys in (([0, 0], [0, 1]), ([0, 1e-12], [0, 1]), ([0, True], [0, 1])):
            with self.assertRaises(MeshError):
                structured_mesh(xs, ys, crs="LOCAL")
        with self.assertRaisesRegex(MeshError, "budget"):
            structured_mesh(list(range(102)), list(range(102)), crs="LOCAL")
        with self.assertRaises(MeshError):
            structured_mesh([0, 1], [0, 1], crs="LOCAL", triangulate="auto")


class MeshRefinementTests(unittest.TestCase):
    def test_single_selected_cell_refinement_area_material_and_conforming_interfaces(self):
        mesh = structured_mesh([0, 1, 2], [0, 1], crs="LOCAL", material_id="aquifer")
        refined = refine_quadtree(mesh, bbox_m=[0, 0, .9, 1])
        report = topology(refined)
        self.assertEqual((report["cells"], report["area_m2"]), (5, 2))
        self.assertEqual(sorted(report["areas_m2"]), [.25, .25, .25, .25, 1])
        coarse = [cell for cell in refined.to_dict()["cells"] if len(cell["vertices"]) == 5]
        self.assertEqual(len(coarse), 1)
        self.assertEqual(len(report["interior_edges"]), 6)
        self.assertTrue(all(cell["material_id"] == "aquifer" for cell in refined.to_dict()["cells"]))
        self.assertEqual(topology(mesh)["cells"], 2)
        record = json.loads("".join(note.split(": ", 1)[1] for note in refined.to_dict()["provenance"][1:]))
        self.assertEqual(record["bbox_m"], [0, 0, .9, 1])
        self.assertEqual(record["points_m"], [])
        self.assertEqual(record["additional_levels"], 1)
        canonical = (json.dumps(mesh.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(record["source_mesh_sha256"], hashlib.sha256(canonical).hexdigest())

    def test_multiple_levels_point_and_repeat_refinement_stay_conforming(self):
        mesh = structured_mesh([0, 1, 2], [0, 1], crs="LOCAL")
        refined = refine_quadtree(mesh, levels=3, points_m=[[.1, .1]])
        self.assertEqual(topology(refined)["cells"], 11)
        self.assertEqual(topology(refined)["area_m2"], 2)
        again = refine_quadtree(refined, points_m=[[1.5, .5]])
        self.assertGreater(topology(again)["cells"], 11)
        self.assertEqual(topology(again)["area_m2"], 2)
        self.assertTrue(any(len(cell["vertices"]) > 4 for cell in again.to_dict()["cells"]))

    def test_whole_frame_uniform_levels_and_outside_feature_noop(self):
        mesh = structured_mesh([0, 2], [0, 3], crs="LOCAL")
        self.assertEqual(topology(refine_quadtree(mesh, levels=2))["cells"], 16)
        outside = refine_quadtree(mesh, bbox_m=[4, 4, 5, 5])
        self.assertEqual(topology(outside)["cells"], 1)
        self.assertEqual(topology(outside)["area_m2"], 6)

    def test_refinement_refuses_triangle_invalid_control_and_budget_without_mutation(self):
        mesh = structured_mesh([0, 1], [0, 1], crs="LOCAL")
        original = mesh.to_dict()
        for kwargs in ({"levels": 0}, {"levels": True}, {"levels": 9}, {"max_cells": 3},
                       {"bbox_m": [0, 0, 0, 1]}, {"points_m": [[float("inf"), 0]]}):
            with self.assertRaises(MeshError):
                refine_quadtree(mesh, **kwargs)
            self.assertEqual(mesh.to_dict(), original)
        triangle = structured_mesh([0, 1], [0, 1], crs="LOCAL", triangulate="sw_ne")
        with self.assertRaisesRegex(MeshError, "rectangular"):
            refine_quadtree(triangle)


class MeshExtrusionTests(unittest.TestCase):
    def test_prism_volumes_independent_closed_shell_faces_and_materials(self):
        mesh = refine_quadtree(structured_mesh([1000, 1002, 1005], [2000, 2003], crs="LOCAL"), bbox_m=[1000, 2000, 1001.9, 2003])
        materials = [f"rock-{i}" for i in range(10)]
        solid = extrude_mesh(mesh, [10, 6, -1], vertical_datum="LOCAL elevation datum", material_ids=materials)
        self.assertEqual(solid["total_volume_m3"], 165)
        self.assertEqual(len(solid["cells"]), 10)
        for cell, material in zip(solid["cells"], materials):
            self.assertEqual(cell["material_id"], material)
            self.assertGreater(cell["volume_m3"], 0)
            self.assertAlmostEqual(signed_face_volume(solid["nodes"], cell["faces"]), cell["volume_m3"], places=9)
            all_nodes = set(cell["node_ids"])
            self.assertTrue(all(set(face).issubset(all_nodes) for face in cell["faces"]))
        expected_materials = {node["id"]: set() for node in solid["nodes"]}
        for cell in solid["cells"]:
            for node_id in cell["node_ids"]:
                expected_materials[node_id].add(cell["material_id"])
        self.assertTrue(any(len(values) > 1 for values in expected_materials.values()))
        for node in solid["nodes"]:
            self.assertEqual(node["material_ids"], sorted(expected_materials[node["id"]]))
        ownership = Counter(tuple(sorted(face)) for cell in solid["cells"] for face in cell["faces"])
        self.assertTrue(all(count in (1, 2) for count in ownership.values()))
        self.assertEqual(solid["interior_faces"], 17)
        self.assertFalse(solid["horizon_interpolation_performed"])

    def test_triangular_prism_volume_and_no_implicit_datum(self):
        mesh = structured_mesh([0, 4], [0, 3], crs="LOCAL", triangulate="nw_se")
        solid = extrude_mesh(mesh, [5, 3], vertical_datum="test zero")
        self.assertEqual([cell["volume_m3"] for cell in solid["cells"]], [12, 12])
        self.assertTrue(all(len(cell["faces"]) == 5 for cell in solid["cells"]))
        for args in (([5, 5], "LOCAL"), ([3, 5], "LOCAL"), ([5, 3], "")):
            with self.assertRaises(MeshError):
                extrude_mesh(mesh, args[0], vertical_datum=args[1])
        with self.assertRaises(MeshError):
            extrude_mesh(mesh, [5, 3], vertical_datum="LOCAL", material_ids=["only-one"])

    def test_disv_clockwise_centres_units_layers_without_xy_reflection(self):
        mesh = refine_quadtree(structured_mesh([10, 12, 15], [20, 23], crs="EPSG:32652"), bbox_m=[10, 20, 11.9, 23])
        kwargs = to_disv(mesh, [7, 4, -2])
        self.assertEqual((kwargs["nlay"], kwargs["ncpl"], kwargs["length_units"]), (2, 5, "METERS"))
        vertices = {v[0]: v[1:] for v in kwargs["vertices"]}
        for record, cell in zip(kwargs["cell2d"], mesh.to_dict()["cells"]):
            self.assertEqual(record[4:], list(reversed(cell["vertices"])))
            points = [vertices[i] for i in record[4:]]
            signed = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2
            self.assertLess(signed, 0)
            self.assertTrue(min(p[0] for p in points) < record[1] < max(p[0] for p in points))
        self.assertEqual(kwargs["top"], [7] * 5)
        self.assertEqual(kwargs["botm"], [[4] * 5, [-2] * 5])


class MeshIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.mesh = structured_mesh([0, 1, 3], [0, 2], crs="LOCAL")

    def test_relocated_roundtrip_exact_geometry_ids_metadata_and_source_hash(self):
        source = write_mesh(self.mesh, self.base / "source.json")
        before = source.read_bytes()
        receipt = verify_mesh_roundtrip(source)
        self.assertTrue(receipt["exact_semantic_roundtrip"])
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(read_mesh(source).to_dict(), self.mesh.to_dict())
        self.assertEqual(receipt["original_gms_comparison"], "NOT_OBSERVED")

    def test_output_existing_symlink_and_fifo_source_refused(self):
        source = write_mesh(self.mesh, self.base / "source.json")
        before = source.read_bytes()
        with self.assertRaises(FileExistsError):
            write_mesh(self.mesh, source)
        linked = self.base / "linked.json"; linked.symlink_to(source)
        with self.assertRaises(MeshError):
            read_mesh(linked)
        dangling = self.base / "dangling.json"; dangling.symlink_to(self.base / "missing")
        with self.assertRaises(MeshError):
            write_mesh(self.mesh, dangling)
        if hasattr(os, "mkfifo"):
            fifo = self.base / "fifo"; os.mkfifo(fifo)
            with self.assertRaisesRegex(MeshError, "regular"):
                read_mesh(fifo)
        self.assertEqual(source.read_bytes(), before)

    def test_duplicate_json_nan_malformed_and_oversized_fail_before_acceptance(self):
        path = self.base / "bad.json"
        for raw in (b'{"schema":"one","schema":"two"}', b'{"value":NaN}', b'\xff', b'['):
            path.write_bytes(raw)
            with self.assertRaises(MeshError):
                read_mesh(path)
        with path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(MeshError, "bounded"):
            read_mesh(path)

    def test_cli_generate_refine_extrude_verify_and_render(self):
        def run(*args):
            process = subprocess.run([sys.executable, "-m", "basinlens_ccs.subsurface.mesh", *args], capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            return json.loads(process.stdout)
        source, refined, solid, rendered, native = (self.base / name for name in ("mesh.json", "refined.json", "solid.json", "render.json", "disv.json"))
        run("generate", "--x-edges", "0", "1", "2", "--y-edges", "0", "1", "--crs", "LOCAL", "--output", str(source))
        run("refine", str(source), "--bbox", "0", "0", ".9", "1", "--output", str(refined))
        run("extrude", str(refined), "--surfaces", "10", "5", "--vertical-datum", "LOCAL", "--output", str(solid))
        run("render-data", str(refined), "--output", str(rendered))
        run("disv-data", str(refined), "--surfaces", "10", "5", "--output", str(native))
        self.assertTrue(run("verify", str(refined))["source_unchanged"])
        self.assertEqual(json.loads(solid.read_text())["total_volume_m3"], 10)
        self.assertEqual(len(json.loads(rendered.read_text())["cells"]), 5)


@unittest.skipUnless(FLOPY and SOLVER, "FloPy and actual MF6_EXE/mf6 are required")
class MeshActualMF6Tests(unittest.TestCase):
    def test_refined_disv_fresh_export_reload_actual_uniform_head_and_geometry(self):
        import flopy
        import numpy as np
        from basinlens_ccs.groundwater.native_run import run_native_simulation, verify_native_run
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mesh = refine_quadtree(structured_mesh([350000, 350002, 350005], [4100000, 4100003, 4100007], crs="LOCAL"), bbox_m=[350000, 4100000, 350001.9, 4100002.9], levels=2)
            kwargs = to_disv(mesh, [10, 0])
            simulation = flopy.mf6.MFSimulation(sim_name="mesh-check", sim_ws=str(root / "source"))
            simulation.simulation_data.float_precision = 17
            simulation.simulation_data.float_characters = 26
            flopy.mf6.ModflowTdis(simulation, time_units="DAYS", perioddata=[(1, 1, 1)])
            flopy.mf6.ModflowIms(simulation, outer_dvclose=1e-10, inner_dvclose=1e-11, rcloserecord=1e-9)
            model = flopy.mf6.ModflowGwf(simulation, modelname="mesh", save_flows=True)
            flopy.mf6.ModflowGwfdisv(model, **kwargs)
            flopy.mf6.ModflowGwfic(model, strt=2.5)
            flopy.mf6.ModflowGwfnpf(model, icelltype=0, k=1)
            boundary = sorted({owner for owner, cell in enumerate(mesh.to_dict()["cells"]) if any(set(edge).issubset(cell["vertices"]) for edge in topology(mesh)["boundary_edges"])})
            flopy.mf6.ModflowGwfchd(model, stress_period_data=[((0, i), 3) for i in boundary])
            flopy.mf6.ModflowGwfoc(model, head_filerecord="mesh.hds", budget_filerecord="mesh.cbc", saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
            simulation.write_simulation(silent=True)
            loaded = flopy.mf6.MFSimulation.load(sim_ws=str(root / "source"), verbosity_level=0)
            grid = loaded.get_model().modelgrid
            expected = np.asarray(topology(mesh)["centres_m"])
            np.testing.assert_allclose(np.column_stack([grid.xcellcenters, grid.ycellcenters]), expected, atol=1e-9, rtol=0)
            np.testing.assert_allclose(grid.verts, np.asarray(kwargs["vertices"])[:, 1:], atol=1e-9, rtol=0)
            self.assertEqual([list(map(int, ring)) for ring in grid.iverts], [row[4:] for row in kwargs["cell2d"]])
            np.testing.assert_array_equal(grid.top, kwargs["top"])
            np.testing.assert_array_equal(grid.botm, kwargs["botm"])
            source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "source").iterdir() if p.is_file()}
            result = run_native_simulation(root / "source", root / "run", exe_name=SOLVER, timeout_seconds=30)
            self.assertEqual(verify_native_run(result.workspace)["status"], "completed")
            with flopy.utils.HeadFile(str(result.simulation_workspace / "mesh.hds"), precision="double") as reader:
                heads = reader.get_alldata()
            np.testing.assert_allclose(heads, 3, atol=1e-9, rtol=0)
            self.assertEqual(source_hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "source").iterdir() if p.is_file()})
