"""Opt-in, static REA/Ghidra probe with a strictly limited public summary.

Raw tool output and snapshots stay in a separate, fresh private directory. This
script never executes the target, disables a provider guard, or publishes native
strings, procedure names, pseudocode, paths, or tool error messages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


KNOWN_CODES = {"capability_unavailable", "analysis_timeout", "analysis_cancelled", "configuration_error",
               "analysis_error", "unsupported_target", "target_not_found", "provider_unavailable"}
ARCHITECTURES = {"x86", "x86_64", "arm", "arm64", "aarch64", "mips", "mips64", "unknown"}


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


def execute_private(command, private, label, timeout, max_bytes):
    """Bound both elapsed time and retained stdout/stderr without printing them."""
    stdout, stderr = private / f"{label}.stdout", private / f"{label}.stderr"
    started = time.monotonic()
    state = {"status": "not_started", "exit_code": None, "elapsed_seconds": 0.0}
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=os.name == "posix")
            try:
                while process.poll() is None:
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
        if stdout.stat().st_size + stderr.stat().st_size > max_bytes:
            state["status"] = "output_limit"
        if state["status"] == "output_limit":
            # A fast producer can exceed the limit between polls; bound retained
            # files too. These bytes are never public artifacts.
            for path in (stdout, stderr):
                with path.open("r+b") as stream:
                    stream.truncate(min(path.stat().st_size, max_bytes // 2))
    except OSError:
        state["status"] = "invocation_error"
    state["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return state, stdout


def read_tool_result(path, state):
    public = dict(state)
    if state["status"] != "exited":
        return public, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        public["status"] = "malformed_json"
        return public, None
    if not isinstance(value, dict):
        public["status"] = "invalid_envelope"
        return public, None
    if isinstance(value.get("error"), dict):
        error = value["error"]
    else:
        error = value
    if "code" in error or value.get("ok") is False or value.get("success") is False:
        public["status"] = "tool_error"
        public["error_code"] = error.get("code") if error.get("code") in KNOWN_CODES else "unrecognized_tool_error"
        return public, None
    if state["exit_code"] != 0:
        public["status"] = "process_error"
        return public, None
    public["status"] = "json_received"
    return public, value


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
    counts["architecture"] = architecture if architecture in ARCHITECTURES else "unknown"
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
        "limitations": ["Static analysis only; target code is never executed",
            "Only aggregate inventory and tool-health metadata are public; raw evidence and snapshots remain private",
            "Procedure/string counts do not establish algorithmic equivalence or complete reconstruction",
            "No native pseudocode, native strings, procedure names, paths, or error messages are exported"]}
    try:
        if not args.target.is_file() or not args.rea_cli.is_file():
            summary["failure_kind"] = "missing_input"
            return 2
        summary["target_sha256"] = sha256(args.target)
        summary["target_size_bytes"] = args.target.stat().st_size
        if not all(os.environ.get(key) and Path(os.environ[key]).is_dir() for key in ("GHIDRA_INSTALL_DIR", "JAVA_HOME")):
            summary["failure_kind"] = "missing_provider_environment"
            return 2
        command = [args.node, str(args.rea_cli.resolve())]
        state, raw = execute_private(command + ["doctor", "--provider", "ghidra", "--format", "json"],
            private, "doctor", min(120, args.timeout_seconds), args.max_output_bytes)
        summary["doctor"], value = read_tool_result(raw, state)
        if value is None or result_payload(value).get("healthy") is not True:
            summary["provider_health"] = "failed"
            if value is not None:
                summary["doctor"]["status"] = "unhealthy_or_unrecognized_report"
            return 1
        summary["provider_health"] = "healthy"
        summary["doctor"]["status"] = "passed"
        state, raw = execute_private(command + ["analyze", str(args.target.resolve()), "--provider", "ghidra", "--format", "json",
            "--snapshot", str(private / "analysis.snapshot.json")], private, "analysis", args.timeout_seconds, args.max_output_bytes)
        summary["analysis"], value = read_tool_result(raw, state)
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
        (output / "public-summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--rea-cli", required=True, type=Path, help="Installed rea-agents/scripts/rea.mjs")
    parser.add_argument("--output", required=True, type=Path, help="Fresh public summary directory")
    parser.add_argument("--private-workspace", required=True, type=Path, help="Fresh private logs/snapshot directory; never upload this directory")
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 3600 or not 1024 <= args.max_output_bytes <= 128 * 1024 * 1024:
        parser.error("Timeout must be 1..3600 seconds; output limit must be 1 KiB..128 MiB")
    try:
        return probe(args)
    except (OSError, ValueError):
        # No raw exceptions: they may contain private paths or tool text.
        print("Probe setup failed; fresh, separate output directories are required.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
