"""Failure honesty and public-output minimization for the opt-in REA probe."""
import importlib.util
import io
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
if mode=="deleted_logs" and sys.argv[1]=="analyze":
 from pathlib import Path
 root=Path(os.environ["TMPDIR"])/"rea-ghidra-fixture";root.mkdir()
 log=root/"ghidra.log"
 log.write_text("INFO (HeadlessAnalyzer) IMPORTING: PRIVATE_NATIVE_BODY\\nINFO (HeadlessAnalyzer) ANALYZING all memory and code: PRIVATE_NATIVE_BODY\\nINFO (AutoAnalysisManager) ANALYSIS REPORT\\n    Disassemble Entry Points    753.416 secs\\n    PRIVATE_NATIVE_BODY    99.0 secs\\n    Stack    1.25 secs PRIVATE_NATIVE_BODY\\n")
 time.sleep(.35);log.unlink();root.rmdir()
 print(json.dumps({"code":"provider_timeout","message":"PRIVATE_NATIVE_BODY","details":{"cleanup":"incomplete","diagnostics":{"target_path":"PRIVATE_NATIVE_BODY","configured_jvm_max_heap":"4G","output_incomplete":True,"diagnostic_truncated":False,"stderr":{"text":"java.lang.OutOfMemoryError: PRIVATE_NATIVE_BODY"}}}}));sys.exit(1)
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

    def test_provider_deadline_unchanged_and_outer_grace_separate(self):
        calls = []
        original = probe.execute_private
        def record(*args, **kwargs):
            calls.append((args[2], args[3], kwargs["environment"]["REA_GHIDRA_STARTUP_TIMEOUT_MS"]))
            return original(*args, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch.object(probe, "execute_private", side_effect=record):
            status, summary, _ = self.invoke(Path(td), timeout=1200)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [("doctor", 120, "1200000"), ("analysis", 1290, "1200000")])
        self.assertEqual(summary["deadlines"]["cleanup_grace_seconds"], 90)

    def test_deleted_owned_logs_still_yield_only_sanitized_facts(self):
        with tempfile.TemporaryDirectory() as td:
            status, summary, private = self.invoke(Path(td), "deleted_logs")
            self.assertEqual(status, 1)
            self.assertEqual(summary["provider_health"], "healthy")
            self.assertEqual(summary["analysis"]["error_code"], "provider_timeout")
            diagnostic = summary["analysis"]["diagnostics"]
            self.assertEqual(diagnostic["analyzer_timings_seconds"], {"Disassemble Entry Points": 753.416})
            self.assertIn("auto_analysis_started", diagnostic["stages_observed"])
            self.assertEqual(diagnostic["configured_jvm_max_heap"], "4G")
            self.assertTrue(diagnostic["jvm_out_of_memory_reported"])
            self.assertEqual(diagnostic["provider_reported_cleanup"], "incomplete")
            self.assertFalse(any((private / "rea-runtime").iterdir()))

    def test_outer_timeout_preserved_for_retained_error_or_success(self):
        for body, expected_code in [({"code": "provider_timeout", "message": "PRIVATE_NATIVE_BODY",
                                     "details": {"diagnostics": {"configured_jvm_max_heap": "4G"}}}, "provider_timeout"),
                                    ({"normalized_result": {"procedure_count": 12, "string_count": 34}}, None)]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                program = root / "slow.py"
                program.write_text("import sys,time\nsys.stdout.write(" + repr(json.dumps(body)) + ")\nsys.stdout.flush()\ntime.sleep(10)\n")
                state, raw = probe.execute_private([sys.executable, str(program)], root, "slow", .15, 100000)
                public, result = probe.read_tool_result(raw, state)
                self.assertEqual(public["status"], "timeout")
                self.assertEqual(public.get("error_code"), expected_code)
                self.assertEqual(public["diagnostics"]["configured_jvm_max_heap"], "4G" if expected_code else None)
                self.assertIsNone(result)
                self.assertNotIn("PRIVATE_NATIVE_BODY", json.dumps(public))

    def test_truncated_or_nonfinite_json_never_promotes_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "raw.json"
            for text in ['{"code":"provider_timeout",', '{"value":NaN}', '{"value":1e9999}', '{"code":"provider_timeout","code":"other"}']:
                path.write_text(text)
                for status in ("timeout", "exited"):
                    public, result = probe.read_tool_result(path, {"status": status, "exit_code": 1, "elapsed_seconds": 1})
                    self.assertIsNone(result)
                    self.assertEqual(public["status"], "timeout" if status == "timeout" else "malformed_json")
                    self.assertEqual(public["retained_json_status"], "malformed_or_truncated")

    def test_retained_json_growth_cannot_exceed_read_budget(self):
        requested = []
        class GrowingStream(io.BytesIO):
            def read(self, size=-1):
                requested.append(size)
                return super().read(size)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "raw.json"
            path.write_bytes(b"{}")
            with patch.object(probe, "MAX_JSON_BYTES", 32), \
                    patch.object(Path, "open", return_value=GrowingStream(b"x" * 100)):
                public, result = probe.read_tool_result(path, {"status": "exited", "exit_code": 0})
            self.assertEqual(requested, [33])
            self.assertIsNone(result)
            self.assertEqual(public["status"], "output_limit")
            self.assertEqual(public["retained_json_status"], "json_size_limit")

    @unittest.skipUnless(os.name == "posix", "Symbolic-link boundary check uses POSIX")
    def test_watcher_refuses_symlink_logs_and_runtime_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); base = root / "owned"; base.mkdir()
            outside = root / "outside"; outside.mkdir()
            (outside / "ghidra.log").write_text("    Stack    123.0 secs\nPRIVATE_NATIVE_BODY")
            (base / "rea-ghidra-symlink").symlink_to(outside, target_is_directory=True)
            runtime = base / "rea-ghidra-real"; runtime.mkdir()
            (runtime / "ghidra.log").symlink_to(outside / "ghidra.log")
            collector = probe.DiagnosticCollector(base); collector.poll(); public = collector.public()
            self.assertEqual(public["analyzer_timings_seconds"], {})
            self.assertEqual(public["owned_log_capture"]["unsafe_entries_ignored"], 2)
            self.assertEqual(public["provider_reported_cleanup"], "unknown")
            self.assertNotIn("PRIVATE_NATIVE_BODY", json.dumps(public))

    def test_untrusted_diagnostics_types_and_unknown_names_are_not_exported(self):
        collector = probe.DiagnosticCollector()
        collector.text("    PRIVATE_NATIVE_BODY    12.0 secs\n    Stack    1.0 secs /PRIVATE_NATIVE_BODY\n    Stack    " + "9" * 400 + " secs")
        collector.error({"details": {"cleanup": "PRIVATE_NATIVE_BODY", "diagnostics": {
            "configured_jvm_max_heap": "4G PRIVATE_NATIVE_BODY", "output_incomplete": 1,
            "diagnostic_truncated": "PRIVATE_NATIVE_BODY", "profile_digest": "PRIVATE_NATIVE_BODY",
            "stdout": {"text": "PRIVATE_NATIVE_BODY"}}}})
        public = collector.public()
        self.assertEqual(public["analyzer_timings_seconds"], {})
        self.assertIsNone(public["configured_jvm_max_heap"])
        self.assertIsNone(public["provider_output_incomplete"])
        self.assertEqual(public["provider_reported_cleanup"], "unknown")
        self.assertNotIn("PRIVATE_NATIVE_BODY", json.dumps(public))
        for value in (True, float("nan"), float("inf"), -1, 10**4000):
            self.assertFalse(probe.bounded_number(value))

    def test_split_log_lines_wait_for_complete_safe_timing(self):
        collector = probe.DiagnosticCollector()
        collector.chunk("first", b"    Stack    1.2 secs")
        self.assertEqual(collector.public()["analyzer_timings_seconds"], {})
        collector.chunk("first", b" PRIVATE_NATIVE_BODY\n    Disassemble Entry")
        collector.chunk("first", b" Points    753.416 secs\n")
        collector.text("INFO (HeadlessAnalyzer) Analysis timed out at 1200 seconds\n")
        collector.text("INFO (HeadlessAnalyzer) SCRIPT: PRIVATE_NATIVE_BODY\n")
        public = collector.public()
        self.assertEqual(public["analyzer_timings_seconds"], {"Disassemble Entry Points": 753.416})
        self.assertEqual(public["last_observed_stage"], "post_analysis_script_observed")
        self.assertTrue(public["auto_analysis_timeout_reported"])
        self.assertNotIn("PRIVATE_NATIVE_BODY", json.dumps(public))

    def test_dot_prefixed_runtime_ancestor_fails_closed_without_global_search(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".hidden"; root.mkdir()
            status, summary, _ = self.invoke(root)
            self.assertEqual(status, 2)
            self.assertEqual(summary["failure_kind"], "unsafe_private_runtime_ancestry")
            self.assertEqual(summary["analysis"]["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
