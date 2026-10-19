"""Small synthetic HDF5 saved-data UI fixtures; no original GMS bytes."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "h5py"))


@unittest.skipUnless(AVAILABLE, "GPR UI needs Streamlit, Plotly and h5py")
class GprViewerBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("gpr_ui_bound_test_app", APP)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_hash_rejects_oversize_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversize.gpr"
            path.write_bytes(b"123456789")
            with patch.object(self.module, "MAX_GPR_BYTES", 8), patch.object(Path, "open") as opened:
                with self.assertRaisesRegex(ValueError, "8바이트"):
                    self.module._gpr_sha(str(path))
                opened.assert_not_called()

    def test_hash_stops_when_file_grows_after_stat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growing.gpr"
            path.write_bytes(b"1234")
            with patch.object(self.module, "MAX_GPR_BYTES", 8), \
                    patch.object(Path, "open", return_value=io.BytesIO(b"123456789")):
                with self.assertRaisesRegex(ValueError, "해시 검사 중 8바이트"):
                    self.module._gpr_sha(str(path))

    def test_cell_centers_do_not_overflow_finite_large_coordinates(self):
        geometry = SimpleNamespace(source={"sha256": "same"}, shape=(1, 1, 1),
            points=np.full((8, 3), 1e308), cells=np.arange(8).reshape((1, 8)),
            receipt=lambda: {"parametric_z_axis": [0, 1]})
        with patch.object(self.module, "read_gpr_rectilinear", return_value=geometry), \
                np.errstate(over="raise"):
            figure, _ = self.module.gpr_saved_figure("unused", "/grid/Geometry.xmsgrid", "", 0, "same")
        np.testing.assert_array_equal(figure.data[0].x, [1e308])
        np.testing.assert_array_equal(figure.data[0].y, [1e308])
        np.testing.assert_array_equal(figure.data[0].z, [1e308])


@unittest.skipUnless(AVAILABLE, "GPR UI needs Streamlit, Plotly and h5py")
class GprSavedDataUITests(unittest.TestCase):
    def setUp(self):
        import h5py
        from streamlit.testing.v1 import AppTest
        from test_gpr_geometry import packet_fixture
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.gpr"
        self.packet = packet_fixture()
        with h5py.File(self.path, "w") as project:
            project.create_dataset("grid/Geometry.xmsgrid", data=np.frombuffer(self.packet, dtype="i1"))
            project.create_dataset("grid/Heads/Values", data=np.array([[10, 11, 12, 13], [20, 21, 22, 23]], dtype="f4"))
            project.create_dataset("grid/Heads/Times", data=np.array([0.0, 86400.0]))
            project["grid/Heads/Values"].attrs["DatasetUnits"] = "unknown"
            project["grid/Heads/Times"].attrs["TimeUnits"] = "Days"
            project.create_dataset("grid/wrong-shape", data=np.ones((2, 3)))
            project.create_dataset("grid/large-integers", data=np.array([2 ** 63] * 4, dtype="u8"))
            project.create_dataset("grid/unsupported-compound", data=np.array([(1, 2.0)], dtype=[("a", "i4"), ("b", "f8")]))
        self.original = self.path.read_bytes()
        self.app = AppTest.from_file(str(APP), default_timeout=45).run()
        self.assertEqual(list(self.app.exception), [])

    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def open(self):
        source = next(field for field in self.app.text_input if field.label == "읽기 전용 GPR 파일 (서버 경로)")
        source.set_value(str(self.path))
        self.button("GPR 자료 목록 열기").click().run()
        self.assertEqual(list(self.app.exception), [])

    def scalar(self, path):
        return next(field for field in self.app.selectbox if field.label == "직접 선택할 원시 셀 필드").set_value(path)

    def test_saved_geometry_and_explicit_time_row_render_without_unit_inference(self):
        original_case = self.app.session_state["gw_case"]
        self.open()
        self.scalar("/grid/Heads/Values")
        index = next(field for field in self.app.number_input if field.label.startswith("저장 배열 첫 축"))
        index.set_value(1)
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        receipt = self.app.session_state["gw_gpr_receipt"]
        self.assertEqual(receipt["shape_kij"], [2, 1, 2])
        self.assertEqual(receipt["rendered_cells"], 4)
        self.assertIs(receipt["new_solver_result"], False)
        self.assertIsNone(receipt["coordinate_units"])
        self.assertIsNone(receipt["field_units"])
        self.assertIsNone(receipt["time_units"])
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(self.original).hexdigest())
        fig = self.app.session_state["gw_gpr_figure"]
        np.testing.assert_array_equal(fig.data[0].marker.color, [20, 21, 22, 23])
        np.testing.assert_array_equal(fig.data[0].z, [8.5, 8.5, 4.0, 4.0])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.app.session_state["gw_case"], original_case)

    def test_unsupported_cell_array_shape_is_visible_and_not_rendered(self):
        self.open()
        self.scalar("/grid/wrong-shape")
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("지원하지 않는 셀 배열" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_figure"]

    def test_unsupported_packet_is_rejected_in_ui(self):
        import h5py
        with h5py.File(self.path, "r+") as project:
            del project["grid/Geometry.xmsgrid"]
            project.create_dataset("grid/Geometry.xmsgrid", data=np.frombuffer(self.packet.replace(b"Version 1\n", b"Version 9\n", 1), dtype="i1"))
        self.open()
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("GPR 기하/원시 배열 오류" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_receipt"]

    def test_large_integer_field_is_not_silently_rounded(self):
        self.open()
        self.scalar("/grid/large-integers")
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("정확히 표현" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_figure"]

    def test_source_change_after_inventory_cannot_mix_geometry_and_field(self):
        import h5py
        self.open()
        with h5py.File(self.path, "r+") as project:
            project["grid/Heads/Values"][0, 0] = 99
        self.scalar("/grid/Heads/Values")
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("변경" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_figure"]


if __name__ == "__main__":
    unittest.main()
