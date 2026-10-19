"""Original synthetic packets; no GMS program or tutorial bytes are distributed."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

from basinlens_ccs.groundwater.gpr_geometry import (
    GprGeometryError, compare_with_dis, decode_rectilinear_packet, read_gpr_rectilinear,
)


def packet_fixture(*, corrupt_connectivity=False, z_axis=(0, 1, 2), nonflat=False):
    """Two layers, one row, two unequal-width columns, with physical Z != axis Z."""
    chunks = [b"Binary RectilinearGrid3d Version 1\nDIMENSIONS 3\nORIGIN 0 0 0\nANGLE 0\n"
              b"NUMBERING KIJ\nORIENTATION Y_DECREASE X_INCREASE Z_DECREASE\n"]

    def vector(key, array, count=None):
        array = np.asarray(array)
        chunks.append(f"{key} {len(array) if count is None else count}\n".encode())
        data = array.tobytes()
        # Split inside elements, so the decoder must join blocks before parsing values.
        for offset in range(0, len(data), 37):
            block = data[offset:offset + 37]
            encoded = base64.b64encode(zlib.compress(block)).rstrip(b"=")
            chunks.extend([f"BINARY_BLOCK {len(encoded)} {len(block)}\n".encode(), encoded, b"\n"])

    vector("LOCATIONS_X", np.array([0, 4, 10], dtype="<f8"))
    vector("LOCATIONS_Y", np.array([0, 6], dtype="<f8"))
    vector("LOCATIONS_Z", np.array(z_axis, dtype="<f8"))
    chunks.append(b"Binary XmUGrid Version 2\n")
    points = np.array([(x, y, z) for z in (10, 7, 1) for y in (6, 0) for x in (0, 4, 10)], dtype="<f8")
    if nonflat:
        # Each face retains its mean elevation while its north/south corners differ.
        points[:, 2] += np.tile([0.5, 0.5, 0.5, -0.5, -0.5, -0.5], 3)
    vector("LOCATIONS", points, len(points))
    cells = np.array([[12, 8, 0, 1, 4, 3, 6, 7, 10, 9],
                      [12, 8, 1, 2, 5, 4, 7, 8, 11, 10],
                      [12, 8, 6, 7, 10, 9, 12, 13, 16, 15],
                      [12, 8, 7, 8, 11, 10, 13, 14, 17, 16]], dtype="<i4")
    if corrupt_connectivity:
        cells[1, 2] = 0
    vector("CELL_STREAM", cells.ravel())
    chunks.append(b"UUID 00000000-0000-0000-0000-000000000001\n")
    vector("POINT_ELEVATIONS", points[:, 2].astype("<f8"))
    vector("CELL_TOPS", np.array([10, 10, 7, 7], dtype="<f8"))
    vector("CELL_BOTTOMS", np.array([7, 7, 1, 1], dtype="<f8"))
    vector("CELL_LAYERS", np.array([1, 1, 2, 2], dtype="<i4"))
    return b"".join(chunks)


class GprGeometryTests(unittest.TestCase):
    def test_physical_geometry_and_all_cell_mapping(self):
        packet = packet_fixture()
        geometry = decode_rectilinear_packet(packet)
        self.assertEqual(geometry.shape, (2, 1, 2))
        self.assertEqual(geometry.packet_sha256, hashlib.sha256(packet).hexdigest())
        np.testing.assert_array_equal(geometry.centers, [[[[2, 3, 8.5], [7, 3, 8.5]]],
                                                         [[[2, 3, 4], [7, 3, 4]]]])
        self.assertEqual(geometry.receipt()["parametric_z_axis"], [0, 1, 2])
        self.assertIsNone(geometry.receipt()["coordinate_units"])
        self.assertIsNone(geometry.receipt()["vertical_datum"])
        self.assertFalse(geometry.points.flags.writeable)
        self.assertFalse(geometry.cell_tops.flags.writeable)

    def test_all_connectivity_is_checked_before_mapping(self):
        with self.assertRaisesRegex(GprGeometryError, "Connectivity"):
            decode_rectilinear_packet(packet_fixture(corrupt_connectivity=True))

    def test_truncated_oversized_and_extra_blocks_fail(self):
        packet = packet_fixture()
        for bad in (packet[:-20], packet.replace(b"BINARY_BLOCK ", b"BINARY_BLOCK 999999999 ", 1),
                    packet + b"UNKNOWN_RECORD 1\n"):
            with self.assertRaises(GprGeometryError):
                decode_rectilinear_packet(bad)

    def test_compressed_bomb_is_stopped_by_declared_output_limit(self):
        packet = packet_fixture()
        start = packet.index(b"BINARY_BLOCK")
        encoded = base64.b64encode(zlib.compress(b"x" * 1000000)).rstrip(b"=")
        # The first vector expects 24 bytes; a 1-byte declared block cannot contain this stream.
        bad = packet[:start] + f"BINARY_BLOCK {len(encoded)} 1\n".encode() + encoded + b"\n"
        with self.assertRaisesRegex(GprGeometryError, "Deflate"):
            decode_rectilinear_packet(bad)

    def test_unsupported_orientation_version_origin_and_nonfinite_are_rejected(self):
        packet = packet_fixture()
        for before, after in ((b"Version 1\n", b"Version 9\n"),
                              (b"Y_DECREASE", b"Y_INCREASE"),
                              (b"ORIGIN 0 0 0", b"ORIGIN 1 0 0")):
            with self.assertRaises(GprGeometryError):
                decode_rectilinear_packet(packet.replace(before, after, 1))
        with self.assertRaisesRegex(GprGeometryError, "Non-finite"):
            decode_rectilinear_packet(packet_fixture(z_axis=(0, float("nan"), 2)))

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_independent_public_dis_arrays_compare_all_cells(self):
        import flopy
        simulation = flopy.mf6.MFSimulation()
        model = flopy.mf6.ModflowGwf(simulation)
        flopy.mf6.ModflowGwfdis(model, nlay=2, nrow=1, ncol=2, delr=[4, 6], delc=6,
                              top=10, botm=[7, 1], length_units="METERS")
        report = compare_with_dis(decode_rectilinear_packet(packet_fixture()), model)
        self.assertTrue(report["exact_coordinate_match"])
        self.assertEqual(report["compared_cells"], 4)
        self.assertEqual(report["compared_xy_nodes"], 18)
        self.assertEqual(report["compared_face_corner_elevations"], 32)
        self.assertFalse(report["native_shared_vertex_z_constructed"])
        self.assertEqual(report["native_length_units"], "meters")
        self.assertIsNone(report["gpr_coordinate_units"])
        model.dis.botm.set_data([7, 0])
        changed = compare_with_dis(decode_rectilinear_packet(packet_fixture()), model)
        self.assertFalse(changed["exact_coordinate_match"])
        self.assertEqual(changed["max_absolute_coordinate_error"]["bottom"], 1)

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_same_centers_with_different_cell_edges_do_not_match(self):
        import flopy
        simulation = flopy.mf6.MFSimulation()
        model = flopy.mf6.ModflowGwf(simulation)
        flopy.mf6.ModflowGwfdis(model, nlay=2, nrow=1, ncol=2, delr=[2, 8], delc=6,
                              xorigin=1, top=10, botm=[7, 1])
        report = compare_with_dis(decode_rectilinear_packet(packet_fixture()), model)
        errors = report["max_absolute_coordinate_error"]
        self.assertEqual(errors["center_x"], 0)
        self.assertEqual(errors["center_y"], 0)
        self.assertEqual(errors["vertex_x"], 1)
        self.assertFalse(report["exact_coordinate_match"])

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_nonflat_face_corners_do_not_match_only_the_native_mean(self):
        import flopy
        simulation = flopy.mf6.MFSimulation()
        model = flopy.mf6.ModflowGwf(simulation)
        flopy.mf6.ModflowGwfdis(model, nlay=2, nrow=1, ncol=2, delr=[4, 6], delc=6,
                              top=10, botm=[7, 1])
        report = compare_with_dis(decode_rectilinear_packet(packet_fixture(nonflat=True)), model)
        errors = report["max_absolute_coordinate_error"]
        self.assertTrue(all(errors[name] == 0 for name in ("center_z", "top", "bottom")))
        self.assertEqual(errors["upper_corner_z_vs_cell_top"], 0.5)
        self.assertEqual(errors["lower_corner_z_vs_cell_bottom"], 0.5)
        self.assertFalse(report["exact_coordinate_match"])

    @unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is optional")
    def test_explicit_hdf5_read_is_bound_to_unchanged_source(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("grid/Geometry.xmsgrid", data=np.frombuffer(packet_fixture(), dtype="i1"),
                                       compression="gzip")
            before = path.read_bytes()
            geometry = read_gpr_rectilinear(path, "/grid")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(geometry.source["sha256"], hashlib.sha256(before).hexdigest())
            self.assertTrue(geometry.source["identity_verified_after_read"])
            self.assertEqual(geometry.source["dataset_storage"]["path"], "/grid/Geometry.xmsgrid")
            with patch("basinlens_ccs.groundwater.gpr_geometry._identity",
                       side_effect=[{"sha256": "a"}, {"sha256": "b"}]):
                with self.assertRaisesRegex(GprGeometryError, "changed"):
                    read_gpr_rectilinear(path, "/grid")


if __name__ == "__main__":
    unittest.main()
