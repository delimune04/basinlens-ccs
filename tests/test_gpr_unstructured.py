"""Independent synthetic single-layer prism meshes, not vendor payloads."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

from basinlens_ccs.groundwater.gpr_unstructured import (
    UnstructuredMeshError, compare_with_disv, decode_quadtree_packet, read_gpr_quadtree,
)


def packet_fixture(*, mutation=None, opaque_value=2147483647):
    chunks = [b"Binary QuadtreeGrid3d Version 1\nDIMENSIONS 3\nORIGIN 123 456 999\nANGLE 0\n"
              b"NUMBERING KIJ\nORIENTATION Y_DECREASE X_INCREASE Z_DECREASE\n"]

    def vector(key, values, count=None):
        values = np.asarray(values)
        chunks.append(f"{key} {len(values) if count is None else count}\n".encode())
        data = values.tobytes()
        for offset in range(0, len(data), 31):
            block = data[offset:offset + 31]
            encoded = base64.b64encode(zlib.compress(block)).rstrip(b"=")
            chunks.extend([f"BINARY_BLOCK {len(encoded)} {len(block)}\n".encode(), encoded, b"\n"])

    for key, values in (("X", [0, 2, 5]), ("Y", [0, 3]), ("Z", [0, 1])):
        vector("LOCATIONS_" + key, np.array(values, dtype="<f8"))
    chunks.append(b"NUM_LEVELS 0\n")
    vector("QUAD_GRID_CELL_ARRAY", np.array([opaque_value, 0], dtype="<i4"))
    vector("QUAD_GRID_POINT_ARRAY", np.arange(12, dtype="<i4"))
    chunks.append(b"Binary XmUGrid Version 2\n")
    points = np.array([(x, y, z) for z in (10, 4) for y in (3, 0) for x in (0, 2, 5)], dtype="<f8")
    cells = []
    for top in ([0, 1, 4, 3], [1, 2, 5, 4]):
        bottom = [value + 6 for value in top]
        faces = [top, bottom[::-1], [top[0], top[3], bottom[3], bottom[0]],
                 [top[2], top[1], bottom[1], bottom[2]], [top[1], top[0], bottom[0], bottom[1]],
                 [top[3], top[2], bottom[2], bottom[3]]]
        cells.append([42, 6, *[number for face in faces for number in (4, *face)]])
    stream = np.array(cells, dtype="<i4")
    if mutation == "split_shared_nodes":
        originals = [1, 4, 7, 10]
        points = np.concatenate((points, points[originals]), axis=0)
        positions = (np.array([3, 8, 13, 18, 23, 28])[:, None] + np.arange(4)).ravel()
        values = stream[1, positions].copy()
        for original, replacement in zip(originals, range(12, 16)):
            stream[1, positions[values == original]] = replacement
    if mutation == "face":
        stream[1, 3] = stream[1, 4]
    elif mutation == "index":
        stream[1, 3] = 999
    elif mutation == "winding":
        stream[0, 3:7] = stream[0, 3:7][::-1]
    elif mutation == "cell_type":
        stream[0, 0] = 12
    elif mutation == "nonfinite":
        points[0, 0] = np.nan
    elif mutation == "z":
        points[0, 2] += 1
    vector("LOCATIONS", points, len(points))
    vector("CELL_STREAM", stream.ravel())
    chunks.append(b"UUID 00000000-0000-0000-0000-000000000001\n")
    vector("CELL_TOPS", np.array([10, 10], dtype="<f8"))
    vector("CELL_BOTTOMS", np.array([4, 4], dtype="<f8"))
    vector("CELL_LAYERS", np.array([1, 1], dtype="<i4"))
    return b"".join(chunks)


def native_model(*, top=10, bottom=4, different_edges=False, origin=0):
    import flopy
    simulation = flopy.mf6.MFSimulation()
    model = flopy.mf6.ModflowGwf(simulation)
    x = [0, 2, 5] if not different_edges else [0, 1, 5]
    vertices = [(index, xx, yy) for index, (xx, yy) in enumerate((
        (x[0], 3), (x[1], 3), (x[2], 3), (x[0], 0), (x[1], 0), (x[2], 0)))]
    cells = [(0, (x[0] + x[1]) / 2, 1.5, 4, 0, 1, 4, 3),
             (1, (x[1] + x[2]) / 2, 1.5, 4, 1, 2, 5, 4)]
    flopy.mf6.ModflowGwfdisv(model, nlay=1, ncpl=2, nvert=6, top=top, botm=bottom,
                           vertices=vertices, cell2d=cells, length_units="METERS", xorigin=origin)
    return model


class QuadtreePacketTests(unittest.TestCase):
    def test_exact_faces_and_opaque_wrapper_without_origin_application(self):
        packet = packet_fixture()
        mesh = decode_quadtree_packet(packet)
        self.assertEqual(mesh.faces.shape, (2, 6, 4))
        self.assertEqual(mesh.points.shape, (12, 3))
        self.assertEqual(mesh.topology["boundary_faces"], 10)
        self.assertEqual(mesh.topology["shared_faces"], 1)
        self.assertEqual(mesh.topology["unused_points"], 0)
        self.assertEqual(mesh.packet_sha256, hashlib.sha256(packet).hexdigest())
        np.testing.assert_array_equal(mesh.points[0], [0, 3, 10])
        np.testing.assert_array_equal(mesh.wrapper["origin"], [123, 456, 999])
        self.assertFalse(mesh.receipt()["wrapper_quad_arrays_interpreted"])
        self.assertFalse(mesh.receipt()["wrapper_origin_or_axis_transform_applied"])
        self.assertIsNone(mesh.receipt()["coordinate_units"])
        self.assertNotIn("origin", mesh.receipt())
        self.assertNotIn("bounds", mesh.receipt())
        self.assertFalse(mesh.faces.flags.writeable)
        # Arbitrary opaque values are retained; they are never used as indices.
        changed = decode_quadtree_packet(packet_fixture(opaque_value=-7))
        np.testing.assert_array_equal(changed.points, mesh.points)
        np.testing.assert_array_equal(changed.faces, mesh.faces)

    def test_invalid_faces_indices_winding_types_and_nonfinite_values_fail(self):
        for mutation in ("face", "index", "winding", "cell_type", "nonfinite", "z"):
            with self.subTest(mutation=mutation), self.assertRaises(UnstructuredMeshError):
                decode_quadtree_packet(packet_fixture(mutation=mutation))

    def test_header_refinement_truncation_and_independent_budgets_fail(self):
        packet = packet_fixture()
        for bad in (packet[:-30], packet + b"UNKNOWN\n", packet.replace(b"NUM_LEVELS 0", b"NUM_LEVELS 1"),
                    packet.replace(b"ANGLE 0\n", b"ANGLE 30\n"), packet.replace(b"ORIGIN 123", b"ORIGIN nan")):
            with self.assertRaises(UnstructuredMeshError):
                decode_quadtree_packet(bad)
        for name, value in (("MAX_PACKET_BYTES", 10), ("MAX_CELLS", 1), ("MAX_POINTS", 4), ("MAX_OPAQUE_ITEMS", 1)):
            with patch("basinlens_ccs.groundwater.gpr_unstructured." + name, value), self.assertRaises(UnstructuredMeshError):
                decode_quadtree_packet(packet)

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_public_native_disv_matches_all_footprints_and_vertices(self):
        mesh = decode_quadtree_packet(packet_fixture())
        report = compare_with_disv(mesh, native_model())
        self.assertTrue(report["all_cell_footprints_match"])
        self.assertTrue(report["all_xy_vertices_match"])
        self.assertTrue(report["all_face_corner_z_match"])
        self.assertTrue(report["single_layer_xy_node_pair_topology_matches"])
        self.assertTrue(report["full_3d_mesh_coordinate_match"])
        self.assertEqual(report["native_xy_vertices"], 6)
        self.assertFalse(report["physical_or_runtime_equivalence_claimed"])

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_same_xy_with_different_z_never_receives_full_match(self):
        mesh = decode_quadtree_packet(packet_fixture())
        report = compare_with_disv(mesh, native_model(top=9, bottom=1))
        self.assertTrue(report["all_cell_footprints_match"])
        self.assertTrue(report["all_xy_vertices_match"])
        self.assertFalse(report["all_face_corner_z_match"])
        self.assertFalse(report["full_3d_mesh_coordinate_match"])
        self.assertEqual(report["max_absolute_coordinate_error"]["upper_corner_z_vs_cell_top"], 1)
        self.assertEqual(report["max_absolute_coordinate_error"]["lower_corner_z_vs_cell_bottom"], 3)
        self.assertFalse(report["origin_or_z_repair_applied"])

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_equal_coordinates_with_disconnected_duplicate_nodes_do_not_full_match(self):
        mesh = decode_quadtree_packet(packet_fixture(mutation="split_shared_nodes"))
        report = compare_with_disv(mesh, native_model())
        self.assertTrue(report["all_cell_footprints_match"])
        self.assertTrue(report["all_xy_vertices_match"])
        self.assertTrue(report["all_face_corner_z_match"])
        self.assertFalse(report["single_layer_xy_node_pair_topology_matches"])
        self.assertFalse(report["full_3d_mesh_coordinate_match"])

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_changed_native_edges_or_declared_offset_are_detected(self):
        mesh = decode_quadtree_packet(packet_fixture())
        for model in (native_model(different_edges=True), native_model(origin=1)):
            report = compare_with_disv(mesh, model)
            self.assertFalse(report["all_cell_footprints_match"])
            self.assertFalse(report["all_xy_vertices_match"])
            self.assertFalse(report["full_3d_mesh_coordinate_match"])

    @unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is optional")
    def test_explicit_hdf5_packet_and_unchanged_source_binding(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("grid/Geometry.xmsgrid", data=np.frombuffer(packet_fixture(), dtype="i1"), compression="gzip")
            before = path.read_bytes()
            mesh = read_gpr_quadtree(path, "/grid")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(mesh.source["sha256"], hashlib.sha256(before).hexdigest())
            self.assertTrue(mesh.source["identity_verified_after_read"])
            self.assertNotIn("private-synthetic", str(mesh.receipt()))
            with patch("basinlens_ccs.groundwater.gpr_unstructured._identity", side_effect=[{"sha256": "a"}, {"sha256": "b"}]):
                with self.assertRaisesRegex(UnstructuredMeshError, "changed"):
                    read_gpr_quadtree(path, "/grid")


if __name__ == "__main__":
    unittest.main()
