"""Optional UI checks for unchanged native decks, isolated from bounded cases."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

APP = Path(__file__).resolve().parents[1] / "groundwater_app.py"
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("streamlit", "plotly", "flopy"))
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


@unittest.skipUnless(AVAILABLE, "Native UI needs Streamlit, Plotly and FloPy")
class NativeWorkbenchUITests(unittest.TestCase):
    def setUp(self):
        import flopy
        from streamlit.testing.v1 import AppTest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        sim = flopy.mf6.MFSimulation(sim_ws=str(self.source))
        flopy.mf6.ModflowTdis(sim, time_units="HOURS", perioddata=[(2.0, 1, 1.0)])
        flopy.mf6.ModflowIms(sim, complexity="MODERATE")
        model = flopy.mf6.ModflowGwf(sim, modelname="native")
        flopy.mf6.ModflowGwfdis(model, length_units="FEET", nlay=1, nrow=1, ncol=3,
                              delr=10.0, delc=10.0, top=100.0, botm=0.0)
        flopy.mf6.ModflowGwfic(model, strt=85.0)
        flopy.mf6.ModflowGwfnpf(model, icelltype=1, k=1.0)
        flopy.mf6.ModflowGwfchd(model, stress_period_data=[((0, 0, 0), 90.0), ((0, 0, 2), 80.0)])
        flopy.mf6.ModflowGwfoc(model, head_filerecord="output/native.hds", saverecord=[("HEAD", "ALL")])
        sim.write_simulation(silent=True)
        (self.source / "gms_options.json").write_text('{"opaque":"preserved"}')
        self.app = AppTest.from_file(str(APP), default_timeout=45).run()
        self.assertEqual(list(self.app.exception), [])

    def text(self, label):
        return next(field for field in self.app.text_input if field.label == label)

    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def fill(self):
        self.text("네이티브 mfsim.nam 또는 폴더").set_value(str(self.source))
        self.text("네이티브 실행 결과 폴더").set_value(str(self.base / "run"))

    def test_native_preflight_preserves_units_and_bounded_case_state(self):
        original = self.app.session_state["gw_case"]
        self.fill()
        self.button("네이티브 입력 검사").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        report = self.app.session_state["gw_native_report"]
        self.assertEqual(report["native_units"]["length"][0]["declared"], "FEET")
        self.assertEqual(report["native_units"]["time"][0]["declared"], "HOURS")
        self.assertIn("NPF6", report["package_types"])
        self.assertEqual(report["opaque_sidecars"], 1)
        self.assertEqual(self.app.session_state["gw_case"], original)
        self.assertFalse((self.base / "run").exists())

    def test_unsafe_native_fileout_has_visible_error_and_no_run(self):
        oc = self.source / "native.oc"
        oc.write_text(oc.read_text().replace("output/native.hds", "../outside.hds"))
        self.fill()
        self.button("네이티브 입력 검사").click().run()
        self.assertEqual(list(self.app.exception), [])
        self.assertTrue(any("네이티브 입력/실행 오류" in error.value for error in self.app.error))
        self.assertFalse((self.base / "run").exists())
        with self.assertRaises(KeyError):
            self.app.session_state["gw_native_zip"]

    @unittest.skipUnless(SOLVER, "MF6_EXE or mf6 is required for a real native UI run")
    def test_actual_native_run_download_is_verified_and_separate(self):
        from basinlens_ccs.groundwater.native_run import verify_native_run
        original = self.app.session_state["gw_case"]
        self.fill()
        self.text("MODFLOW 6 실행 파일").set_value(SOLVER)
        self.button("네이티브 MF6 실행").click().run(timeout=90)
        self.assertEqual(list(self.app.exception), [])
        self.assertEqual(list(self.app.error), [])
        result = self.app.session_state["gw_native_result"]
        self.assertEqual(result["verified_status"], "completed")
        self.assertEqual(verify_native_run(self.base / "run")["status"], "completed")
        archive = zipfile.ZipFile(io.BytesIO(self.app.session_state["gw_native_zip"]))
        self.assertIn("native_run_metadata.json", archive.namelist())
        self.assertIn("native/output/native.hds", archive.namelist())
        self.assertIn("source_sidecars/gms_options.json", archive.namelist())
        summary = json.loads(archive.read("native_summary.json"))
        self.assertEqual(summary["native_units"]["time"][0]["declared"], "HOURS")
        self.assertEqual(summary["physics_validation"], "not evaluated")
        self.assertEqual(self.app.session_state["gw_case"], original)
        with self.assertRaises(KeyError):
            self.app.session_state["gw_result"]


if __name__ == "__main__":
    unittest.main()
