"""Failure honesty and public-output minimization for the opt-in REA probe."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("native_rea_probe", Path(__file__).parents[1] / "tools" / "native_rea_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


FAKE = '''import json,os,sys,time
mode=os.environ.get("PROBE_FIXTURE_MODE","success")
if mode=="timeout":time.sleep(10)
if mode=="oversized":print("PRIVATE_NATIVE_BODY"*1000);sys.exit(0)
if mode=="malformed":print("PRIVATE_NATIVE_BODY");sys.exit(0)
if mode=="error":
 print(json.dumps({"code":"capability_unavailable","message":"PRIVATE_NATIVE_BODY"}));sys.exit(0)
if sys.argv[1]=="doctor":print(json.dumps({"healthy":True,"checks":[{"detail":"PRIVATE_NATIVE_BODY"}]}))
else:print(json.dumps({"subject":{"architecture":"x86_64","local_path":"PRIVATE_NATIVE_BODY"},"normalized_result":{"procedure_count":12,"string_count":34,"pseudocode":"PRIVATE_NATIVE_BODY"}}))
print("PRIVATE_NATIVE_BODY",file=sys.stderr)
'''


class NativeProbeTests(unittest.TestCase):
    def invoke(self, root, mode="success", timeout=10, max_bytes=100000):
        target = root / "target.exe"; target.write_bytes(b"MZsynthetic-fixture-only")
        cli = root / "fake.py"; cli.write_text(FAKE)
        ghidra, jdk = root / "ghidra", root / "jdk"
        ghidra.mkdir(); jdk.mkdir()
        public, private = root / "public", root / "private"
        with patch.dict(os.environ, {"GHIDRA_INSTALL_DIR": str(ghidra), "JAVA_HOME": str(jdk), "PROBE_FIXTURE_MODE": mode}):
            status = probe.main(["--target", str(target), "--rea-cli", str(cli), "--node", sys.executable,
                "--output", str(public), "--private-workspace", str(private), "--timeout-seconds", str(timeout),
                "--max-output-bytes", str(max_bytes)])
        raw = (public / "public-summary.json").read_text()
        self.assertNotIn("PRIVATE_NATIVE_BODY", raw)
        self.assertEqual([p.name for p in public.iterdir()], ["public-summary.json"])
        return status, json.loads(raw), private

    def test_success_exports_only_counts_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            status, summary, private = self.invoke(Path(td))
            self.assertEqual(status, 0)
            self.assertEqual(summary["overview"], {"procedure_count": 12, "string_count": 34, "architecture": "x86_64"})
            self.assertEqual(summary["provider_health"], "healthy")
            self.assertIn("PRIVATE_NATIVE_BODY", (private / "analysis.stdout").read_text())

    def test_json_error_fails_even_with_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            status, summary, private = self.invoke(Path(td), "error")
            self.assertEqual(status, 1)
            self.assertEqual(summary["doctor"]["status"], "tool_error")
            self.assertEqual(summary["doctor"]["exit_code"], 0)
            self.assertEqual(summary["analysis"]["status"], "not_run")
            self.assertFalse((private / "analysis.stdout").exists())

    def test_malformed_oversized_and_timed_out_outputs_fail(self):
        for mode, expected in [("malformed", "malformed_json"), ("oversized", "output_limit"), ("timeout", "timeout")]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                status, summary, private = self.invoke(Path(td), mode, timeout=1, max_bytes=1024)
                self.assertNotEqual(status, 0)
                self.assertEqual(summary["doctor"]["status"], expected)
                self.assertEqual(summary["status"], "failed")
                if mode == "oversized":
                    self.assertLessEqual(sum(p.stat().st_size for p in private.glob("*.stdout")), 1024)

    def test_public_private_paths_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = probe.main(["--target", str(root / "none"), "--rea-cli", str(root / "none"),
                "--output", str(root / "public"), "--private-workspace", str(root / "public" / "private")])
            self.assertEqual(status, 2)
            self.assertFalse((root / "public").exists())


if __name__ == "__main__":
    unittest.main()
