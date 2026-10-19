"""Synthetic HDF5 projects only; no proprietary example data is distributed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from basinlens_ccs.groundwater.gpr_hdf5 import (
    GprInspectionError, inventory_gpr, read_gpr_numeric_array,
)


@unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is optional")
class GprHdf5Tests(unittest.TestCase):
    def test_inventory_preserves_link_boundaries_and_reads_no_payloads(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.attrs["GMS Version"] = "synthetic fixture"
                project.create_dataset("head", data=[[1.0, 2.0]], compression="gzip")
                project["alias"] = h5py.SoftLink("/head")
                project["outside"] = h5py.ExternalLink("missing-external.h5", "/values")
                group = project.create_group("group")
                group["cycle"] = group
            before = path.read_bytes()
            report = inventory_gpr(path)
            self.assertFalse(report["dataset_payloads_read"])
            self.assertFalse(report["indirect_links_followed"])
            kinds = {item["kind"] for item in report["objects"]}
            self.assertTrue({"dataset", "group", "soft_link", "external_link", "hard_link_alias"} <= kinds)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((Path(directory) / "missing-external.h5").exists())

    def test_explicit_numeric_read_has_size_and_type_limits(self):
        import h5py
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", data=[[2.0, 4.0]], compression="gzip")
                project.create_dataset("text", data=[b"not a numeric field"])
            array, metadata = read_gpr_numeric_array(path, "/values")
            np.testing.assert_array_equal(array, [[2.0, 4.0]])
            self.assertFalse(metadata["units_converted"])
            with self.assertRaisesRegex(GprInspectionError, "budget"):
                read_gpr_numeric_array(path, "/values", max_bytes=1)
            with self.assertRaisesRegex(GprInspectionError, "fixed-width"):
                read_gpr_numeric_array(path, "/text")

    def test_indirect_explicit_reads_are_rejected(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", data=[1])
                project["alias"] = h5py.SoftLink("/values")
                project["outside"] = h5py.ExternalLink("outside.h5", "/values")
            for name in ("/alias", "/outside", "/../values"):
                with self.assertRaises(GprInspectionError):
                    read_gpr_numeric_array(path, name)

    def test_virtual_data_is_not_loaded(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            layout = h5py.VirtualLayout(shape=(2,), dtype="f8")
            layout[:] = h5py.VirtualSource("missing.h5", "values", shape=(2,))
            with h5py.File(path, "w", libver="latest") as project:
                project.create_virtual_dataset("values", layout)
            with self.assertRaisesRegex(GprInspectionError, "Virtual"):
                read_gpr_numeric_array(path, "/values")

    def test_external_storage_is_not_read(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                project.create_dataset("values", shape=(2,), dtype="f8",
                                       external=[("missing-external.raw", 0, 16)])
            with self.assertRaisesRegex(GprInspectionError, "external-storage"):
                read_gpr_numeric_array(path, "/values")

    def test_unavailable_optional_filter_is_inventoried_but_not_loaded(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            with h5py.File(path, "w") as project:
                properties = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
                properties.set_chunk((2,))
                properties.set_filter(32000, h5py.h5z.FLAG_OPTIONAL)
                space = h5py.h5s.create_simple((2,))
                h5py.h5d.create(project.id, b"values", h5py.h5t.NATIVE_DOUBLE, space, dcpl=properties)
            report = inventory_gpr(path)
            self.assertEqual(report["objects"][0]["filter_ids"], [32000])
            with self.assertRaisesRegex(GprInspectionError, "plugin"):
                read_gpr_numeric_array(path, "/values")


if __name__ == "__main__":
    unittest.main()
