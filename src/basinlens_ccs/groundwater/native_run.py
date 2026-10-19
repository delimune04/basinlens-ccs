"""Isolated execution of an unchanged, resolved native MODFLOW 6 file graph.

This operational runner does not pass through GroundwaterCase, convert units,
infer absolute pressure, validate arbitrary model physics or establish GMS parity.
GMS sidecars are byte-preserved separately and never interpreted as solver input.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time

from .gms_native import (MAX_FILE_BYTES, MAX_TEXT_BYTES, NativeImportError,
                         _parse_records, import_native_simulation)

MAX_TOTAL_INPUT_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024


class NativeRunError(RuntimeError):
    """Preflight or execution failed; failed executions retain diagnostics."""


@dataclass
class NativeRunResult:
    workspace: Path
    simulation_workspace: Path
    summary: dict


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False) + "\n", encoding="utf-8")


def _safe_relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise NativeRunError("Importer returned an unsafe relative file path")
    return Path(value)


def _no_symlinks(path, root):
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise NativeRunError("Native inputs, outputs and sidecars must not use symbolic links")


def _reference_path(raw, workspace, allowed):
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise NativeRunError("Malformed native file reference")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or ":" in normalized:
        raise NativeRunError(f"Absolute native references require explicit relocation: {raw}")
    if "\\" in raw and os.name != "nt":
        raise NativeRunError("Windows path separators cannot be executed unchanged on this platform")
    lexical = workspace
    for part in Path(normalized).parts:
        lexical = lexical.parent if part == ".." else lexical / part
        if not lexical.is_relative_to(allowed):
            raise NativeRunError(f"Native reference traverses outside the allowed root: {raw}")
        if lexical.is_symlink():
            raise NativeRunError("Native references must not traverse symbolic links")
    candidate = lexical.resolve()
    if not candidate.is_relative_to(allowed):
        raise NativeRunError(f"Native input/output reference escapes the allowed root: {raw}")
    _no_symlinks(candidate, allowed)
    return candidate


def _preflight(source, allowed_root):
    report = import_native_simulation(source, allowed_root=allowed_root, database_row_limit=0)
    if report.get("native_inputs_resolved") is not True or report.get("issues"):
        raise NativeRunError("Native input graph is unresolved: " + json.dumps(report.get("issues", [])))
    allowed = Path(report["allowed_root"]).resolve(strict=True)
    workspace = Path(report["workspace"]).resolve(strict=True)
    main = allowed / _safe_relative(report["simulation"])
    if main.name != "mfsim.nam" and os.name != "nt":
        raise NativeRunError("Native MF6 on this platform requires the simulation file name mfsim.nam")
    inputs, sidecars, records = {}, {}, {}
    for entry in report["files"]:
        if entry.get("exists") is not True or entry.get("loaded") is not True:
            raise NativeRunError("Only fully loaded native input graphs can run")
        relative = _safe_relative(entry["path"])
        path = allowed / relative
        _no_symlinks(path, allowed)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES or _sha(path) != entry["sha256"]:
            raise NativeRunError("Native input changed since import or exceeds limits")
        inputs[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": entry["sha256"]}
        if entry.get("scan") not in ("complete_text", "declared_binary_array_leaf"):
            raise NativeRunError("Importer did not establish complete text/binary-leaf scan coverage")
        records[relative.as_posix()] = [] if entry["scan"] == "declared_binary_array_leaf" else _parse_records(path)
    for entry in report["sidecars"]:
        relative = _safe_relative(entry["path"])
        path = allowed / relative
        _no_symlinks(path, allowed)
        if not path.is_file() or _sha(path) != entry["sha256"]:
            raise NativeRunError("Opaque sidecar changed since import")
        sidecars[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": entry["sha256"]}
    if sum(item["bytes"] for item in [*inputs.values(), *sidecars.values()]) > MAX_TOTAL_INPUT_BYTES:
        raise NativeRunError("Native inputs and sidecars exceed the 512 MiB run-copy limit")
    outputs, binary_inputs, units = {}, set(), {"time": [], "length": []}
    for relative, rows in records.items():
        for _, words in rows:
            upper = [word.upper() for word in words]
            for keyword, category in (("TIME_UNITS", "time"), ("LENGTH_UNITS", "length")):
                if upper[0] == keyword and len(words) == 2:
                    units[category].append({"file": relative, "declared": upper[1]})
            for index, token in enumerate(upper[:-1]):
                if token not in ("FILEIN", "FILEOUT", "OPEN/CLOSE"):
                    continue
                path = _reference_path(words[index + 1], workspace, allowed)
                key = path.relative_to(allowed).as_posix()
                if token == "FILEOUT":
                    outputs[key] = {"declared_by": relative,
                                    "quantity_keyword": upper[index - 1] if index else "unknown"}
                elif token == "OPEN/CLOSE" and any("BINARY" in flag for flag in upper[index + 2:]):
                    binary_inputs.add(key)
            if upper[0] == "LIST" and len(words) == 2:
                path = _reference_path(words[1], workspace, allowed)
                outputs[path.relative_to(allowed).as_posix()] = {"declared_by": relative, "quantity_keyword": "LIST"}
    # Recheck every graph edge, including package/model paths and all FILEOUTs.
    for reference in report["references"]:
        path = _reference_path(reference["path"], workspace, allowed)
        key = path.relative_to(allowed).as_posix()
        if reference["input"] and key not in inputs:
            raise NativeRunError("A referenced native input is absent from the copied graph")
        if reference["input"] is not True:
            outputs.setdefault(key, {"declared_by": reference["from"], "quantity_keyword": reference["kind"]})
    for relative, rows in records.items():
        path = allowed / relative
        if path.stat().st_size > MAX_TEXT_BYTES:
            if relative not in binary_inputs:
                raise NativeRunError("Native text reference scan is incomplete")
        elif not rows:
            data = path.read_bytes()
            try:
                text = data.decode("utf-8-sig")
                opaque = "\0" in text
            except UnicodeDecodeError:
                opaque = True
            if opaque and relative not in binary_inputs:
                raise NativeRunError("Opaque native inputs require an explicit BINARY array declaration")
    # Implicit listing files are also writes, even without FILEOUT syntax.
    defaults = [(workspace / "mfsim.lst", "simulation default listing")]
    for model in report["models"]:
        name_file = _reference_path(model["name_file"], workspace, allowed).relative_to(allowed).as_posix()
        if not any(words[0].upper() == "LIST" for _, words in records[name_file]):
            defaults.append((_reference_path(model["name"] + ".lst", workspace, allowed), "model default listing"))
    if any(words[0].upper() == "LIST" for _, words in records[report["simulation"]]):
        defaults = [item for item in defaults if item[1] != "simulation default listing"]
    for path, reason in defaults:
        outputs.setdefault(path.relative_to(allowed).as_posix(), {"declared_by": reason, "quantity_keyword": "LIST"})
    if set(inputs) & set(outputs):
        raise NativeRunError("Native output would overwrite a copied input")
    return report, allowed, workspace, inputs, sidecars, outputs, units


def _terminate(process):
    if process.poll() is None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
    process.wait()


def _execute(command, cwd, stdout, stderr, timeout_seconds, max_output_bytes, *, watch_root=None, on_started=None):
    started = time.monotonic()
    watch_root = cwd if watch_root is None else watch_root
    def check_size():
        size = 0
        for path in watch_root.rglob("*"):
            if path.is_symlink():
                raise NativeRunError("Solver generated a symbolic link")
            if path.is_file():
                size += path.stat().st_size
        for log in (stdout, stderr):
            if not log.is_relative_to(watch_root):
                size += log.stat().st_size
        if size > max_output_bytes:
            raise NativeRunError("Native workspace exceeded output-size budget")
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   start_new_session=os.name == "posix")
        if on_started is not None:
            on_started()
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout_seconds:
                    raise NativeRunError(f"Native solver exceeded {timeout_seconds:g} second timeout")
                check_size()
                time.sleep(0.05)
            check_size()
        except BaseException:
            _terminate(process)
            raise
    return process.returncode


def _check_snapshot(base, records):
    for relative, expected in records.items():
        path = base / relative
        if not path.is_file() or path.is_symlink() or path.stat().st_size != expected["bytes"] or _sha(path) != expected["sha256"]:
            raise NativeRunError(f"Input/sidecar bytes changed: {relative}")


def _manifest(root, status, metadata):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise NativeRunError("Native run bundles cannot contain symbolic links")
        if path.is_file() and path != root / "native_run_metadata.json":
            files[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    _write(root / "native_run_metadata.json", {**metadata, "status": status, "files": files})


def verify_native_run(workspace: str | Path) -> dict:
    """Recheck exact bundle inventory and preserved input bytes, not run truth.

    A content manifest detects missing, altered or unlisted files. It does not
    authenticate an operator, establish physical validity or prove GMS parity.
    """
    root = Path(workspace)
    manifest = root / "native_run_metadata.json"
    if root.is_symlink() or not root.is_dir() or manifest.is_symlink() or not manifest.is_file():
        raise NativeRunError("Expected a regular native run directory and manifest")
    if manifest.stat().st_size > 16 * 1024 * 1024:
        raise NativeRunError("Native manifest exceeds the read budget")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise NativeRunError("Duplicate JSON keys in native manifest")
            value[key] = item
        return value

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise NativeRunError("Nonfinite JSON number in native manifest")
        return value

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_float=number, parse_constant=number)
        if not isinstance(data, dict) or data.get("schema") != "basinlens-native-mf6-run-v1":
            raise NativeRunError("Unsupported native run manifest")
        status, files = data.get("status"), data.get("files")
        if status not in ("completed", "failed") or not isinstance(files, dict) or not files:
            raise NativeRunError("Native manifest has no valid status/file inventory")
        required = {"native_failure.json"}
        if status == "completed":
            required = {"solver.stdout.log", "solver.stderr.log", "native_import.json", "native_summary.json"}
        elif data.get("solver_executed") is True:
            required.update({"solver.stdout.log", "solver.stderr.log"})
        if not required <= set(files):
            raise NativeRunError("Native manifest omits required execution artifacts")
        if status == "completed" and any(data.get(key) is not True for key in (
                "solver_executed", "original_sources_unchanged", "copied_inputs_unchanged")):
            raise NativeRunError("Completed native run lacks byte-preservation/execution markers")
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise NativeRunError("Native run bundle contains a symbolic link")
            if path.is_file() and path != manifest:
                actual.add(path.relative_to(root).as_posix())
        if actual != set(files):
            raise NativeRunError("Native file inventory differs from the exact bundle contents")
        for relative, expected in files.items():
            path = root / _safe_relative(relative)
            if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
                    or expected["bytes"] < 0 or not isinstance(expected.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None
                    or path.stat().st_size != expected["bytes"] or _sha(path) != expected["sha256"]):
                raise NativeRunError(f"Native artifact identity mismatch: {relative}")
        snapshot = data["source_snapshot"]
        for group, prefix in (("inputs", "native/"), ("sidecars", "source_sidecars/")):
            entries = snapshot[group]
            if not isinstance(entries, dict) or (group == "inputs" and not entries):
                raise NativeRunError("Native source snapshot is incomplete")
            for relative, expected in entries.items():
                _safe_relative(relative)
                captured = files.get(prefix + relative)
                if (status == "completed" or captured is not None) and captured != expected:
                    raise NativeRunError("Native source snapshot differs from preserved bundle bytes")
        return data
    except NativeRunError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise NativeRunError(f"Malformed native bundle: {error}") from error


def run_native_simulation(source: str | Path, output_dir: str | Path, *,
                          allowed_root: str | Path | None = None, exe_name="mf6",
                          timeout_seconds: float = 300, max_output_bytes: int = MAX_OUTPUT_BYTES) -> NativeRunResult:
    """Copy and execute native files without writing any original input or output.

    Completion is solver termination plus byte-preservation checks. Numerical
    conservation, calibration, units correctness, CCS physics and GMS parity are
    not inferred from a successful operational run.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 1800:
        raise NativeRunError("timeout_seconds must be a finite number in (0,1800]")
    if type(max_output_bytes) is not int or not 1024 * 1024 <= max_output_bytes <= 2 * MAX_OUTPUT_BYTES:
        raise NativeRunError("max_output_bytes must be an integer in [1 MiB,2 GiB]")
    report, allowed, original_workspace, inputs, sidecars, outputs, units = _preflight(source, allowed_root)
    requested = Path(output_dir).expanduser().absolute()
    if requested.is_symlink():
        raise FileExistsError("Output must not be a symbolic link")
    root = requested.resolve()
    if root.exists():
        raise FileExistsError(f"Choose a fresh native output directory: {root}")
    if root.is_relative_to(allowed) or allowed.is_relative_to(root):
        raise NativeRunError("Native output and original allowed source root must be disjoint directory trees")
    executable = shutil.which(str(exe_name))
    if executable is None or not Path(executable).is_file():
        raise NativeRunError("Trusted MODFLOW 6 executable not found; no solver is downloaded automatically")
    executable = str(Path(executable).resolve())
    executable_sha = _sha(executable)
    with tempfile.TemporaryDirectory(prefix="basinlens-mf6-version-") as version_dir:
        base = Path(version_dir)
        code = _execute([executable, "-v"], base, base / "stdout.log", base / "stderr.log", 10, 1024 * 1024)
        version = (base / "stdout.log").read_text(encoding="utf-8", errors="replace").strip()
        if code or re.search(r"\bmf6\s*:\s*6\.", version, re.I) is None:
            raise NativeRunError("Selected executable did not identify as MODFLOW 6")
    root.mkdir(parents=True, exist_ok=False)
    native = root / "native"
    copied_workspace = native / original_workspace.relative_to(allowed)
    metadata = {"schema": "basinlens-native-mf6-run-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "runner_source_sha256": _sha(Path(__file__)), "python": platform.python_version(),
        "importer_source_sha256": _sha(Path(__file__).with_name("gms_native.py")),
        "platform": platform.platform(),
        "solver": {"name": Path(executable).name, "sha256": executable_sha, "version": version},
        "simulation": report["simulation"], "native_units": units, "unit_conversion": "none",
        "undeclared_units_policy": "Missing declarations remain unknown; no SI assumption or conversion",
        "timeout_seconds": timeout_seconds, "max_workspace_bytes": max_output_bytes,
        "source_snapshot": {"inputs": inputs, "sidecars": sidecars},
        "original_sources_unchanged": False, "copied_inputs_unchanged": False,
        "solver_executed": False, "validation_scope": "operational native execution only; arbitrary model physics not validated",
        "gms_sidecar_native_sync": "not performed or established; copied native bytes alone determine calculation",
        "bounded_confined_schema_used": False, "gms_runtime_executed": False, "gms_parity_established": False}
    try:
        for group, destination in ((inputs, native), (sidecars, root / "source_sidecars")):
            for relative, expected in group.items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(allowed / relative, target)
                if _sha(target) != expected["sha256"]:
                    raise NativeRunError("Source changed while copying native input/sidecar")
        for relative in outputs:
            (native / relative).parent.mkdir(parents=True, exist_ok=True)
        sanitized = {key: value for key, value in report.items() if key not in ("workspace", "allowed_root", "sidecars")}
        sanitized["workspace_relative_to_allowed_root"] = original_workspace.relative_to(allowed).as_posix()
        sanitized["sidecar_policy"] = "Opaque source bytes archived under source_sidecars; never synchronized into solver input"
        _write(root / "native_import.json", sanitized)
        returncode = _execute([executable], copied_workspace, root / "solver.stdout.log", root / "solver.stderr.log",
                              timeout_seconds, max_output_bytes, watch_root=root,
                              on_started=lambda: metadata.__setitem__("solver_executed", True))
        metadata["returncode"] = returncode
        _check_snapshot(allowed, inputs)
        _check_snapshot(allowed, sidecars)
        metadata["original_sources_unchanged"] = True
        _check_snapshot(native, inputs)
        _check_snapshot(root / "source_sidecars", sidecars)
        metadata["copied_inputs_unchanged"] = True
        if _sha(executable) != executable_sha:
            raise NativeRunError("Selected solver executable changed during run")
        text = (root / "solver.stdout.log").read_text(encoding="utf-8", errors="replace")
        if returncode != 0 or "normal termination of simulation" not in text.lower():
            raise NativeRunError("Native MODFLOW 6 did not report normal termination; raw diagnostics retained")
        produced = [{**entry, "path": relative, "exists": (native / relative).is_file(),
            "bytes": (native / relative).stat().st_size if (native / relative).is_file() else None}
            for relative, entry in sorted(outputs.items())]
        summary = {"status": "completed", "engine": "MODFLOW 6", "mode": "unchanged native project",
            "native_units": units, "declared_outputs": produced, "source_files": len(inputs),
            "opaque_sidecars": len(sidecars), "unit_conversion": "none", "physics_validation": "not evaluated",
            "gms_sidecar_native_sync": metadata["gms_sidecar_native_sync"],
            "limitations": ["Native project physics and units retained; no confined-schema validation applied",
                "GUI/sidecar edits are not synchronized into native inputs; export freshness is not established",
                "Head is native hydraulic head, not absolute pressure; no automatic unit conversion",
                "Normal solver termination is not an independent physical benchmark or field validation",
                "GMS GUI behavior, native DMI compatibility and whole-product equivalence remain unverified"]}
        _write(root / "native_summary.json", summary)
        _manifest(root, "completed", metadata)
        return NativeRunResult(root, copied_workspace, summary)
    except BaseException as error:
        # Retain failures and recheck original files even when execution times out.
        try:
            _check_snapshot(allowed, inputs)
            _check_snapshot(allowed, sidecars)
            metadata["original_sources_unchanged"] = True
        except NativeRunError:
            metadata["original_sources_unchanged"] = False
        _write(root / "native_failure.json", {"status": "failed", "error_type": type(error).__name__, "message": str(error)})
        _manifest(root, "failed", metadata)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(error, NativeRunError):
            raise
        raise NativeRunError(f"Native run failed; diagnostics retained in {root}: {error}") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--allowed-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", default="mf6")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        result = run_native_simulation(args.source, args.output, allowed_root=args.allowed_root,
                                       exe_name=args.exe, timeout_seconds=args.timeout)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Native run failed: {error}\n")
    print(json.dumps(result.summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
