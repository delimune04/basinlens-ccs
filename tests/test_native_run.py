"""Native execution/isolation checks, separate from confined-schema benchmarks."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from basinlens_ccs.groundwater.native_run import NativeRunError, _execute, _manifest, run_native_simulation, verify_native_run

FLOPY = importlib.util.find_spec("flopy") is not None
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def static_graph(root):
    """A resolved text graph for preflight tests; it is not a runnable physics case."""
    root.mkdir(parents=True)
    (root / "mfsim.nam").write_text("BEGIN TIMING\nTDIS6 time.tdis\nEND TIMING\nBEGIN MODELS\nGWF6 flow.nam flow\nEND MODELS\n")
    (root / "time.tdis").write_text("BEGIN OPTIONS\nTIME_UNITS SECONDS\nEND OPTIONS\n")
    (root / "flow.nam").write_text("BEGIN PACKAGES\nDIS6 flow.dis\nOC6 flow.oc\nEND PACKAGES\n")
    (root / "flow.dis").write_text("BEGIN OPTIONS\nLENGTH_UNITS FEET\nEND OPTIONS\n")
    (root / "flow.oc").write_text("BEGIN OPTIONS\nHEAD FILEOUT result/head.hds\nEND OPTIONS\n")


def unconfined_case(root):
    import flopy
    sim = flopy.mf6.MFSimulation(sim_name="native-test", sim_ws=str(root))
    flopy.mf6.ModflowTdis(sim, time_units="SECONDS", perioddata=[(10.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="MODERATE", outer_dvclose=1e-8, inner_dvclose=1e-9)
    model = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    flopy.mf6.ModflowGwfdis(model, length_units="FEET", nlay=1, nrow=5, ncol=5,
                          delr=10.0, delc=10.0, top=100.0, botm=0.0)
    flopy.mf6.ModflowGwfic(model, strt=85.0)
    flopy.mf6.ModflowGwfnpf(model, icelltype=1, k=0.1, save_flows=True)
    flopy.mf6.ModflowGwfchd(model, stress_period_data=[((0, row, col), head)
        for row in range(5) for col, head in ((0, 90.0), (4, 80.0))])
    flopy.mf6.ModflowGwfwel(model, stress_period_data=[((0, 2, 2), 0.01)])
    flopy.mf6.ModflowGwfdrn(model, stress_period_data=[((0, 1, 2), 85.0, 0.05)])
    flopy.mf6.ModflowGwfrcha(model, recharge=0.00001)
    flopy.mf6.ModflowGwfoc(model, head_filerecord="outputs/flow.hds", budget_filerecord="outputs/flow.cbc",
                          saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
    sim.write_simulation(silent=True)
    (root / "settings.json").write_text('{"opaque_unknown_setting":[1,"preserve",false]}')
    (root / "gms_options.json").write_text('{"unknown_model_option":{"native_unit_label":"feet"}}')


class NativePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        static_graph(self.source)
        self.output = self.base / "run"

    def reject(self):
        with self.assertRaises((ValueError, RuntimeError)):
            run_native_simulation(self.source, self.output, exe_name="/nonexistent/mf6")
        self.assertFalse(self.output.exists())

    def test_absolute_and_escaping_fileout_and_listing_paths_are_rejected(self):
        for value in ("../escape.hds", "/tmp/native-escape.hds", "C:/native-escape.hds", str(self.source / "inside-absolute.hds")):
            (self.source / "flow.oc").write_text(f"BEGIN OPTIONS\nHEAD FILEOUT {value}\nEND OPTIONS\n")
            self.reject()
        (self.source / "flow.oc").write_text("BEGIN OPTIONS\nEND OPTIONS\n")
        (self.source / "flow.nam").write_text("BEGIN OPTIONS\nLIST ../escape.lst\nEND OPTIONS\nBEGIN PACKAGES\nDIS6 flow.dis\nEND PACKAGES\n")
        self.reject()

    def test_unresolved_graph_and_input_output_collision_are_rejected(self):
        (self.source / "flow.oc").unlink()
        self.reject()
        (self.source / "flow.oc").write_text("BEGIN OPTIONS\nHEAD FILEOUT flow.dis\nEND OPTIONS\n")
        self.reject()

    def test_source_tree_output_and_existing_output_are_refused(self):
        with self.assertRaises((ValueError, RuntimeError)):
            run_native_simulation(self.source, self.source / "nested-run", exe_name="/nonexistent/mf6")
        self.assertFalse((self.source / "nested-run").exists())
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("existing user output")
        with self.assertRaises(FileExistsError):
            run_native_simulation(self.source, self.output)
        self.assertEqual(sentinel.read_text(), "existing user output")

    def test_symlink_inputs_and_dangling_output_links_are_refused(self):
        outside = self.base / "outside.dis"
        outside.write_text((self.source / "flow.dis").read_text())
        (self.source / "flow.dis").unlink()
        (self.source / "flow.dis").symlink_to(outside)
        self.reject()

    def test_invalid_budgets_and_missing_solver_create_no_run(self):
        for timeout in (True, 0, -1, float("nan"), float("inf"), 1801):
            with self.assertRaises(NativeRunError):
                run_native_simulation(self.source, self.output, timeout_seconds=timeout)
        with self.assertRaises(NativeRunError):
            run_native_simulation(self.source, self.output, max_output_bytes=True)
        self.reject()

    def test_timeout_and_disk_budget_kill_child_and_keep_logs(self):
        stdout, stderr = self.base / "stdout", self.base / "stderr"
        with self.assertRaisesRegex(NativeRunError, "timeout"):
            _execute([sys.executable, "-c", "import time;print('started',flush=True);time.sleep(5)"],
                     self.base, stdout, stderr, 0.1, 1024 * 1024)
        self.assertIn("started", stdout.read_text())
        stdout.unlink()
        stderr.unlink()
        with self.assertRaisesRegex(NativeRunError, "budget"):
            _execute([sys.executable, "-c", "from pathlib import Path;Path('big-output').write_bytes(b'x'*2000000)"],
                     self.base, stdout, stderr, 5, 1024 * 1024)

    def test_nested_manifest_basenames_remain_checksummed(self):
        root = self.base / "bundle"
        for folder in ("native", "source_sidecars"):
            path = root / folder / "native_run_metadata.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"nested input or output bytes")
        _manifest(root, "failed", {"schema": "test"})
        metadata = json.loads((root / "native_run_metadata.json").read_text())
        self.assertEqual(set(metadata["files"]), {"native/native_run_metadata.json", "source_sidecars/native_run_metadata.json"})

    def test_failed_bundle_verifier_rejects_tamper_extra_missing_and_unsafe_inventory(self):
        root = self.base / "failed-bundle"
        root.mkdir()
        failure = root / "native_failure.json"
        failure.write_text('{"status":"failed","error_type":"OSError"}')
        metadata = {"schema": "basinlens-native-mf6-run-v1", "solver_executed": False,
                    "source_snapshot": {"inputs": {"mfsim.nam": {"bytes": 1, "sha256": "a" * 64}}, "sidecars": {}}}
        _manifest(root, "failed", metadata)
        self.assertEqual(verify_native_run(root)["status"], "failed")
        captured = (root / "native_run_metadata.json").read_text()
        extra = root / "unlisted"
        extra.write_text("extra")
        with self.assertRaisesRegex(NativeRunError, "inventory"):
            verify_native_run(root)
        extra.unlink()
        original = failure.read_text()
        failure.write_text("tampered")
        with self.assertRaisesRegex(NativeRunError, "identity"):
            verify_native_run(root)
        failure.unlink()
        with self.assertRaisesRegex(NativeRunError, "inventory"):
            verify_native_run(root)
        failure.write_text(original)
        changed = json.loads(captured)
        changed["files"]["../outside"] = {"bytes": 0, "sha256": "a" * 64}
        (root / "native_run_metadata.json").write_text(json.dumps(changed))
        with self.assertRaises(NativeRunError):
            verify_native_run(root)
        (root / "native_run_metadata.json").write_text(captured)
        self.assertEqual(verify_native_run(root)["status"], "failed")


@unittest.skipUnless(FLOPY and SOLVER, "FloPy and MF6_EXE/mf6 are required for actual native execution")
class NativeActualSolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        unconfined_case(self.source)

    def test_unconfined_native_feet_seconds_wells_drains_recharge_and_sidecars(self):
        import flopy
        original = {path.name: digest(path) for path in self.source.iterdir() if path.is_file()}
        result = run_native_simulation(self.source, self.base / "run", exe_name=SOLVER)
        metadata = json.loads((result.workspace / "native_run_metadata.json").read_text())
        self.assertEqual(verify_native_run(result.workspace), metadata)
        self.assertEqual(metadata["status"], "completed")
        self.assertIs(metadata["original_sources_unchanged"], True)
        self.assertIs(metadata["copied_inputs_unchanged"], True)
        self.assertIs(metadata["bounded_confined_schema_used"], False)
        self.assertEqual(result.summary["physics_validation"], "not evaluated")
        self.assertEqual(result.summary["native_units"]["length"][0]["declared"], "FEET")
        self.assertEqual(result.summary["native_units"]["time"][0]["declared"], "SECONDS")
        self.assertEqual({path.name: digest(path) for path in self.source.iterdir() if path.is_file()}, original)
        self.assertFalse((result.simulation_workspace / "settings.json").exists())
        self.assertEqual((result.workspace / "source_sidecars/settings.json").read_bytes(), (self.source / "settings.json").read_bytes())
        reader = flopy.utils.HeadFile(result.simulation_workspace / "outputs/flow.hds")
        try:
            heads = reader.get_data()
        finally:
            reader.close()
        self.assertEqual(heads.shape, (1, 5, 5))
        self.assertLess(float(heads.max()), 100.0)  # Unconfined water, below model top.
        self.assertEqual(set(metadata["source_snapshot"]["sidecars"]), {"settings.json", "gms_options.json"})
        for relative, record in metadata["files"].items():
            self.assertEqual(digest(result.workspace / relative), record["sha256"])

    def test_native_solver_failure_retains_diagnostics_and_original_inputs(self):
        npf = self.source / "flow.npf"
        npf.write_text(npf.read_text().replace("BEGIN options", "BEGIN INVALID_BLOCK"))
        # FloPy writes lowercase begin/end. Force a native grammar failure directly.
        npf.write_text("BEGIN INVALID_BLOCK\nINVALID_KEYWORD 1\nEND INVALID_BLOCK\n")
        original = digest(npf)
        output = self.base / "failed"
        with self.assertRaises(NativeRunError):
            run_native_simulation(self.source, output, exe_name=SOLVER)
        metadata = json.loads((output / "native_run_metadata.json").read_text())
        self.assertEqual(metadata["status"], "failed")
        self.assertIs(metadata["solver_executed"], True)
        self.assertIs(metadata["original_sources_unchanged"], True)
        self.assertEqual(digest(npf), original)
        self.assertTrue((output / "solver.stdout.log").is_file())
        self.assertTrue((output / "native_failure.json").is_file())

    def test_native_head_named_like_root_manifest_is_preserved(self):
        oc = self.source / "flow.oc"
        oc.write_text(oc.read_text().replace("outputs/flow.hds", "native_run_metadata.json"))
        result = run_native_simulation(self.source, self.base / "same-name-run", exe_name=SOLVER)
        metadata = json.loads((result.workspace / "native_run_metadata.json").read_text())
        key = "native/native_run_metadata.json"
        self.assertIn(key, metadata["files"])
        self.assertEqual(metadata["files"][key]["sha256"], digest(result.workspace / key))


if __name__ == "__main__":
    unittest.main()
