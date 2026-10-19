"""Bounded scalar scatter data, deterministic interpolation and explicit dataset math.

Own JSON/CSV formats only. No GMS, kriging, uncertainty or physical-model parity.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

SCHEMA = "basinlens-scatter-v1"
QUERY_SCHEMA = "basinlens-scatter-query-v1"
MAX_POINTS = 20_000
MAX_QUERIES = 20_000
MAX_PAIRS = 2_000_000
MAX_TRIANGLES = 1024
MAX_BYTES = 16 * 1024 * 1024
CSV_PREFIX = "# " + SCHEMA + " "


class ScatterError(ValueError):
    """Invalid, unsupported or over-budget scatter operation."""


def _text(value: Any, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > limit:
        raise ScatterError(f"{label}: expected nonempty trimmed string, at most {limit} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ScatterError(f"{label}: control characters are forbidden")
    return value


def _number(value: Any, label: str, bound: float = 1e100) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScatterError(f"{label}: expected finite numeric value")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ScatterError(f"{label}: invalid number") from exc
    if not math.isfinite(result) or abs(result) > bound:
        raise ScatterError(f"{label}: value must be finite and within +/-{bound:g}")
    return result


def _keys(value: Any, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ScatterError(f"{label}: expected exact keys {sorted(expected)}")
    return value


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ScatterError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda token: (_ for _ in ()).throw(ScatterError(f"nonfinite JSON: {token}")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ScatterError(f"invalid UTF-8 JSON: {exc}") from exc


def _no_symlinks(path: Path) -> None:
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ScatterError(f"symlink paths are forbidden: {entry}")


def _read(path: Path) -> bytes:
    path = Path(path).absolute()
    _no_symlinks(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise ScatterError("input must be a regular file within the 16 MiB read budget")
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if len(raw) > MAX_BYTES or len(raw) != before.st_size or identity(before) != identity(after):
                raise ScatterError("input changed while reading or exceeded read budget")
            return raw
    except OSError as exc:
        raise ScatterError(f"cannot read input: {exc}") from exc


def _write(path: Path, raw: bytes) -> Path:
    path = Path(path).absolute()
    if len(raw) > MAX_BYTES:
        raise ScatterError("output exceeds 16 MiB budget")
    _no_symlinks(path)
    if not path.parent.is_dir():
        raise ScatterError("output parent must already exist")
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".scatter-", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staged, path)  # Atomic publication, refuses any existing destination.
        return path
    except OSError as exc:
        raise ScatterError(f"cannot publish fresh output: {exc}") from exc
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _validate(raw: Any) -> dict:
    keys = {"schema", "id", "dimension", "coordinate_unit", "crs", "vertical_datum", "vertical_axis", "quantity", "value_unit", "basis", "provenance", "duplicate_coordinate_policy", "points"}
    obj = _keys(raw, keys, "dataset")
    if obj["schema"] != SCHEMA or type(obj["dimension"]) is not int or obj["dimension"] not in (2, 3):
        raise ScatterError("unsupported dataset schema or dimension (2 or 3 required)")
    dim = obj["dimension"]
    if obj["coordinate_unit"] != "m" or obj["duplicate_coordinate_policy"] != "reject":
        raise ScatterError("literal metre coordinates and duplicate_coordinate_policy='reject' required")
    expected_axis = "positive_up" if dim == 3 else "not_applicable"
    if obj["vertical_axis"] != expected_axis:
        raise ScatterError(f"vertical_axis must be {expected_axis}")
    if obj["basis"] not in ("synthetic", "measured", "interpreted", "assumed"):
        raise ScatterError("basis must explicitly declare synthetic/measured/interpreted/assumed")
    for key in ("id", "crs", "vertical_datum", "quantity", "value_unit"):
        _text(obj[key], key, 128)
    if not isinstance(obj["provenance"], list) or not 1 <= len(obj["provenance"]) <= 32:
        raise ScatterError("provenance: expected 1..32 explicit statements")
    for item in obj["provenance"]:
        _text(item, "provenance")
    points = obj["points"]
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise ScatterError(f"points: expected 1..{MAX_POINTS} records")
    ids, coordinates, parsed = set(), set(), []
    for index, record in enumerate(points):
        p = _keys(record, {"id", "coordinates_m", "value", "missing_reason"}, f"point[{index}]")
        identity = _text(p["id"], "point id", 128)
        if identity in ids:
            raise ScatterError(f"duplicate point id: {identity}")
        ids.add(identity)
        c = p["coordinates_m"]
        if not isinstance(c, list) or len(c) != dim:
            raise ScatterError("coordinates_m: dimension mismatch")
        xyz = tuple(_number(v, "coordinate", 1e9) for v in c)
        if xyz in coordinates:
            raise ScatterError("duplicate coordinates are rejected, including missing observations")
        coordinates.add(xyz)
        if p["value"] is None:
            value, reason = None, _text(p["missing_reason"], "missing_reason")
        else:
            value, reason = _number(p["value"], "point value"), p["missing_reason"]
            if reason is not None:
                raise ScatterError("valued points require missing_reason=null")
        parsed.append({"id": identity, "coordinates_m": list(xyz), "value": value, "missing_reason": reason})
    return {**obj, "points": parsed}


@dataclass(frozen=True)
class ScatterDataset:
    """Immutable canonical representation; every public operation revalidates it."""
    _json: str

    @classmethod
    def from_dict(cls, value: dict) -> "ScatterDataset":
        raw = _canonical(_validate(value))
        if len(raw) > MAX_BYTES:
            raise ScatterError("canonical dataset exceeds 16 MiB budget")
        return cls(raw.decode("utf-8"))

    def to_dict(self) -> dict:
        if not isinstance(self._json, str) or len(self._json.encode("utf-8")) > MAX_BYTES:
            raise ScatterError("invalid or over-budget canonical dataset")
        return _validate(_json(self._json.encode("utf-8")))

    @property
    def sha256(self) -> str:
        return _digest(self.to_dict())


def load_scatter(path: str | Path) -> ScatterDataset:
    """Read own complete JSON or metadata-prefixed CSV; no implicit units."""
    path = Path(path)
    raw = _read(path)
    if path.suffix.lower() == ".json":
        return ScatterDataset.from_dict(_json(raw))
    if path.suffix.lower() != ".csv":
        raise ScatterError("input extension must be .json or .csv")
    try:
        text = raw.decode("utf-8")
        first, rest = text.split("\n", 1)
        if not first.startswith(CSV_PREFIX):
            raise ScatterError("CSV requires its self-contained versioned metadata line")
        meta = _json(first[len(CSV_PREFIX):].encode("utf-8"))
        if not isinstance(meta, dict) or "points" in meta:
            raise ScatterError("CSV metadata must be an object without points")
        dim = meta.get("dimension")
        if type(dim) is not int or dim not in (2, 3):
            raise ScatterError("CSV metadata dimension must be 2 or 3")
        expected = ["id", "x_m", "y_m"] + (["z_m"] if dim == 3 else []) + ["value", "missing_reason"]
        reader = csv.DictReader(io.StringIO(rest, newline=""), strict=True)
        if reader.fieldnames != expected:
            raise ScatterError(f"CSV header must be exactly {expected}")
        points = []
        for row in reader:
            if set(row) != set(expected) or any(v is None for v in row.values()):
                raise ScatterError("ragged CSV record")
            if len(points) >= MAX_POINTS:
                raise ScatterError("CSV point count exceeds budget")
            coords = [float(row[key]) for key in expected[1:1+dim]]
            value = None if row["value"] == "" else float(row["value"])
            reason = row["missing_reason"] or None
            points.append({"id": row["id"], "coordinates_m": coords, "value": value, "missing_reason": reason})
        return ScatterDataset.from_dict({**meta, "points": points})
    except (UnicodeError, ValueError, OverflowError, csv.Error) as exc:
        if isinstance(exc, ScatterError):
            raise
        raise ScatterError(f"invalid scatter CSV: {exc}") from exc


def save_scatter(dataset: ScatterDataset, path: str | Path) -> Path:
    obj = dataset.to_dict()
    path = Path(path)
    if path.suffix.lower() == ".json":
        return _write(path, _canonical(obj))
    if path.suffix.lower() != ".csv":
        raise ScatterError("output extension must be .json or .csv")
    meta = {k: v for k, v in obj.items() if k != "points"}
    output = io.StringIO(newline="")
    output.write(CSV_PREFIX + _canonical(meta).decode("utf-8").rstrip("\n") + "\n")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", "x_m", "y_m"] + (["z_m"] if obj["dimension"] == 3 else []) + ["value", "missing_reason"])
    for p in obj["points"]:
        writer.writerow([p["id"], *[repr(v) for v in p["coordinates_m"]], "" if p["value"] is None else repr(p["value"]), p["missing_reason"] or ""])
    return _write(path, output.getvalue().encode("utf-8"))


def verify_scatter_roundtrip(path: str | Path) -> dict:
    dataset = load_scatter(path)
    with tempfile.TemporaryDirectory(prefix="scatter-roundtrip-") as directory:
        identities = {}
        for extension in ("json", "csv"):
            target = Path(directory) / ("roundtrip." + extension)
            save_scatter(dataset, target)
            other = load_scatter(target)
            if other.to_dict() != dataset.to_dict():
                raise ScatterError(f"{extension} semantic roundtrip mismatch")
            identities[extension] = {"file_sha256": hashlib.sha256(_read(target)).hexdigest(), "dataset_sha256": other.sha256}
    return {"schema": "basinlens-scatter-roundtrip-v1", "dataset_sha256": dataset.sha256, "point_count": len(dataset.to_dict()["points"]), "formats": identities, "semantic_equal": True, "original_gms_comparison": "not_performed"}


def edit_values(dataset: ScatterDataset, edits: dict[str, float | None], *, missing_reason: str = "explicit user edit: value unavailable") -> ScatterDataset:
    obj = dataset.to_dict()
    if not isinstance(edits, dict) or not edits:
        raise ScatterError("edits must be a nonempty id-to-value mapping")
    ids = {p["id"] for p in obj["points"]}
    if set(edits) - ids:
        raise ScatterError("edit contains unknown point ids")
    for p in obj["points"]:
        if p["id"] in edits:
            p["value"] = edits[p["id"]]
            p["missing_reason"] = missing_reason if p["value"] is None else None
    obj["basis"] = "interpreted"
    obj["provenance"] = obj["provenance"] + [f"Explicit value edit of {len(edits)} points; parent dataset SHA-256 {dataset.sha256}"]
    return ScatterDataset.from_dict(obj)


def dataset_math(left: ScatterDataset, operator: str, right: ScatterDataset, *, result_id: str, result_quantity: str, result_unit: str) -> ScatterDataset:
    """Pointwise +,-,*,/ on exactly shared ID/coordinate support, never eval."""
    a, b = left.to_dict(), right.to_dict()
    if operator not in ("+", "-", "*", "/"):
        raise ScatterError("only literal +, -, *, / operators are supported")
    metadata = ("dimension", "coordinate_unit", "crs", "vertical_datum", "vertical_axis")
    if any(a[k] != b[k] for k in metadata):
        raise ScatterError("dataset coordinate contracts differ; no automatic transformation")
    support = lambda d: {p["id"]: p["coordinates_m"] for p in d["points"]}
    if support(a) != support(b):
        raise ScatterError("dataset point identity/coordinate support differs")
    if operator in ("+", "-"):
        expected = (a["quantity"], a["value_unit"])
        if expected != (b["quantity"], b["value_unit"]):
            raise ScatterError("addition/subtraction require identical quantity and unit")
    elif operator == "*":
        if a["value_unit"] == "1":
            expected = (b["quantity"], b["value_unit"])
        elif b["value_unit"] == "1":
            expected = (a["quantity"], a["value_unit"])
        else:
            raise ScatterError("multiplication currently requires one dimensionless operand")
    else:
        if b["value_unit"] == "1":
            expected = (a["quantity"], a["value_unit"])
        elif (a["quantity"], a["value_unit"]) == (b["quantity"], b["value_unit"]):
            expected = ("ratio", "1")
        else:
            raise ScatterError("division requires dimensionless divisor or matching quantities/units")
    if (result_quantity, result_unit) != expected:
        raise ScatterError(f"result quantity/unit must be exactly {expected}")
    points_b = {p["id"]: p for p in b["points"]}
    result = {**a, "id": result_id, "quantity": result_quantity, "value_unit": result_unit, "basis": "interpreted", "points": []}
    for pa in a["points"]:
        pb = points_b[pa["id"]]
        if pa["value"] is None or pb["value"] is None:
            value, reason = None, "dataset math: at least one operand is missing"
        else:
            x, y = pa["value"], pb["value"]
            if operator == "/" and y == 0:
                raise ScatterError(f"division by zero at point {pa['id']}")
            value = {"+": lambda: x+y, "-": lambda: x-y, "*": lambda: x*y, "/": lambda: x/y}[operator]()
            value, reason = _number(value, "math result"), None
        result["points"].append({**pa, "value": value, "missing_reason": reason})
    result["provenance"] = [f"Pointwise {operator}; left SHA-256 {left.sha256}; right SHA-256 {right.sha256}; shared support; missing operands propagate"]
    return ScatterDataset.from_dict(result)


def _queries(obj: dict, points: Any, support_count: int) -> list[list[float]]:
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_QUERIES:
        raise ScatterError(f"query_points must contain 1..{MAX_QUERIES} coordinates")
    if len(points) * support_count > MAX_PAIRS:
        raise ScatterError(f"query/support pair budget exceeds {MAX_PAIRS}; submit smaller explicit batches")
    result = []
    for point in points:
        if not isinstance(point, list) or len(point) != obj["dimension"]:
            raise ScatterError("query coordinate dimension mismatch")
        result.append([_number(v, "query coordinate", 1e9) for v in point])
    return result


def _result(obj: dict, dataset: ScatterDataset, method: str, settings: dict, rows: list[dict]) -> dict:
    return {"schema": QUERY_SCHEMA, "method": method, "dataset_sha256": dataset.sha256,
            "quantity": obj["quantity"], "value_unit": obj["value_unit"], "coordinate_unit": "m",
            "crs": obj["crs"], "vertical_datum": obj["vertical_datum"], "rows": rows,
            "receipt": {"settings": settings, "source_count": len(obj["points"]),
                        "missing_source_count": sum(p["value"] is None for p in obj["points"]),
                        "query_count": len(rows), "supported_count": sum(r["supported"] for r in rows),
                        "truncated_query_count": sum(r["truncated"] for r in rows),
                        "original_gms_comparison": "not_performed", "uncertainty_estimated": False}}


def _row(index, point, value=None, reason="unsupported", source_ids=None, distances=None, outside=False, truncated=False):
    return {"query_index": index, "coordinates_m": point, "value": value, "supported": value is not None,
            "reason": reason, "source_ids": source_ids or [], "distances_scaled_m": distances or [],
            "outside_source_bounds": outside, "truncated": truncated}


def interpolate_idw(dataset: ScatterDataset, query_points: list[list[float]], *, power: float = 2.0,
                    max_neighbors: int = 8, min_neighbors: int = 1, radius_m: float | None = None,
                    vertical_scale: float = 1.0, bounds_policy: str = "mask") -> dict:
    return _distance_query(dataset, query_points, "idw", power, max_neighbors, min_neighbors, radius_m, vertical_scale, bounds_policy)


def interpolate_nearest(dataset: ScatterDataset, query_points: list[list[float]], *, radius_m: float | None = None,
                        vertical_scale: float = 1.0, bounds_policy: str = "mask") -> dict:
    return _distance_query(dataset, query_points, "nearest", 1.0, 1, 1, radius_m, vertical_scale, bounds_policy)


def _distance_query(dataset, query_points, method, power, max_neighbors, min_neighbors, radius_m, vertical_scale, bounds_policy):
    obj = dataset.to_dict()
    queries = _queries(obj, query_points, len(obj["points"]))
    power, vertical_scale = _number(power, "power", 16), _number(vertical_scale, "vertical_scale", 1e6)
    if power <= 0 or vertical_scale <= 0 or (obj["dimension"] == 2 and vertical_scale != 1):
        raise ScatterError("positive power/vertical_scale required; 2D vertical_scale must equal 1")
    if type(max_neighbors) is not int or type(min_neighbors) is not int or not 1 <= min_neighbors <= max_neighbors <= MAX_POINTS:
        raise ScatterError("neighbors must be integers with 1 <= min <= max <= 20000")
    if radius_m is not None:
        radius_m = _number(radius_m, "radius_m", 1e16)
        if radius_m <= 0:
            raise ScatterError("radius must be positive or explicitly null for unlimited search")
    if bounds_policy not in ("mask", "allow"):
        raise ScatterError("bounds_policy must be mask or allow")
    points = obj["points"]
    coordinates = {tuple(p["coordinates_m"]): p for p in points}
    low = [min(p["coordinates_m"][i] for p in points) for i in range(obj["dimension"])]
    high = [max(p["coordinates_m"][i] for p in points) for i in range(obj["dimension"])]
    rows = []
    for index, q in enumerate(queries):
        outside = any(q[i] < low[i] or q[i] > high[i] for i in range(obj["dimension"]))
        if outside and bounds_policy == "mask":
            rows.append(_row(index, q, reason="outside_source_axis_aligned_bounds", outside=True))
            continue
        exact = coordinates.get(tuple(q))
        if exact is not None:
            rows.append(_row(index, q, exact["value"], "exact_hit" if exact["value"] is not None else "exact_source_value_missing", [exact["id"]], [0.0], outside))
            continue
        neighbors = []
        for p in points:
            if p["value"] is None:
                continue
            delta = [(p["coordinates_m"][i] - q[i]) * (vertical_scale if i == 2 else 1) for i in range(obj["dimension"])]
            distance = math.hypot(*delta)
            if distance == 0:
                raise ScatterError("nonexact distance underflow; revise coordinate scale or vertical_scale")
            if radius_m is None or distance <= radius_m:
                neighbors.append((distance, p["id"], p["value"]))
        neighbors.sort(key=lambda item: (item[0], item[1]))
        truncated = len(neighbors) > max_neighbors
        selected = neighbors[:max_neighbors]
        if len(selected) < min_neighbors:
            rows.append(_row(index, q, reason="insufficient_neighbors_within_radius", source_ids=[n[1] for n in selected], distances=[n[0] for n in selected], outside=outside, truncated=truncated))
            continue
        if method == "nearest":
            value = selected[0][2]
        else:
            # Scale by nearest distance: finite weights in [0,1], equivalent to d^-p.
            nearest = selected[0][0]
            weights = [(nearest / n[0]) ** power for n in selected]
            denom = math.fsum(weights)
            value = math.fsum(n[2] * (weight / denom) for n, weight in zip(selected, weights))
        rows.append(_row(index, q, _number(value, "interpolated value"), "interpolated", [n[1] for n in selected], [n[0] for n in selected], outside, truncated))
    settings = {"power": power if method == "idw" else None, "max_neighbors": max_neighbors, "min_neighbors": min_neighbors,
                "radius_scaled_m": radius_m, "vertical_scale": vertical_scale, "distance_metric": "sqrt(dx^2+dy^2+(vertical_scale*dz)^2)",
                "bounds_policy": bounds_policy, "bounds_definition": "axis-aligned source coordinate bounds, not convex hull or physical boundary",
                "tie_break": "distance then literal point id", "exact_missing_policy": "unsupported", "missing_neighbors_policy": "exclude"}
    return _result(obj, dataset, method, settings, rows)


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _weights(point, triangle):
    a, b, c = triangle
    denominator = _cross(a, b, c)
    u, v = _cross(point, b, c)/denominator, _cross(a, point, c)/denominator
    return (u, v, 1-u-v)


def _intersection_area(subject, clip):
    # Convex Sutherland-Hodgman clipping in locally translated coordinates.
    origin = clip[0]
    polygon = [[p[0]-origin[0], p[1]-origin[1]] for p in subject]
    clipping = [[p[0]-origin[0], p[1]-origin[1]] for p in clip]
    if _cross(*clipping) < 0:
        clipping.reverse()
    for i in range(3):
        edge_a, edge_b = clipping[i], clipping[(i+1) % 3]
        output = []
        if not polygon:
            return 0.0
        previous = polygon[-1]
        dp = _cross(edge_a, edge_b, previous)
        for current in polygon:
            dc = _cross(edge_a, edge_b, current)
            if (dc >= 0) != (dp >= 0):
                fraction = dp / (dp-dc)
                output.append([previous[j] + fraction*(current[j]-previous[j]) for j in range(2)])
            if dc >= 0:
                output.append(current)
            previous, dp = current, dc
        polygon = output
    if len(polygon) < 3:
        return 0.0
    return abs(math.fsum(_cross(polygon[0], polygon[i], polygon[i+1]) for i in range(1, len(polygon)-1))) / 2


def interpolate_tin(dataset: ScatterDataset, query_points: list[list[float]], triangles: list[list[str]]) -> dict:
    """Linear barycentric values inside a validated, user-supplied 2D TIN only."""
    obj = dataset.to_dict()
    if obj["dimension"] != 2:
        raise ScatterError("linear TIN supports 2D coordinates only")
    if not isinstance(triangles, list) or not 1 <= len(triangles) <= MAX_TRIANGLES:
        raise ScatterError(f"TIN requires 1..{MAX_TRIANGLES} explicit triangles")
    queries = _queries(obj, query_points, len(triangles))
    by_id = {p["id"]: p for p in obj["points"]}
    parsed, seen, edges = [], set(), {}
    for tri in triangles:
        if not isinstance(tri, list) or len(tri) != 3 or any(not isinstance(i, str) or i not in by_id for i in tri) or len(set(tri)) != 3:
            raise ScatterError("triangle must contain three different existing literal point ids")
        identity = tuple(sorted(tri))
        if identity in seen:
            raise ScatterError("duplicate triangle connectivity")
        seen.add(identity)
        coordinates = [by_id[i]["coordinates_m"] for i in tri]
        area2 = abs(_cross(*coordinates))
        scale2 = max(sum((a[j]-b[j])**2 for j in range(2)) for a in coordinates for b in coordinates)
        if scale2 == 0 or area2 <= 1e-12 * scale2:
            raise ScatterError("degenerate or numerically ill-conditioned triangle")
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge = tuple(sorted((a, b)))
            edges[edge] = edges.get(edge, 0) + 1
            if edges[edge] > 2:
                raise ScatterError("non-manifold triangle edge")
        parsed.append((tri, coordinates, area2/2))
    # Reject overlapping interiors, including crossing/unconnected triangles.
    for i, (_, a, area_a) in enumerate(parsed):
        for _, b, area_b in parsed[i+1:]:
            if _intersection_area(a, b) > 1e-10 * min(area_a, area_b):
                raise ScatterError("TIN triangles overlap in their interiors")
    rows = []
    for index, point in enumerate(queries):
        found = []
        for tri, coordinates, _ in parsed:
            weights = _weights(point, coordinates)
            if min(weights) >= -1e-12 and max(weights) <= 1+1e-12:
                found.append((tri, weights))
        if not found:
            rows.append(_row(index, point, reason="outside_explicit_tin"))
            continue
        tri, weights = min(found, key=lambda item: tuple(sorted(item[0])))
        weights = [0.0 if abs(w) <= 1e-12 else max(0.0, w) for w in weights]
        if any(by_id[i]["value"] is None for i, w in zip(tri, weights) if w > 0):
            rows.append(_row(index, point, reason="triangle_source_value_missing", source_ids=tri))
            continue
        # A zero-weight missing vertex does not affect a shared edge or exact hit.
        denom = math.fsum(weights)
        value = math.fsum((by_id[i]["value"] or 0.0)*(w/denom) for i, w in zip(tri, weights))
        row = _row(index, point, _number(value, "TIN value"), "linear_inside_explicit_tin", tri)
        row["barycentric_weights"] = [w/denom for w in weights]
        rows.append(row)
    settings = {"triangles": triangles, "triangles_sha256": _digest(triangles), "construction": "user_supplied_connectivity; no automatic triangulation",
                "inside_tolerance_barycentric": 1e-12, "overlap_relative_area_tolerance": 1e-10, "outside_policy": "unsupported", "disconnected_components": "allowed; gaps remain unsupported"}
    return _result(obj, dataset, "linear_tin", settings, rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load")
    load.add_argument("input")
    load.add_argument("--output", required=True)
    check = commands.add_parser("roundtrip")
    check.add_argument("input")
    check.add_argument("--output", required=True)
    query = commands.add_parser("query")
    query.add_argument("input")
    query.add_argument("queries", help="JSON array of metre coordinates")
    query.add_argument("--method", choices=("idw", "nearest", "tin"), default="idw")
    query.add_argument("--triangles", help="JSON list of explicit triangle point-id triples")
    query.add_argument("--power", type=float, default=2)
    query.add_argument("--neighbors", type=int, default=8)
    query.add_argument("--min-neighbors", type=int, default=1)
    query.add_argument("--radius-m", type=float)
    query.add_argument("--vertical-scale", type=float, default=1)
    query.add_argument("--bounds-policy", choices=("mask", "allow"), default="mask")
    query.add_argument("--output", required=True)
    calc = commands.add_parser("math")
    calc.add_argument("left")
    calc.add_argument("operator", choices=("+", "-", "*", "/"))
    calc.add_argument("right")
    calc.add_argument("--id", required=True)
    calc.add_argument("--quantity", required=True)
    calc.add_argument("--unit", required=True)
    calc.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "load":
            save_scatter(load_scatter(args.input), args.output)
        elif args.command == "roundtrip":
            _write(Path(args.output), _canonical(verify_scatter_roundtrip(args.input)))
        elif args.command == "math":
            save_scatter(dataset_math(load_scatter(args.left), args.operator, load_scatter(args.right), result_id=args.id, result_quantity=args.quantity, result_unit=args.unit), args.output)
        else:
            dataset, points = load_scatter(args.input), _json(_read(Path(args.queries)))
            if args.method == "tin":
                if not args.triangles:
                    raise ScatterError("TIN requires --triangles; no implicit triangulation")
                result = interpolate_tin(dataset, points, _json(_read(Path(args.triangles))))
            elif args.method == "nearest":
                result = interpolate_nearest(dataset, points, radius_m=args.radius_m, vertical_scale=args.vertical_scale, bounds_policy=args.bounds_policy)
            else:
                result = interpolate_idw(dataset, points, power=args.power, max_neighbors=args.neighbors, min_neighbors=args.min_neighbors, radius_m=args.radius_m, vertical_scale=args.vertical_scale, bounds_policy=args.bounds_policy)
            _write(Path(args.output), _canonical(result))
    except (ScatterError, OSError) as exc:
        parser.exit(2, f"scatter: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
