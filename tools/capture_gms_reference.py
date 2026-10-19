"""Capture files from a run already observed by a human on authorized Windows GMS.

This tool NEVER launches GMS, runs a solver, acquires a licence, or observes UI.
It hashes the selected executable, reads Windows PE version metadata, and copies
the operator-specified native inputs, exports, original run log and run record.
An executable hash alone does not establish an observed GMS modelling run.

Example (after performing and checking a run in GMS):
  python tools/capture_gms_reference.py --executable C:/GMS/gms.exe
    --engine-executable C:/solvers/mf6.exe
    --inputs C:/cases/model --exports C:/cases/export
    --run-log C:/cases/model/model.lst --run-record C:/cases/run_record.json
    --output build/gms-capture-001

Required run_record.json fields: schema_version=1, source_kind="observed",
system="GMS", system_version, system_executable_sha256, implementation_git_commit,
run_id, operator, run_started_at, run_finished_at (timezone-aware ISO timestamps),
successful=true, command_or_workflow, engine={name,version,executable_sha256}, and the literal
attestation printed by --help. Every statement remains an operator attestation.
No comparison dataset or GMS-match result is manufactured by this capture.
For an executed implementation capture, use source_kind="candidate" and the
candidate attestation in RUN_ATTESTATIONS. This works without Windows because
it does not claim an observed original GMS version. The normalized physical-case
JSON must be included in the captured input directory; numerical CSV/NPZ must
be in the export directory. The implementation commit for an observed GMS run
identifies the capture/normalization code, never unavailable proprietary GMS
source code. Frontend and numerical-solver executable hashes are distinct.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from basinlens_ccs.parity.dataset import (ParityError, RUN_ATTESTATIONS, artifact_record, file_sha,
                                        read_json, validate_operator_record)


ATTESTATION = RUN_ATTESTATIONS["observed"]


def _validate_record(record):
    validate_operator_record(record)


def _pe_version(executable):
    """Windows version-resource API reads metadata without activating the target."""
    if sys.platform != "win32":
        raise ParityError("Windows PE version API unavailable; original GMS executable version is unknown. Capture must run on Windows.")
    from ctypes import wintypes

    class FixedInfo(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in (
            "signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
            "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]

    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD(0)
    size = version.GetFileVersionInfoSizeW(str(executable), ctypes.byref(ignored))
    if not size:
        raise ParityError("GMS executable has no readable Windows file version resource")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(executable), 0, size, buffer):
        raise ParityError("Windows could not read GMS file version resource")
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < ctypes.sizeof(FixedInfo):
        raise ParityError("GMS version resource has no valid fixed file information")
    info = ctypes.cast(pointer, ctypes.POINTER(FixedInfo)).contents
    if info.signature != 0xFEEF04BD:
        raise ParityError("Invalid GMS fixed file version signature")
    return ".".join(str(part) for part in (info.file_ms >> 16, info.file_ms & 65535, info.file_ls >> 16, info.file_ls & 65535))


def _version_tuple(value):
    try:
        parts = [int(part) for part in value.split(".")]
    except ValueError as exc:
        raise ParityError("GMS system_version must be a dotted numeric Windows file version") from exc
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _files(directory):
    if not directory.is_dir():
        raise ParityError(f"Missing snapshot directory: {directory}")
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ParityError(f"Snapshot symlinks are refused: {path}")
        if path.is_file():
            result.append(path)
    if not result:
        raise ParityError(f"Snapshot directory is empty: {directory}")
    return result


def capture(*, executable, engine_executable, inputs, exports, run_log, run_record, output, max_bytes=536870912):
    paths = {key: Path(value).resolve() for key, value in {
        "executable": executable, "engine_executable": engine_executable,
        "inputs": inputs, "exports": exports, "run_log": run_log,
        "run_record": run_record, "output": output}.items()}
    output = paths["output"]
    if output.exists():
        raise ParityError(f"Capture output already exists: {output}")
    for source in (paths["inputs"], paths["exports"]):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ParityError("Snapshot source and output directories must not overlap")
    record = read_json(paths["run_record"])
    _validate_record(record)
    executable_record = artifact_record(paths["executable"])
    engine_record = artifact_record(paths["engine_executable"])
    if executable_record["sha256"] != record["system_executable_sha256"] or engine_record["sha256"] != record["engine"]["executable_sha256"]:
        raise ParityError("Attested system/solver executable hashes differ from the actual selected files")
    version = _pe_version(paths["executable"]) if record["source_kind"] == "observed" else None
    if version is not None and _version_tuple(version) != _version_tuple(record["system_version"]):
        raise ParityError(f"Attested GMS version {record['system_version']} differs from executable file version {version}")
    entries = [(path, Path(label) / path.relative_to(paths[label]))
               for label in ("inputs", "exports") for path in _files(paths[label])]
    entries += [(paths["run_log"], Path("original_run.log")),
                (paths["run_record"], Path("operator_run_record.json"))]
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ParityError("max_bytes must be a positive integer")
    before = {source: artifact_record(source) for source, _ in entries}
    if any(item["size_bytes"] == 0 for item in before.values()):
        raise ParityError("Captured run evidence may not contain empty files")
    if sum(source.stat().st_size for source, _ in entries) > max_bytes:
        raise ParityError("Capture exceeds max_bytes; select a smaller deliberate export subset")
    output.mkdir(parents=True, exist_ok=False)
    snapshots = []
    for source, relative in entries:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        receipt = artifact_record(destination, root=output)
        if receipt["sha256"] != before[source]["sha256"] or file_sha(source) != before[source]["sha256"]:
            raise ParityError("Source changed during capture; output is incomplete and must not be used")
        snapshots.append(receipt)
    capture_record = {"capture_schema_version": 1, "source_kind": record["source_kind"],
                      "captured_at": datetime.now(timezone.utc).isoformat(),
                      "capture_method": "non-executing_file_snapshot",
                      "runtime_observed_by_tool": False,
                      "provenance_class": "operator_attestation_with_captured_files",
                      "qualification": "This tool did not run GMS or verify the truth of the operator's run attestation",
                      "system": record["system"], "system_version": record["system_version"], "file_version": version,
                      "system_executable": executable_record, "engine": record["engine"], "engine_executable": engine_record,
                      "implementation_git_commit": record["implementation_git_commit"],
                      "run_id": record["run_id"], "snapshots": snapshots}
    (output / "capture_record.json").write_text(json.dumps(capture_record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Required attestation: " + ATTESTATION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    for field in ("executable", "engine-executable", "inputs", "exports", "run-log", "run-record", "output"):
        parser.add_argument("--" + field, required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=536870912)
    args = parser.parse_args(argv)
    try:
        result = capture(**vars(args))
    except (ParityError, OSError) as exc:
        print(f"capture: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(result), "runtime_observed_by_tool": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
