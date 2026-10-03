import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from basinlens_ccs.artifacts import verify_run_bundle
from basinlens_ccs.cli import main


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_sites.csv"


class RunBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_example(self, name="run", *, source=EXAMPLE):
        target = self.root / name
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(source), "--output", str(target), "--samples", "500", "--seed", "7"]), 0)
        return target

    def test_exact_input_bytes_and_artifact_integrity(self):
        target = self.run_example()
        self.assertEqual((target / "input.csv").read_bytes(), EXAMPLE.read_bytes())
        manifest = json.loads((target / "run_metadata.json").read_text())
        self.assertEqual(manifest["artifacts"]["input.csv"]["sha256"], sha256(EXAMPLE.read_bytes()).hexdigest())
        self.assertEqual(manifest["assessment_level"], "concept-screening")
        self.assertEqual(list(manifest["site_seeds"].values()), [7, 8, 9])
        verify_run_bundle(target)

    def test_repeated_runs_have_equal_numerical_artifacts(self):
        first, second = self.run_example("first"), self.run_example("second")
        for name in ("summary.csv", "sensitivity.csv", "report.md"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_existing_run_is_not_overwritten(self):
        target = self.run_example()
        original = (target / "run_metadata.json").read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.run_example()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual((target / "run_metadata.json").read_bytes(), original)

    def test_modified_artifact_fails_verification(self):
        target = self.run_example()
        (target / "summary.csv").write_text("modified\n")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_run_bundle(target)

    def test_missing_artifact_fails_verification(self):
        target = self.run_example()
        (target / "report.md").unlink()
        with self.assertRaises(FileNotFoundError):
            verify_run_bundle(target)

    def test_incomplete_or_unexpected_manifest_is_rejected(self):
        target = self.run_example()
        path = target / "run_metadata.json"
        manifest = json.loads(path.read_text())
        manifest["status"] = "running"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            verify_run_bundle(target)
        manifest["status"] = "completed"
        manifest["artifacts"]["../unexpected"] = {}
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "expected artifacts"):
            verify_run_bundle(target)

    def test_invalid_input_leaves_no_completed_bundle(self):
        source = self.root / "invalid.csv"
        source.write_text("site_id,site_name\nA,Incomplete\n")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_example(source=source)
        self.assertFalse((self.root / "run").exists())

    def test_negative_seed_is_rejected_before_writing(self):
        target = self.root / "run"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([str(EXAMPLE), "--output", str(target), "--seed", "-1"])
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
