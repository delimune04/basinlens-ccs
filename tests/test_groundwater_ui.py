"""Optional end-to-end checks for the groundwater workbench.

Install the app and groundwater extras to run these tests. Set MF6_EXE to an
installed MODFLOW 6 executable to include the real-solver UI flow.
"""

from __future__ import annotations

import importlib.util
import io
import json
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

    def test_domain_change_sets_background_water_and_invalidates_outputs(self):
        original_case = self.app.session_state["gw_case"]
        self.app.session_state["gw_result"] = {"old": True}
        self.app.session_state["gw_input_zip"] = b"old"
        selector = next(box for box in self.app.selectbox if box.label == "프로젝트 분야")
        selector.set_value("ccs").run()
        self.assertEqual(list(self.app.exception), [])
        project = self.app.session_state["gw_project"]
        self.assertEqual(project["domain"], "ccs")
        self.assertEqual(project["model"]["role"], "background_water")
        self.assertEqual(self.app.session_state["gw_case"], original_case)
        for key in ("gw_result", "gw_input_zip"):
            with self.assertRaises(KeyError):
                self.app.session_state[key]
        selector = next(box for box in self.app.selectbox if box.label == "프로젝트 분야")
        selector.set_value("oil_exploration").run()
        self.assertEqual(self.app.session_state["gw_project"]["model"]["role"], "background_water")

    def test_unsupported_multiphase_engine_controls_are_disabled(self):
        buttons = [button for button in self.app.button if button.key and button.key.startswith("gw_unavailable_")]
        self.assertEqual(len(buttons), 3)
        self.assertTrue(all(button.disabled for button in buttons))

    def test_common_project_import_is_strict_and_rejects_unavailable_physics(self):
        from groundwater_app import project_from_upload
        example = APP.parent / "examples/subsurface/ccs_background_water.json"
        project = project_from_upload(example.read_bytes())
        self.assertEqual(project.domain, "ccs")
        self.assertTrue(project.assets)
        with self.assertRaises(ValueError):
            project_from_upload(b'{"schema_version":1,"schema_version":1}')
        data = project.to_dict()
        data["model"].update(engine_id="opm_flow_co2", physics="co2_brine_multiphase", role="co2_storage")
        with self.assertRaises(RuntimeError):
            project_from_upload(json.dumps(data).encode())

    def import_fixture_into_state(self):
        from dataclasses import replace
        from basinlens_ccs.subsurface import Modflow6Adapter, load_project
        example = APP.parent / "examples/subsurface/ccs_background_water.json"
        project = load_project(example)
        project = replace(project, geometry=replace(project.geometry, origin_x_m=350000.0, origin_y_m=4100000.0))
        case, _ = Modflow6Adapter().prepare(project)
        self.app.session_state["gw_case"] = case.to_dict()
        self.app.session_state["gw_project"] = project.to_dict()
        self.app.session_state["gw_revision"] += 1
        self.app.run()
        return project, example

    def test_native_edit_preserves_common_evidence_and_export_verifies_assets(self):
        project, example = self.import_fixture_into_state()
        root = next(field for field in self.app.text_input if field.label == "원본 자료가 있는 실행 서버 폴더")
        root.set_value(str(example.parent))
        self.number("좌측 고정수두 (m)").set_value(13.0)
        self.button("경계와 함양 적용").click().run()
        self.assertEqual(list(self.app.exception), [])
        stored = self.app.session_state["gw_project"]
        self.assertEqual(stored["assets"], project.to_dict()["assets"])
        self.assertEqual(stored["stratigraphy"], project.to_dict()["stratigraphy"])
        self.assertEqual(stored["geometry"]["origin_x_m"], 350000.0)
        self.assertEqual(stored["model"]["options"]["boundaries"]["left_head_m"], 13.0)
        self.button("엔진 없이 MF6 입력 파일 만들기").click().run()
        self.assertEqual(list(self.app.error), [])
        archive = zipfile.ZipFile(io.BytesIO(self.app.session_state["gw_project_input_zip"]))
        self.assertIn("engine/model/mfsim.nam", archive.namelist())
        summary = json.loads(archive.read("project_summary.json"))
        self.assertEqual(summary["assets_verified"], {asset.asset_id: asset.sha256 for asset in project.assets})
        self.assertEqual(json.loads(archive.read("project.json"))["geometry"]["origin_x_m"], 350000.0)

    def test_referenced_assets_without_server_root_block_export(self):
        self.import_fixture_into_state()
        self.button("엔진 없이 MF6 입력 파일 만들기").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("asset_root" in error.value for error in self.app.error))
        with self.assertRaises(KeyError):
            self.app.session_state["gw_project_input_zip"]

    def test_edited_hydraulic_fields_keep_sources_and_become_assumptions(self):
        from basinlens_ccs.subsurface import Modflow6Adapter, load_project
        from groundwater_app import common_project_for_case
        project = load_project(APP.parent / "examples/subsurface/ccs_background_water.json")
        native, _ = Modflow6Adapter().prepare(project)
        edited = native.to_dict()
        edited["properties"]["kx_m_per_day"][0] = 20.0
        updated = common_project_for_case(edited, "ccs", project)
        field = next(field for field in updated.rock_properties if field.name == "hydraulic_conductivity_x")
        original = next(field for field in project.rock_properties if field.name == "hydraulic_conductivity_x")
        self.assertEqual(field.basis, "assumed")
        self.assertEqual(field.source_asset_ids, original.source_asset_ids)
        self.assertEqual(updated.assets, project.assets)
        self.assertTrue(any("not new measurements" in note for note in updated.provenance.assumptions))

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
        selector = next(box for box in self.app.selectbox if box.label == "프로젝트 분야")
        selector.set_value("ccs").run()
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
        common = zipfile.ZipFile(io.BytesIO(result["project_bundle"]))
        self.assertIn("engine/heads.npz", common.namelist())
        self.assertIn("project_run_metadata.json", common.namelist())
        summary = json.loads(common.read("project_summary.json"))
        self.assertEqual(summary["domain"], "ccs")
        self.assertEqual(summary["role"], "background_water")
        self.assertEqual(summary["physics"], "single_phase_confined_groundwater")
        self.button("모든 시각·층의 수두 CSV 준비").click().run()
        import pandas as pd

        frame = pd.read_csv(io.BytesIO(self.app.session_state["gw_csv"]))
        self.assertEqual(len(frame), 13 * 3 * 21 * 41)
        self.assertEqual(list(frame.columns), ["time_days", "layer", "row", "column", "x_center_m", "y_center_m", "head_m"])
        self.assertEqual(frame["time_days"].max(), 31.0)


if __name__ == "__main__":
    unittest.main()
