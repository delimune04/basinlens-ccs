"""A deliberately strict interchange contract for paired numerical results.

The manifest captures explicit spatial and temporal support. It never guesses
units, reorders cells, interpolates time, converts flux signs, or ignores NaNs.
SHA256 binds bytes; provenance is an operator attestation, not proof of identity.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


class ParityError(ValueError):
    """Missing, altered, or ambiguous comparison evidence."""


class NumericalDataError(ParityError):
    """Declared numerical output is absent, non-finite, or malformed."""


RUN_ATTESTATIONS = {
    "observed": "I personally observed this authorized GMS run and these inputs, exports and original run log belong to it.",
    "candidate": "I personally observed this implementation run and these inputs, exports and original run log belong to it."}


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ParityError(f"Non-canonical JSON: {exc}") from exc


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ParityError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def read_json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"),
                           object_pairs_hook=_pairs,
                           parse_constant=lambda x: (_ for _ in ()).throw(ParityError(f"Non-finite JSON: {x}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParityError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ParityError(f"Expected JSON object: {path}")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ParityError(f"{name}: nonempty text required")
    return value


def _sha(value, name, *, commit=False):
    pattern = r"[0-9a-f]{40}(?:[0-9a-f]{24})?" if commit else r"[0-9a-f]{64}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ParityError(f"{name}: lowercase hexadecimal SHA required")
    if not value.strip("0"):
        raise ParityError(f"{name}: all-zero placeholder SHA is insufficient")
    return value


def _known_version(value, name):
    value = _text(value, name)
    if value.strip().lower() in {"unknown", "unavailable", "unspecified", "n/a", "none"}:
        raise ParityError(f"{name}: an observed explicit version is required")
    return value


def _object(value, name, required):
    if not isinstance(value, dict):
        raise ParityError(f"{name}: object required")
    missing = set(required) - value.keys()
    if missing:
        raise ParityError(f"{name}: missing {sorted(missing)}")
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParityError(f"{name}: finite numeric value required")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ParityError(f"{name}: finite numeric value required") from None
    if not math.isfinite(value):
        raise ParityError(f"{name}: finite numeric value required")
    return value


def _relative_file(root: Path, name: str) -> Path:
    _text(name, "artifact.path")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ParityError(f"Unsafe artifact path: {name}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ParityError(f"Missing or escaped artifact: {name}")
    return path


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ParityError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def artifact_record(path: str | Path, *, root: str | Path | None = None) -> dict:
    """Record actual bytes; never manufactures run provenance."""
    path = Path(path).resolve()
    root = Path(root).resolve() if root is not None else path.parent
    try:
        name = path.relative_to(root).as_posix()
        size = path.stat().st_size
    except (ValueError, OSError) as exc:
        raise ParityError(f"Cannot record artifact {path}: {exc}") from exc
    return {"path": name, "sha256": file_sha(path), "size_bytes": size}


def verify_artifact(root: Path, record: dict, name="artifact", *, nonempty=True) -> Path:
    _object(record, name, {"path", "sha256", "size_bytes"})
    _sha(record["sha256"], name + ".sha256")
    if type(record["size_bytes"]) is not int or record["size_bytes"] < int(nonempty):
        raise ParityError(f"{name}: {'nonempty' if nonempty else 'non-negative'} size required")
    path = _relative_file(root, record["path"])
    if path.stat().st_size != record["size_bytes"] or file_sha(path) != record["sha256"]:
        raise ParityError(f"{name}: artifact checksum/size mismatch: {record['path']}")
    return path


def input_fingerprint(records: list[dict]) -> str:
    """Hash exact native input path/hash/size records, sorted by path."""
    if not isinstance(records, list) or not records:
        raise ParityError("inputs: at least one captured input file required")
    normal = []
    seen = set()
    for record in records:
        _object(record, "input", {"path", "sha256", "size_bytes"})
        _text(record["path"], "input.path")
        _sha(record["sha256"], "input.sha256")
        if record["path"] in seen:
            raise ParityError("inputs: duplicate path")
        seen.add(record["path"])
        normal.append({key: record[key] for key in ("path", "sha256", "size_bytes")})
    return fingerprint(sorted(normal, key=lambda item: item["path"]))


def _numeric_array(value, name, shape):
    try:
        raw = np.asarray(value)
        if raw.dtype.kind in ("b", "c", "O"):
            raise NumericalDataError(f"{name}: real numerical values required; boolean/complex/object refused")
        array = np.asarray(value, dtype=np.float64)
    except (ValueError, TypeError, OverflowError) as exc:
        raise NumericalDataError(f"{name}: numeric array required") from exc
    if array.shape != tuple(shape) or not np.isfinite(array).all():
        raise NumericalDataError(f"{name}: expected finite shape {list(shape)}, got {list(array.shape)}")
    return array


def _geometry(grid):
    _object(grid, "geometry", {"kind", "shape", "origin_xy", "rotation_degrees",
                                "x_edges", "y_edges", "top", "bottoms"})
    if grid["kind"] != "rectilinear":
        raise ParityError("geometry.kind: only explicit rectilinear support currently implemented")
    shape = grid["shape"]
    if not isinstance(shape, list) or len(shape) != 3 or any(type(v) is not int or v <= 0 for v in shape):
        raise ParityError("geometry.shape: positive integer [layer, row, column] required")
    nl, nr, nc = shape
    _numeric_array(grid["origin_xy"], "geometry.origin_xy", (2,))
    _number(grid["rotation_degrees"], "geometry.rotation_degrees")
    x = _numeric_array(grid["x_edges"], "geometry.x_edges", (nc + 1,))
    y = _numeric_array(grid["y_edges"], "geometry.y_edges", (nr + 1,))
    if not (np.diff(x) > 0).all() or not (np.diff(y) > 0).all():
        raise ParityError("geometry: x/y edges must strictly increase; cell order must be explicit")
    top = _numeric_array(grid["top"], "geometry.top", (nr, nc))
    bottoms = _numeric_array(grid["bottoms"], "geometry.bottoms", (nl, nr, nc))
    if not (np.diff(np.concatenate([top[None], bottoms]), axis=0) < 0).all():
        raise ParityError("geometry: each layer bottom must be below its top")
    return shape


def _output_shape(support, times, shape):
    spatial = list(shape)
    if support in ("face_x", "face_y", "face_z"):
        spatial[{"face_x": 2, "face_y": 1, "face_z": 0}[support]] += 1
    elif support == "scalar":
        spatial = []
    elif support != "cell":
        raise ParityError(f"Unsupported output support: {support}")
    return (times, *spatial)


def _read_npz(path, outputs, times, shape):
    result = {}
    try:
        with np.load(path, allow_pickle=False) as arrays:
            for name, item in outputs.items():
                key = item["key"]
                if key not in arrays:
                    raise NumericalDataError(f"Missing output array: {key}")
                result[name] = _numeric_array(arrays[key], f"output.{name}",
                                               _output_shape(item["support"], times, shape))
    except (OSError, ValueError, TypeError, EOFError, zipfile.BadZipFile) as exc:
        raise NumericalDataError(f"Cannot read numerical NPZ: {exc}") from exc
    return result


def _read_csv(path, outputs, times, shape):
    if any(item["support"] != "cell" for item in outputs.values()):
        raise NumericalDataError("CSV supports cell outputs only; use NPZ for face/scalar arrays")
    result = {name: np.empty((times, *shape), dtype=float) for name in outputs}
    seen = set()
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            expected = ["time_index", "layer", "row", "column"] + [item["key"] for item in outputs.values()]
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)) or set(reader.fieldnames) != set(expected):
                raise NumericalDataError(f"CSV columns must be exactly {expected}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise NumericalDataError("CSV row has extra or missing fields")
                try:
                    key = tuple(int(row[k]) for k in ("time_index", "layer", "row", "column"))
                except (TypeError, ValueError):
                    raise NumericalDataError("CSV indices must be integers") from None
                if key in seen or any(not 0 <= index < count for index, count in zip(key, (times, *shape))):
                    raise NumericalDataError("CSV contains duplicate or out-of-range cell/time indices")
                seen.add(key)
                for name, item in outputs.items():
                    result[name][key] = float(row[item["key"]])
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise NumericalDataError(f"Cannot read numerical CSV: {exc}") from exc
    if len(seen) != times * math.prod(shape):
        raise NumericalDataError("CSV is missing cell/time outputs")
    if any(not np.isfinite(array).all() for array in result.values()):
        raise NumericalDataError("CSV output contains NaN or infinity")
    return result


def _timestamp(value, name):
    _text(value, name)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParityError(f"{name}: ISO timestamp required") from exc
    if result.tzinfo is None:
        raise ParityError(f"{name}: timezone required")
    return result


def validate_operator_record(record):
    """Validate a recognized human run attestation, without authenticating it."""
    from datetime import timezone
    _object(record, "operator_run_record", {"schema_version", "source_kind", "system", "system_version",
            "run_id", "operator", "run_started_at", "run_finished_at", "successful",
            "command_or_workflow", "engine", "implementation_git_commit",
            "system_executable_sha256", "attestation"})
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ParityError("operator_run_record.schema_version: integer 1 required")
    kind = record["source_kind"]
    if kind not in RUN_ATTESTATIONS or record["attestation"] != RUN_ATTESTATIONS[kind] or record["successful"] is not True:
        raise ParityError("operator_run_record: recognized kind, literal attestation and successful=true required")
    if kind == "observed" and record["system"] != "GMS":
        raise ParityError("observed operator_run_record must identify GMS")
    for key in ("system", "system_version", "run_id", "operator", "command_or_workflow"):
        _text(record[key], "operator_run_record." + key)
    _known_version(record["system_version"], "operator_run_record.system_version")
    start = _timestamp(record["run_started_at"], "run_started_at")
    finish = _timestamp(record["run_finished_at"], "run_finished_at")
    if finish < start or finish > datetime.now(timezone.utc):
        raise ParityError("operator_run_record: finish must follow start and cannot be in the future")
    _sha(record["implementation_git_commit"], "operator_run_record.implementation_git_commit", commit=True)
    _sha(record["system_executable_sha256"], "operator_run_record.system_executable_sha256")
    engine = _object(record["engine"], "operator_run_record.engine", {"name", "version", "executable_sha256"})
    for key in ("name", "version"):
        _text(engine[key], "operator_run_record.engine." + key)
    _known_version(engine["version"], "operator_run_record.engine.version")
    _sha(engine["executable_sha256"], "operator_run_record.engine.executable_sha256")


def _receipt_identity(record):
    return {key: record[key] for key in ("path", "sha256", "size_bytes")}


def _validate_run_provenance(root, data):
    """Bind recognized capture, run attestation and numerical artifacts together."""
    from datetime import timezone
    provenance = _object(data.get("provenance"), "provenance", {
        "run_id", "operator", "captured_at", "command_or_workflow", "observation_method", "receipts"})
    for key in ("run_id", "operator", "command_or_workflow", "observation_method"):
        _text(provenance[key], "provenance." + key)
    captured_at = _timestamp(provenance["captured_at"], "provenance.captured_at")
    if captured_at > datetime.now(timezone.utc):
        raise ParityError("provenance.captured_at cannot be in the future")
    receipts = provenance["receipts"]
    if not isinstance(receipts, list) or not receipts:
        raise ParityError("provenance: actual run, structured capture and operator records required")
    by_role = {}
    for index, receipt in enumerate(receipts):
        _object(receipt, "provenance.receipt", {"role"})
        role = _text(receipt["role"], "receipt.role")
        if role in by_role:
            raise ParityError("provenance: duplicate receipt role")
        by_role[role] = (receipt, verify_artifact(root, receipt, f"provenance.receipts[{index}]"))
    if not {"run_log", "capture_record", "operator_run_record"} <= by_role.keys():
        raise ParityError("provenance: run_log, capture_record and operator_run_record receipts all required")
    if len({item[1] for item in by_role.values()}) != len(by_role):
        raise ParityError("provenance receipt roles must refer to distinct files")
    capture = read_json(by_role["capture_record"][1])
    operator = read_json(by_role["operator_run_record"][1])
    validate_operator_record(operator)
    _object(capture, "capture_record", {"capture_schema_version", "source_kind", "captured_at",
        "capture_method", "runtime_observed_by_tool", "provenance_class", "system", "system_version",
        "system_executable", "engine", "engine_executable", "implementation_git_commit", "run_id", "snapshots"})
    if type(capture["capture_schema_version"]) is not int or capture["capture_schema_version"] != 1:
        raise ParityError("capture_record.capture_schema_version: integer 1 required")
    if capture["capture_method"] != "non-executing_file_snapshot" or capture["runtime_observed_by_tool"] is not False or capture["provenance_class"] != "operator_attestation_with_captured_files":
        raise ParityError("capture_record: unrecognized capture method/provenance class")
    if provenance["observation_method"] != capture["capture_method"]:
        raise ParityError("run provenance: observation/capture method mismatch")
    source = data["source"]
    for key in ("system", "system_version"):
        if source[key] != capture[key] or source[key] != operator[key]:
            raise ParityError(f"run provenance: {key} differs from dataset/capture/operator record")
    if capture["source_kind"] != source["kind"] or operator["source_kind"] != source["kind"]:
        raise ParityError("run provenance: source kind mismatch")
    for key in ("run_id", "operator", "command_or_workflow"):
        if provenance[key] != operator[key] or (key == "run_id" and capture[key] != operator[key]):
            raise ParityError(f"run provenance: {key} mismatch")
    if provenance["captured_at"] != capture["captured_at"] or captured_at < _timestamp(operator["run_finished_at"], "run_finished_at"):
        raise ParityError("run provenance: capture timestamps do not follow the attested run")
    commit = data["implementation"]["git_commit"]
    if commit != operator["implementation_git_commit"] or commit != capture["implementation_git_commit"]:
        raise ParityError("run provenance: implementation commit mismatch")
    if canonical_bytes(data["engine"]) != canonical_bytes(operator["engine"]) or canonical_bytes(data["engine"]) != canonical_bytes(capture["engine"]):
        raise ParityError("run provenance: engine identity/version/executable hash mismatch")
    for key in ("system_executable", "engine_executable"):
        item = _object(capture[key], "capture_record." + key, {"path", "sha256", "size_bytes"})
        _text(item["path"], key + ".path")
        _sha(item["sha256"], key + ".sha256")
        if type(item["size_bytes"]) is not int or item["size_bytes"] <= 0:
            raise ParityError("capture_record: nonempty executable metadata required")
    if capture["system_executable"]["sha256"] != operator["system_executable_sha256"] or capture["engine_executable"]["sha256"] != data["engine"]["executable_sha256"]:
        raise ParityError("run provenance: captured executable identity mismatch")
    if source["kind"] == "observed":
        version = _text(capture.get("file_version"), "capture_record.file_version")
        def version_parts(value):
            try:
                parts = [int(part) for part in value.split(".")]
            except ValueError as exc:
                raise ParityError("Observed GMS file version must be numeric Windows PE metadata") from exc
            while len(parts) > 1 and parts[-1] == 0:
                parts.pop()
            return parts
        if version_parts(version) != version_parts(source["system_version"]):
            raise ParityError("run provenance: observed GMS Windows file version mismatch")
    snapshots = capture["snapshots"]
    if not isinstance(snapshots, list) or not snapshots:
        raise ParityError("capture_record: snapshots cannot be empty")
    snapshot_map = {}
    for record in snapshots:
        verify_artifact(root, record, "capture_record.snapshot")
        if record["path"] in snapshot_map:
            raise ParityError("capture_record: duplicate snapshot path")
        snapshot_map[record["path"]] = _receipt_identity(record)
    expected_inputs = sorted((_receipt_identity(item) for item in data["inputs"]), key=lambda item: item["path"])
    captured_inputs = sorted((item for path, item in snapshot_map.items() if path.startswith("inputs/")), key=lambda item: item["path"])
    if canonical_bytes(expected_inputs) != canonical_bytes(captured_inputs):
        raise ParityError("run provenance: exact captured native input set differs from dataset")
    comparison = _receipt_identity(data["comparison_input"])
    if comparison not in expected_inputs:
        raise ParityError("run provenance: normalized comparison input is not among captured inputs")
    numerical = _receipt_identity(data["data"])
    if not numerical["path"].startswith("exports/") or snapshot_map.get(numerical["path"]) != numerical:
        raise ParityError("run provenance: numerical output is not a captured export")
    for role in ("run_log", "operator_run_record"):
        receipt = _receipt_identity(by_role[role][0])
        if snapshot_map.get(receipt["path"]) != receipt:
            raise ParityError(f"run provenance: {role} does not match captured snapshot")


def load_dataset(manifest_path: str | Path) -> dict:
    """Validate every receipt before loading values; returns a normalized view."""
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    data = read_json(manifest_path)
    _object(data, "dataset", {"schema_version", "dataset_id", "source", "engine", "implementation",
                              "inputs", "exact_run_inputs_sha256", "comparison_input", "coordinates",
                              "geometry", "times", "data", "outputs"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ParityError("dataset.schema_version: integer 1 required")
    _text(data["dataset_id"], "dataset_id")
    source = _object(data["source"], "source", {"kind", "system", "system_version", "description"})
    if source["kind"] not in ("observed", "synthetic", "candidate"):
        raise ParityError("source.kind: observed, synthetic, or candidate required")
    for key in ("system", "system_version", "description"):
        _text(source[key], "source." + key)
    _known_version(source["system_version"], "source.system_version")
    engine = _object(data["engine"], "engine", {"name", "version", "executable_sha256"})
    for key in ("name", "version"):
        _text(engine[key], "engine." + key)
    _known_version(engine["version"], "engine.version")
    _sha(engine["executable_sha256"], "engine.executable_sha256")
    implementation = _object(data["implementation"], "implementation", {"git_commit"})
    _sha(implementation["git_commit"], "implementation.git_commit", commit=True)
    records = data["inputs"]
    expected_inputs = input_fingerprint(records)
    for index, record in enumerate(records):
        verify_artifact(root, record, f"inputs[{index}]")
    if data["exact_run_inputs_sha256"] != expected_inputs:
        raise ParityError("exact_run_inputs_sha256 does not bind the captured input files")
    comparison_path = verify_artifact(root, data["comparison_input"], "comparison_input")
    # A shared canonical physical case is required even when native deck formats differ.
    comparison_input = read_json(comparison_path)
    if not comparison_input:
        raise ParityError("comparison_input: empty physical case is insufficient")
    coordinates = _object(data["coordinates"], "coordinates", {"crs", "vertical_datum", "length_unit", "time_unit"})
    for key in coordinates:
        _text(coordinates[key], "coordinates." + key)
    shape = _geometry(data["geometry"])
    if not isinstance(data["times"], list) or not data["times"]:
        raise ParityError("times: nonempty saved-time array required")
    times = [_number(value, "times") for value in data["times"]]
    if any(v < 0 for v in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ParityError("times: finite, non-negative, strictly increasing times required")
    outputs = _object(data["outputs"], "outputs", set())
    if not outputs:
        raise NumericalDataError("outputs: empty output set is not a comparison")
    keys = set()
    for name, item in outputs.items():
        _text(name, "output name")
        _object(item, f"outputs.{name}", {"key", "unit", "quantity", "support", "sign_convention"})
        for key in ("key", "unit", "quantity", "support", "sign_convention"):
            _text(item[key], f"outputs.{name}.{key}")
        _output_shape(item["support"], len(times), shape)
        if item["key"] in keys:
            raise ParityError("outputs: duplicate data-array keys")
        keys.add(item["key"])
    blob = _object(data["data"], "data", {"path", "sha256", "size_bytes", "format"})
    path = verify_artifact(root, blob, "data")
    if blob["format"] == "npz":
        arrays = _read_npz(path, outputs, len(times), shape)
    elif blob["format"] == "csv":
        arrays = _read_csv(path, outputs, len(times), shape)
    else:
        raise ParityError("data.format: csv or npz required")
    observed = source["kind"] == "observed"
    if source["kind"] in ("observed", "candidate"):
        _validate_run_provenance(root, data)
    return {"manifest": data, "arrays": arrays, "manifest_path": str(manifest_path),
            "manifest_sha256": file_sha(manifest_path), "observed": observed,
            "comparison_input_sha256": fingerprint(comparison_input)}
