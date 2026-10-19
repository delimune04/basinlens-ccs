"""Read-only saved project tree UI checks using original synthetic HDF5."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "h5py"))


@unittest.skipUnless(AVAILABLE, "Project tree UI needs Streamlit, Plotly and h5py")
class GprProjectTreeUITests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        from test_gpr_project import create_fixture
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "PRIVATE_PROJECT.gpr"
        create_fixture(self.path)
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

    def test_explicit_tree_load_preserves_private_labels_and_redacts_download(self):
        from test_gpr_project import UUIDS
        original_case = self.app.session_state["gw_case"]
        self.open()
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_tree_summary"]
        self.button("저장 프로젝트 트리 읽기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        rows = self.app.session_state["gw_gpr_tree_rows"]
        self.assertEqual(len(rows), 13)
        self.assertTrue(all(row["이름 (원본 파일)"] == "PRIVATE_LABEL" for row in rows))
        ids = {row["ID"] for row in rows}
        self.assertIsNone(rows[0]["부모 ID"])
        self.assertTrue(all(row["부모 ID"] in ids for row in rows[1:]))
        self.assertTrue(any("이름 (원본 파일)" in item.value.columns for item in self.app.dataframe))
        payload = self.app.session_state["gw_gpr_tree_summary_json"]
        summary = json.loads(payload)
        self.assertEqual(summary, self.app.session_state["gw_gpr_tree_summary"])
        self.assertEqual(summary["counts"]["tree_nodes"], 13)
        self.assertGreater(summary["counts"]["unresolved"], 0)
        self.assertEqual(summary["source"]["sha256"], hashlib.sha256(self.original).hexdigest())
        encoded = payload.decode("utf-8")
        self.assertNotIn("PRIVATE", encoded)
        self.assertTrue(all(value not in encoded for value in UUIDS.values()))
        self.assertFalse(summary["original_labels_included"])
        self.assertFalse(summary["raw_uuids_included"])
        self.assertFalse(summary["original_hdf5_paths_included"])
        self.assertTrue(any(item.label == "익명 프로젝트 트리 요약 JSON 다운로드"
                            for item in self.app.get("download_button")))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.app.session_state["gw_case"], original_case)

    def test_malformed_tree_is_visible_and_geometry_remains_independent(self):
        import h5py
        from test_gpr_geometry import packet_fixture
        with h5py.File(self.path, "r+") as project:
            project["Tree/Tree"][0] = b"BROKEN_TREE"
            grid = project["UnstructuredGridModule/PRIVATE_GRID_PATH"]
            del grid["Geometry.xmsgrid"]
            grid.create_dataset("Geometry.xmsgrid", data=np.frombuffer(packet_fixture(), dtype="i1"))
        self.open()
        self.button("저장 프로젝트 트리 읽기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("GPR 프로젝트 트리 오류" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_tree_summary_json"]
        self.button("선택한 저장 기하·필드 보기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["gw_gpr_receipt"]["rendered_cells"], 4)

    def test_tree_read_rejects_source_change_after_inventory(self):
        import h5py
        self.open()
        with h5py.File(self.path, "r+") as project:
            project["Tree/Tree"][3] = b'TRNAME "CHANGED_PRIVATE_LABEL"'
        changed = self.path.read_bytes()
        self.button("저장 프로젝트 트리 읽기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("목록 검사 이후 변경" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_gpr_tree_summary"]
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertFalse(any(item.label == "익명 프로젝트 트리 요약 JSON 다운로드"
                             for item in self.app.get("download_button")))


if __name__ == "__main__":
    unittest.main()
