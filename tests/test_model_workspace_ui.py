"""Coherent model workspace checks, using the actual optional MF6 engine."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "model_workspace.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "flopy"))
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


@unittest.skipUnless(AVAILABLE, "Model workspace UI requires Streamlit, Plotly and FloPy")
class ModelWorkspaceUITests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = AppTest.from_file(str(APP), default_timeout=60).run()
        self.addCleanup(self._cleanup_opened_package)
        self.assertEqual(list(self.app.exception), [])

    def _cleanup_opened_package(self):
        try:
            keeper = self.app.session_state["mw_package_keeper"]
        except KeyError:
            return
        keeper.cleanup()

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def text(self, label):
        return next(item for item in self.app.text_input if item.label == label)

    def select(self, label):
        return next(item for item in self.app.selectbox if item.label == label)

    def load(self):
        # Bind the fixture by identity; the production default may be another example.
        self.select("모델 합성 예제").set_value("layered_background_water.json")
        self.button("모델 합성 예제 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])

    def test_initial_load_and_invalid_import_preserve_valid_case_and_diagnostics(self):
        self.assertEqual(len(self.app.get("plotly_chart")), 0)
        with self.assertRaises(KeyError):
            self.app.session_state["mw_case"]
        self.load()
        original = copy.deepcopy(self.app.session_state["mw_case"])
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        self.assertTrue(any(trace.name == "우물 셀" for trace in self.app.session_state["mw_figure"].data))
        next(item for item in self.app.checkbox if item.label == "모델 우물 표시").set_value(False).run()
        self.assertFalse(any(trace.name == "우물 셀" for trace in self.app.session_state["mw_figure"].data))
        upload = next(iter(self.app.file_uploader))
        upload.set_value(("bad.json", b'{"schema_version":1,"schema_version":1}', "application/json"))
        self.button("모델 파일 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("모델 불러오기" in item.value for item in self.app.error))
        self.assertEqual(self.app.session_state["mw_case"], original)
        diagnostic = self.app.session_state["mw_diagnostic"]
        self.assertTrue(diagnostic["last_valid_case_preserved"])
        self.assertIn("Duplicate", diagnostic["message"])
        self.assertEqual(list(self.base.iterdir()), [])

    def test_invalid_and_unapplied_drafts_block_execution_and_clear_stale_products(self):
        self.load()
        original = copy.deepcopy(self.app.session_state["mw_case"])
        self.app.session_state["mw_result"] = {"stale": True}
        self.app.session_state["mw_export"] = {"stale": True}
        self.app.text_area[0].set_value('{"invalid": true}').run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("초안 검증 오류" in item.value for item in self.app.error))
        for label in ("모델 프로젝트 저장 · 왕복 검증", "모델 MF6 입력 내보내기", "모델 MF6 실제 실행"):
            self.assertTrue(self.button(label).disabled)
        for key in ("mw_result", "mw_export"):
            with self.assertRaises(KeyError):
                self.app.session_state[key]
        self.assertEqual(self.app.session_state["mw_case"], original)
        self.button("마지막 유효 모델로 초안 복구").click().run()
        self.assertEqual(list(self.app.error), [])
        self.assertFalse(self.button("모델 MF6 실제 실행").disabled)
        changed = copy.deepcopy(original)
        changed["project"]["name"] += " edited"
        self.app.text_area[0].set_value(json.dumps(changed)).run()
        self.assertTrue(self.button("모델 MF6 실제 실행").disabled)
        self.button("검증한 모델 초안 적용").click().run()
        self.assertEqual(self.app.session_state["mw_case"]["project"]["name"], changed["project"]["name"])
        self.assertFalse(self.button("모델 MF6 실제 실행").disabled)

    def test_package_save_reopen_preserves_case_view_and_rejects_tampering(self):
        self.load()
        self.select("모델 표시 항목").set_value("porosity")
        self.select("모델 표시 방식").set_value("3d")
        next(item for item in self.app.checkbox if item.label == "모델 우물 표시").set_value(False)
        self.app.run()
        original = copy.deepcopy(self.app.session_state["mw_case"])
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(self.base / "new-parent" / "saved"))
        self.button("모델 프로젝트 저장 · 왕복 검증").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        package = self.app.session_state["mw_package"]
        self.assertTrue(Path(package["path"]).is_file())
        with zipfile.ZipFile(io.BytesIO(package["bytes"])) as archive:
            self.assertIn("project.json", archive.namelist())
        next(iter(self.app.file_uploader)).set_value(("saved.blproj", package["bytes"], "application/zip"))
        self.button("모델 파일 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["mw_case"], original)
        self.assertEqual(self.app.session_state["mw_view"], {"selected_layer": 0, "selected_field": "porosity",
                                                             "chart_mode": "3d", "show_wells": False})
        self.select("모델 표시 항목").set_value("head").run()
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(self.base / "saved-head-view"))
        self.button("모델 프로젝트 저장 · 왕복 검증").click().run()
        head_package = self.app.session_state["mw_package"]["bytes"]
        next(iter(self.app.file_uploader)).set_value(("head.blproj", head_package, "application/zip"))
        self.button("모델 파일 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["mw_view"]["selected_field"], "head")
        self.assertTrue(any("수두 표시 설정은 보존" in item.value for item in self.app.info))
        self.assertFalse(any(item.label == "선택 시각 모델 수두 CSV 다운로드" for item in self.app.get("download_button")))
        next(iter(self.app.file_uploader)).set_value(("tampered.blproj", package["bytes"][:-30], "application/zip"))
        self.button("모델 파일 불러오기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state["mw_case"], original)
        keeper = self.app.session_state["mw_package_keeper"]
        loaded_root = Path(keeper.name)
        changed = copy.deepcopy(original)
        changed["project"]["name"] += " edited after package load"
        view_before = copy.deepcopy(self.app.session_state["mw_view"])
        self.app.text_area[0].set_value(json.dumps(changed)).run()
        self.button("검증한 모델 초안 적용").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertEqual(self.app.session_state["mw_source"], "검증해 적용한 편집 초안")
        self.assertEqual(self.app.session_state["mw_view"], view_before)
        for key in ("mw_loaded_package_receipt", "mw_package_keeper"):
            with self.assertRaises(KeyError):
                self.app.session_state[key]
        self.assertFalse(loaded_root.exists())

    def test_native_export_roundtrip_and_missing_engine_retains_valid_case(self):
        from basinlens_ccs.subsurface.model_workflow import verify_workflow_export
        self.load()
        original = copy.deepcopy(self.app.session_state["mw_case"])
        exported = self.base / "export"
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(exported))
        self.text("모델 MODFLOW 6 실행 파일").set_value(str(self.base / "no-mf6"))
        self.button("모델 MF6 입력 내보내기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        verify_workflow_export(exported)
        archive = zipfile.ZipFile(io.BytesIO(self.app.session_state["mw_export"]["bundle"]))
        self.assertTrue(any(name.endswith("mfsim.nam") for name in archive.namelist()))
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(self.base / "roundtrip"))
        self.button("모델 네이티브 왕복 검증").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        self.assertIn("receipt", self.app.session_state["mw_roundtrip"])
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(self.base / "failed-run"))
        self.button("모델 MF6 실제 실행").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("실제 실행" in item.value for item in self.app.error))
        self.assertEqual(self.app.session_state["mw_case"], original)
        self.assertEqual(self.app.session_state["mw_diagnostic"]["output_path"], str(self.base / "failed-run"))
        with self.assertRaises(KeyError):
            self.app.session_state["mw_result"]

    @unittest.skipUnless(SOLVER, "MF6_EXE or mf6 on PATH is required for the actual model UI run")
    def test_actual_run_results_are_captured_case_bound_and_downloads_verified(self):
        from basinlens_ccs.groundwater.native_run import verify_native_run
        from basinlens_ccs.subsurface.model_workflow import preview_grid
        self.load()
        # Asymmetric rows make an accidental native/project row flip observable.
        data = copy.deepcopy(self.app.session_state["mw_case"])
        data["grid"]["nrow"] = 2
        for assignment in data["assignments"]:
            assignment["cells"] += [[k, 1, col] for k, row, col in list(assignment["cells"])]
        extra = []
        for boundary in data["boundaries"]:
            if boundary["kind"] == "CHD":
                item = copy.deepcopy(boundary)
                item["cell"][1] = 1
                item["label"] += "_north"
                item["values"]["head_m"] += 0.75
                extra.append(item)
        data["boundaries"] += extra
        data["initial_head_m"] = [12.0] * (len(data["grid"]["layer_surfaces_m"]) - 1) * data["grid"]["nrow"] * data["grid"]["ncol"]
        self.app.text_area[0].set_value(json.dumps(data)).run()
        self.button("검증한 모델 초안 적용").click().run()
        self.assertEqual(list(self.app.error), [])
        self.text("모델 작업 폴더 (새 폴더)").set_value(str(self.base / "actual"))
        self.text("모델 MODFLOW 6 실행 파일").set_value(SOLVER)
        self.button("모델 MF6 실제 실행").click().run(timeout=120)
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        products = self.app.session_state["mw_result"]
        result = products["captured_result"]
        self.assertEqual(verify_native_run(self.base / "actual")["status"], "completed")
        self.assertEqual(result.case.to_dict(), self.app.session_state["mw_case"])
        self.assertTrue(np.isfinite(result.heads_m).all())
        self.assertTrue(result.summary["water_balance_passed"])
        self.assertTrue(result.summary["boundary_rates_passed"])
        self.assertTrue(result.summary["confined_saturation_support_passed"])
        self.assertTrue(any("판정이 통과했습니다" in item.value for item in self.app.success))
        self.select("모델 표시 항목").set_value("head").run()
        self.assertEqual(list(self.app.exception), [])
        figure = self.app.session_state["mw_figure"]
        self.assertEqual(figure.layout.xaxis.title.text, "x (m)")
        self.assertEqual(figure.layout.yaxis.title.text, "y (m)")
        csv = pd.read_csv(io.BytesIO(self.app.session_state["mw_result"]["heads_csv"]))
        cells = pd.DataFrame(preview_grid(result.case)["cells"])
        np.testing.assert_allclose(csv["head_m"], result.heads_m[0].reshape(-1))
        np.testing.assert_allclose(csv["x_m"], cells["x_m"])
        np.testing.assert_allclose(csv["y_m"], cells["y_m"])
        self.assertTrue(np.all(np.diff(np.unique(csv["y_m"])) > 0))
        # Fixed-head north/south edges retain their distinct physical coordinates.
        self.assertAlmostEqual(result.heads_m[0, 0, 0, 0], 12.0)
        self.assertAlmostEqual(result.heads_m[0, 0, 1, 0], 12.75)
        self.assertEqual(float(figure.data[0].y[0]), data["grid"]["y_origin_m"] + data["grid"]["dy_m"] / 2)
        archive = zipfile.ZipFile(io.BytesIO(products["bundle"]))
        self.assertIn("native_run_metadata.json", archive.namelist())
        self.assertTrue(any(name.endswith(".hds") for name in archive.namelist()))
        labels = {item.label for item in self.app.get("download_button")}
        self.assertTrue({"검증한 모델 실행 ZIP 다운로드", "선택 시각 모델 수두 CSV 다운로드"} <= labels)
        result.summary["confined_saturation_support_passed"] = False
        self.app.run()
        self.assertTrue(any("통과하지 않은 판정" in item.value for item in self.app.error))
        self.assertFalse(any("판정이 통과했습니다" in item.value for item in self.app.success))
        changed = copy.deepcopy(self.app.session_state["mw_case"])
        changed["project"]["name"] += " new"
        self.app.text_area[0].set_value(json.dumps(changed)).run()
        self.assertNotIn("검증한 모델 실행 ZIP 다운로드", {item.label for item in self.app.get("download_button")})
        self.assertEqual(verify_native_run(self.base / "actual")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
