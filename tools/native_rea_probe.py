"""Opt-in, static REA/Ghidra probe with a strictly limited public summary.

Raw tool output and snapshots stay in a separate, fresh private directory. This
script never executes the target, disables a provider guard, or publishes native
strings, procedure names, pseudocode, paths, or tool error messages.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time


KNOWN_CODES = {"capability_unavailable", "analysis_timeout", "analysis_cancelled", "configuration_error",
               "analysis_error", "unsupported_target", "target_not_found", "provider_unavailable",
               "provider_timeout", "cleanup_incomplete", "resource_constraint", "cancelled"}
ARCHITECTURES = {"x86", "x86_64", "arm", "arm64", "aarch64", "mips", "mips64", "unknown"}
MAX_JSON_BYTES = 16 * 1024 * 1024
# Fixed public names from Ghidra's analyzer registry/timing reports. Unrecognized
# names, log messages and target-derived text are never copied into a receipt.
ANALYZER_NAMES = frozenset({
    "ASCII Strings", "Apply Data Archives", "Call Convention ID", "Call-Fixup Installer",
    "Create Address Tables", "Create Function", "Data Reference", "Decompiler Parameter ID",
    "Decompiler Switch Analysis", "Demangler GNU", "Demangler Microsoft", "Disassemble",
    "Disassemble Entry Points", "Embedded Media", "Function ID", "Function Start Search",
    "Non-Returning Functions - Discovered", "Non-Returning Functions - Known", "PDB Universal",
    "Reference", "Scalar Operand References", "Stack", "Subroutine References",
    "Windows x86 PE Exception Handling", "Windows x86 Thread Environment Block (TEB) Analyzer",
})


def bounded_number(value, maximum=86400):
    return type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value)


class DiagnosticCollector:
    """Read only this invocation's private logs; retain only fixed safe facts.

    REA 6.7 creates ``rea-ghidra-*`` below os.tmpdir(), logs to ghidra.log and
    script.log, then removes its runtime during cleanup. Polling before cleanup
    preserves observations without modifying the provider or its ownership guard.
    """
    def __init__(self, runtime_parent=None):
        self.runtime_parent = runtime_parent
        self.positions = {}
        self.partial_lines = {}
        self.unsafe = set()
        self.bytes_read = 0
        self.truncated = False
        self.stages = set()
        self.last_stage = "unknown"
        self.timings = {}
        self.total_seconds = None
        self.analysis_timeout = False
        self.oom = False
        self.heap = None
        self.cleanup = "unknown"
        self.output_incomplete = None
        self.provider_truncated = None
        self.profile_digest = None

    def stage(self, name):
        self.stages.add(name)
        self.last_stage = name

    def chunk(self, identity, content, reset=False):
        # File polling can split a timing line. Keep only a bounded final line
        # privately, and parse complete lines so a later suffix cannot turn an
        # incomplete line into an apparently valid public timing.
        pending = (b"" if reset else self.partial_lines.get(identity, b"")) + content
        lines = pending.split(b"\n")
        tail = lines.pop()
        if len(tail) > 4096:
            tail = b""
            self.truncated = True
        self.partial_lines[identity] = tail
        self.text(b"\n".join(lines).decode("utf-8", errors="replace"))

    def unsafe_entry(self, name):
        if len(self.unsafe) < 1024:
            self.unsafe.add(name)
        else:
            self.truncated = True

    def text(self, text):
        if not isinstance(text, str):
            return
        if len(text) > 262144:
            text = text[-262144:]
            self.truncated = True
        self.oom |= bool(re.search(r"java\.lang\.OutOfMemoryError\b", text))
        for line in text.splitlines():
            if "HeadlessAnalyzer" in line:
                if "IMPORTING:" in line:
                    self.stage("import_started")
                if "ANALYZING all memory and code" in line:
                    self.stage("auto_analysis_started")
                if "Analysis timed out at" in line:
                    self.analysis_timeout = True
                    self.stage("auto_analysis_timeout_reported")
                if "SCRIPT:" in line:
                    self.stage("post_analysis_script_observed")
            if "AutoAnalysisManager" in line and "ANALYSIS REPORT" in line:
                self.stage("analyzer_timing_report_observed")
            match = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9 ()_.-]{0,119}?)\s{2,}([0-9]+(?:\.[0-9]+)?) secs\s*", line)
            if match:
                value = float(match.group(2))
                if bounded_number(value):
                    if match.group(1) in ANALYZER_NAMES:
                        self.timings[match.group(1)] = value
                    elif match.group(1) == "Total Time":
                        self.total_seconds = value

    def error(self, error):
        if not isinstance(error, dict):
            return
        details = error.get("details")
        if not isinstance(details, dict):
            return
        cleanup = details.get("cleanup")
        if cleanup in ("complete", "incomplete"):
            self.cleanup = cleanup
        diagnostics = details.get("diagnostics")
        if not isinstance(diagnostics, dict):
            return
        heap = diagnostics.get("configured_jvm_max_heap")
        if isinstance(heap, str) and re.fullmatch(r"[1-9][0-9]{0,5}[KMGkmg]", heap):
            self.heap = heap.upper()
        for key, attribute in (("output_incomplete", "output_incomplete"), ("diagnostic_truncated", "provider_truncated")):
            if type(diagnostics.get(key)) is bool:
                setattr(self, attribute, diagnostics[key])
        digest = diagnostics.get("profile_digest")
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            self.profile_digest = digest
        streams = [diagnostics]
        if isinstance(diagnostics.get("failure_output"), dict):
            streams.append(diagnostics["failure_output"])
        for source in streams:
            for key in ("stdout", "stderr"):
                stream = source.get(key)
                if isinstance(stream, dict):
                    self.text(stream.get("text"))

    def poll(self):
        if self.runtime_parent is None or self.bytes_read >= 4 * 1024 * 1024:
            return
        try:
            if self.runtime_parent.is_symlink():
                self.unsafe_entry("runtime_parent")
                return
            entries = list(itertools.islice(self.runtime_parent.iterdir(), 17))
            if len(entries) > 16:
                self.truncated = True
            entries = entries[:16]
        except OSError:
            return
        roots = 0
        for entry in entries:
            if not entry.name.startswith("rea-ghidra-"):
                continue
            if entry.is_symlink():
                self.unsafe_entry(entry.name)
                continue
            if not entry.is_dir() or entry.resolve().parent != self.runtime_parent.resolve():
                continue
            roots += 1
            if roots > 4:
                self.truncated = True
                break
            for name in ("ghidra.log", "script.log"):
                path = entry / name
                try:
                    if path.is_symlink():
                        self.unsafe_entry(entry.name + "/" + name)
                        continue
                    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(descriptor, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                            self.unsafe_entry(entry.name + "/" + name)
                            continue
                        identity = (str(path), info.st_dev, info.st_ino)
                        if identity not in self.positions and len(self.positions) >= 128:
                            self.truncated = True
                            continue
                        previous = self.positions.get(identity, 0)
                        start = previous if info.st_size >= previous else 0
                        if info.st_size - start > 262144:
                            start = info.st_size - 262144
                            self.truncated = True
                        remaining = 4 * 1024 * 1024 - self.bytes_read
                        stream.seek(start)
                        content = stream.read(min(262144, remaining))
                        self.bytes_read += len(content)
                        self.positions[identity] = start + len(content)
                        if len(content) < info.st_size - start:
                            self.truncated = True
                        self.chunk(identity, content, reset=start != previous)
                except OSError:
                    continue  # A legitimate REA cleanup can race with this read.
        if self.bytes_read >= 4 * 1024 * 1024:
            self.truncated = True

    def public(self):
        order = ["import_started", "auto_analysis_started", "analyzer_timing_report_observed",
                 "post_analysis_script_observed", "auto_analysis_timeout_reported"]
        stages = [name for name in order if name in self.stages]
        return {"stages_observed": stages, "last_observed_stage": self.last_stage,
            "analyzer_timings_seconds": dict(sorted(self.timings.items())),
            "reported_total_analyzer_seconds": self.total_seconds,
            "auto_analysis_timeout_reported": self.analysis_timeout,
            "jvm_out_of_memory_reported": self.oom, "configured_jvm_max_heap": self.heap,
            "provider_reported_cleanup": self.cleanup,
            "provider_output_incomplete": self.output_incomplete,
            "provider_diagnostic_truncated": self.provider_truncated,
            "profile_digest": self.profile_digest,
            "owned_log_capture": {"enabled": self.runtime_parent is not None,
                "files_observed": min(len(self.positions), 128), "bytes_read": self.bytes_read,
                "byte_limit": 4 * 1024 * 1024, "truncated": self.truncated,
                "unsafe_entries_ignored": min(len(self.unsafe), 1024)},
            "limitations": ["Only observed log and provider-reported facts are retained; missing timings are unmeasured",
                "A last observed stage is not a verified active analyzer or proof of progress",
                "Leader exit alone does not establish descendant cleanup"]}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stop_owned_process(process):
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def execute_private(command, private, label, timeout, max_bytes, *, environment=None, collector=None):
    """Bound both elapsed time and retained stdout/stderr without printing them."""
    stdout, stderr = private / f"{label}.stdout", private / f"{label}.stderr"
    started = time.monotonic()
    state = {"status": "not_started", "exit_code": None, "elapsed_seconds": 0.0}
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, env=environment, start_new_session=os.name == "posix")
            try:
                while process.poll() is None:
                    if collector is not None:
                        collector.poll()
                    if time.monotonic() - started > timeout:
                        state["status"] = "timeout"
                        stop_owned_process(process)
                        break
                    if stdout.stat().st_size + stderr.stat().st_size > max_bytes:
                        state["status"] = "output_limit"
                        stop_owned_process(process)
                        break
                    time.sleep(0.1)
                state["exit_code"] = process.returncode
                if state["status"] == "not_started":
                    state["status"] = "exited"
            finally:
                stop_owned_process(process)
                if collector is not None:
                    collector.poll()
        if stdout.stat().st_size + stderr.stat().st_size > max_bytes:
            state["output_limit_reached"] = True
            if state["status"] != "timeout":
                state["status"] = "output_limit"
        if state["status"] == "output_limit" or state.get("output_limit_reached"):
            # A fast producer can exceed the limit between polls; bound retained
            # files too. These bytes are never public artifacts.
            for path in (stdout, stderr):
                with path.open("r+b") as stream:
                    stream.truncate(min(path.stat().st_size, max_bytes // 2))
    except OSError:
        if state["status"] != "timeout":
            state["status"] = "invocation_error"
    state["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return state, stdout


def read_tool_result(path, state, collector=None):
    """Retain error diagnostics after a watchdog hit, without promoting success."""
    public = dict(state)
    authoritative_failure = state["status"] != "exited"
    collector = collector or DiagnosticCollector()
    def finish(status, value=None):
        if not authoritative_failure:
            public["status"] = status
        public["diagnostics"] = collector.public()
        return public, None if authoritative_failure else value
    def reject_constant(_):
        raise ValueError("non-finite JSON number")
    def finite_float(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            public["retained_json_status"] = "json_size_limit"
            return finish("output_limit")
        with path.open("rb") as stream:
            retained = stream.read(MAX_JSON_BYTES + 1)
        if len(retained) > MAX_JSON_BYTES:
            public["retained_json_status"] = "json_size_limit"
            return finish("output_limit")
        value = json.loads(retained.decode("utf-8"), parse_constant=reject_constant,
                           parse_float=finite_float, object_pairs_hook=unique_pairs)
    except (OSError, ValueError, UnicodeError, RecursionError):
        public["retained_json_status"] = "malformed_or_truncated"
        return finish("malformed_json")
    if not isinstance(value, dict):
        public["retained_json_status"] = "invalid_envelope"
        return finish("invalid_envelope")
    if isinstance(value.get("error"), dict):
        error = value["error"]
    else:
        error = value
    if "code" in error or value.get("ok") is False or value.get("success") is False:
        code = error.get("code")
        public["error_code"] = code if isinstance(code, str) and code in KNOWN_CODES else "unrecognized_tool_error"
        public["retained_json_status"] = "provider_error"
        collector.error(error)
        return finish("tool_error")
    public["retained_json_status"] = "result_envelope"
    if state["exit_code"] != 0:
        return finish("process_error")
    return finish("json_received", value)


def result_payload(value):
    """Recognize only normal REA envelope layers, without mining raw bodies."""
    for _ in range(4):
        if not isinstance(value, dict):
            return {}
        if isinstance(value.get("normalized_result"), dict):
            return value["normalized_result"]
        next_value = value.get("result")
        if not isinstance(next_value, dict):
            return value
        value = next_value
    return {}


def sanitized_overview(value):
    payload = result_payload(value)
    counts = {}
    for field in ("procedure_count", "string_count"):
        number = payload.get(field)
        if type(number) is not int or number < 0:
            return None
        counts[field] = number
    architecture = value.get("subject", {}).get("architecture") if isinstance(value.get("subject"), dict) else None
    if architecture is None:
        architecture = payload.get("architecture")
    counts["architecture"] = architecture if isinstance(architecture, str) and architecture in ARCHITECTURES else "unknown"
    segment_count = payload.get("segment_count")
    if type(segment_count) is int and segment_count >= 0:
        counts["segment_count"] = segment_count
    return counts


def declared_versions(rea_cli):
    versions = {"rea": None, "ghidra": None, "jdk": None}
    try:
        package = json.loads((rea_cli.parent.parent / "package.json").read_text())
        text = package.get("version", "")
        versions["rea"] = text if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?", text) else None
    except (OSError, ValueError, TypeError):
        pass
    for key, env, relative, pattern in [
        ("ghidra", "GHIDRA_INSTALL_DIR", "Ghidra/application.properties", r"(?m)^application.version=(\d+\.\d+(?:\.\d+)?)\s*$"),
        ("jdk", "JAVA_HOME", "release", r'(?m)^JAVA_VERSION="([0-9.]+)"\s*$')]:
        try:
            match = re.search(pattern, (Path(os.environ[env]) / relative).read_text())
            versions[key] = match.group(1) if match else None
        except (KeyError, OSError, UnicodeError):
            pass
    return versions


def probe(args):
    output, private = args.output.expanduser().absolute(), args.private_workspace.expanduser().absolute()
    if output.exists() or output.is_symlink() or private.exists() or private.is_symlink():
        raise ValueError("Both output and private workspace must be fresh paths")
    if output.resolve() == private.resolve() or output.resolve() in private.resolve().parents or private.resolve() in output.resolve().parents:
        raise ValueError("Public and private directories must be separate and must not contain each other")
    output.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False, mode=0o700)
    summary = {"schema_version": 1, "status": "failed", "target_sha256": None, "target_size_bytes": None,
        "probe_sha256": sha256(__file__), "tool_versions": declared_versions(args.rea_cli),
        "provider": "ghidra", "provider_health": "not_checked", "doctor": {"status": "not_run"},
        "analysis": {"status": "not_run"}, "overview": None,
        "deadlines": {"provider_startup_seconds": args.timeout_seconds,
            "outer_watchdog_seconds": args.timeout_seconds + args.cleanup_grace_seconds,
            "cleanup_grace_seconds": args.cleanup_grace_seconds,
            "doctor_watchdog_seconds": min(120, args.timeout_seconds)},
        "limitations": ["Static analysis only; target code is never executed",
            "Only aggregate inventory and tool-health metadata are public; raw evidence and snapshots remain private",
            "Procedure/string counts do not establish algorithmic equivalence or complete reconstruction",
            "No native pseudocode, native strings, procedure names, paths, or error messages are exported",
            "A timeout remains a failure even when a retained result or provider diagnostic can be parsed",
            "Observed stages and timings do not establish completed coverage; unobserved timings are unknown"]}
    analysis_collector = None
    try:
        if not args.target.is_file() or not args.rea_cli.is_file():
            summary["failure_kind"] = "missing_input"
            return 2
        summary["target_sha256"] = sha256(args.target)
        summary["target_size_bytes"] = args.target.stat().st_size
        if not all(os.environ.get(key) and Path(os.environ[key]).is_dir() for key in ("GHIDRA_INSTALL_DIR", "JAVA_HOME")):
            summary["failure_kind"] = "missing_provider_environment"
            return 2
        # REA's supported GhidraSessionRoot uses os.tmpdir(). Dot-prefixed
        # ancestors trigger a fallback to global /tmp, which we must not scan.
        runtime_parent = (private / "rea-runtime").resolve()
        if any(part.startswith(".") for part in runtime_parent.parts):
            summary["failure_kind"] = "unsafe_private_runtime_ancestry"
            return 2
        runtime_parent.mkdir(mode=0o700)
        environment = dict(os.environ)
        environment["TMPDIR"] = str(runtime_parent)
        environment["REA_GHIDRA_STARTUP_TIMEOUT_MS"] = str(args.timeout_seconds * 1000)
        requested = [name.strip() for name in environment.get("REA_GHIDRA_DISABLED_ANALYZERS", "").split(",") if name.strip()]
        summary["analysis_profile"] = {"disabled_analyzers": sorted(set(name for name in requested if name in ANALYZER_NAMES)),
            "unrecognized_analyzer_name_count": sum(name not in ANALYZER_NAMES for name in requested)}
        command = [args.node, str(args.rea_cli.resolve())]
        state, raw = execute_private(command + ["doctor", "--provider", "ghidra", "--format", "json"],
            private, "doctor", min(120, args.timeout_seconds), args.max_output_bytes, environment=environment)
        summary["doctor"], value = read_tool_result(raw, state)
        if value is None or result_payload(value).get("healthy") is not True:
            summary["provider_health"] = "failed"
            if value is not None:
                summary["doctor"]["status"] = "unhealthy_or_unrecognized_report"
            return 1
        summary["provider_health"] = "healthy"
        summary["doctor"]["status"] = "passed"
        analysis_collector = DiagnosticCollector(runtime_parent)
        state, raw = execute_private(command + ["analyze", str(args.target.resolve()), "--provider", "ghidra", "--format", "json",
            "--snapshot", str(private / "analysis.snapshot.json")], private, "analysis",
            args.timeout_seconds + args.cleanup_grace_seconds, args.max_output_bytes,
            environment=environment, collector=analysis_collector)
        summary["analysis"], value = read_tool_result(raw, state, analysis_collector)
        if value is None:
            return 1
        summary["overview"] = sanitized_overview(value)
        if summary["overview"] is None:
            summary["analysis"]["status"] = "unrecognized_overview"
            return 1
        summary["analysis"]["status"] = "passed"
        summary["status"] = "completed"
        return 0
    except (OSError, ValueError, TypeError):
        summary["failure_kind"] = "probe_operational_error"
        return 2
    finally:
        if analysis_collector is not None:
            summary["analysis"]["diagnostics"] = analysis_collector.public()
        (output / "public-summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--rea-cli", required=True, type=Path, help="Installed rea-agents/scripts/rea.mjs")
    parser.add_argument("--output", required=True, type=Path, help="Fresh public summary directory")
    parser.add_argument("--private-workspace", required=True, type=Path, help="Fresh private logs/snapshot directory; never upload this directory")
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout-seconds", type=int, default=1200,
        help="Provider startup budget; command-scopes supported REA_GHIDRA_STARTUP_TIMEOUT_MS (default: 1200)")
    parser.add_argument("--cleanup-grace-seconds", type=int, default=90,
        help="Separate outer watchdog grace for REA's own error/cleanup diagnostics (60..120; default: 90)")
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 3600 or not 1024 <= args.max_output_bytes <= 128 * 1024 * 1024:
        parser.error("Timeout must be 1..3600 seconds; output limit must be 1 KiB..128 MiB")
    if not 60 <= args.cleanup_grace_seconds <= 120:
        parser.error("Cleanup grace must be 60..120 seconds")
    try:
        return probe(args)
    except (OSError, ValueError):
        # No raw exceptions: they may contain private paths or tool text.
        print("Probe setup failed; fresh, separate output directories are required.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
