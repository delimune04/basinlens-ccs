"""Optional end-to-end checks for the groundwater workbench.

Install the app and groundwater extras to run these tests. Set MF6_EXE to an
installed MODFLOW 6 executable to include the real-solver UI flow.
"""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import shutil
import unittest
import zipfile

APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
UI_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "flopy"))
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


@unittest.skipUnless(UI_AVAILABLE, "Streamlit, Plotly and FloPy are optional dependencies")
class GroundwaterWorkbenchTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.app = AppTest.from_file(str(APP), default_timeout=45).run()
        self.assertEqual(list(self.app.exception), [])

    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def number(self, label):
        return next(number for number in self.app.number_input if number.label == label)

    def test_demo_render_exposes_model_and_scientific_scope(self):
        self.assertTrue(any("단상·피압" in info.value for info in self.app.info))
        self.assertEqual(self.number("열 수").value, 41)
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        self.assertEqual(list(self.app.error), [])

    def test_committed_input_change_invalidates_old_products(self):
        self.app.session_state["gw_result"] = {"old": True}
        self.app.session_state["gw_input_zip"] = b"old-input"
        self.app.session_state["gw_csv"] = b"old-csv"
        self.number("좌측 고정수두 (m)").set_value(13.0)
        self.button("경계와 함양 적용").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(self.app.session_state["gw_case"]["boundaries"]["left_head_m"], 13.0)
        for name in ("gw_result", "gw_input_zip", "gw_csv"):
            with self.assertRaises(KeyError):
                self.app.session_state[name]

    def test_invalid_geometry_retains_last_valid_project(self):
        # The demonstration well is in column 20; shrinking to 3 must fail.
        self.number("열 수").set_value(3)
        self.button("격자와 물성 적용").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state["gw_case"]["grid"]["ncol"], 41)

    def test_export_produces_real_mf6_inputs_without_solver(self):
        self.button("엔진 없이 MF6 입력 파일 만들기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        archive = zipfile.ZipFile(io.BytesIO(self.app.session_state["gw_input_zip"]))
        self.assertIn("model/mfsim.nam", archive.namelist())
        self.assertIn("case.json", archive.namelist())
        with self.assertRaises(KeyError):
            self.app.session_state["gw_result"]

    def test_missing_solver_is_visible_without_fake_results(self):
        field = next(field for field in self.app.text_input if field.label == "MODFLOW 6 실행 파일")
        field.set_value("/nonexistent/basinlens-test-no-mf6")
        self.button("MODFLOW 6 계산").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("계산 실패" in error.value for error in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_result"]

    @unittest.skipUnless(SOLVER, "MF6_EXE or mf6 on PATH is required for a real solver run")
    def test_real_solver_results_csv_and_bundle(self):
        field = next(field for field in self.app.text_input if field.label == "MODFLOW 6 실행 파일")
        field.set_value(SOLVER)
        self.button("MODFLOW 6 계산").click().run(timeout=90)
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        result = self.app.session_state["gw_result"]
        self.assertEqual(result["heads"].shape, (13, 3, 21, 41))
        self.assertEqual(len(self.app.get("plotly_chart")), 3)
        archive = zipfile.ZipFile(io.BytesIO(result["bundle"]))
        self.assertIn("heads.npz", archive.namelist())
        self.assertIn("run_metadata.json", archive.namelist())
        self.button("모든 시각·층의 수두 CSV 준비").click().run()
        import pandas as pd

        frame = pd.read_csv(io.BytesIO(self.app.session_state["gw_csv"]))
        self.assertEqual(len(frame), 13 * 3 * 21 * 41)
        self.assertEqual(list(frame.columns), ["time_days", "layer", "row", "column", "x_center_m", "y_center_m", "head_m"])
        self.assertEqual(frame["time_days"].max(), 31.0)


if __name__ == "__main__":
    unittest.main()
