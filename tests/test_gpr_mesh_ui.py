"""Explicit measured Quadtree UI selection with original synthetic HDF5 only."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "h5py"))


@unittest.skipUnless(AVAILABLE, "Saved mesh UI needs Streamlit, Plotly and h5py")
class GprQuadtreeUITests(unittest.TestCase):
    def setUp(self):
        import h5py
        from streamlit.testing.v1 import AppTest
        from test_gpr_unstructured import packet_fixture
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.gpr"
        with h5py.File(self.path, "w") as project:
            project.create_dataset("mesh/Geometry.xmsgrid", data=np.frombuffer(packet_fixture(), dtype="i1"))
            project.create_dataset("mesh/raw-values", data=np.array([[1, 2], [11, 12]], dtype="f8"))
            project.create_dataset("mesh/wrong-size", data=np.ones(3))
            project.create_dataset("mesh/nonfinite", data=np.array([np.nan, 9.0]))
        self.original = self.path.read_bytes()
        self.app = AppTest.from_file(str(APP), default_timeout=45).run()
        self.assertEqual(list(self.app.exception), [])
        self.original_case = copy.deepcopy(self.app.session_state["gw_case"])

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def select(self, label):
        return next(item for item in self.app.selectbox if item.label == label)

    def open(self):
        next(item for item in self.app.text_input if item.label == "읽기 전용 GPR 파일 (서버 경로)").set_value(str(self.path))
        self.button("GPR 자료 목록 열기").click().run()
        self.assertEqual(list(self.app.exception), [])

    def render(self):
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])

    def test_explicit_quadtree_choice_uses_physical_corner_means_and_selected_field_row(self):
        self.open()
        self.assertEqual(self.select("저장 기하 해석 형식").value, "rectilinear")
        self.select("저장 기하 해석 형식").set_value("quadtree_level0")
        self.select("직접 선택할 원시 셀 필드").set_value("/mesh/raw-values")
        next(item for item in self.app.number_input if item.label.startswith("저장 배열 첫 축")).set_value(1)
        self.render()
        self.assertEqual(list(self.app.error), [])
        figure = self.app.session_state["gw_gpr_figure"]
        np.testing.assert_array_equal(figure.data[0].x, [1, 3.5])
        np.testing.assert_array_equal(figure.data[0].y, [1.5, 1.5])
        np.testing.assert_array_equal(figure.data[0].z, [7, 7])
        np.testing.assert_array_equal(figure.data[0].marker.color, [11, 12])
        self.assertNotIn("KIJ", figure.data[0].hovertemplate)
        receipt = self.app.session_state["gw_gpr_receipt"]
        self.assertEqual(receipt["geometry_representation"], "quadtree_level0")
        self.assertEqual(receipt["cell_count"], 2)
        self.assertEqual(receipt["node_count"], 12)
        self.assertEqual(receipt["rendered_cells"], 2)
        self.assertEqual(receipt["source_sha256"], hashlib.sha256(self.original).hexdigest())
        for name in ("coordinate_units", "crs", "vertical_datum", "field_units", "time_units"):
            self.assertIsNone(receipt[name])
        self.assertFalse(receipt["wrapper_origin_or_axis_transform_applied"])
        self.assertFalse(receipt["new_solver_result"])
        self.assertTrue(receipt["saved_data_only"])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.app.session_state["gw_case"], self.original_case)

    def test_wrong_representation_rejects_without_fallback_or_cached_figure(self):
        self.open()
        self.render()
        self.assertTrue(any("GPR 기하/원시 배열 오류" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_figure"]
        self.select("저장 기하 해석 형식").set_value("quadtree_level0")
        self.render()
        self.assertEqual(list(self.app.error), [])
        self.select("저장 기하 해석 형식").set_value("rectilinear")
        self.render()
        self.assertTrue(any("GPR 기하/원시 배열 오류" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_receipt"]

    def test_cell_count_mismatch_is_rejected_and_nonfinite_sample_values_are_omitted(self):
        self.open()
        self.select("저장 기하 해석 형식").set_value("quadtree_level0")
        self.select("직접 선택할 원시 셀 필드").set_value("/mesh/wrong-size")
        self.render()
        self.assertTrue(any("지원하지 않는 셀 배열" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_figure"]
        self.select("직접 선택할 원시 셀 필드").set_value("/mesh/nonfinite")
        self.render()
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["gw_gpr_receipt"]["omitted_nonfinite_sample_values"], 1)
        self.assertEqual(self.app.session_state["gw_gpr_receipt"]["rendered_cells"], 1)
        np.testing.assert_array_equal(self.app.session_state["gw_gpr_figure"].data[0].marker.color, [9])

    def test_source_change_after_inventory_is_not_relabelled_as_original_mesh(self):
        import h5py
        self.open()
        with h5py.File(self.path, "r+") as project:
            project["mesh/raw-values"][0, 0] = 99
        changed = self.path.read_bytes()
        self.select("저장 기하 해석 형식").set_value("quadtree_level0")
        self.render()
        self.assertTrue(any("목록 검사 이후 변경" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_receipt"]
        self.assertEqual(self.path.read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
