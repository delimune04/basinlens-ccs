"""Synthetic raw-chunk regressions for bounded HDF5 payload decoding."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

from basinlens_ccs.groundwater.gpr_hdf5 import GprInspectionError, read_gpr_numeric_array
from basinlens_ccs.groundwater.gpr_project import GprProjectError, read_gpr_project
from basinlens_ccs.groundwater.gpr_storage import StorageReadError, read_fixed_array


@unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is optional")
class GprStorageTests(unittest.TestCase):
    def test_multidimensional_deflate_edge_chunks_and_endian_values(self):
        import h5py
        values = np.arange(15, dtype=">f8").reshape(3, 5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", data=values, chunks=(2, 3), compression="gzip")
            with h5py.File(path, "r") as project, patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("HDF5 decode invoked")):
                result, receipt = read_fixed_array(project["values"], max_bytes=1024)
            np.testing.assert_array_equal(result, values)
            self.assertEqual(receipt["chunks_read"], 4)
            self.assertEqual(receipt["decoded_chunk_bytes"], 192)
            self.assertFalse(receipt["hdf5_filter_decode_invoked"])

    def test_streamed_32mib_excess_deflate_output_is_rejected_for_tree_and_numeric(self):
        import h5py
        rows = np.array([b"BEGTREE", b"BEGTRNODE", b"TRTYPE Project", b'RESERVED', b"ENDTRNODE", b"ENDTREE"], dtype="S32")
        # Use a valid small tree prefix. The extra output is streamed through a
        # compressor; the fixture itself never allocates a 32 MiB expanded buffer.
        rows[3] = b'TRNAME "synthetic"'
        compressor = zlib.compressobj()
        compressed = [compressor.compress(rows.tobytes())]
        zeros = b"\x00" * (1024 * 1024)
        for _ in range(32):
            compressed.append(compressor.compress(zeros))
        compressed.append(compressor.flush())
        raw_chunk = b"".join(compressed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                tree = project.create_dataset("Tree/Tree", shape=(6,), dtype="S32", chunks=(6,), compression="gzip")
                tree.id.write_direct_chunk((0,), raw_chunk)
                numeric = project.create_dataset("numeric", shape=(192,), dtype="u1", chunks=(192,), compression="gzip")
                numeric.id.write_direct_chunk((0,), raw_chunk)
            before = path.read_bytes()
            with patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("HDF5 inflation invoked")):
                with self.assertRaisesRegex(GprProjectError, "Deflate chunk"):
                    read_gpr_project(path)
                with self.assertRaisesRegex(GprInspectionError, "Deflate chunk"):
                    read_gpr_numeric_array(path, "/numeric")
            self.assertEqual(path.read_bytes(), before)

    def test_filter_skipped_chunk_is_bounded_and_unknown_mask_rejected(self):
        import h5py
        values = np.array([2.0, 4.0], dtype="<f8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                data = project.create_dataset("values", shape=(2,), dtype="<f8", chunks=(2,), compression="gzip")
                data.id.write_direct_chunk((0,), values.tobytes(), filter_mask=1)
                unknown = project.create_dataset("unknown_mask", shape=(2,), dtype="<f8", chunks=(2,), compression="gzip")
                unknown.id.write_direct_chunk((0,), values.tobytes(), filter_mask=2)
            result, _ = read_gpr_numeric_array(path, "/values")
            np.testing.assert_array_equal(result, values)
            with self.assertRaisesRegex(GprInspectionError, "filter mask"):
                read_gpr_numeric_array(path, "/unknown_mask")

    def test_noncanonical_integer_file_precision_is_not_silently_reinterpreted(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                file_type = h5py.h5t.STD_I32LE.copy()
                file_type.set_precision(16)
                file_type.set_offset(8)
                props = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
                props.set_chunk((3,))
                props.set_deflate(6)
                identifier = h5py.h5d.create(project.id, b"values", file_type,
                                            h5py.h5s.create_simple((3,)), dcpl=props)
                identifier.write(h5py.h5s.ALL, h5py.h5s.ALL, np.array([1, 2, -3], dtype="i4"))
            with self.assertRaisesRegex(GprInspectionError, "Noncanonical"):
                read_gpr_numeric_array(path, "/values")

    def test_null_termination_matches_hdf5_and_space_or_interior_nullpad_are_rejected(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                file_type = h5py.h5t.C_S1.copy()
                file_type.set_size(8)
                file_type.set_strpad(h5py.h5t.STR_SPACEPAD)
                props = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
                props.set_chunk((1,))
                identifier = h5py.h5d.create(project.id, b"space_padded", file_type,
                                            h5py.h5s.create_simple((1,)), dcpl=props)
                identifier.write(h5py.h5s.ALL, h5py.h5s.ALL, np.array([b"abc"], dtype="S8"))
                file_type.set_strpad(h5py.h5t.STR_NULLTERM)
                props.set_deflate(6)
                identifier = h5py.h5d.create(project.id, b"interior_terminated", file_type,
                                            h5py.h5s.create_simple((1,)), dcpl=props)
                identifier.write_direct_chunk((0,), zlib.compress(b"abc\x00junk"))
                data = project.create_dataset("interior_nullpad", shape=(1,), dtype="S8", chunks=(1,), compression="gzip")
                data.id.write_direct_chunk((0,), zlib.compress(b"abc\x00junk"))
            with h5py.File(path, "r") as project:
                result, _ = read_fixed_array(project["interior_terminated"])
                np.testing.assert_array_equal(result, project["interior_terminated"][()])
                np.testing.assert_array_equal(result, [b"abc"])
                for name in ("space_padded", "interior_nullpad"):
                    with self.subTest(name=name), self.assertRaises(StorageReadError):
                        read_fixed_array(project[name])

    def test_trailing_or_truncated_deflate_streams_are_rejected(self):
        import h5py
        values = np.array([2.0, 4.0], dtype="<f8")
        for raw in (zlib.compress(values.tobytes()) + b"extra", zlib.compress(values.tobytes())[:-1]):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "synthetic.gpr"
                with h5py.File(path, "w") as project:
                    data = project.create_dataset("values", shape=(2,), dtype="<f8", chunks=(2,), compression="gzip")
                    data.id.write_direct_chunk((0,), raw)
                with self.assertRaisesRegex(GprInspectionError, "Deflate chunk"):
                    read_gpr_numeric_array(path, "/values")

    def test_sparse_chunks_and_unsupported_builtin_filter_pipelines_fail_closed(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("sparse", shape=(4,), dtype="f8", chunks=(2,), compression="gzip")
                project.create_dataset("shuffle", data=[2.0, 4.0], shuffle=True, compression="gzip")
                project.create_dataset("checksum", data=[2.0, 4.0], fletcher32=True)
            for name in ("sparse", "shuffle", "checksum"):
                with self.subTest(name=name), self.assertRaises(GprInspectionError):
                    read_gpr_numeric_array(path, "/" + name)

    def test_unallocated_contiguous_fill_policy_is_not_invented(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", shape=(4,), dtype="f8")
            with self.assertRaisesRegex(GprInspectionError, "Unallocated"):
                read_gpr_numeric_array(path, "/values")

    def test_stored_chunk_count_and_aggregate_expansion_budgets(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", data=np.arange(16), chunks=(1,), compression="gzip")
                project.create_dataset("edge_waste", data=np.ones((2, 1), dtype="u1"), maxshape=(None, None),
                                       chunks=(1, 1024), compression="gzip")
            with h5py.File(path, "r") as project:
                for options, message in (({"max_chunks": 2}, "chunk count"), ({"max_stored_bytes": 1}, "Stored byte")):
                    with self.assertRaisesRegex(StorageReadError, message):
                        read_fixed_array(project["values"], **options)
                with self.assertRaisesRegex(StorageReadError, "Aggregate decoded"):
                    read_fixed_array(project["edge_waste"], max_bytes=1024)

    def test_empty_chunked_array_does_not_expand_empty_cartesian_products(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", shape=(0, 1024), maxshape=(None, None), dtype="u1", chunks=(1, 1))
            with h5py.File(path, "r") as project:
                array, receipt = read_fixed_array(project["values"], max_bytes=1024)
            self.assertEqual(array.shape, (0, 1024))
            self.assertEqual(receipt["chunks_read"], 0)


if __name__ == "__main__":
    unittest.main()
