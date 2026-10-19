"""Bounded, portable BasinLens project packages; never a native GMS writer.

A package is inert JSON and exact registered asset bytes. Opening it does not
import its asset formats, run a solver, or deserialize executable Python data.
All source and destination parents must be trusted against concurrent mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
import zlib

from .schema import ProjectValidationError, SubsurfaceProject

FORMAT = "basinlens-project"
BUNDLE_VERSION = 1
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_PROJECT_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 2_000_000
MAX_VIEW_BYTES = 4096
MAX_MEMBERS = 1003
CHUNK_BYTES = 64 * 1024
_VIEW_DEFAULTS = {"selected_layer": 0, "selected_field": "head", "chart_mode": "2d", "show_wells": True}
_VIEW_FIELDS = {"head", "hydraulic_conductivity_x", "hydraulic_conductivity_y",
                "hydraulic_conductivity_z", "specific_storage", "porosity"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)


@dataclass(frozen=True)
class LoadedProjectPackage:
    """A verified project whose relative asset paths resolve within asset_root."""

    project: SubsurfaceProject
    asset_root: Path
    view_state: dict
    receipt: dict
    root: Path


def _fail(message):
    raise ProjectValidationError("project package: " + message)


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _json_tree(value, *, max_nodes=200_000):
    """Bound JSON depth/values, including direct Python call inputs."""
    count = 0
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        count += 1
        if depth > 32 or count > max_nodes:
            _fail("JSON nesting or value-count budget exceeded")
        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                _fail("JSON object keys must be strings")
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
        elif current is None or isinstance(current, (str, bool)):
            pass
        elif isinstance(current, (int, float)):
            try:
                finite = math.isfinite(current)
            except (OverflowError, ValueError):
                finite = False
            if not finite:
                _fail("JSON numbers must be finite")
        else:
            _fail("only inert finite JSON data is supported")


def _canonical(value):
    _json_tree(value)
    try:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        _fail(f"cannot encode JSON: {type(exc).__name__}")


def _json(payload, *, maximum, name):
    if len(payload) > maximum:
        _fail(f"{name} size budget exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail(f"duplicate JSON key in {name}")
            result[key] = value
        return result
    def constant(value):
        _fail(f"nonfinite JSON number in {name}")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _json_tree(value)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProjectValidationError):
            raise
        _fail(f"cannot parse {name}: {type(exc).__name__}")
    if _canonical(value) != payload:
        _fail(f"{name} must use canonical UTF-8 JSON")
    return value


def _safe_name(name):
    if (not isinstance(name, str) or not name or len(name) > 1024
            or unicodedata.normalize("NFC", name) != name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(c in name for c in ("\\", ":", "<", ">", '"', "|", "?", "*"))):
        _fail("unsafe or nonportable member/asset path")
    parts = name.split("/")
    if any(part in ("", ".", "..") or len(part) > 200 or part.endswith((" ", "."))
           or _RESERVED.fullmatch(part) for part in parts):
        _fail("unsafe or nonportable member/asset path")
    return name


def _check_names(names):
    seen = {}
    components = {}
    for name in names:
        _safe_name(name)
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            prefix_key = prefix.casefold()
            if prefix_key in components and components[prefix_key] != prefix:
                _fail("case-fold-colliding file or directory spellings")
            components[prefix_key] = prefix
        key = name.casefold()
        if key in seen:
            _fail("duplicate or case-fold-colliding paths")
        seen[key] = name
    for key in seen:
        parts = key.split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            _fail("file/directory path collision")


def _path_no_links(path, *, directory=False):
    path = Path(path).expanduser().absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            _fail("symbolic-link source/destination paths are refused")
    if directory and not path.is_dir():
        _fail("expected an existing regular directory")
    return path


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_file(path, maximum):
    """Read a bounded regular file and reject replacement/mutation while reading."""
    path = _path_no_links(path)
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        declared = path.lstat()
        if not stat.S_ISREG(declared.st_mode) or declared.st_size > maximum:
            _fail("source is not a regular file within its size budget")
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if _identity(before) != _identity(declared):
                _fail("source changed before reading")
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                _fail("source is not a regular file within its size budget")
            blocks = []
            size = 0
            while True:
                block = stream.read(min(CHUNK_BYTES, maximum + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > maximum:
                    _fail("source size budget exceeded while reading")
                blocks.append(block)
            after = os.fstat(stream.fileno())
        if _identity(before) != _identity(after) or _identity(after) != _identity(path.stat()):
            _fail("source changed while reading")
        payload = b"".join(blocks)
        if len(payload) != before.st_size:
            _fail("source length changed while reading")
        return payload
    except OSError as exc:
        raise ProjectValidationError("project package: source unavailable or unreadable") from exc


def _fresh_output(output, *, package=False):
    output = _path_no_links(output)
    _path_no_links(output.parent, directory=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    if package and output.suffix != ".blproj":
        _fail("package output must use .blproj")
    return output


def _project(project):
    if not isinstance(project, SubsurfaceProject):
        _fail("expected a typed SubsurfaceProject")
    _json_tree(project.model.options)
    result = SubsurfaceProject.from_dict(project.to_dict())
    payload = _canonical(result.to_dict())
    if len(payload) > MAX_PROJECT_BYTES:
        _fail("project JSON size budget exceeded")
    paths = {}
    for asset in result.assets:
        _safe_name(asset.relative_path)
        if asset.relative_path in paths and paths[asset.relative_path] != asset.sha256:
            _fail("assets sharing a path must declare the same checksum")
        paths[asset.relative_path] = asset.sha256
    _check_names(paths)
    return result, payload, paths


def _view_state(value, project):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(_VIEW_DEFAULTS):
        _fail("unsupported view-state fields")
    result = {**_VIEW_DEFAULTS, **value}
    layer = result["selected_layer"]
    if type(layer) is not int or not 0 <= layer < project.geometry.nlay:
        _fail("view selected_layer lies outside project geometry")
    if not isinstance(result["selected_field"], str) or result["selected_field"] not in _VIEW_FIELDS:
        _fail("unsupported view selected_field")
    if not isinstance(result["chart_mode"], str) or result["chart_mode"] not in ("2d", "3d"):
        _fail("unsupported view chart_mode")
    if type(result["show_wells"]) is not bool:
        _fail("view show_wells must be boolean")
    return result


def _semantic(project, view, assets):
    return _digest(_canonical({"project": project.to_dict(), "view_state": view, "assets": assets}))


def _asset_records(project, paths):
    return {asset.asset_id: {"member": "assets/" + asset.relative_path,
            "sha256": asset.sha256, "size_bytes": len(paths[asset.relative_path])}
            for asset in project.assets}


def _manifest(project, view, payloads, assets):
    files = {name: {"sha256": _digest(payload), "size_bytes": len(payload)}
             for name, payload in sorted(payloads.items())}
    return {"format": FORMAT, "bundle_version": BUNDLE_VERSION, "project_schema_version": 1,
            "project_sha256": files["project.json"]["sha256"],
            "view_state_sha256": files["view_state.json"]["sha256"],
            "semantic_sha256": _semantic(project, view, assets), "files": files, "assets": assets}


def _zip_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o444) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def save_project_package(project, output, *, asset_root=None, view_state=None):
    """Atomically create a fresh .blproj; include only explicitly registered assets.

    Shared paths are allowed only for assets declaring exactly the same bytes.
    All assets are read and checked twice around package construction. A failed
    write removes the staging file; no final package is published on failure.
    """
    output = _fresh_output(output, package=True)
    project, project_payload, expected = _project(project)
    view = _view_state(view_state, project)
    if expected and asset_root is None:
        _fail("asset_root is required for registered assets")
    asset_root = _path_no_links(asset_root, directory=True) if asset_root is not None else None
    assets = {}
    total = len(project_payload)
    for relative, digest in sorted(expected.items()):
        payload = _read_file(asset_root / relative, MAX_ASSET_BYTES)
        if _digest(payload) != digest:
            _fail("registered asset checksum mismatch")
        total += len(payload)
        if total > MAX_TOTAL_BYTES:
            _fail("total decoded payload budget exceeded")
        assets[relative] = payload
    payloads = {"project.json": project_payload, "view_state.json": _canonical(view),
                **{"assets/" + name: payload for name, payload in assets.items()}}
    records = _asset_records(project, assets)
    manifest = _manifest(project, view, payloads, records)
    manifest_payload = _canonical(manifest)
    if len(manifest_payload) > MAX_MANIFEST_BYTES:
        _fail("manifest size budget exceeded")
    payloads["manifest.json"] = manifest_payload
    if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES or len(payloads) > MAX_MEMBERS:
        _fail("package payload/member budget exceeded")
    staged = None
    try:
        fd, name = tempfile.mkstemp(prefix="." + output.name + ".partial-", dir=output.parent)
        staged = Path(name)
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, payload in sorted(payloads.items()):
                    archive.writestr(_zip_info(name), payload)
            stream.flush()
            os.fsync(stream.fileno())
            if stream.tell() > MAX_ARCHIVE_BYTES:
                _fail("compressed archive size budget exceeded")
        for relative, digest in expected.items():
            if _digest(_read_file(asset_root / relative, MAX_ASSET_BYTES)) != digest:
                _fail("registered asset changed during save")
        # Linking is an atomic no-replace publication on both POSIX and Windows.
        os.link(staged, output)
        staged.unlink()
        staged = None
        return output
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _record(value):
    if (not isinstance(value, dict) or set(value) != {"sha256", "size_bytes"}
            or not isinstance(value["sha256"], str) or not _HASH.fullmatch(value["sha256"])
            or type(value["size_bytes"]) is not int or not 0 <= value["size_bytes"] <= MAX_ASSET_BYTES):
        _fail("malformed inventory checksum/size record")
    return value


def _read_member(archive, info, maximum):
    blocks = []
    size = 0
    with archive.open(info, "r") as stream:
        while True:
            block = stream.read(min(CHUNK_BYTES, maximum + 1 - size))
            if not block:
                break
            size += len(block)
            if size > maximum:
                _fail("decoded member size budget exceeded")
            blocks.append(block)
    payload = b"".join(blocks)
    if len(payload) != info.file_size:
        _fail("member size disagrees with central directory")
    return payload


def _decode_archive(payload):
    import io
    try:
        if len(payload) < 22 or not payload.startswith(b"PK\x03\x04") or payload[-22:-18] != b"PK\x05\x06":
            _fail("ZIP prefixes, trailing data, or comments are unsupported")
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            if archive.comment:
                _fail("archive comments are unsupported")
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS or not infos:
                _fail("archive member-count budget exceeded")
            # orig_filename catches NUL truncation performed by zipfile itself.
            names = [info.orig_filename for info in infos]
            _check_names(names)
            if any(info.filename != info.orig_filename for info in infos):
                _fail("truncated archive path")
            total = 0
            payloads = {}
            for info in infos:
                mode = (info.external_attr >> 16) & 0xFFFF
                if (info.is_dir() or info.extra or info.comment
                        or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                        or (info.flag_bits & 1) or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    _fail("only unencrypted regular stored/deflated members are supported")
                maximum = {"manifest.json": MAX_MANIFEST_BYTES, "project.json": MAX_PROJECT_BYTES,
                           "view_state.json": MAX_VIEW_BYTES}.get(info.filename, MAX_ASSET_BYTES)
                if info.file_size > maximum or info.compress_size > MAX_ARCHIVE_BYTES:
                    _fail("member declared-size budget exceeded")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    _fail("total decoded payload budget exceeded")
                payloads[info.filename] = _read_member(archive, info, maximum)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, ValueError, EOFError, zlib.error) as exc:
        if isinstance(exc, ProjectValidationError):
            raise
        raise ProjectValidationError("project package: malformed or unreadable ZIP") from exc
    return _validate_payloads(payloads)


def _validate_payloads(payloads):
    if not {"manifest.json", "project.json", "view_state.json"} <= set(payloads):
        _fail("missing manifest, project or view-state member")
    manifest = _json(payloads["manifest.json"], maximum=MAX_MANIFEST_BYTES, name="manifest.json")
    fields = {"format", "bundle_version", "project_schema_version", "project_sha256",
              "view_state_sha256", "semantic_sha256", "files", "assets"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        _fail("unsupported manifest fields")
    if (manifest["format"] != FORMAT or type(manifest["bundle_version"]) is not int
            or manifest["bundle_version"] != BUNDLE_VERSION
            or type(manifest["project_schema_version"]) is not int or manifest["project_schema_version"] != 1):
        _fail("unsupported package/project version")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(payloads) - {"manifest.json"}:
        _fail("manifest inventory and actual members disagree")
    for name, record in files.items():
        _safe_name(name)
        _record(record)
        if record != {"sha256": _digest(payloads[name]), "size_bytes": len(payloads[name])}:
            _fail("member integrity mismatch")
    raw_project = _json(payloads["project.json"], maximum=MAX_PROJECT_BYTES, name="project.json")
    try:
        project, project_payload, expected = _project(SubsurfaceProject.from_dict(raw_project))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ProjectValidationError):
            raise
        _fail("invalid typed project")
    if project_payload != payloads["project.json"]:
        _fail("project is not in canonical typed representation")
    raw_view = _json(payloads["view_state.json"], maximum=MAX_VIEW_BYTES, name="view_state.json")
    view = _view_state(raw_view, project)
    if view != raw_view:
        _fail("view state must contain exactly the supported fields")
    asset_payloads = {relative: payloads.get("assets/" + relative) for relative in expected}
    if any(value is None for value in asset_payloads.values()):
        _fail("registered asset payload is missing")
    expected_names = {"project.json", "view_state.json", *["assets/" + path for path in expected]}
    if set(files) != expected_names:
        _fail("unregistered or unknown package members are refused")
    for relative, digest in expected.items():
        if _digest(asset_payloads[relative]) != digest:
            _fail("registered asset and package bytes disagree")
    assets = _asset_records(project, asset_payloads)
    if manifest["assets"] != assets:
        _fail("asset inventory disagrees with project registrations")
    expected_manifest = _manifest(project, view, {key: value for key, value in payloads.items() if key != "manifest.json"}, assets)
    if _canonical(manifest) != _canonical(expected_manifest):
        _fail("semantic or canonical hash binding disagrees")
    return project, view, manifest, payloads


def _verify_staged_payloads(root, payloads):
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            _fail("restored symbolic links are refused")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            _fail("restored nonregular paths are refused")
    if actual != set(payloads):
        _fail("restored inventory disagrees with package")
    checked = {}
    for name, expected in payloads.items():
        maximum = {"manifest.json": MAX_MANIFEST_BYTES, "project.json": MAX_PROJECT_BYTES,
                   "view_state.json": MAX_VIEW_BYTES}.get(name, MAX_ASSET_BYTES)
        payload = _read_file(root / name, maximum)
        if payload != expected:
            _fail("restored member bytes disagree with package")
        checked[name] = _digest(payload)
    return checked


def _verify_restored_assets(project, root, *, verified_payloads=None):
    """Reuse complete staged inventory checks, including many IDs per path."""
    checked = {} if verified_payloads is None else {
        name.removeprefix("assets/"): digest for name, digest in verified_payloads.items()
        if name.startswith("assets/")}
    for asset in project.assets:
        if asset.relative_path not in checked:
            checked[asset.relative_path] = _digest(_read_file(root / asset.relative_path, MAX_ASSET_BYTES))
        if checked[asset.relative_path] != asset.sha256:
            _fail("restored asset checksum mismatch")
    return {asset.asset_id: checked[asset.relative_path] for asset in project.assets}


def _promote_directory(staging, output):
    # A fresh sibling staging directory gives atomic visibility on the same FS.
    # Parents must be trusted against concurrent external replacement.
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    os.rename(staging, output)


def open_project_package(path, output_dir):
    """Validate a package fully, then publish a fresh relocated asset directory.

    Every ZIP entry is checked and read within hard budgets before any entry is
    written. Extraction uses explicit fresh paths, never ZipFile.extract().
    Source bytes are hashed before/after opening. The returned receipt is an
    integrity/relocation result, not evidence of GMS equivalence or asset truth.
    """
    source = _path_no_links(path)
    if source.suffix != ".blproj":
        _fail("expected a .blproj file; native GPR and unrelated ZIPs are unsupported")
    output = _fresh_output(output_dir)
    before = _read_file(source, MAX_ARCHIVE_BYTES)
    project, view, manifest, payloads = _decode_archive(before)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".partial-", dir=output.parent))
    try:
        for name, payload in sorted(payloads.items()):
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(payload)
        # Ensure an asset_root exists even for empty projects.
        (staging / "assets").mkdir(exist_ok=True)
        staged_checksums = _verify_staged_payloads(staging, payloads)
        verified = _verify_restored_assets(project, staging / "assets", verified_payloads=staged_checksums)
        after = _read_file(source, MAX_ARCHIVE_BYTES)
        if _digest(before) != _digest(after):
            _fail("source archive changed during opening")
        receipt = {"format": FORMAT, "bundle_version": BUNDLE_VERSION,
                   "source_archive_sha256_before": _digest(before),
                   "source_archive_sha256_after": _digest(after), "source_unchanged": True,
                   "project_sha256": manifest["project_sha256"],
                   "view_state_sha256": manifest["view_state_sha256"],
                   "semantic_sha256": manifest["semantic_sha256"],
                   "assets_verified": verified, "asset_count": len(project.assets),
                   "unique_asset_file_count": len({a.relative_path for a in project.assets}),
                   "inventory_verified": True, "original_gms_comparison": "not_performed"}
        _promote_directory(staging, output)
        staging = None
        return LoadedProjectPackage(project, output / "assets", dict(view), receipt, output)
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def verify_project_roundtrip(path):
    """Actually open, repack from relocated assets, reopen, and compare all bytes."""
    source = _path_no_links(path)
    original_hash = _digest(_read_file(source, MAX_ARCHIVE_BYTES))
    with tempfile.TemporaryDirectory(prefix="basinlens-roundtrip-") as temporary:
        root = Path(temporary)
        first = open_project_package(source, root / "first")
        repacked = save_project_package(first.project, root / "repacked.blproj",
                                       asset_root=first.asset_root, view_state=first.view_state)
        second = open_project_package(repacked, root / "second")
        if (_canonical(first.project.to_dict()) != _canonical(second.project.to_dict())
                or _canonical(first.view_state) != _canonical(second.view_state)
                or first.receipt["semantic_sha256"] != second.receipt["semantic_sha256"]):
            _fail("project or view-state semantics changed during round trip")
        assets = {}
        compared = {}
        for asset in first.project.assets:
            if asset.relative_path not in compared:
                first_bytes = _read_file(first.asset_root / asset.relative_path, MAX_ASSET_BYTES)
                second_bytes = _read_file(second.asset_root / asset.relative_path, MAX_ASSET_BYTES)
                if first_bytes != second_bytes:
                    _fail("asset bytes changed during round trip")
                compared[asset.relative_path] = {"sha256": _digest(first_bytes), "size_bytes": len(first_bytes)}
            assets[asset.asset_id] = dict(compared[asset.relative_path])
        final_hash = _digest(_read_file(source, MAX_ARCHIVE_BYTES))
        if original_hash != final_hash:
            _fail("original archive changed during round trip")
        return {"format": FORMAT, "bundle_version": BUNDLE_VERSION,
                "operation": "open_repack_reopen_compare", "roundtrip_verified": True,
                "project_semantics_equal": True, "view_state_equal": True, "asset_bytes_equal": True,
                "source_archive_sha256_before": original_hash,
                "source_archive_sha256_after": final_hash, "source_unchanged": True,
                "repacked_archive_sha256": _digest(_read_file(repacked, MAX_ARCHIVE_BYTES)),
                "archive_bytes_equal": original_hash == _digest(_read_file(repacked, MAX_ARCHIVE_BYTES)),
                "semantic_sha256": first.receipt["semantic_sha256"], "assets": assets,
                "original_gms_comparison": "not_performed"}
