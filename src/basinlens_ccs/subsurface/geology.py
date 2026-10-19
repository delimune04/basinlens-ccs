"""Inert, bounded vertical borehole logs and explicit section projections.

Depth is positive downward from each collar, elevations positive upward. This
module neither infers missing logs nor interpolates a geological solid. Source
and destination parents must be trusted against concurrent filesystem mutation.
"""
from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unicodedata

SCHEMA = "basinlens-geology-v1"
CSV_SCHEMA = "basinlens-geology-csv-v1"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BOREHOLES = 200
MAX_INTERVALS = 20_000
MAX_HISTORY = 32
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
_TABLES = {
    "materials.csv": ("id", "name", "description", "provenance_id"),
    "horizons.csv": ("id", "name", "provenance_id"),
    "boreholes.csv": ("id", "name", "x_m", "y_m", "z_m", "total_depth_m", "provenance_id"),
    "intervals.csv": ("borehole_id", "id", "top_depth_m", "bottom_depth_m", "kind", "material_id",
                      "top_horizon_id", "bottom_horizon_id", "provenance_id"),
}


class GeologyValidationError(ValueError):
    """A geological contract, asset, section or portable file is inconsistent."""


def _fail(message):
    raise GeologyValidationError("geology: " + message)


def _object(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail(f"{name}: expected exact fields {sorted(fields)}")
    return value


def _text(value, name, maximum=1000):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail(f"{name}: expected nonempty bounded trimmed text")
    return value


def _id(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(f"{name}: expected portable identifier")
    return value


def _number(value, name, lower=-1e9, upper=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name}: expected finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail(f"{name}: expected finite number")
    if not math.isfinite(result) or not lower <= result <= upper:
        _fail(f"{name}: number outside [{lower}, {upper}]")
    return result


def _list(value, name, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail(f"{name}: expected {minimum}..{maximum} entries")
    return value


def _tree(value):
    count = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 20 or count > 500_000:
            _fail("JSON depth/value budget exceeded")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                _fail("JSON keys must be strings")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif item is None or isinstance(item, (str, bool)):
            pass
        elif isinstance(item, (int, float)):
            _number(item, "JSON number", -1e300, 1e300)
        else:
            _fail("only inert JSON values are supported")


def _canonical(value):
    _tree(value)
    try:
        payload = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        _fail(f"cannot encode JSON: {type(exc).__name__}")
    if len(payload) > MAX_FILE_BYTES:
        _fail("JSON byte budget exceeded")
    return payload


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _parse_json(payload):
    if len(payload) > MAX_FILE_BYTES:
        _fail("JSON byte budget exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        _fail("nonfinite JSON constant")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _tree(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, GeologyValidationError):
            raise
        _fail(f"invalid JSON: {type(exc).__name__}")


def _safe_relative(value):
    if (not isinstance(value, str) or not value.startswith("assets/") or len(value) > 400
            or unicodedata.normalize("NFC", value) != value
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(c in value for c in '\\:<>"|?*')):
        _fail("assets require portable relative paths below assets/")
    parts = value.split("/")
    if len(parts) > 8:
        _fail("asset path nesting budget exceeded")
    if any(p in ("", ".", "..") or len(p) > 150 or p.endswith((" ", "."))
           or _RESERVED.fullmatch(p) for p in parts):
        _fail("unsafe asset path")
    return value


def _no_links(path, *, directory=False):
    path = Path(path).expanduser().absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            _fail("symbolic-link paths are refused")
    if directory and not path.is_dir():
        _fail("expected existing regular directory")
    return path


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(path, maximum=MAX_FILE_BYTES):
    path = _no_links(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        declared = path.lstat()
        if not stat.S_ISREG(declared.st_mode) or declared.st_size > maximum:
            _fail("source must be a regular file within byte budget")
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if _identity(before) != _identity(declared):
                _fail("source changed before reading")
            payload = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > maximum or len(payload) != before.st_size:
            _fail("source size budget or length changed")
        if _identity(before) != _identity(after) or _identity(after) != _identity(path.lstat()):
            _fail("source changed while reading")
    except OSError as exc:
        raise GeologyValidationError("geology: source unavailable or unreadable") from exc
    return payload, {"path": str(path), "size_bytes": len(payload), "sha256": _sha(payload)}


def _fresh(path):
    path = _no_links(path)
    _no_links(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    return path


def _write_file(payload, path):
    path = _fresh(path)
    fd, temporary = tempfile.mkstemp(prefix=".geology-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic no-overwrite publication.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def _index(items, name):
    result = {}
    for item in items:
        key = _id(item["id"], name + ".id")
        if key in result:
            _fail(f"duplicate {name} identifier")
        result[key] = item
    return result


def _state_hash(value):
    return _sha(_canonical({key: item for key, item in value.items() if key != "history"}))


def _interval(value, borehole_id, interval_id):
    for hole in value["boreholes"]:
        if hole["id"] == borehole_id:
            for interval in hole["intervals"]:
                if interval["id"] == interval_id:
                    return interval
    _fail("unknown borehole or interval")


def _validate(value):
    _tree(value)
    _object(value, {"schema", "id", "name", "length_unit", "crs", "vertical_datum", "depth_reference",
                    "assets", "provenance", "materials", "horizons", "boreholes", "history"}, "project")
    value = copy.deepcopy(value)
    if value["schema"] != SCHEMA or value["length_unit"] != "m" or value["depth_reference"] != "vertical_depth_below_collar":
        _fail("unsupported schema, units or depth reference; convert explicitly")
    _id(value["id"], "project.id")
    for name in ("name", "crs", "vertical_datum"):
        _text(value[name], name)
    if value["crs"].upper() == "EPSG:4326":
        _fail("EPSG:4326 longitude/latitude degrees contradict metre collar coordinates; transform explicitly")
    assets = _list(value["assets"], "assets", 100)
    asset_paths = set()
    components = {}
    for asset in assets:
        _object(asset, {"id", "relative_path", "sha256", "media_type", "license"}, "asset")
        path = _safe_relative(asset["relative_path"])
        if path.casefold() in asset_paths:
            _fail("duplicate or case-colliding asset paths")
        asset_paths.add(path.casefold())
        parts = path.split("/")
        for n in range(1, len(parts) + 1):
            prefix = "/".join(parts[:n])
            if prefix.casefold() in components and components[prefix.casefold()] != prefix:
                _fail("case-colliding asset directories")
            components[prefix.casefold()] = prefix
        if not isinstance(asset["sha256"], str) or not _HASH.fullmatch(asset["sha256"]):
            _fail("invalid asset sha256")
        _text(asset["media_type"], "asset.media_type", 200)
        _text(asset["license"], "asset.license")
    for path in asset_paths:
        if any("/".join(path.split("/")[:n]) in asset_paths for n in range(1, len(path.split("/")))):
            _fail("asset file/directory collision")
    asset_ids = _index(assets, "asset")
    provenance = _list(value["provenance"], "provenance", 1000, 1)
    for record in provenance:
        _object(record, {"id", "description", "basis", "source_asset_ids"}, "provenance")
        _text(record["description"], "provenance.description")
        if record["basis"] not in ("synthetic", "observed", "interpreted", "unknown"):
            _fail("unknown provenance basis")
        refs = _list(record["source_asset_ids"], "source_asset_ids", 100)
        if any(not isinstance(ref, str) or ref not in asset_ids for ref in refs) or len(set(refs)) != len(refs):
            _fail("provenance has unknown or duplicate source asset")
        if record["basis"] in ("observed", "interpreted") and not refs:
            _fail("observed/interpreted provenance requires registered source asset")
    provenance_ids = _index(provenance, "provenance")
    def prov(item):
        if not isinstance(item["provenance_id"], str) or item["provenance_id"] not in provenance_ids:
            _fail("unknown provenance_id")
    materials = _list(value["materials"], "materials", 1000, 1)
    for material in materials:
        _object(material, {"id", "name", "description", "provenance_id"}, "material")
        _text(material["name"], "material.name")
        _text(material["description"], "material.description")
        prov(material)
    material_ids = _index(materials, "material")
    horizons = _list(value["horizons"], "horizons", 1000)
    for horizon in horizons:
        _object(horizon, {"id", "name", "provenance_id"}, "horizon")
        _text(horizon["name"], "horizon.name")
        prov(horizon)
    horizon_ids = _index(horizons, "horizon")
    holes = _list(value["boreholes"], "boreholes", MAX_BOREHOLES, 1)
    interval_count = 0
    for hole in holes:
        _object(hole, {"id", "name", "x_m", "y_m", "z_m", "total_depth_m", "provenance_id", "intervals"}, "borehole")
        _text(hole["name"], "borehole.name")
        prov(hole)
        for axis in ("x_m", "y_m", "z_m"):
            hole[axis] = _number(hole[axis], "borehole." + axis)
        hole["total_depth_m"] = _number(hole["total_depth_m"], "borehole.total_depth_m", 1e-6, 1e6)
        intervals = _list(hole["intervals"], "intervals", MAX_INTERVALS, 1)
        interval_count += len(intervals)
        if interval_count > MAX_INTERVALS:
            _fail("total interval budget exceeded")
        previous = 0.0
        previous_horizon = None
        contacts = {}
        for interval in intervals:
            _object(interval, {"id", "top_depth_m", "bottom_depth_m", "kind", "material_id",
                               "top_horizon_id", "bottom_horizon_id", "provenance_id"}, "interval")
            prov(interval)
            top = interval["top_depth_m"] = _number(interval["top_depth_m"], "interval.top_depth_m", 0, 1e6)
            bottom = interval["bottom_depth_m"] = _number(interval["bottom_depth_m"], "interval.bottom_depth_m", 0, 1e6)
            if top != previous or bottom <= top or bottom > hole["total_depth_m"]:
                _fail("intervals must be ordered, nonoverlapping and cover depth exactly; encode gaps explicitly")
            if interval["kind"] == "gap":
                if any(interval[key] is not None for key in ("material_id", "top_horizon_id", "bottom_horizon_id")):
                    _fail("gap cannot declare material or interpreted horizon contacts")
            elif interval["kind"] == "logged":
                if not isinstance(interval["material_id"], str) or interval["material_id"] not in material_ids:
                    _fail("logged interval requires known material")
            else:
                _fail("interval.kind must be logged or gap")
            for key, depth in (("top_horizon_id", top), ("bottom_horizon_id", bottom)):
                horizon = interval[key]
                if horizon is not None:
                    if not isinstance(horizon, str) or horizon not in horizon_ids:
                        _fail("unknown contact horizon identifier")
                    if horizon in contacts and contacts[horizon] != depth:
                        _fail("one horizon cannot repeat at different depths in a vertical borehole")
                    contacts[horizon] = depth
            if previous_horizon is not None and interval["top_horizon_id"] is not None and previous_horizon != interval["top_horizon_id"]:
                _fail("adjacent declared horizon IDs disagree at the same contact")
            previous, previous_horizon = bottom, interval["bottom_horizon_id"]
        _index(intervals, "interval")
        if previous != hole["total_depth_m"]:
            _fail("intervals must reach total_depth_m; encode unknown remainder as gap")
    _index(holes, "borehole")
    history = _list(value["history"], "history", MAX_HISTORY)
    # Replay edits backwards against the complete retained model. Hashes detect
    # accidental corruption; they are not signatures or proof of an observation.
    replay = copy.deepcopy(value)
    for index in range(len(history) - 1, -1, -1):
        event = history[index]
        _object(event, {"operation", "borehole_id", "interval_id", "old_material_id", "new_material_id",
                        "reason", "provenance_id", "source_project_sha256", "before_state_sha256", "after_state_sha256"}, "history")
        if event["operation"] != "edit_interval_material":
            _fail("unknown history operation")
        _text(event["reason"], "history.reason")
        prov(event)
        for key in ("source_project_sha256", "before_state_sha256", "after_state_sha256"):
            if not isinstance(event[key], str) or not _HASH.fullmatch(event[key]):
                _fail("invalid edit history hash")
        for key in ("old_material_id", "new_material_id"):
            if not isinstance(event[key], str) or event[key] not in material_ids:
                _fail("history references unknown material")
        interval = _interval(replay, event["borehole_id"], event["interval_id"])
        if interval["kind"] != "logged" or interval["material_id"] != event["new_material_id"]:
            _fail("history does not describe current interval material")
        if _state_hash(replay) != event["after_state_sha256"]:
            _fail("history after-state hash mismatch")
        interval["material_id"] = event["old_material_id"]
        replay["history"] = history[:index]
        if _state_hash(replay) != event["before_state_sha256"] or _sha(_canonical(replay)) != event["source_project_sha256"]:
            _fail("history source/before-state hash mismatch")
    _canonical(value)
    return value


@dataclass(frozen=True)
class GeologyProject:
    """Validated canonical geological document; use from_dict for construction."""
    _json: str

    @classmethod
    def from_dict(cls, value):
        return cls(_canonical(_validate(value)).decode("utf-8"))

    def to_dict(self):
        return _validate(_parse_json(self._json.encode("utf-8")))


@dataclass(frozen=True)
class LoadedGeology:
    project: GeologyProject
    source_identity: dict
    asset_root: Path


def _project(project):
    if not isinstance(project, GeologyProject):
        _fail("expected typed GeologyProject")
    return project.to_dict()


def _asset_bytes(value, asset_root):
    if not value["assets"]:
        return {}, {}
    if asset_root is None:
        _fail("registered assets require explicit asset_root")
    root = _no_links(asset_root, directory=True)
    payloads, identities = {}, {}
    total = 0
    for asset in value["assets"]:
        payload, identity = _read(root / asset["relative_path"], MAX_ASSET_BYTES)
        total += len(payload)
        if total > MAX_TOTAL_BYTES:
            _fail("registered asset total byte budget exceeded")
        if identity["sha256"] != asset["sha256"]:
            _fail("registered asset checksum mismatch")
        payloads[asset["relative_path"]] = payload
        identities[asset["relative_path"]] = identity
    return payloads, identities


def _recheck(identities):
    for identity in identities.values():
        _, current = _read(identity["path"], MAX_ASSET_BYTES)
        if current != identity:
            _fail("source changed during operation")


def load_geology(path, *, asset_root=None):
    """Load strict JSON and verify every registered asset without changing source."""
    payload, source = _read(path)
    project = GeologyProject.from_dict(_parse_json(payload))
    root = _no_links(asset_root if asset_root is not None else Path(path).absolute().parent, directory=True)
    _, assets = _asset_bytes(project.to_dict(), root)
    _recheck({"project": source, **assets})
    return LoadedGeology(project, {"format": SCHEMA, "files": {"project": source, **assets},
                                  "project_sha256": _sha(_canonical(project.to_dict()))}, root)


def save_geology(project, path, *, asset_root=None):
    """Create a fresh JSON document; assets remain at explicitly supplied root.

    Use export_geology_csv for a portable directory containing asset bytes.
    """
    value = _project(project)
    _, identities = _asset_bytes(value, asset_root)
    _recheck(identities)
    return _write_file(_canonical(value), path)


def _csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row[key] is None else repr(row[key]) if type(row[key]) is float else row[key] for key in fields})
    result = stream.getvalue().encode("utf-8")
    if len(result) > MAX_FILE_BYTES:
        _fail("CSV byte budget exceeded")
    return result


def _csv_rows(payload, name):
    fields = _TABLES[name]
    try:
        stream = io.StringIO(payload.decode("utf-8"), newline="")
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != list(fields):
            _fail(f"{name}: expected exact ordered CSV header")
        rows = []
        for row in reader:
            if len(rows) >= MAX_INTERVALS or None in row or any(value is None for value in row.values()):
                _fail(f"{name}: row/column budget or malformed row")
            for key in fields:
                if key.endswith("_m"):
                    try:
                        row[key] = float(row[key])
                    except (ValueError, OverflowError):
                        _fail(f"{name}: invalid numeric {key}")
                elif key in ("material_id", "top_horizon_id", "bottom_horizon_id") and row[key] == "":
                    row[key] = None
            rows.append(row)
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise GeologyValidationError(f"geology: invalid {name} CSV") from exc


def export_geology_csv(project, directory, *, asset_root=None):
    """Atomically publish portable strict CSV tables, metadata and exact assets."""
    value = _project(project)
    directory = _fresh(directory)
    assets, identities = _asset_bytes(value, asset_root)
    metadata = {key: item for key, item in value.items() if key not in ("materials", "horizons", "boreholes")}
    payloads = {"metadata.json": _canonical({"format": CSV_SCHEMA, "project": metadata})}
    for filename, key in (("materials.csv", "materials"), ("horizons.csv", "horizons")):
        payloads[filename] = _csv_bytes(_TABLES[filename], value[key])
    payloads["boreholes.csv"] = _csv_bytes(_TABLES["boreholes.csv"], value["boreholes"])
    intervals = [{"borehole_id": hole["id"], **interval} for hole in value["boreholes"] for interval in hole["intervals"]]
    payloads["intervals.csv"] = _csv_bytes(_TABLES["intervals.csv"], intervals)
    payloads.update(assets)
    if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        _fail("portable bundle total byte budget exceeded")
    manifest = {"format": CSV_SCHEMA, "project_sha256": _sha(_canonical(value)),
                "files": {name: {"size_bytes": len(payload), "sha256": _sha(payload)} for name, payload in sorted(payloads.items())}}
    payloads["manifest.json"] = _canonical(manifest)
    staging = Path(tempfile.mkdtemp(prefix=".geology-csv-", dir=directory.parent))
    try:
        for name, payload in payloads.items():
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        _recheck(identities)
        if directory.exists() or directory.is_symlink():
            raise FileExistsError(f"output already exists: {directory}")
        os.rename(staging, directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return directory


def import_geology_csv(directory):
    """Read and fully verify an exported portable bundle; execute no content."""
    directory = _no_links(directory, directory=True)
    manifest_payload, manifest_identity = _read(directory / "manifest.json")
    manifest = _object(_parse_json(manifest_payload), {"format", "project_sha256", "files"}, "manifest")
    if manifest["format"] != CSV_SCHEMA or not isinstance(manifest["files"], dict) or len(manifest["files"]) > 105:
        _fail("unsupported CSV manifest or member budget")
    for key in ("project_sha256",):
        if not isinstance(manifest[key], str) or not _HASH.fullmatch(manifest[key]):
            _fail("invalid manifest project hash")
    payloads, identities, total = {}, {"manifest.json": manifest_identity}, 0
    required = {"metadata.json", *_TABLES}
    for name, record in manifest["files"].items():
        if name not in required:
            _safe_relative(name)
        _object(record, {"size_bytes", "sha256"}, "manifest.file")
        if type(record["size_bytes"]) is not int or not 0 <= record["size_bytes"] <= MAX_ASSET_BYTES:
            _fail("manifest member byte budget exceeded")
        payload, identity = _read(directory / name, MAX_FILE_BYTES if name in required else MAX_ASSET_BYTES)
        total += len(payload)
        if total > MAX_TOTAL_BYTES or identity["sha256"] != record["sha256"] or len(payload) != record["size_bytes"]:
            _fail("CSV bundle byte budget or checksum mismatch")
        payloads[name], identities[name] = payload, identity
    if not required <= set(payloads):
        _fail("CSV bundle missing required table or metadata")
    # Inventory is exact: unrelated payloads are not silently discarded.
    actual = set()
    for member_index, entry in enumerate(directory.rglob("*")):
        if member_index >= 1024 or len(entry.relative_to(directory).parts) > 8:
            _fail("CSV directory inventory budget exceeded")
        _no_links(entry)
        if entry.is_file():
            actual.add(entry.relative_to(directory).as_posix())
        elif not entry.is_dir():
            _fail("nonregular CSV bundle member")
    if actual != {"manifest.json", *payloads}:
        _fail("CSV bundle inventory contains unregistered or missing files")
    metadata = _object(_parse_json(payloads["metadata.json"]), {"format", "project"}, "CSV metadata")
    if metadata["format"] != CSV_SCHEMA or not isinstance(metadata["project"], dict):
        _fail("unsupported CSV metadata")
    value = metadata["project"]
    if any(key in value for key in ("materials", "horizons", "boreholes")):
        _fail("CSV metadata duplicates a table")
    value["materials"] = _csv_rows(payloads["materials.csv"], "materials.csv")
    value["horizons"] = _csv_rows(payloads["horizons.csv"], "horizons.csv")
    holes = value["boreholes"] = _csv_rows(payloads["boreholes.csv"], "boreholes.csv")
    by_id = _index(holes, "borehole")
    for hole in holes:
        hole["intervals"] = []
    for row in _csv_rows(payloads["intervals.csv"], "intervals.csv"):
        hole = by_id.get(row.pop("borehole_id"))
        if hole is None:
            _fail("interval CSV references unknown borehole")
        hole["intervals"].append(row)
    project = GeologyProject.from_dict(value)
    expected_assets = {asset["relative_path"] for asset in project.to_dict()["assets"]}
    if set(payloads) != required | expected_assets:
        _fail("CSV manifest asset inventory differs from project")
    _, asset_identities = _asset_bytes(project.to_dict(), directory)
    if _sha(_canonical(project.to_dict())) != manifest["project_sha256"]:
        _fail("CSV semantic project hash mismatch")
    _recheck(identities)
    return LoadedGeology(project, {"format": CSV_SCHEMA, "files": identities,
                                  "project_sha256": manifest["project_sha256"]}, directory)


def edit_interval_material(project, borehole_id, interval_id, material_id, *, reason, provenance_id):
    """Return a new model with an auditable material edit; never alter source."""
    before = _project(project)
    if len(before["history"]) >= MAX_HISTORY:
        _fail("edit history budget reached; retain source and begin a reviewed revision")
    _text(reason, "reason")
    _id(provenance_id, "provenance_id")
    _id(material_id, "material_id")
    after = copy.deepcopy(before)
    target = _interval(after, borehole_id, interval_id)
    if target["kind"] != "logged":
        _fail("editing a gap into a logged interval requires a new explicit source revision")
    if target["material_id"] == material_id:
        _fail("material edit must change the declared material")
    old_material = target["material_id"]
    target["material_id"] = material_id
    event = {"operation": "edit_interval_material", "borehole_id": borehole_id, "interval_id": interval_id,
             "old_material_id": old_material, "new_material_id": material_id, "reason": reason,
             "provenance_id": provenance_id, "source_project_sha256": _sha(_canonical(before)),
             "before_state_sha256": _state_hash(before), "after_state_sha256": _state_hash(after)}
    after["history"].append(event)
    return GeologyProject.from_dict(after)


def correlate_horizons(project):
    """Group explicitly declared contacts by exact horizon ID, without inference."""
    value = _project(project)
    groups = {horizon["id"]: {"horizon": horizon, "contacts": []} for horizon in value["horizons"]}
    for hole in value["boreholes"]:
        seen = {}
        for interval in hole["intervals"]:
            for side in ("top", "bottom"):
                horizon = interval[f"{side}_horizon_id"]
                depth = interval[f"{side}_depth_m"]
                if horizon is None:
                    continue
                reference = {"interval_id": interval["id"], "side": side,
                             "provenance_id": interval["provenance_id"]}
                key = (horizon, depth)
                if key in seen:
                    seen[key]["references"].append(reference)
                    continue
                contact = {"borehole_id": hole["id"], "x_m": hole["x_m"], "y_m": hole["y_m"],
                           "z_m": hole["z_m"] - depth, "depth_m": depth,
                           "references": [reference]}
                seen[key] = contact
                groups[horizon]["contacts"].append(contact)
    return {"schema": "basinlens-explicit-horizon-contacts-v1", "source_project_sha256": _sha(_canonical(value)),
            "crs": value["crs"],
            "vertical_datum": value["vertical_datum"], "length_unit": "m",
            "correlation_rule": "exact declared horizon identifier only", "surfaces_inferred": False,
            "groups": list(groups.values())}


def project_section(project, polyline_xy, *, max_distance_m):
    """Project collars to nearest clamped segment; deterministic first-segment tie.

    The signed offset is positive on the left of the selected oriented segment.
    A nonzero endpoint distance can have signed_offset=0 for a collinear point;
    distance_m is always the complete Euclidean distance to the finite segment.
    """
    value = _project(project)
    _list(polyline_xy, "section polyline", 1000, 2)
    points = []
    for point in polyline_xy:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            _fail("section vertices require explicit [x_m,y_m]")
        points.append(tuple(_number(v, "section coordinate") for v in point))
    maximum = _number(max_distance_m, "max_distance_m", 0, 1e9)
    segments = []
    chainage = 0.0
    for first, last in zip(points[:-1], points[1:]):
        dx, dy = last[0] - first[0], last[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            _fail("section has duplicate or numerically zero-length adjacent vertices")
        segments.append((first, dx, dy, length, chainage))
        chainage += length
    included, excluded = [], []
    for hole in value["boreholes"]:
        best = None
        for index, (first, dx, dy, length, start) in enumerate(segments):
            ox, oy = hole["x_m"] - first[0], hole["y_m"] - first[1]
            fraction = min(1.0, max(0.0, (ox * dx + oy * dy) / (length * length)))
            x, y = first[0] + fraction * dx, first[1] + fraction * dy
            distance = math.hypot(hole["x_m"] - x, hole["y_m"] - y)
            candidate = (distance, index, start + fraction * length, (dx * oy - dy * ox) / length, x, y)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        distance, index, along, signed_offset, x, y = best
        if distance > maximum:
            excluded.append({"borehole_id": hole["id"], "distance_m": distance})
            continue
        included.append({"borehole_id": hole["id"], "segment_index": index, "chainage_m": along,
                         "distance_m": distance, "signed_offset_m": signed_offset,
                         "projected_x_m": x, "projected_y_m": y, "collar_z_m": hole["z_m"],
                         "intervals": [{**interval, "top_z_m": hole["z_m"] - interval["top_depth_m"],
                                        "bottom_z_m": hole["z_m"] - interval["bottom_depth_m"]}
                                       for interval in hole["intervals"]]})
    return {"schema": "basinlens-borehole-section-v1", "source_project_sha256": _sha(_canonical(value)),
            "crs": value["crs"], "vertical_datum": value["vertical_datum"], "length_unit": "m",
            "polyline_xy_m": [list(point) for point in points], "length_m": chainage,
            "max_distance_m": maximum, "projection_rule": "nearest finite segment; earliest segment wins exact ties",
            "offset_convention": "positive to left of oriented segment; distance_m includes endpoint displacement",
            "geological_interpolation": False, "boreholes": sorted(included, key=lambda h: (h["chainage_m"], h["borehole_id"])),
            "excluded": excluded}


def verify_geology_roundtrip(path, output_dir, *, asset_root=None):
    """Load JSON, export/import CSV, save/reload JSON and compare complete meaning."""
    source = load_geology(path, asset_root=asset_root)
    output_dir = _fresh(output_dir)
    staging = Path(tempfile.mkdtemp(prefix=".geology-roundtrip-", dir=output_dir.parent))
    try:
        csv_path = export_geology_csv(source.project, staging / "csv", asset_root=source.asset_root)
        loaded_csv = import_geology_csv(csv_path)
        save_geology(loaded_csv.project, staging / "roundtrip.json", asset_root=loaded_csv.asset_root)
        loaded_json = load_geology(staging / "roundtrip.json", asset_root=loaded_csv.asset_root)
        expected = source.project.to_dict()
        if loaded_csv.project.to_dict() != expected or loaded_json.project.to_dict() != expected:
            _fail("roundtrip changed geological document")
        _recheck(source.source_identity["files"])
        report = {"schema": "basinlens-geology-roundtrip-v1", "source_identity": source.source_identity,
                  "project_sha256": _sha(_canonical(expected)), "json_csv_json_semantics_equal": True,
                  "all_registered_asset_bytes_equal": True, "source_unchanged": True,
                  "original_gms_comparison": "not performed", "geological_interpolation": False}
        (staging / "receipt.json").write_bytes(_canonical(report))
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError(f"output already exists: {output_dir}")
        os.rename(staging, output_dir)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "export-csv", "roundtrip", "contacts", "section", "edit-material"):
        command = sub.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--asset-root", type=Path)
        if name != "check":
            command.add_argument("--output", type=Path, required=True)
        if name == "section":
            command.add_argument("--polyline-json", type=Path, required=True)
            command.add_argument("--max-distance-m", type=float, required=True)
        if name == "edit-material":
            for argument in ("borehole-id", "interval-id", "material-id", "reason", "provenance-id"):
                command.add_argument("--" + argument, required=True)
    command = sub.add_parser("import-csv")
    command.add_argument("source", type=Path)
    command.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "import-csv":
            loaded = import_geology_csv(arguments.source)
            save_geology(loaded.project, arguments.output, asset_root=loaded.asset_root)
            result = {"output": str(arguments.output), "assets_remain_at": str(loaded.asset_root)}
        elif arguments.command == "roundtrip":
            result = verify_geology_roundtrip(arguments.source, arguments.output, asset_root=arguments.asset_root)
        else:
            loaded = load_geology(arguments.source, asset_root=arguments.asset_root)
            if arguments.command == "check":
                value = loaded.project.to_dict()
                result = {"valid": True, "boreholes": len(value["boreholes"]),
                          "intervals": sum(len(h["intervals"]) for h in value["boreholes"]),
                          "source_identity": loaded.source_identity, "original_gms_comparison": "not performed"}
            elif arguments.command == "export-csv":
                export_geology_csv(loaded.project, arguments.output, asset_root=loaded.asset_root)
                result = {"output": str(arguments.output)}
            elif arguments.command == "contacts":
                result = correlate_horizons(loaded.project)
                _write_file(_canonical(result), arguments.output)
            elif arguments.command == "section":
                vertices = _parse_json(_read(arguments.polyline_json)[0])
                result = project_section(loaded.project, vertices, max_distance_m=arguments.max_distance_m)
                _write_file(_canonical(result), arguments.output)
            elif arguments.command == "edit-material":
                edited = edit_interval_material(loaded.project, arguments.borehole_id, arguments.interval_id,
                                                arguments.material_id, reason=arguments.reason,
                                                provenance_id=arguments.provenance_id)
                save_geology(edited, arguments.output, asset_root=loaded.asset_root)
                result = {"output": str(arguments.output), "history_entries": len(edited.to_dict()["history"])}
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (GeologyValidationError, OSError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
