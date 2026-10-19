"""Bounded conceptual vector coverages; no GMS/GPR equivalence is implied.

The native contract retains explicit local metre coordinates and noding. RFC 7946
GeoJSON is accepted only as WGS 84 longitude/latitude degrees; no CRS transform is
performed. Polygon geometry is planar and strictly simple, including hole rules.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

SCHEMA = "basinlens-feature-coverage-v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 5000
MAX_OBJECTS = 1000
MAX_RING = 256
MAX_TOPOLOGY_WORK = 2_000_000
KINDS = ("nodes", "points", "arcs", "polygons")


class FeatureError(ValueError):
    """Invalid, unsupported or over-budget feature input."""


def _canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise FeatureError("Input must be finite JSON data") from exc


def _keys(value: Any, keys: set[str], where: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise FeatureError(f"{where}: expected exactly {sorted(keys)}")
    return value


def _text(value: Any, where: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise FeatureError(f"{where}: nonblank literal string of at most {limit} characters required")
    if any(ord(ch) < 32 for ch in value):
        raise FeatureError(f"{where}: control characters are refused")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FeatureError(f"{where}: finite numeric coordinate required")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise FeatureError(f"{where}: finite numeric coordinate required") from exc
    if not math.isfinite(result) or abs(result) > 1e9:
        raise FeatureError(f"{where}: finite coordinate within +/-1e9 required")
    return result


def _attributes(value: Any, where: str, depth: int = 0) -> None:
    if depth > 8:
        raise FeatureError(f"{where}: JSON nesting exceeds eight levels")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and len(value) > 4096:
            raise FeatureError(f"{where}: attribute string exceeds 4096 characters")
        return
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise FeatureError(f"{where}: finite JSON attributes required")
        return
    if isinstance(value, list):
        if len(value) > 256:
            raise FeatureError(f"{where}: attribute array exceeds 256 items")
        for item in value:
            _attributes(item, where, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 128:
            raise FeatureError(f"{where}: attribute object exceeds 128 keys")
        for key, item in value.items():
            _text(key, where, 128)
            _attributes(item, where, depth + 1)
        return
    raise FeatureError(f"{where}: attributes must be literal finite JSON data")


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    # Exact floating-point planar predicate: no hidden distance tolerance.
    return _cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _intersects(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return (((ab_c > 0) != (ab_d > 0) and (cd_a > 0) != (cd_b > 0)
             and ab_c != 0 and ab_d != 0 and cd_a != 0 and cd_b != 0)
            or _on_segment(a, b, c) or _on_segment(a, b, d)
            or _on_segment(c, d, a) or _on_segment(c, d, b))


def _location(ring, point):
    """Return boundary, inside or outside using planar ray crossing."""
    inside = False
    x, y = point
    for a, b in zip(ring, ring[1:]):
        if _on_segment(a, b, point):
            return "boundary"
        if (a[1] > y) != (b[1] > y):
            intersect_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < intersect_x:
                inside = not inside
    return "inside" if inside else "outside"


def _signed_area(ring):
    # Translate first to avoid cancellation for small shapes at large eastings.
    ox, oy = ring[0]
    return sum((a[0] - ox) * (b[1] - oy) - (b[0] - ox) * (a[1] - oy)
               for a, b in zip(ring, ring[1:])) / 2


class _Work:
    def __init__(self):
        self.count = 0

    def check(self):
        self.count += 1
        if self.count > MAX_TOPOLOGY_WORK:
            raise FeatureError("Topology intersection work exceeds the bounded comparison budget")


def _simple_line(coords, where, work, *, ring=False, geographic=False):
    if any(a == b for a, b in zip(coords, coords[1:])):
        raise FeatureError(f"{where}: zero-length edge is refused")
    if geographic and any(abs(a[0] - b[0]) > 180 for a, b in zip(coords, coords[1:])):
        raise FeatureError(f"{where}: antimeridian-crossing geometry is unsupported; split explicitly")
    edges = list(zip(coords, coords[1:]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 1, len(edges)):
            c, d = edges[j]
            work.check()
            adjacent = j == i + 1 or (ring and i == 0 and j == len(edges) - 1)
            if adjacent:
                # Shared endpoint is allowed; folded overlapping adjacent edges are not.
                common = b if j == i + 1 else a
                other_a, other_b = (a, d) if j == i + 1 else (b, c)
                if _cross(other_a, common, other_b) == 0 and (
                    _on_segment(other_a, common, other_b) or _on_segment(common, other_b, other_a)
                ):
                    raise FeatureError(f"{where}: adjacent edges overlap")
            elif _intersects(a, b, c, d):
                raise FeatureError(f"{where}: self-intersection or self-touch is refused")
    if ring and _signed_area(coords) == 0:
        raise FeatureError(f"{where}: polygon ring has zero area")


def _rings_disjoint(first, second, where, work):
    for a, b in zip(first, first[1:]):
        for c, d in zip(second, second[1:]):
            work.check()
            if _intersects(a, b, c, d):
                raise FeatureError(f"{where}: rings cross or touch")


def _validate(data):
    _keys(data, {"schema", "id", "name", "coordinate_system", "provenance", *KINDS}, "coverage")
    if data["schema"] != SCHEMA:
        raise FeatureError("Unsupported feature coverage schema")
    _text(data["id"], "coverage.id", 128)
    _text(data["name"], "coverage.name")
    coordinate = _keys(data["coordinate_system"], {"units", "crs", "axis_order"}, "coordinate_system")
    _text(coordinate["crs"], "coordinate_system.crs")
    if coordinate["axis_order"] != "x,y":
        raise FeatureError("Only explicit x,y axis order is supported")
    if coordinate["units"] not in ("m", "degrees"):
        raise FeatureError("Only literal m or degrees coordinate units are supported")
    geographic = coordinate["units"] == "degrees"
    if geographic and coordinate["crs"] != "EPSG:4326":
        raise FeatureError("Degree coordinates require literal EPSG:4326; x=longitude, y=latitude")
    angular = {"EPSG:4326", "EPSG:4269", "EPSG:4258", "EPSG:4979", "OGC:CRS84", "CRS:84"}
    if not geographic and coordinate["crs"].upper() in angular:
        raise FeatureError("EPSG:4326 coordinates cannot be labelled metres")
    provenance = data["provenance"]
    if not isinstance(provenance, list) or not 1 <= len(provenance) <= 32:
        raise FeatureError("provenance requires 1..32 literal source/assumption statements")
    for item in provenance:
        _text(item, "provenance")
    for kind in KINDS:
        if not isinstance(data[kind], list) or len(data[kind]) > (MAX_NODES if kind == "nodes" else MAX_OBJECTS):
            raise FeatureError(f"{kind}: invalid list or object budget exceeded")
    if sum(len(data[kind]) for kind in KINDS[1:]) > MAX_OBJECTS:
        raise FeatureError("Combined points/arcs/polygons exceed 1000 objects")
    seen = set()
    for kind in KINDS:
        for feature in data[kind]:
            expected = {"id", "attributes", *( ("x", "y") if kind in ("nodes", "points") else ("node_ids",) if kind == "arcs" else ("shell", "holes"))}
            _keys(feature, expected, kind)
            identity = _text(feature["id"], f"{kind}.id", 128)
            if identity in seen:
                raise FeatureError(f"Duplicate global feature ID: {identity}")
            seen.add(identity)
            if not isinstance(feature["attributes"], dict):
                raise FeatureError("Feature attributes must be JSON objects")
            _attributes(feature["attributes"], f"{kind}.{identity}.attributes")
            if kind in ("nodes", "points"):
                x, y = _number(feature["x"], identity + ".x"), _number(feature["y"], identity + ".y")
                if geographic and (not -180 <= x <= 180 or not -90 <= y <= 90):
                    raise FeatureError(f"{identity}: longitude/latitude outside RFC 7946 bounds")
    nodes = {node["id"]: (node["x"], node["y"]) for node in data["nodes"]}
    work = _Work()

    def resolve(ids, where, ring=False):
        if not isinstance(ids, list) or not (4 if ring else 2) <= len(ids) <= MAX_RING:
            raise FeatureError(f"{where}: expected bounded {'closed ring of 4..256' if ring else 'line of 2..256'} node IDs")
        for identity in ids:
            _text(identity, where, 128)
            if identity not in nodes:
                raise FeatureError(f"{where}: missing node {identity}")
        if ring and ids[0] != ids[-1]:
            raise FeatureError(f"{where}: polygon rings must close by repeated node ID")
        if ring and len(set(ids[:-1])) != len(ids) - 1:
            raise FeatureError(f"{where}: repeated interior ring node")
        coords = [nodes[identity] for identity in ids]
        _simple_line(coords, where, work, ring=ring, geographic=geographic)
        return coords

    for arc in data["arcs"]:
        ids = arc["node_ids"]
        closed = isinstance(ids, list) and len(ids) > 2 and ids[0] == ids[-1]
        resolve(ids, arc["id"], ring=closed)
    for polygon in data["polygons"]:
        shell = resolve(polygon["shell"], polygon["id"] + ".shell", ring=True)
        if not isinstance(polygon["holes"], list) or len(polygon["holes"]) > 16:
            raise FeatureError("Polygon holes must be a list of at most 16 rings")
        holes = [resolve(ids, polygon["id"] + ".hole", ring=True) for ids in polygon["holes"]]
        for i, hole in enumerate(holes):
            _rings_disjoint(shell, hole, polygon["id"], work)
            if _location(shell, hole[0]) != "inside":
                raise FeatureError(f"{polygon['id']}: hole must lie strictly within shell")
            for previous in holes[:i]:
                _rings_disjoint(previous, hole, polygon["id"], work)
                if _location(previous, hole[0]) != "outside" or _location(hole, previous[0]) != "outside":
                    raise FeatureError(f"{polygon['id']}: holes overlap or nest")
    if len(_canonical(data)) > MAX_BYTES:
        raise FeatureError("Feature coverage exceeds 8 MiB serialized budget")


@dataclass(frozen=True)
class FeatureCoverage:
    """Immutable validated conceptual objects with literal metadata."""
    _json: str

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureCoverage":
        _validate(data)
        return cls(_canonical(data).decode("utf-8"))

    def to_dict(self) -> dict:
        if not isinstance(self._json, str) or len(self._json.encode("utf-8")) > MAX_BYTES:
            raise FeatureError("Invalid direct FeatureCoverage construction or serialized budget exceeded")
        try:
            result = json.loads(self._json)
        except (ValueError, TypeError, RecursionError) as exc:
            raise FeatureError("Invalid direct FeatureCoverage construction") from exc
        _validate(result)
        return result


def _parse(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise FeatureError("Input exceeds 8 MiB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise FeatureError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(FeatureError("Nonfinite JSON constant: " + value)))
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, FeatureError):
            raise
        raise FeatureError("Invalid bounded UTF-8 JSON input") from exc


def _assert_no_symlinks(path):
    absolute = Path(path).absolute()
    for part in [*reversed(absolute.parents), absolute]:
        try:
            if stat.S_ISLNK(part.lstat().st_mode):
                raise FeatureError("Symlink inputs/output ancestors are refused")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise FeatureError(f"Cannot inspect feature path: {exc}") from exc
    return absolute


def _read(path) -> bytes:
    path = _assert_no_symlinks(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise FeatureError("Input must be a regular file, not a link/device/pipe")
        if before.st_size > MAX_BYTES:
            raise FeatureError("Input exceeds 8 MiB")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise FeatureError("Input changed into a non-regular file")
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise FeatureError("Input identity changed while opening")
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise FeatureError("Input exceeded its budget or changed while reading")
        return raw
    except OSError as exc:
        raise FeatureError(f"Cannot read feature input: {exc}") from exc


def _write_fresh(path, raw):
    destination = _assert_no_symlinks(path)
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlinks(destination.parent)
        fd, temporary = tempfile.mkstemp(prefix=".features-", dir=destination.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard linking is atomic and refuses any existing target.
        os.link(temporary, destination, follow_symlinks=False)
        return destination
    except OSError as exc:
        raise FeatureError(f"Cannot write fresh atomic feature output: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass



def load_coverage(path) -> FeatureCoverage:
    return FeatureCoverage.from_dict(_parse(_read(path)))


def save_coverage(coverage: FeatureCoverage, path) -> Path:
    return _write_fresh(path, _canonical(coverage.to_dict()))


def verify_coverage_roundtrip(path) -> dict:
    raw = _read(path)
    first = FeatureCoverage.from_dict(_parse(raw))
    second = FeatureCoverage.from_dict(_parse(_canonical(first.to_dict())))
    if first.to_dict() != second.to_dict():
        raise FeatureError("Coverage semantic roundtrip failed")
    return {"schema": "basinlens-feature-roundtrip-v1", "source_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_sha256": hashlib.sha256(_canonical(first.to_dict())).hexdigest(),
            "semantic_roundtrip": True, "original_gms_comparison": "NOT_OBSERVED",
            "counts": {kind: len(first.to_dict()[kind]) for kind in KINDS}}


def select_features(coverage, *, ids=None, kind=None, attribute=None):
    """Return copied feature rows; attribute is an exact (key, literal JSON value)."""
    data = coverage.to_dict()
    if kind is not None and kind not in KINDS:
        raise FeatureError("Unknown feature kind")
    available = {item["id"] for group in KINDS for item in data[group]}
    if ids is not None and (not isinstance(ids, (list, tuple, set)) or any(not isinstance(identity, str) for identity in ids)):
        raise FeatureError("ids selection must be a sequence of literal feature IDs")
    requested = available if ids is None else set(ids)
    if requested - available:
        raise FeatureError("Selection contains unknown IDs: " + str(sorted(requested - available)))
    if attribute is not None and (not isinstance(attribute, (tuple, list)) or len(attribute) != 2):
        raise FeatureError("attribute filter requires (key, exact value)")
    if attribute is not None:
        _text(attribute[0], "attribute filter key", 128)
        _attributes(attribute[1], "attribute filter value")
    return [{"kind": group, **item} for group in KINDS if kind in (None, group)
            for item in data[group] if item["id"] in requested
            and (attribute is None or (attribute[0] in item["attributes"] and item["attributes"][attribute[0]] == attribute[1]))]


def _record_edit(data, before, operation):
    source_hash = hashlib.sha256(_canonical(before)).hexdigest()
    data["provenance"].append(f"BasinLens conceptual edit: {operation}; source_sha256={source_hash}; authored change, not a measured observation")


def add_feature(coverage, kind, feature):
    data = coverage.to_dict()
    if kind not in KINDS:
        raise FeatureError("Unknown feature kind")
    before = json.loads(_canonical(data))
    data[kind].append(feature)
    _record_edit(data, before, "add " + str(kind) + " " + str(feature.get("id", "unknown") if isinstance(feature, dict) else "invalid"))
    return FeatureCoverage.from_dict(data)


def move_node(coverage, identity, x, y):
    data = coverage.to_dict()
    for node in data["nodes"]:
        if node["id"] == identity:
            before = json.loads(_canonical(data))
            node.update(x=x, y=y)
            _record_edit(data, before, "move node " + str(identity))
            return FeatureCoverage.from_dict(data)
    raise FeatureError("Unknown node ID: " + str(identity))


def move_point(coverage, identity, x, y):
    data = coverage.to_dict()
    for point in data["points"]:
        if point["id"] == identity:
            before = json.loads(_canonical(data))
            point.update(x=x, y=y)
            _record_edit(data, before, "move independent point " + str(identity))
            return FeatureCoverage.from_dict(data)
    raise FeatureError("Unknown independent point ID: " + str(identity))


def delete_feature(coverage, identity, *, cascade=False):
    data = coverage.to_dict()
    before = json.loads(_canonical(data))
    if not isinstance(cascade, bool):
        raise FeatureError("cascade must be an explicit boolean")
    kind = next((group for group in KINDS if any(item["id"] == identity for item in data[group])), None)
    if kind is None:
        raise FeatureError("Unknown feature ID: " + str(identity))
    if kind == "nodes":
        arcs = [item["id"] for item in data["arcs"] if identity in item["node_ids"]]
        polygons = [item["id"] for item in data["polygons"] if any(identity in ring for ring in [item["shell"], *item["holes"]])]
        if (arcs or polygons) and not cascade:
            raise FeatureError("Referenced node deletion refused; dependent arcs/polygons: " + str(arcs + polygons))
        if cascade:
            data["arcs"] = [item for item in data["arcs"] if item["id"] not in arcs]
            data["polygons"] = [item for item in data["polygons"] if item["id"] not in polygons]
    data[kind] = [item for item in data[kind] if item["id"] != identity]
    _record_edit(data, before, "delete " + str(kind) + " " + str(identity) + "; cascade=" + str(cascade))
    return FeatureCoverage.from_dict(data)


def _polygon(data, identity):
    polygon = next((item for item in data["polygons"] if item["id"] == identity), None)
    if polygon is None:
        raise FeatureError("Unknown polygon ID: " + str(identity))
    nodes = {node["id"]: (node["x"], node["y"]) for node in data["nodes"]}
    return [[nodes[node] for node in ring] for ring in [polygon["shell"], *polygon["holes"]]]


def contains_point(coverage, polygon_id, x, y, *, edge_policy="include"):
    """Planar containment; include/exclude applies to shell AND hole boundaries."""
    if edge_policy not in ("include", "exclude"):
        raise FeatureError("edge_policy must be include or exclude")
    point = (_number(x, "x"), _number(y, "y"))
    data = coverage.to_dict()
    rings = _polygon(data, polygon_id)
    outer = _location(rings[0], point)
    locations = [_location(ring, point) for ring in rings[1:]]
    if outer == "boundary" or "boundary" in locations:
        return edge_policy == "include"
    return outer == "inside" and all(location == "outside" for location in locations)


def prepare_polygon_xy(rings):
    """Validate explicit planar coordinate rings, then apply the same containment policy.

    Intended for trusted mesh integration. No tolerance, projection or CRS inference.
    """
    nodes, node_rings = [], []
    if not isinstance(rings, (list, tuple)) or not rings:
        raise FeatureError("At least one closed coordinate ring required")
    for r, ring in enumerate(rings):
        ids = []
        if not isinstance(ring, (list, tuple)) or len(ring) < 4 or ring[0] != ring[-1]:
            raise FeatureError("Coordinate rings require explicit repeated closing coordinate")
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise FeatureError("Coordinate rings require XY pairs")
            _number(point[0], "ring x")
            _number(point[1], "ring y")
        for i, point in enumerate(ring[:-1]):
            identity = f"r{r}n{i}"
            nodes.append({"id": identity, "x": point[0], "y": point[1], "attributes": {}})
            ids.append(identity)
        ids.append(ids[0])
        node_rings.append(ids)
    synthetic = FeatureCoverage.from_dict({"schema": SCHEMA, "id": "predicate", "name": "Explicit planar predicate", "coordinate_system": {"units": "m", "crs": "unknown", "axis_order": "x,y"}, "provenance": ["Caller-supplied planar rings; units must be matched by caller"], "nodes": nodes, "points": [], "arcs": [], "polygons": [{"id": "region", "shell": node_rings[0], "holes": node_rings[1:], "attributes": {}}]})
    return prepare_polygon(synthetic, "region")


@dataclass(frozen=True, init=False)
class PreparedPolygon:
    """Validated immutable planar rings for repeated bounded mesh queries."""
    rings: tuple

    def __init__(self, *args, **kwargs):
        raise FeatureError("Use prepare_polygon or prepare_polygon_xy to validate immutable rings")

    def contains(self, x, y, *, edge_policy="include"):
        if edge_policy not in ("include", "exclude"):
            raise FeatureError("edge_policy must be include or exclude")
        point = (_number(x, "x"), _number(y, "y"))
        locations = [_location(ring, point) for ring in self.rings]
        if "boundary" in locations:
            return edge_policy == "include"
        return locations[0] == "inside" and all(location == "outside" for location in locations[1:])


def prepare_polygon(coverage, polygon_id):
    """Validate coverage once and capture immutable rings for repeated queries."""
    rings = _polygon(coverage.to_dict(), polygon_id)
    prepared = object.__new__(PreparedPolygon)
    object.__setattr__(prepared, "rings", tuple(tuple(tuple(point) for point in ring) for ring in rings))
    return prepared


def polygon_contains_xy(rings, x, y, *, edge_policy="include"):
    return prepare_polygon_xy(rings).contains(x, y, edge_policy=edge_policy)


def _require_metres(data):
    if data["coordinate_system"]["units"] != "m":
        raise FeatureError("Metric geometry requires metre coordinates; no geographic projection is inferred")


def feature_metrics(coverage, identity):
    data = coverage.to_dict()
    _require_metres(data)
    nodes = {node["id"]: (node["x"], node["y"]) for node in data["nodes"]}
    for arc in data["arcs"]:
        if arc["id"] == identity:
            coords = [nodes[node] for node in arc["node_ids"]]
            return {"length_m": sum(math.dist(a, b) for a, b in zip(coords, coords[1:]))}
    rings = _polygon(data, identity)
    return {"area_m2": abs(_signed_area(rings[0])) - sum(abs(_signed_area(ring)) for ring in rings[1:]),
            "perimeter_m": sum(math.dist(a, b) for ring in rings for a, b in zip(ring, ring[1:]))}


def feature_table(coverage):
    data = coverage.to_dict()
    rows = []
    for row in select_features(coverage):
        if row["kind"] in ("nodes", "points"):
            count = 1
        elif row["kind"] == "arcs":
            count = len(row["node_ids"])
        else:
            count = sum(len(ring) - 1 for ring in [row["shell"], *row["holes"]])
        rows.append({"id": row["id"], "kind": row["kind"], "vertices": count,
                     "attributes": row["attributes"], "coordinate_units": data["coordinate_system"]["units"]})
    return rows


def grid_extent(coverage, *, padding_m=0):
    """Axis-aligned local grid frame; all nodes and independent points participate."""
    data = coverage.to_dict()
    _require_metres(data)
    padding = _number(padding_m, "padding_m")
    if padding < 0:
        raise FeatureError("Grid-frame padding must be non-negative")
    coords = [(node["x"], node["y"]) for kind in ("nodes", "points") for node in data[kind]]
    if not coords:
        raise FeatureError("An empty coverage has no grid extent")
    xmin, xmax = min(x for x, _ in coords) - padding, max(x for x, _ in coords) + padding
    ymin, ymax = min(y for _, y in coords) - padding, max(y for _, y in coords) + padding
    if xmax <= xmin or ymax <= ymin:
        raise FeatureError("Grid extent must have positive area; provide explicit padding for degenerate coverage")
    return {"x_origin_m": xmin, "y_origin_m": ymin, "width_m": xmax - xmin,
            "height_m": ymax - ymin, "rotation_degrees": 0, "row_axis": "south_to_north",
            "crs": data["coordinate_system"]["crs"], "source": "all coverage nodes and independent points"}


def _centroid(rings):
    weighted_x = weighted_y = total = 0.
    for i, ring in enumerate(rings):
        ox, oy = ring[0]
        signed = _signed_area(ring)
        cx = sum(((a[0]-ox)+(b[0]-ox))*((a[0]-ox)*(b[1]-oy)-(b[0]-ox)*(a[1]-oy)) for a,b in zip(ring,ring[1:]))/(6*signed)+ox
        cy = sum(((a[1]-oy)+(b[1]-oy))*((a[0]-ox)*(b[1]-oy)-(b[0]-ox)*(a[1]-oy)) for a,b in zip(ring,ring[1:]))/(6*signed)+oy
        weight = abs(signed) * (1 if i == 0 else -1)
        total += weight
        weighted_x += cx * weight
        weighted_y += cy * weight
    return weighted_x/total, weighted_y/total


def to_scatter_points(coverage, *, value_attribute, sampling="points"):
    """Explicit object sampling, preserving duplicated vertices as separate samples."""
    data = coverage.to_dict()
    _text(value_attribute, "value_attribute", 128)
    if sampling not in ("points", "nodes", "arc_vertices", "arc_endpoints", "polygon_centroids"):
        raise FeatureError("Unsupported explicit vector sampling policy")
    nodes = {node["id"]: (node["x"], node["y"]) for node in data["nodes"]}
    group = "arcs" if sampling.startswith("arc_") else "polygons" if sampling == "polygon_centroids" else sampling
    samples = []
    for item in data[group]:
        if value_attribute not in item["attributes"]:
            raise FeatureError(f"{item['id']}: missing requested scatter attribute {value_attribute}")
        value = _number(item["attributes"][value_attribute], "scatter value")
        if group in ("nodes", "points"):
            coords = [(item["x"], item["y"])]
        elif group == "arcs":
            ids = item["node_ids"] if sampling == "arc_vertices" else [item["node_ids"][0], item["node_ids"][-1]]
            coords = [nodes[identity] for identity in ids]
        else:
            _require_metres(data)
            coords = [_centroid(_polygon(data, item["id"]))]
        for index, (x, y) in enumerate(coords):
            samples.append({"id": f"{item['id']}:{index}", "source_feature_id": item["id"],
                            "x": x, "y": y, "value": value})
    return {"schema": "basinlens-vector-samples-v1", "coordinate_system": data["coordinate_system"],
            "value_attribute": value_attribute, "sampling": sampling,
            "value_units": "unknown; caller must declare before interpolation/model assignment",
            "centroid_may_lie_outside_region": sampling == "polygon_centroids", "samples": samples,
            "provenance": data["provenance"], "interpolation_performed": False}


def _geo_features(data):
    nodes = {node["id"]: [node["x"], node["y"]] for node in data["nodes"]}
    features = []
    for kind in ("points", "arcs", "polygons"):
        for item in data[kind]:
            if kind == "points":
                geometry = {"type": "Point", "coordinates": [item["x"], item["y"]]}
            elif kind == "arcs":
                geometry = {"type": "LineString", "coordinates": [nodes[identity] for identity in item["node_ids"]]}
            else:
                rings = []
                for i, ids in enumerate([item["shell"], *item["holes"]]):
                    ring = [nodes[identity] for identity in ids]
                    if (_signed_area(ring) > 0) != (i == 0):
                        ring = ring[::-1]
                    rings.append(ring)
                geometry = {"type": "Polygon", "coordinates": rings}
            features.append({"type": "Feature", "id": item["id"], "properties": item["attributes"],
                             "geometry": geometry})
    return features


def export_geojson(coverage, path):
    data = coverage.to_dict()
    if data["coordinate_system"] != {"units": "degrees", "crs": "EPSG:4326", "axis_order": "x,y"}:
        raise FeatureError("RFC 7946 export requires explicit EPSG:4326 longitude/latitude degrees; projected/local metres refused")
    document = {"type": "FeatureCollection", "features": _geo_features(data),
                "basinlens_coverage": data,
                "basinlens_coverage_sha256": hashlib.sha256(_canonical(data)).hexdigest()}
    raw = _canonical(document)
    if len(raw) > MAX_BYTES:
        raise FeatureError("GeoJSON exceeds 8 MiB budget")
    return _write_fresh(path, raw)


def import_geojson(path, *, coverage_id=None, name=None, provenance=None):
    document = _parse(_read(path))
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection" or "crs" in document:
        raise FeatureError("Only RFC 7946 FeatureCollection without legacy crs is supported")
    allowed = {"type", "features", "basinlens_coverage", "basinlens_coverage_sha256"}
    if set(document) - allowed:
        raise FeatureError("Unsupported top-level GeoJSON members; not silently discarded")
    if "basinlens_coverage" in document or "basinlens_coverage_sha256" in document:
        _keys(document, allowed, "embedded GeoJSON")
        coverage = FeatureCoverage.from_dict(document["basinlens_coverage"])
        data = coverage.to_dict()
        if data["coordinate_system"] != {"units": "degrees", "crs": "EPSG:4326", "axis_order": "x,y"}:
            raise FeatureError("Embedded GeoJSON coverage must use EPSG:4326 degrees")
        if document["basinlens_coverage_sha256"] != hashlib.sha256(_canonical(data)).hexdigest() or _canonical(document["features"]) != _canonical(_geo_features(data)):
            raise FeatureError("Embedded coverage hash or visible GeoJSON geometry/attributes disagree")
        if coverage_id is not None or name is not None or provenance is not None:
            raise FeatureError("Embedded metadata is retained exactly; import overrides are refused")
        return coverage
    _keys(document, {"type", "features"}, "GeoJSON")
    features = document["features"]
    if not isinstance(features, list) or len(features) > MAX_OBJECTS:
        raise FeatureError("GeoJSON feature budget exceeded")
    data = {"schema": SCHEMA, "id": coverage_id, "name": name,
            "coordinate_system": {"units": "degrees", "crs": "EPSG:4326", "axis_order": "x,y"},
            "provenance": provenance, "nodes": [], "points": [], "arcs": [], "polygons": []}
    occupied = set()
    for i, feature in enumerate(features):
        if not isinstance(feature, dict) or set(feature) not in ({"type", "geometry", "properties"}, {"type", "id", "geometry", "properties"}):
            raise FeatureError("Only geometry/properties/optional literal id GeoJSON Features supported")
        if feature["type"] != "Feature":
            raise FeatureError("GeoJSON entry must be Feature")
        identity = feature.get("id", f"geo-feature-{i}")
        _text(identity, "GeoJSON feature ID", 128)
        if identity in occupied:
            raise FeatureError("Duplicate GeoJSON feature ID")
        occupied.add(identity)
    next_node = 0
    def position(point):
        if not isinstance(point, list) or len(point) != 2:
            raise FeatureError("Only two-dimensional XY GeoJSON positions supported; Z is not discarded")
        x, y = _number(point[0], "GeoJSON longitude"), _number(point[1], "GeoJSON latitude")
        if not -180 <= x <= 180 or not -90 <= y <= 90:
            raise FeatureError("GeoJSON longitude/latitude outside RFC 7946 bounds")
        return point
    def node(point):
        nonlocal next_node
        position(point)
        while f"geo-node-{next_node}" in occupied:
            next_node += 1
        identity = f"geo-node-{next_node}"
        next_node += 1
        occupied.add(identity)
        data["nodes"].append({"id": identity, "x": point[0], "y": point[1], "attributes": {}})
        return identity
    for i, feature in enumerate(features):
        identity, attributes = feature.get("id", f"geo-feature-{i}"), feature["properties"]
        geometry = _keys(feature["geometry"], {"type", "coordinates"}, "GeoJSON geometry")
        coords = geometry["coordinates"]
        if geometry["type"] == "Point":
            if not isinstance(coords, list) or len(coords) != 2:
                raise FeatureError("Point requires exactly XY; Z is not discarded")
            data["points"].append({"id": identity, "x": coords[0], "y": coords[1], "attributes": attributes})
        elif geometry["type"] == "LineString":
            if not isinstance(coords, list) or not 2 <= len(coords) <= MAX_RING:
                raise FeatureError("LineString requires 2..256 coordinate positions")
            ids = [node(point) for point in coords]
            if len(coords) > 2 and coords[0] == coords[-1]:
                ids[-1] = ids[0]
                data["nodes"].pop()
            data["arcs"].append({"id": identity, "node_ids": ids, "attributes": attributes})
        elif geometry["type"] == "Polygon":
            if not isinstance(coords, list) or not 1 <= len(coords) <= 17:
                raise FeatureError("Polygon requires a shell and at most 16 holes")
            rings = []
            for ring in coords:
                if not isinstance(ring, list) or not 4 <= len(ring) <= MAX_RING or ring[0] != ring[-1]:
                    raise FeatureError("GeoJSON polygon ring must explicitly close")
                for point in ring:
                    position(point)
                ids = [node(point) for point in ring[:-1]]
                ids.append(ids[0])
                rings.append(ids)
            data["polygons"].append({"id": identity, "shell": rings[0], "holes": rings[1:], "attributes": attributes})
        else:
            raise FeatureError("Only Point, LineString and simple Polygon GeoJSON geometries supported")
    return FeatureCoverage.from_dict(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check"); check.add_argument("source")
    export = sub.add_parser("export"); export.add_argument("source"); export.add_argument("output"); export.add_argument("--geojson", action="store_true")
    move = sub.add_parser("move-node"); move.add_argument("source"); move.add_argument("id"); move.add_argument("x", type=float); move.add_argument("y", type=float); move.add_argument("output")
    delete = sub.add_parser("delete"); delete.add_argument("source"); delete.add_argument("id"); delete.add_argument("output"); delete.add_argument("--cascade", action="store_true")
    select = sub.add_parser("select"); select.add_argument("source"); select.add_argument("--kind", choices=KINDS); select.add_argument("--id", action="append")
    args = parser.parse_args(argv)
    try:
        coverage = load_coverage(args.source)
        if args.command == "check":
            print(json.dumps(verify_coverage_roundtrip(args.source), sort_keys=True))
        elif args.command == "select":
            print(json.dumps(select_features(coverage, ids=args.id, kind=args.kind), sort_keys=True))
        elif args.command == "export":
            print(export_geojson(coverage, args.output) if args.geojson else save_coverage(coverage, args.output))
        elif args.command == "move-node":
            print(save_coverage(move_node(coverage, args.id, args.x, args.y), args.output))
        else:
            print(save_coverage(delete_feature(coverage, args.id, cascade=args.cascade), args.output))
    except FeatureError as exc:
        parser.exit(2, f"feature error: {exc}\n")


if __name__ == "__main__":
    main()
