"""Portable collections of explicitly typed geoscience objects in own .blproj.

This layer reuses the bounded project container. It does not change GPR, execute
assets, transform coordinates, map geology into a solver or restore live runs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import project_package as package
from .schema import DataAsset, ProjectValidationError, SubsurfaceProject

SCHEMA = "basinlens-geoscience-objects-v1"
MANIFEST_ID = "bl_geoscience_manifest"
MANIFEST_PATH = "geoscience/objects.json"
MAX_OBJECTS = 64
MAX_OBJECT_BYTES = package.MAX_ASSET_BYTES
KINDS = ("geology", "scatter", "features", "mesh", "raster", "pointcloud", "surfaces", "analysis_archive")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_LICENSE = "Owner-supplied project object; redistribution permission not inferred"
_SCOPE = "typed inert objects; no coordinate transformation, solver mapping, execution or original GMS parity"


def _fail(message):
    raise ProjectValidationError("geoscience project: " + message)


def _canonical(value):
    package._json_tree(value, max_nodes=2_000_000)
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        _fail(f"invalid finite canonical JSON: {type(error).__name__}")
    if len(raw) > MAX_OBJECT_BYTES:
        _fail("one canonical object exceeds the 32 MiB package asset budget")
    return raw


def _decode(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_OBJECT_BYTES:
        _fail("bounded UTF-8 object bytes required")
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _fail("duplicate JSON object key")
            value[key] = item
        return value
    def constant(value):
        _fail("nonfinite JSON object number")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if _canonical(value) != raw:
            _fail("object/manifest must use exact canonical UTF-8 JSON")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, ProjectValidationError):
            raise
        _fail(f"invalid JSON object: {type(error).__name__}")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _types():
    # Explicit trusted imports only; the package cannot select a Python module.
    from .geology import GeologyProject
    from .scatter import ScatterDataset
    from .features import FeatureCoverage
    from .mesh import PlanarMesh
    from .raster import RasterGrid
    from .pointcloud import PointCloud
    from .surfaces import SurfaceModel
    return {"geology": GeologyProject, "scatter": ScatterDataset,
            "features": FeatureCoverage, "mesh": PlanarMesh, "raster": RasterGrid,
            "pointcloud": PointCloud, "surfaces": SurfaceModel,
            "analysis_archive": AnalysisArchive}


@dataclass(frozen=True)
class ProjectObject:
    """Project-local collection ID does not replace IDs inside the source object."""
    kind: str
    object_id: str
    value: object


@dataclass(frozen=True)
class LoadedGeoscienceProject:
    project: SubsurfaceProject
    objects: tuple[ProjectObject, ...]
    asset_root: Path
    view_state: dict
    receipt: dict
    root: Path

    @property
    def object_asset_roots(self):
        return {item.object_id: self.asset_root for item in self.objects if item.kind == "geology"}


@dataclass(frozen=True)
class AnalysisArchive:
    """Exact exported analysis files, archived as inert data, never a live run."""
    _files: tuple[tuple[str, bytes], ...]

    @classmethod
    def from_files(cls, files):
        if not isinstance(files, dict) or set(files) != {"analysis.json", "samples.csv", "manifest.json"}:
            _fail("analysis archive requires exact analysis.json/samples.csv/manifest.json files")
        if any(not isinstance(raw, bytes) or len(raw) > MAX_OBJECT_BYTES for raw in files.values()):
            _fail("analysis archive files must be bounded immutable bytes")
        from .analysis import verify_analysis_bundle
        with tempfile.TemporaryDirectory(prefix="basinlens-inert-analysis-") as temporary:
            root = Path(temporary)
            for name, raw in files.items():
                (root / name).write_bytes(raw)
            verify_analysis_bundle(root)
        return cls(tuple(sorted(files.items())))

    @property
    def files(self):
        if (type(self._files) is not tuple or len(self._files) != 3 or
                any(type(pair) is not tuple or len(pair) != 2 or not isinstance(pair[0], str)
                    or not isinstance(pair[1], bytes) for pair in self._files) or
                len({pair[0] for pair in self._files}) != 3):
            _fail("analysis archive requires three unique immutable named byte payloads")
        return dict(self._files)

    def to_dict(self):
        validated = type(self).from_files(self.files)
        raw = validated.files["analysis.json"]
        # Analysis output uses its own pretty JSON contract; validate with its
        # own strict parser, without rewriting the archived original file bytes.
        from .analysis import _decode as decode_analysis
        result = decode_analysis(raw)
        required = {"schema", "operation", "crs", "vertical_datum", "coordinate_unit", "source", "field", "value_unit"}
        from .analysis import FIELDS
        if (not isinstance(result, dict) or not required <= set(result)
                or result["schema"] != "basinlens-structured-analysis-v1"
                or result["operation"] not in ("query", "section", "clip", "manual_observation_comparison")
                or result["coordinate_unit"] != "m" or not isinstance(result["field"], str) or result["field"] not in FIELDS
                or result["value_unit"] != FIELDS[result["field"]]
                or not isinstance(result["source"], dict)
                or any(not isinstance(result[key], str) or not result[key].strip() for key in ("crs", "vertical_datum"))):
            _fail("analysis archive lacks supported explicit operation/spatial/unit/source metadata")
        return {"schema": "basinlens-inert-analysis-archive-v1",
                "archive_role": "inert exported bundle; live engine state not reconstructed",
                "crs": result["crs"], "vertical_datum": result["vertical_datum"],
                "coordinate_unit": result["coordinate_unit"], "operation": result["operation"],
                "original_source": result["source"],
                "files": {name: {"bytes": len(payload), "sha256": _digest(payload)}
                          for name, payload in validated._files},
                "verification_scope": "file inventory and JSON/CSV consistency only; no numerical recomputation",
                "live_engine_state_restored": False, "gms_parity_established": False}


def archive_analysis_bundle(path):
    """Capture an existing exported bundle without following its stored run path."""
    root = package._path_no_links(path, directory=True)
    from .analysis import verify_analysis_bundle
    verify_analysis_bundle(root)
    files = {name: package._read_file(root / name, MAX_OBJECT_BYTES)
             for name in ("analysis.json", "samples.csv", "manifest.json")}
    archived = AnalysisArchive.from_files(files)
    if any(package._read_file(root / name, MAX_OBJECT_BYTES) != raw for name, raw in files.items()):
        _fail("analysis source bundle changed while capturing")
    return archived


def _validated(item):
    if (type(item) is not ProjectObject or item.kind not in KINDS
            or not isinstance(item.object_id, str) or not _ID.fullmatch(item.object_id)):
        _fail("typed ProjectObject, known kind and portable ASCII collection ID required")
    expected = _types()[item.kind]
    if type(item.value) is not expected:
        _fail(f"{item.kind}: requires exact trusted {expected.__name__} type")
    if item.kind == "analysis_archive":
        value = AnalysisArchive.from_files(item.value.files)
    else:
        value = expected.from_dict(item.value.to_dict())
    data = value.to_dict()
    raw = _canonical(data)
    return ProjectObject(item.kind, item.object_id, value), data, raw


def _spatial(kind, data):
    if kind == "features":
        c = data["coordinate_system"]
        return {"crs": c["crs"], "coordinate_unit": c["units"], "vertical_datum": None}
    if kind == "pointcloud":
        c = data["metadata"]
        if c["horizontal_unit"] != "m" or c["vertical_unit"] != "m":
            _fail("point cloud must explicitly declare horizontal and vertical metres; no conversion")
        return {"crs": c["crs"], "coordinate_unit": "m", "vertical_datum": c["vertical_datum"]}
    if kind == "surfaces":
        unit = data["units"]["length"]
    else:
        unit = data.get("coordinate_unit", data.get("length_unit"))
    return {"crs": data["crs"], "coordinate_unit": unit,
            "vertical_datum": data.get("vertical_datum")}


def _check_spatial(project, spatial):
    reference = project.spatial_reference
    if spatial["coordinate_unit"] != "m" or reference.length_unit != "m":
        _fail("all spatial objects require explicit metre coordinates; no inferred conversion")
    if spatial["crs"] != reference.crs:
        _fail("object CRS contradicts common project CRS; transform explicitly before packaging")
    if spatial["vertical_datum"] is not None and spatial["vertical_datum"] != reference.vertical_datum:
        _fail("object vertical datum contradicts common project datum")


def _asset(asset_id, path, raw, *, media_type="application/json", license=_LICENSE, source):
    package._safe_name(path)
    return DataAsset(asset_id, path, _digest(raw), media_type, license, source)


def _base_project(project, managed_ids=()):
    data = project.to_dict()
    data["assets"] = [a for a in data["assets"] if a["asset_id"] not in managed_ids]
    return SubsurfaceProject.from_dict(data)


def _check_base_assets(project):
    if any(a.relative_path.casefold().startswith("geoscience/") or
           a.asset_id.casefold().startswith("bl_geo_") or
           a.asset_id.casefold() == MANIFEST_ID.casefold() for a in project.assets):
        _fail("generic asset conflicts with reserved geoscience paths/IDs")


def _ids_and_paths(assets):
    ids, paths = set(), {}
    for asset in assets:
        if asset.asset_id.casefold() in ids:
            _fail("duplicate or case-fold-colliding registered asset IDs")
        ids.add(asset.asset_id.casefold())
        previous = paths.get(asset.relative_path)
        if previous and (previous.sha256, previous.media_type, previous.license) != (asset.sha256, asset.media_type, asset.license):
            _fail("same asset path has contradictory bytes/media type/license")
        paths[asset.relative_path] = asset
    package._check_names(paths)


def _manifest(project, root):
    matches = [a for a in project.assets if a.asset_id == MANIFEST_ID]
    if len(matches) != 1 or matches[0].relative_path != MANIFEST_PATH:
        _fail("exact registered geoscience manifest required")
    asset = matches[0]
    raw = package._read_file(root / MANIFEST_PATH, MAX_OBJECT_BYTES)
    if _digest(raw) != asset.sha256:
        _fail("geoscience manifest checksum mismatch")
    expected = _asset(MANIFEST_ID, MANIFEST_PATH, raw, source="BasinLens typed geoscience object manifest")
    if asset != expected:
        _fail("manifest asset metadata contradicts this format")
    value = _decode(raw)
    if (not isinstance(value, dict) or set(value) != {"schema", "base_project_sha256", "objects", "managed_assets", "scope"}
            or value["schema"] != SCHEMA or value["scope"] != _SCOPE
            or not isinstance(value["objects"], list) or not 1 <= len(value["objects"]) <= MAX_OBJECTS
            or not isinstance(value["managed_assets"], list)):
        _fail("unsupported or malformed typed object manifest")
    try:
        managed = [DataAsset(**record) for record in value["managed_assets"]]
    except (TypeError, ValueError) as error:
        _fail(f"malformed managed asset record: {type(error).__name__}")
    if len(managed) > 999 or MANIFEST_ID in {a.asset_id for a in managed}:
        _fail("managed asset budget or manifest self-reference violation")
    _ids_and_paths([*managed, asset])
    all_assets = {a.asset_id: a for a in project.assets}
    if any(all_assets.get(a.asset_id) != a for a in managed):
        _fail("managed asset declaration contradicts outer project assets")
    ids = {a.asset_id for a in managed} | {MANIFEST_ID}
    base = _base_project(project, ids)
    _check_base_assets(base)
    if value["base_project_sha256"] != _digest(_canonical(base.to_dict())):
        _fail("manifest contradicts preserved generic project metadata")
    return value, managed, base


def _read_objects(project, root):
    _ids_and_paths(project.assets)
    manifest, managed, base = _manifest(project, root)
    assets = {a.asset_id: a for a in managed}
    referenced, ids, result, ordered = set(), set(), [], []
    for record in manifest["objects"]:
        required = {"id", "kind", "asset_id", "relative_path", "sha256", "document_id", "spatial_reference", "dependencies"}
        if not isinstance(record, dict) or set(record) != required:
            _fail("malformed object record")
        oid, kind = record["id"], record["kind"]
        if not isinstance(oid, str) or not _ID.fullmatch(oid) or oid.casefold() in ids or kind not in KINDS:
            _fail("duplicate, conflicting or unsupported object ID/kind")
        ids.add(oid.casefold())
        expected_id = "bl_geo_obj_" + oid
        expected_path = f"geoscience/objects/{oid}.json"
        if record["asset_id"] != expected_id or record["relative_path"] != expected_path or expected_id not in assets:
            _fail("object declaration uses conflicting asset ID/path")
        object_asset = assets[expected_id]
        raw = package._read_file(root / expected_path, MAX_OBJECT_BYTES)
        if record["sha256"] != _digest(raw) or object_asset.sha256 != _digest(raw):
            _fail("object payload checksum mismatch")
        if object_asset != _asset(expected_id, expected_path, raw,
                source=f"Canonical typed {kind} object; collection ID {oid}"):
            _fail("object asset metadata/path contradicts typed declaration")
        data = _decode(raw)
        if not isinstance(record["dependencies"], list):
            _fail("object dependencies must be explicit registered IDs")
        dependencies = []
        for aid in record["dependencies"]:
            if not isinstance(aid, str) or aid not in assets or aid in referenced or aid == expected_id:
                _fail("duplicate or unregistered object dependency")
            dependencies.append(assets[aid]); referenced.add(aid)
        if kind == "analysis_archive":
            expected_files = {f"geoscience/analysis/{oid}/{name}" for name in ("analysis.json", "samples.csv", "manifest.json")}
            if {a.relative_path for a in dependencies} != expected_files:
                _fail("analysis archive dependency file inventory differs")
            value = AnalysisArchive.from_files({Path(a.relative_path).name: package._read_file(root / a.relative_path, MAX_OBJECT_BYTES)
                                               for a in dependencies})
            expected_ids = []
            for index, (name, payload) in enumerate(sorted(value.files.items())):
                aid = f"bl_geo_analysis_{oid}_{index}"
                expected_ids.append(aid)
                expected_asset = _asset(aid, f"geoscience/analysis/{oid}/{name}", payload,
                    media_type="text/csv" if name.endswith(".csv") else "application/json",
                    source=f"Inert exact exported analysis file {name}; no live engine state")
                if assets.get(aid) != expected_asset:
                    _fail("analysis original file identity/metadata differs")
            if record["dependencies"] != expected_ids:
                _fail("analysis dependency ordering/IDs differ")
        else:
            value = _types()[kind].from_dict(data)
        item, actual, canonical = _validated(ProjectObject(kind, oid, value))
        if canonical != raw:
            _fail("typed object canonical data differ after validation")
        spatial = _spatial(kind, actual); _check_spatial(project, spatial)
        if record["spatial_reference"] != spatial or record["document_id"] != actual.get("id", actual.get("asset_id")):
            _fail("object manifest identity/spatial metadata contradicts typed data")
        if kind == "geology":
            expected_dependencies = []
            for index, dependency in enumerate(actual["assets"]):
                aid = f"bl_geo_dep_{oid}_{index}"
                expected_dependencies.append(aid)
                if aid not in assets:
                    _fail("geology asset is not explicitly registered")
                a = assets[aid]
                if (a.relative_path, a.sha256, a.media_type, a.license) != (
                        dependency["relative_path"], dependency["sha256"], dependency["media_type"], dependency["license"]):
                    _fail("geology dependency metadata contradicts original reference")
                if _digest(package._read_file(root / a.relative_path, MAX_OBJECT_BYTES)) != a.sha256:
                    _fail("geology dependency bytes differ")
                if a.source != f"Exact source dependency {dependency['id']} of geology object {oid}":
                    _fail("geology source dependency identity differs")
            if record["dependencies"] != expected_dependencies:
                _fail("geology dependency inventory differs")
        elif kind != "analysis_archive" and dependencies:
            _fail("self-contained typed object cannot declare extra dependencies")
        referenced.add(expected_id)
        ordered.extend([expected_id, *record["dependencies"]])
        result.append(item)
    if referenced != set(assets):
        _fail("unreferenced or missing managed object assets")
    if [a.asset_id for a in managed] != ordered:
        _fail("managed asset ordering contradicts canonical object ordering")
    if list(project.assets) != [*base.assets, *managed, next(a for a in project.assets if a.asset_id == MANIFEST_ID)]:
        _fail("outer asset ordering contradicts preserved base/managed collections")
    return tuple(result), manifest, base


def save_geoscience_project(project, objects, output, *, asset_root=None,
                            object_asset_roots=None, view_state=None):
    """Append exact validated typed object assets to a preserved generic project.

    Generic assets resolve at asset_root. A geology object's original referenced
    files may use object_asset_roots[object_id]; paths inside them never change.
    Previously generated collections are first validated, then replaced explicitly.
    """
    project, _, _ = package._project(project)
    if not isinstance(objects, (list, tuple)) or not 1 <= len(objects) <= MAX_OBJECTS:
        _fail("one to 64 explicit typed ProjectObjects required")
    if object_asset_roots is None:
        object_asset_roots = {}
    if not isinstance(object_asset_roots, dict):
        _fail("object_asset_roots must map explicit collection IDs to roots")
    roots = dict(object_asset_roots)
    for item in objects:
        if (type(item) is not ProjectObject or item.kind not in KINDS or
                not isinstance(item.object_id, str) or not _ID.fullmatch(item.object_id)):
            _fail("typed objects with bounded explicit kind/collection IDs required")
    ids = [item.object_id.casefold() for item in objects]
    if len(ids) != len(set(ids)):
        _fail("collection IDs must be globally unique, including case folding")
    if set(roots) - {item.object_id for item in objects if item.kind == "geology"}:
        _fail("dependency roots may name only included geology objects")
    source_root = package._path_no_links(asset_root, directory=True) if asset_root is not None else None
    if any(a.asset_id == MANIFEST_ID for a in project.assets):
        if source_root is None:
            _fail("re-saving an existing collection requires its restored asset_root")
        _, _, project = _read_objects(project, source_root)
    _check_base_assets(project)
    if len(project.assets) + len(objects) + 1 > 1000:
        _fail("base assets plus object/manifest registrations exceed 1,000 assets")
    payloads, identities, records, managed = {}, {}, [], []
    payload_bytes = 0
    def reserve(relative, size):
        if relative not in payloads and payload_bytes + size > package.MAX_TOTAL_BYTES:
            _fail("combined source assets exceed 128 MiB decoded budget before next capture")
    def put(relative, raw):
        nonlocal payload_bytes
        reserve(relative, len(raw))
        if relative in payloads and payloads[relative] != raw:
            _fail("conflicting source bytes at one relative path")
        if relative not in payloads:
            payload_bytes += len(raw)
        payloads[relative] = raw
    def capture(path, expected_sha, relative):
        path = package._path_no_links(path)
        # Fail before reading the next payload when its regular-file size is
        # already known to exceed the remaining aggregate budget. _read_file
        # still performs its stronger regular/identity checks and bounded read.
        try:
            reserve(relative, path.stat().st_size)
        except OSError as error:
            raise ProjectValidationError("geoscience project: source unavailable before capture") from error
        raw = identities.get(path)
        if raw is None:
            raw = package._read_file(path, min(MAX_OBJECT_BYTES, package.MAX_TOTAL_BYTES - payload_bytes)
                                     if relative not in payloads else MAX_OBJECT_BYTES)
        if _digest(raw) != expected_sha:
            _fail("registered original asset checksum differs")
        if relative in payloads:
            if payloads[relative] != raw:
                _fail("conflicting source bytes at one relative path")
            # Distinct source roots may intentionally share the same original
            # path/bytes. Keep one byte object, not one 32-MiB copy per root.
            raw = payloads[relative]
        identities[path] = raw
        return raw
    def register(asset, raw):
        if len(project.assets) + len(managed) + 2 > 1000:
            _fail("managed registrations exceed 1,000 project assets")
        put(asset.relative_path, raw)
        managed.append(asset)
    for asset in project.assets:
        if source_root is None:
            _fail("asset_root required for preserved generic source assets")
        put(asset.relative_path, capture(source_root / asset.relative_path, asset.sha256, asset.relative_path))
    for original in objects:
        # Validate one object at a time; never retain 64 canonical 32-MiB
        # clones before applying the common decoded-payload budget.
        if original.kind == "analysis_archive" and type(original.value) is AnalysisArchive:
            required = sum(len(v) for v in original.value.files.values())
            if payload_bytes + required > package.MAX_TOTAL_BYTES:
                _fail("analysis archive exceeds remaining decoded-payload budget")
        item, data, raw = _validated(original)
        oid, kind = item.object_id, item.kind
        spatial = _spatial(kind, data); _check_spatial(project, spatial)
        aid, path = "bl_geo_obj_" + oid, f"geoscience/objects/{oid}.json"
        register(_asset(aid, path, raw, source=f"Canonical typed {kind} object; collection ID {oid}"), raw)
        dependencies = []
        if kind == "geology":
            dependency_root = roots.get(oid, source_root)
            if data["assets"] and dependency_root is None:
                _fail("geology references require an explicit object dependency root")
            if dependency_root is not None:
                dependency_root = package._path_no_links(dependency_root, directory=True)
            for index, dependency in enumerate(data["assets"]):
                if len(project.assets) + len(managed) + 2 > 1000:
                    _fail("geological registrations exceed 1,000 project assets before next capture")
                payload = capture(dependency_root / dependency["relative_path"], dependency["sha256"], dependency["relative_path"])
                dep_id = f"bl_geo_dep_{oid}_{index}"
                register(_asset(dep_id, dependency["relative_path"], payload,
                    media_type=dependency["media_type"], license=dependency["license"],
                    source=f"Exact source dependency {dependency['id']} of geology object {oid}"), payload)
                dependencies.append(dep_id)
        elif kind == "analysis_archive":
            for index, (name, payload) in enumerate(sorted(item.value.files.items())):
                dep_id = f"bl_geo_analysis_{oid}_{index}"
                register(_asset(dep_id, f"geoscience/analysis/{oid}/{name}", payload,
                    media_type="text/csv" if name.endswith(".csv") else "application/json",
                    source=f"Inert exact exported analysis file {name}; no live engine state"), payload)
                dependencies.append(dep_id)
        records.append({"id": oid, "kind": kind, "asset_id": aid, "relative_path": path,
                        "sha256": _digest(raw), "document_id": data.get("id", data.get("asset_id")),
                        "spatial_reference": spatial, "dependencies": dependencies})
    value = {"schema": SCHEMA, "base_project_sha256": _digest(_canonical(project.to_dict())),
             "objects": records, "managed_assets": [asdict(a) for a in managed], "scope": _SCOPE}
    raw = _canonical(value)
    manifest_asset = _asset(MANIFEST_ID, MANIFEST_PATH, raw, source="BasinLens typed geoscience object manifest")
    put(MANIFEST_PATH, raw)
    combined = [*project.assets, *managed, manifest_asset]
    _ids_and_paths(combined)
    data = project.to_dict(); data["assets"] = [asdict(a) for a in combined]
    enriched = SubsurfaceProject.from_dict(data)
    with tempfile.TemporaryDirectory(prefix="basinlens-geoscience-assets-") as temporary:
        root = Path(temporary)
        for relative, payload in payloads.items():
            target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
        # Validate the exact generated graph before the existing package writer.
        _read_objects(enriched, root)
        for path, before in identities.items():
            if package._read_file(path, MAX_OBJECT_BYTES) != before:
                _fail("original source changed before publication")
        target = package.save_project_package(enriched, output, asset_root=root, view_state=view_state)
        owned_identity = package._identity(target.lstat())
        try:
            for path, before in identities.items():
                if package._read_file(path, MAX_OBJECT_BYTES) != before:
                    _fail("original source changed during publication")
        except Exception as error:
            # Missing/replaced/special source files are failures as well as a
            # returned byte mismatch. Delete only our unchanged new output.
            if target.exists() or target.is_symlink():
                if package._identity(target.lstat()) == owned_identity:
                    target.unlink()
                else:
                    raise ProjectValidationError("geoscience project: source verification failed and destination changed; replacement preserved") from error
            raise
        return target


def open_geoscience_project(path, output_dir):
    """Validate every registered type/reference before publishing the fresh root."""
    output = package._fresh_output(output_dir)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".geoscience-partial-", dir=output.parent))
    try:
        loaded = package.open_project_package(path, staging / "project")
        objects, manifest, _ = _read_objects(loaded.project, loaded.asset_root)
        after = package._read_file(path, package.MAX_ARCHIVE_BYTES)
        if _digest(after) != loaded.receipt["source_archive_sha256_before"]:
            _fail("source archive changed before final restored publication")
        receipt = {**loaded.receipt, "geoscience_schema": SCHEMA,
                   "typed_objects_validated": [{"id": item.object_id, "kind": item.kind,
                        "canonical_sha256": _digest(_canonical(item.value.to_dict()))} for item in objects],
                   "generic_metadata_preserved": True, "asset_bytes_preserved": True,
                   "object_to_model_mapping_performed": False, "solver_executed": False,
                   "analysis_archives_are_inert": True, "unknown_spatial_labels_preserved": True,
                   "native_gpr_writer_implemented": False, "gms_parity_established": False,
                   "source_archive_sha256_after": _digest(after)}
        package._promote_directory(loaded.root, output)
        return LoadedGeoscienceProject(loaded.project, objects, output / "assets",
                                      dict(loaded.view_state), receipt, output)
    finally:
        shutil.rmtree(staging)


def verify_geoscience_project_roundtrip(path):
    source = package._path_no_links(path)
    before = package._read_file(source, package.MAX_ARCHIVE_BYTES)
    with tempfile.TemporaryDirectory(prefix="basinlens-geoscience-roundtrip-") as temporary:
        root = Path(temporary)
        first = open_geoscience_project(source, root / "first")
        repacked = save_geoscience_project(first.project, first.objects, root / "repacked.blproj",
            asset_root=first.asset_root, view_state=first.view_state)
        second = open_geoscience_project(repacked, root / "second")
        signature = lambda loaded: [(i.kind, i.object_id, _canonical(i.value.to_dict())) for i in loaded.objects]
        if (first.project.to_dict() != second.project.to_dict() or first.view_state != second.view_state
                or signature(first) != signature(second)):
            _fail("typed objects/project/views changed during actual save/reopen round trip")
        for asset in first.project.assets:
            if package._read_file(first.asset_root / asset.relative_path, MAX_OBJECT_BYTES) != package._read_file(second.asset_root / asset.relative_path, MAX_OBJECT_BYTES):
                _fail("registered source asset bytes changed during actual round trip")
        after = package._read_file(source, package.MAX_ARCHIVE_BYTES)
        rewritten = package._read_file(repacked, package.MAX_ARCHIVE_BYTES)
        if before != after:
            _fail("original archive changed during round trip")
        return {"schema": "basinlens-geoscience-roundtrip-v1", "roundtrip_verified": True,
                "typed_objects_equal": True, "project_metadata_equal": True,
                "registered_asset_bytes_equal": True, "view_state_equal": True,
                "source_unchanged": True, "archive_bytes_equal": before == rewritten,
                "source_archive_sha256": _digest(before), "repacked_archive_sha256": _digest(rewritten),
                "object_count": len(first.objects), "solver_executed": False,
                "original_gms_comparison": "not_performed", "gms_parity_established": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    item = commands.add_parser("open"); item.add_argument("source", type=Path); item.add_argument("--output", type=Path, required=True)
    item = commands.add_parser("roundtrip"); item.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        result = open_geoscience_project(args.source, args.output).receipt if args.command == "open" else verify_geoscience_project_roundtrip(args.source)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(2, f"geoscience project failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
