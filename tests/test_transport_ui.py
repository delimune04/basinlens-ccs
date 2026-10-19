"""Bounded synthetic transport UI workflow; actual MF6 is explicit and optional."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd


APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "flopy"))
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


@unittest.skipUnless(AVAILABLE, "Transport UI needs Streamlit, Plotly and FloPy")
class TransportWorkbenchUITests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = AppTest.from_file(str(APP), default_timeout=45).run()
        self.assertEqual(list(self.app.exception), [])
        self.original_case = copy.deepcopy(self.app.session_state["gw_case"])
        self.original_project = copy.deepcopy(self.app.session_state["gw_project"])

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def text(self, label):
        return next(item for item in self.app.text_input if item.label == label)

    def load_example(self, name="uniform.json"):
        next(item for item in self.app.selectbox if item.label == "용질 합성 예제").set_value(name)
        self.button("합성 용질 예제 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])

    def assert_other_projects_unchanged(self):
        self.assertEqual(self.app.session_state["gw_case"], self.original_case)
        self.assertEqual(self.app.session_state["gw_project"], self.original_project)

    def test_initial_view_requires_explicit_case_and_does_not_execute(self):
        self.assertTrue(any("1D 보존성 용질" in item.value for item in self.app.info))
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        for key in ("gw_transport_case", "gw_transport_result", "gw_transport_export"):
            with self.assertRaises(KeyError):
                self.app.session_state[key]
        self.assertFalse(any(item.label == "용질 MF6 실제 실행" for item in self.app.button))
        self.load_example("closed_gaussian.json")
        self.assertEqual(self.app.session_state["gw_transport_case"]["darcy_flux_m_per_day"], 0.0)
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        self.assertEqual(list(self.base.iterdir()), [])
        self.assert_other_projects_unchanged()

    def test_strict_upload_and_missing_solver_fail_visibly_without_fallback(self):
        self.load_example()
        uploader = next(item for item in self.app.file_uploader if item.label.startswith("용질 케이스 JSON"))
        uploader.set_value(("bad.json", b'{"schema":1,"schema":1}', "application/json"))
        self.button("용질 JSON 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("용질 케이스 오류" in item.value and "Duplicate" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_transport_case"]
        data = (APP.parent / "examples/transport/inlet_front.json").read_bytes()
        next(item for item in self.app.file_uploader if item.label.startswith("용질 케이스 JSON")).set_value(
            ("valid.json", data, "application/json"))
        self.button("용질 JSON 불러오기").click().run()
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["gw_transport_case"], json.loads(data))
        self.text("용질 작업 폴더 (새 폴더)").set_value(str(self.base / "missing-engine"))
        self.text("MODFLOW 6 실행 파일").set_value(str(self.base / "no-such-mf6"))
        self.button("용질 MF6 실제 실행").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("용질 내보내기/실행 오류" in item.value for item in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_transport_result"]
        self.assertFalse(any(item.label == "검증한 용질 실행 ZIP 다운로드" for item in self.app.get("download_button")))
        self.assert_other_projects_unchanged()

    def test_verified_native_export_requires_no_engine_and_preserves_input_case(self):
        from basinlens_ccs.groundwater.transport import verify_transport_export
        self.load_example()
        self.text("MODFLOW 6 실행 파일").set_value(str(self.base / "no-such-mf6"))
        self.text("용질 작업 폴더 (새 폴더)").set_value(str(self.base / "export"))
        self.button("엔진 없이 용질 MF6 입력 내보내기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        exported = self.app.session_state["gw_transport_export"]
        case = verify_transport_export(exported["workspace"])
        self.assertEqual(case.to_dict(), self.app.session_state["gw_transport_case"])
        archive = zipfile.ZipFile(io.BytesIO(exported["bundle"]))
        self.assertIn("mfsim.nam", archive.namelist())
        self.assertIn("solute.mst", archive.namelist())
        self.assertIn("settings.json", archive.namelist())
        self.assertNotIn("solute.ucn", archive.namelist())
        with self.assertRaises(KeyError):
            self.app.session_state["gw_transport_result"]
        self.assert_other_projects_unchanged()

    @unittest.skipUnless(SOLVER, "Set MF6_EXE for a real transport UI run")
    def test_actual_run_captured_case_profiles_mass_downloads_and_gate_visibility(self):
        from basinlens_ccs.groundwater.native_run import verify_native_run
        from basinlens_ccs.groundwater.transport import read_transport_results
        self.load_example()
        workspace = self.base / "run"
        self.text("용질 작업 폴더 (새 폴더)").set_value(str(workspace))
        self.text("MODFLOW 6 실행 파일").set_value(SOLVER)
        self.button("용질 MF6 실제 실행").click().run(timeout=90)
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(verify_native_run(workspace)["status"], "completed")
        products = self.app.session_state["gw_transport_result"]
        result = products["captured_result"]
        self.assertEqual(result.case, read_transport_results(workspace).case)
        self.assertTrue(result.summary["conservation_passed"])
        self.assertTrue(result.summary["concentration_bounds_passed"])
        np.testing.assert_allclose(result.concentrations_kg_m3, 0.2, atol=1e-8)
        np.testing.assert_allclose(result.mass_kg, 12.0, atol=1e-7)
        self.assertEqual(products["profile_figure"].layout.xaxis.title.text, "셀 중심 x (m)")
        self.assertEqual(products["profile_figure"].layout.yaxis.title.text, "농도 (kg/m³ 공극수)")
        self.assertEqual(products["mass_figure"].layout.xaxis.title.text, "경과 시간 (day)")
        self.assertEqual(products["mass_figure"].layout.yaxis.title.text, "총 용존 질량 (kg)")
        profile = pd.read_csv(io.BytesIO(products["profile_csv"]))
        self.assertEqual(len(profile), result.case.ncol)
        self.assertEqual(list(profile), ["time_day", "cell_column_0based", "x_center_m", "concentration_kg_per_m3_pore_water"])
        np.testing.assert_allclose(profile["concentration_kg_per_m3_pore_water"], result.concentrations_kg_m3[-1])
        mass = pd.read_csv(io.BytesIO(products["mass_csv"]))
        self.assertEqual(len(mass), result.case.nsteps + 1)
        self.assertEqual(mass.iloc[0]["time_day"], 0.0)
        self.assertAlmostEqual(mass.iloc[-1]["total_dissolved_mass_kg"], 12.0)
        archive = zipfile.ZipFile(io.BytesIO(products["bundle"]))
        self.assertIn("native_run_metadata.json", archive.namelist())
        self.assertIn("native/solute.ucn", archive.namelist())
        self.assertIn("source_sidecars/settings.json", archive.namelist())
        labels = {item.label for item in self.app.get("download_button")}
        self.assertTrue({"검증한 용질 실행 ZIP 다운로드", "선택 시각 용질 농도 CSV 다운로드",
                         "총 용존 질량 시간 CSV 다운로드", "용질 케이스 JSON 다운로드"} <= labels)
        # Render a failed gate flag without changing the completed native bundle.
        result.summary["conservation_passed"] = False
        self.app.run()
        self.assertTrue(any("네이티브 엔진 실행은 완료했지만" in item.value for item in self.app.error))
        self.assertFalse(any("모두 통과" in item.value for item in self.app.success))
        self.load_example("closed_gaussian.json")
        with self.assertRaises(KeyError):
            self.app.session_state["gw_transport_result"]
        self.assertEqual(verify_native_run(workspace)["status"], "completed")
        self.assert_other_projects_unchanged()


if __name__ == "__main__":
    unittest.main()
