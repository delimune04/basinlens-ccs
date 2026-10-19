"""Explicit, bounded TIN horizons and closed prism geometry (metres only).

Connectivity and correlation are supplied by the user. No triangulation,
extrapolation, CRS transformation, solver discretisation or GMS parity is implied.
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
import shutil
import stat
import tempfile

SCHEMA = "basinlens-surfaces-v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_VERTICES = 2000
MAX_TRIANGLES = 1000
MAX_HORIZONS = 20
MAX_WORK = 500000
UNITS = {"length": "m", "elevation": "m", "volume": "m3"}


class SurfaceError(ValueError):
    """Unsupported, inconsistent or over-budget explicit surface input."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise SurfaceError(f"{field}: expected nonblank literal text (maximum 500 characters)")
    return value


def _number(value, field, limit=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SurfaceError(f"{field}: expected a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise SurfaceError(f"{field}: expected a finite bounded number") from exc
    if not math.isfinite(result) or abs(result) > limit:
        raise SurfaceError(f"{field}: expected finite magnitude <= {limit}")
    return result


def _keys(value, expected, field):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise SurfaceError(f"{field}: expected exactly {sorted(expected)}")


def _list(value, low, high, field):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise SurfaceError(f"{field}: expected {low}..{high} items")


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _barycentric(point, triangle):
    a, b, c = triangle
    area2 = _cross(a, b, c)
    wb = _cross(a, point, c) / area2
    wc = _cross(a, b, point) / area2
    return (1.0 - wb - wc, wb, wc)


def _strict_inside(point, triangle, tol):
    return all(_cross(triangle[k], triangle[(k + 1) % 3], point) > tol for k in range(3))


def _geometry(data):
    xy = [(v["x_m"], v["y_m"]) for v in data["vertices"]]
    index = {v["id"]: i for i, v in enumerate(data["vertices"])}
    triangles = [[index[v] for v in t["vertex_ids"]] for t in data["triangles"]]
    span = max(max(p[k] for p in xy) - min(p[k] for p in xy) for k in (0, 1))
    tol = max(span * span * 1e-12, 1e-18)
    return xy, triangles, tol


def _validate(value):
    data = copy.deepcopy(value)
    _keys(data, ("schema", "id", "name", "units", "crs", "vertical_datum", "provenance", "vertices", "triangles", "horizons", "layers", "history"), "surface")
    if data["schema"] != SCHEMA or data["units"] != UNITS:
        raise SurfaceError("unsupported surface schema or units; explicit metres are required")
    for key in ("id", "name", "crs", "vertical_datum"):
        _text(data[key], key)
    _list(data["provenance"], 1, 32, "provenance")
    for p in data["provenance"]:
        _text(p, "provenance")
    _list(data["history"], 0, 64, "history")
    for record in data["history"]:
        _keys(record, ("source_sha256", "operation", "parameters", "reason"), "history record")
        if not isinstance(record["source_sha256"], str) or len(record["source_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in record["source_sha256"]):
            raise SurfaceError("history source must be a SHA-256 identity")
        _text(record["operation"], "history operation")
        _text(record["reason"], "history reason")
        if not isinstance(record["parameters"], dict) or len(_canonical(record["parameters"])) > 131072:
            raise SurfaceError("history parameters must be a bounded JSON object")
    _list(data["vertices"], 3, MAX_VERTICES, "vertices")
    _list(data["triangles"], 1, MAX_TRIANGLES, "triangles")
    _list(data["horizons"], 1, MAX_HORIZONS, "horizons")
    seen = set()
    positions = set()
    for v in data["vertices"]:
        _keys(v, ("id", "x_m", "y_m"), "vertex")
        _text(v["id"], "vertex id")
        v["x_m"] = _number(v["x_m"], "vertex x_m")
        v["y_m"] = _number(v["y_m"], "vertex y_m")
        if v["id"] in seen or (v["x_m"], v["y_m"]) in positions:
            raise SurfaceError("duplicate vertex identity or XY position")
        seen.add(v["id"])
        positions.add((v["x_m"], v["y_m"]))
    tids = set()
    used = set()
    for t in data["triangles"]:
        _keys(t, ("id", "vertex_ids"), "triangle")
        _text(t["id"], "triangle id")
        _list(t["vertex_ids"], 3, 3, "triangle vertices")
        if not all(isinstance(v, str) for v in t["vertex_ids"]) or len(set(t["vertex_ids"])) != 3 or not set(t["vertex_ids"]) <= seen or t["id"] in tids:
            raise SurfaceError("triangle identities/connectivity are inconsistent")
        tids.add(t["id"])
        used.update(t["vertex_ids"])
    if used != seen:
        raise SurfaceError("unreferenced vertices are unsupported")
    xy, triangles, tol = _geometry(data)
    edges = {}
    signatures = set()
    for t in triangles:
        sig = tuple(sorted(t))
        if sig in signatures or _cross(*(xy[i] for i in t)) <= tol:
            raise SurfaceError("triangles must be distinct, nondegenerate and counterclockwise in XY")
        signatures.add(sig)
        for a, b in zip(t, t[1:] + t[:1]):
            key = tuple(sorted((a, b)))
            prior = edges.setdefault(key, [])
            if len(prior) >= 2 or (prior and prior[0] == (a, b)):
                raise SurfaceError("nonmanifold or inconsistently oriented shared edge")
            prior.append((a, b))
    # Edge counts alone miss two disconnected triangle fans meeting at a point.
    # A 2-manifold vertex link is one connected path (boundary) or cycle (interior).
    for vertex in range(len(xy)):
        link = {}
        for tri in triangles:
            if vertex in tri:
                a, b = [v for v in tri if v != vertex]
                link.setdefault(a, set()).add(b)
                link.setdefault(b, set()).add(a)
        pending = [next(iter(link))]
        reached = set()
        while pending:
            v = pending.pop()
            if v not in reached:
                reached.add(v)
                pending.extend(link[v] - reached)
        endpoints = sum(len(neighbours) == 1 for neighbours in link.values())
        if len(reached) != len(link) or any(len(neighbours) > 2 for neighbours in link.values()) or endpoints not in (0, 2):
            raise SurfaceError("nonmanifold vertex link")
    # Exhaustive pairs are deliberately bounded; there is no hidden unbounded search.
    if len(triangles) * (len(triangles) - 1) // 2 > MAX_WORK:
        raise SurfaceError("triangle overlap check exceeds pair budget")
    for i, ti in enumerate(triangles):
        a = [xy[v] for v in ti]
        for tj in triangles[i + 1:]:
            b = [xy[v] for v in tj]
            if any(max(p[k] for p in a) < min(p[k] for p in b) or max(p[k] for p in b) < min(p[k] for p in a) for k in (0, 1)):
                continue
            if any(_strict_inside(p, b, tol) for p in a) or any(_strict_inside(p, a, tol) for p in b):
                raise SurfaceError("overlapping triangle interiors")
            for u, v in zip(ti, ti[1:] + ti[:1]):
                for w, z in zip(tj, tj[1:] + tj[:1]):
                    if {u, v} == {w, z}:
                        continue
                    p, q, r, s = xy[u], xy[v], xy[w], xy[z]
                    c1, c2 = _cross(p, q, r), _cross(p, q, s)
                    c3, c4 = _cross(r, s, p), _cross(r, s, q)
                    if ((c1 > tol and c2 < -tol) or (c1 < -tol and c2 > tol)) and ((c3 > tol and c4 < -tol) or (c3 < -tol and c4 > tol)):
                        raise SurfaceError("crossing triangle edges")
                    # No T-junctions/partial coincident edges: only shared vertex IDs and complete edges.
                    for idx, point in ((w, r), (z, s)):
                        if idx not in (u, v) and abs(_cross(p, q, point)) <= tol and min(p[0], q[0]) <= point[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= point[1] <= max(p[1], q[1]):
                            raise SurfaceError("triangle T-junction or partial coincident edge")
    hids = set()
    prior = None
    for h in data["horizons"]:
        _keys(h, ("id", "name", "elevations_m"), "horizon")
        _text(h["id"], "horizon id")
        _text(h["name"], "horizon name")
        if h["id"] in hids:
            raise SurfaceError("duplicate horizon id")
        hids.add(h["id"])
        _list(h["elevations_m"], len(xy), len(xy), "horizon elevations")
        h["elevations_m"] = [_number(z, "elevation_m", 1e7) for z in h["elevations_m"]]
        if prior is not None and any(a - b < 1e-6 for a, b in zip(prior, h["elevations_m"])):
            raise SurfaceError("horizons cross, touch or violate the 1e-6 m minimum vertex thickness")
        prior = h["elevations_m"]
    _list(data["layers"], len(hids) - 1, len(hids) - 1, "layers")
    lids = set()
    for layer in data["layers"]:
        _keys(layer, ("id", "name", "material_id"), "layer")
        for key in ("id", "name", "material_id"):
            _text(layer[key], f"layer {key}")
        if layer["id"] in lids:
            raise SurfaceError("duplicate layer id")
        lids.add(layer["id"])
    return data


@dataclass(frozen=True)
class SurfaceModel:
    _json: bytes

    @classmethod
    def from_dict(cls, value):
        try:
            if len(_canonical(value)) > MAX_BYTES:
                raise SurfaceError("surface JSON exceeds 8 MiB")
            return cls(_canonical(_validate(value)))
        except (TypeError, OverflowError, ValueError, RecursionError) as exc:
            if isinstance(exc, SurfaceError):
                raise
            raise SurfaceError(f"invalid surface JSON: {exc}") from exc

    def to_dict(self):
        if not isinstance(self._json, bytes) or len(self._json) > MAX_BYTES:
            raise SurfaceError("invalid or oversized directly constructed SurfaceModel")
        try:
            value = _decode(self._json)
            return _validate(value)
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
            if isinstance(exc, SurfaceError):
                raise
            raise SurfaceError("invalid directly constructed SurfaceModel") from exc

    @property
    def sha256(self):
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


def _read(path, maximum=MAX_BYTES):
    path = Path(path)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise SurfaceError(f"source must be a regular non-symlink file: {path}")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise SurfaceError("source is not a bounded regular file")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > maximum or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise SurfaceError("source changed during read or exceeds budget")
        return raw
    except OSError as exc:
        raise SurfaceError(f"cannot read surface input: {exc}") from exc


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SurfaceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda text: (_ for _ in ()).throw(SurfaceError(f"nonfinite JSON number: {text}")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SurfaceError(f"invalid JSON: {exc}") from exc


def load_surfaces(path):
    return SurfaceModel.from_dict(_decode(_read(path)))


def _fresh_write(path, raw):
    path = Path(path)
    if len(raw) > 64 * 1024 * 1024:
        raise SurfaceError("output exceeds the 64 MiB artifact budget")
    if not path.parent.is_dir():
        raise SurfaceError("output parent must already exist")
    fd, tmp = tempfile.mkstemp(prefix=".surface-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, path)  # Atomic no-replace publication, including dangling symlinks.
        except FileExistsError as exc:
            raise SurfaceError(f"output already exists: {path}") from exc
    finally:
        os.unlink(tmp)
    return path


def save_surfaces(model, output):
    return _fresh_write(output, _canonical(model.to_dict()) + b"\n")


def _points(points, maximum=10000):
    _list(points, 1, maximum, "XY points")
    checked = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise SurfaceError("each XY point must contain two coordinates")
        checked.append(tuple(_number(v, "query XY") for v in p))
    return checked


def query_surface(model, horizon_id, points_xy):
    data = model.to_dict()
    horizons = {h["id"]: h for h in data["horizons"]}
    if horizon_id not in horizons:
        raise SurfaceError("unknown horizon id")
    points = _points(points_xy)
    xy, triangles, _ = _geometry(data)
    if len(points) * len(triangles) > MAX_WORK:
        raise SurfaceError("query exceeds point/triangle work budget")
    z = horizons[horizon_id]["elevations_m"]
    rows = []
    for p in points:
        found = None
        for i, tri in enumerate(triangles):
            tri_xy = [xy[v] for v in tri]
            # Boundary ownership is deterministic: first supplied triangle wins.
            weights = _barycentric(p, tri_xy)
            # Query tolerance is dimensionless and local to this triangle. A
            # distant large component must not expand a small triangle's domain.
            if all(-1e-12 <= weight <= 1 + 1e-12 for weight in weights):
                found = {"x_m": p[0], "y_m": p[1], "supported": True, "elevation_m": sum(w * z[v] for w, v in zip(weights, tri)), "triangle_id": data["triangles"][i]["id"], "vertex_ids": data["triangles"][i]["vertex_ids"], "weights": list(weights)}
                break
        rows.append(found or {"x_m": p[0], "y_m": p[1], "supported": False, "elevation_m": None, "triangle_id": None, "vertex_ids": [], "weights": []})
    return {"source_sha256": model.sha256, "horizon_id": horizon_id, "units": {"length": "m", "elevation": "m"}, "crs": data["crs"], "vertical_datum": data["vertical_datum"], "outside_policy": "unsupported; no extrapolation", "points": rows}


def _changed(model, data, operation, parameters, reason):
    _text(reason, "edit reason")
    data["history"].append({"source_sha256": model.sha256, "operation": operation, "parameters": parameters, "reason": reason})
    return SurfaceModel.from_dict(data)


def edit_vertices(model, *, horizon_id=None, elevations=None, xy=None, reason):
    data = model.to_dict()
    index = {v["id"]: i for i, v in enumerate(data["vertices"])}
    elevations = {} if elevations is None else elevations
    xy = {} if xy is None else xy
    if not isinstance(elevations, dict) or not isinstance(xy, dict) or not (elevations or xy) or not set(elevations) <= set(index) or not set(xy) <= set(index):
        raise SurfaceError("edits require known vertex IDs and at least one update")
    horizons = {h["id"]: h for h in data["horizons"]}
    if elevations and horizon_id not in horizons:
        raise SurfaceError("elevation edits require a known horizon")
    if not elevations and horizon_id is not None:
        raise SurfaceError("horizon id without elevation changes is unsupported")
    for vertex_id, elevation in elevations.items():
        horizons[horizon_id]["elevations_m"][index[vertex_id]] = _number(elevation, "edit elevation", 1e7)
    for vertex_id, point in xy.items():
        point = _points([point])[0]
        data["vertices"][index[vertex_id]]["x_m"], data["vertices"][index[vertex_id]]["y_m"] = point
    return _changed(model, data, "explicit vertex edit", {"horizon_id": horizon_id, "elevations_m": elevations, "xy_m": xy}, reason)


def smooth_horizon(model, horizon_id, *, iterations, weight=0.5, reason):
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 100:
        raise SurfaceError("smoothing iterations must be an integer in 1..100")
    weight = _number(weight, "smoothing weight", 1)
    if not 0 < weight <= 1:
        raise SurfaceError("smoothing weight must be in (0,1]")
    data = model.to_dict()
    horizons = {h["id"]: h for h in data["horizons"]}
    if horizon_id not in horizons:
        raise SurfaceError("unknown horizon id")
    _, triangles, _ = _geometry(data)
    if iterations * sum(len(t) for t in triangles) > MAX_WORK:
        raise SurfaceError("smoothing exceeds work budget")
    neighbours = [set() for _ in data["vertices"]]
    edges = {}
    for tri in triangles:
        for a, b in zip(tri, tri[1:] + tri[:1]):
            neighbours[a].add(b)
            neighbours[b].add(a)
            key = tuple(sorted((a, b)))
            edges[key] = edges.get(key, 0) + 1
    boundary = {v for edge, count in edges.items() if count == 1 for v in edge}
    h = horizons[horizon_id]
    horizon_index = next(i for i, item in enumerate(data["horizons"]) if item["id"] == horizon_id)
    for _ in range(iterations):
        old = h["elevations_m"]
        h["elevations_m"] = [z if i in boundary else (1 - weight) * z + weight * sum(old[j] for j in sorted(neighbours[i])) / len(neighbours[i]) for i, z in enumerate(old)]
        # XY/connectivity stay unchanged. Rechecking the O(Ntri^2) topology each
        # iteration would exceed the declared smoothing work budget. Only the
        # edited surface's two neighbouring thickness contracts can change.
        if horizon_index > 0 and any(a - b < 1e-6 for a, b in zip(data["horizons"][horizon_index - 1]["elevations_m"], h["elevations_m"])):
            raise SurfaceError("smoothing causes crossing or touching horizons")
        if horizon_index + 1 < len(data["horizons"]) and any(a - b < 1e-6 for a, b in zip(h["elevations_m"], data["horizons"][horizon_index + 1]["elevations_m"])):
            raise SurfaceError("smoothing causes crossing or touching horizons")
    return _changed(model, data, "uniform-neighbour Jacobi Laplacian elevation smoothing", {"horizon_id": horizon_id, "iterations": iterations, "weight": weight, "fixed_boundary_vertex_ids": [v["id"] for i, v in enumerate(data["vertices"]) if i in boundary], "interpretation": "explicit numerical edit, not geological truth"}, reason)


def extrude_solids(model):
    data = model.to_dict()
    xy, triangles, _ = _geometry(data)
    if len(triangles) * len(data["layers"]) > 20000:
        raise SurfaceError("solid count exceeds budget")
    solids = []
    for k, layer in enumerate(data["layers"]):
        upper, lower = data["horizons"][k:k + 2]
        for i, tri in enumerate(triangles):
            vertices = [[*xy[v], upper["elevations_m"][v]] for v in tri] + [[*xy[v], lower["elevations_m"][v]] for v in tri]
            area = _cross(*(xy[v] for v in tri)) / 2
            volume = area * sum(upper["elevations_m"][v] - lower["elevations_m"][v] for v in tri) / 3
            solids.append({"id": f"prism-{k}-{i}", "layer_id": layer["id"], "material_id": layer["material_id"], "upper_horizon_id": upper["id"], "lower_horizon_id": lower["id"], "triangle_id": data["triangles"][i]["id"], "source_vertex_ids": data["triangles"][i]["vertex_ids"], "vertices_xyz_m": vertices, "faces": [[0, 1, 2], [5, 4, 3], [0, 3, 4, 1], [1, 4, 5, 2], [2, 5, 3, 0]], "area_xy_m2": area, "volume_m3": volume})
    return {"schema": "basinlens-explicit-prisms-v1", "source_sha256": model.sha256, "units": UNITS, "crs": data["crs"], "vertical_datum": data["vertical_datum"], "geometry": "closed triangular prisms between piecewise linear horizons; no solver mapping", "solids": solids, "total_volume_m3": math.fsum(s["volume_m3"] for s in solids)}


def section_surfaces(model, polyline):
    data = model.to_dict()
    points = _points(polyline, maximum=1000)
    if len(points) < 2:
        raise SurfaceError("section polyline needs at least two points")
    xy, triangles, _ = _geometry(data)
    if (len(points) - 1) * len(triangles) * len(data["horizons"]) > MAX_WORK:
        raise SurfaceError("section exceeds segment/triangle work budget")
    rows = []
    offset = 0.0
    for seg, (p, q) in enumerate(zip(points, points[1:])):
        length = math.dist(p, q)
        if length <= 1e-9:
            raise SurfaceError("section contains a zero-length segment")
        pieces = []
        for i, tri in enumerate(triangles):
            a = [xy[v] for v in tri]
            tol = _cross(*a) * 1e-12
            lo, hi = 0.0, 1.0
            for j in range(3):
                c0, c1 = _cross(a[j], a[(j + 1) % 3], p), _cross(a[j], a[(j + 1) % 3], q)
                delta = c1 - c0
                if abs(delta) <= tol:
                    if c0 < -tol:
                        hi = -1.0
                        break
                elif delta > 0:
                    lo = max(lo, -c0 / delta)
                else:
                    hi = min(hi, -c0 / delta)
            if hi - lo > 1e-12:
                pieces.append((lo, hi, i, tri))
        # A section lying on a shared edge has two identical intervals. Partition at
        # every endpoint and assign each interval to its first supplied triangle.
        cuts = sorted({v for lo, hi, _, _ in pieces for v in (lo, hi)})
        for lo, hi in zip(cuts, cuts[1:]):
            if hi - lo <= 1e-12:
                continue
            mid = (lo + hi) / 2
            owners = [piece for piece in pieces if piece[0] <= mid <= piece[1]]
            if not owners:
                continue
            _, _, i, tri = min(owners, key=lambda item: item[2])
            ends = [(p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])) for t in (lo, hi)]
            weights = [_barycentric(e, [xy[v] for v in tri]) for e in ends]
            horizons = [{"horizon_id": h["id"], "elevations_m": [sum(w * h["elevations_m"][v] for w, v in zip(ws, tri)) for ws in weights]} for h in data["horizons"]]
            rows.append({"segment_index": seg, "triangle_id": data["triangles"][i]["id"], "distance_m": [offset + lo * length, offset + hi * length], "endpoints_xy_m": [list(e) for e in ends], "horizons": horizons, "bands": [{"layer_id": layer["id"], "material_id": layer["material_id"], "polygon_distance_elevation_m": [[offset + lo * length, horizons[k]["elevations_m"][0]], [offset + hi * length, horizons[k]["elevations_m"][1]], [offset + hi * length, horizons[k + 1]["elevations_m"][1]], [offset + lo * length, horizons[k + 1]["elevations_m"][0]]]} for k, layer in enumerate(data["layers"])]})
        offset += length
    return {"schema": "basinlens-explicit-section-v1", "source_sha256": model.sha256, "crs": data["crs"], "vertical_datum": data["vertical_datum"], "units": {"distance": "m", "elevation": "m"}, "polyline_xy_m": [list(p) for p in points], "total_polyline_length_m": offset, "outside_policy": "only supported intervals emitted; holes/outside remain gaps", "pieces": rows}


def _csv_bytes(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def export_surface_tables(model, output_dir):
    data = model.to_dict()
    output = Path(output_dir)
    if not output.parent.is_dir() or output.exists() or output.is_symlink():
        raise SurfaceError("table output requires an absent path under an existing parent")
    payloads = {
        "vertices.csv": _csv_bytes(["vertex_id", "x_m", "y_m"], [[v["id"], repr(v["x_m"]), repr(v["y_m"])] for v in data["vertices"]]),
        "triangles.csv": _csv_bytes(["triangle_id", "vertex_id_0", "vertex_id_1", "vertex_id_2"], [[t["id"], *t["vertex_ids"]] for t in data["triangles"]]),
        "elevations.csv": _csv_bytes(["horizon_id", "vertex_id", "elevation_m"], [[h["id"], v["id"], repr(h["elevations_m"][i])] for h in data["horizons"] for i, v in enumerate(data["vertices"])]),
    }
    if sum(len(raw) for raw in payloads.values()) > MAX_BYTES:
        raise SurfaceError("CSV export exceeds the 8 MiB table bundle budget; use shorter literal IDs or a smaller explicit model")
    metadata = {k: v for k, v in data.items() if k not in ("vertices", "triangles")}
    metadata["horizons"] = [{k: v for k, v in h.items() if k != "elevations_m"} for h in data["horizons"]]
    manifest = {"schema": "basinlens-surface-tables-v1", "source_sha256": model.sha256, "metadata": metadata, "tables": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in payloads.items()}}
    payloads["manifest.json"] = _canonical(manifest) + b"\n"
    stage = Path(tempfile.mkdtemp(prefix=".surface-tables-", dir=output.parent))
    try:
        for name, raw in payloads.items():
            (stage / name).write_bytes(raw)
        # Reserve destination ourselves before moving files: no replacement of an
        # existing empty directory or a concurrently created destination.
        output.mkdir()
        try:
            for name in payloads:
                os.rename(stage / name, output / name)
        except BaseException:
            for name in payloads:
                try:
                    (output / name).unlink()
                except FileNotFoundError:
                    pass
            output.rmdir()
            raise
    except FileExistsError as exc:
        raise SurfaceError("table output already exists") from exc
    finally:
        shutil.rmtree(stage)
    return output


def import_surface_tables(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or {p.name for p in path.iterdir()} != {"vertices.csv", "triangles.csv", "elevations.csv", "manifest.json"}:
        raise SurfaceError("surface table directory has missing/unregistered entries")
    manifest = _decode(_read(path / "manifest.json"))
    _keys(manifest, ("schema", "source_sha256", "metadata", "tables"), "table manifest")
    if manifest["schema"] != "basinlens-surface-tables-v1" or not isinstance(manifest["metadata"], dict):
        raise SurfaceError("unsupported surface table schema")
    names = {"vertices.csv", "triangles.csv", "elevations.csv"}
    _keys(manifest["tables"], names, "table inventory")
    tables = {}
    total = 0
    for name in sorted(names):
        raw = _read(path / name)
        total += len(raw)
        expected = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if manifest["tables"][name] != expected or total > MAX_BYTES:
            raise SurfaceError("changed table bytes or table budget exceeded")
        maximum_rows = {"vertices.csv": MAX_VERTICES, "triangles.csv": MAX_TRIANGLES, "elevations.csv": MAX_HORIZONS * MAX_VERTICES}[name]
        if raw.count(b"\n") > maximum_rows + 1:
            raise SurfaceError("CSV row count exceeds declared table budget")
        try:
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))
        except (csv.Error, UnicodeError) as exc:
            raise SurfaceError(f"invalid CSV table {name}") from exc
        tables[name] = rows
    expected_headers = {"vertices.csv": ["vertex_id", "x_m", "y_m"], "triangles.csv": ["triangle_id", "vertex_id_0", "vertex_id_1", "vertex_id_2"], "elevations.csv": ["horizon_id", "vertex_id", "elevation_m"]}
    for name, header in expected_headers.items():
        rows = tables[name]
        if not rows or rows[0] != header or any(len(row) != len(header) for row in rows[1:]):
            raise SurfaceError(f"invalid CSV columns in {name}")
    data = copy.deepcopy(manifest["metadata"])
    _keys(data, ("schema", "id", "name", "units", "crs", "vertical_datum", "provenance", "horizons", "layers", "history"), "table metadata")
    _list(data["horizons"], 1, MAX_HORIZONS, "table horizons")
    for h in data["horizons"]:
        _keys(h, ("id", "name"), "table horizon metadata")
        _text(h["id"], "table horizon id")
        _text(h["name"], "table horizon name")
    _list(tables["vertices.csv"][1:], 3, MAX_VERTICES, "vertex rows")
    _list(tables["triangles.csv"][1:], 1, MAX_TRIANGLES, "triangle rows")
    _list(tables["elevations.csv"][1:], 3, MAX_HORIZONS * MAX_VERTICES, "elevation rows")
    try:
        data["vertices"] = [{"id": r[0], "x_m": float(r[1]), "y_m": float(r[2])} for r in tables["vertices.csv"][1:]]
        data["triangles"] = [{"id": r[0], "vertex_ids": r[1:]} for r in tables["triangles.csv"][1:]]
        zs = {}
        for r in tables["elevations.csv"][1:]:
            key = (r[0], r[1])
            if key in zs:
                raise SurfaceError("duplicate horizon/vertex elevation row")
            zs[key] = float(r[2])
        expected = {(h["id"], v["id"]) for h in data["horizons"] for v in data["vertices"]}
        if set(zs) != expected:
            raise SurfaceError("missing or unregistered elevation row")
        for h in data["horizons"]:
            h["elevations_m"] = [zs[(h["id"], v["id"])] for v in data["vertices"]]
        model = SurfaceModel.from_dict(data)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise SurfaceError(f"invalid table values: {exc}") from exc
    if model.sha256 != manifest["source_sha256"]:
        raise SurfaceError("table semantic identity differs from source manifest")
    return model


def verify_surface_roundtrip(source, output_dir):
    raw = _read(source)
    model = SurfaceModel.from_dict(_decode(raw))
    root = Path(output_dir)
    if not root.parent.is_dir():
        raise SurfaceError("roundtrip output parent must exist")
    try:
        root.mkdir()
    except FileExistsError as exc:
        raise SurfaceError("roundtrip output already exists") from exc
    save_surfaces(model, root / "model.json")
    export_surface_tables(model, root / "tables")
    restored = import_surface_tables(root / "tables")
    save_surfaces(restored, root / "restored.json")
    same = model.to_dict() == restored.to_dict() == load_surfaces(root / "restored.json").to_dict()
    unchanged = _read(source) == raw
    if not same or not unchanged:
        raise SurfaceError("surface roundtrip mismatch or changed original source")
    receipt = {"schema": "basinlens-surface-roundtrip-v1", "source_bytes_sha256": hashlib.sha256(raw).hexdigest(), "model_sha256": model.sha256, "source_unchanged": unchanged, "json_and_csv_semantics_equal": same, "original_gms_comparison": "NOT_OBSERVED", "geometry_scope": "explicit user-authored TIN/horizons/prisms only"}
    _fresh_write(root / "receipt.json", _canonical(receipt) + b"\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "query", "edit", "smooth", "extrude", "section", "roundtrip", "export-tables", "import-tables"):
        p = sub.add_parser(command)
        p.add_argument("source")
        if command != "check":
            p.add_argument("--output", required=True)
        if command in ("query", "edit", "smooth"):
            p.add_argument("--horizon", required=True)
        if command in ("query", "section", "edit"):
            p.add_argument("--values", required=True, help="bounded JSON file: XY point list, section polyline, or vertex-ID/elevation object")
        if command == "smooth":
            p.add_argument("--iterations", type=int, required=True)
            p.add_argument("--weight", type=float, default=0.5)
        if command in ("edit", "smooth"):
            p.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "roundtrip":
            result = verify_surface_roundtrip(args.source, args.output)
        elif args.command == "import-tables":
            model = import_surface_tables(args.source)
            save_surfaces(model, args.output)
            result = {"model_sha256": model.sha256}
        else:
            model = load_surfaces(args.source)
            if args.command == "check":
                result = {"model_sha256": model.sha256, "valid": True, "original_gms_comparison": "NOT_OBSERVED"}
            elif args.command == "export-tables":
                export_surface_tables(model, args.output)
                result = {"model_sha256": model.sha256}
            elif args.command in ("edit", "smooth"):
                edited = edit_vertices(model, horizon_id=args.horizon, elevations=_decode(_read(args.values)), reason=args.reason) if args.command == "edit" else smooth_horizon(model, args.horizon, iterations=args.iterations, weight=args.weight, reason=args.reason)
                save_surfaces(edited, args.output)
                result = {"model_sha256": edited.sha256, "source_sha256": model.sha256}
            else:
                if args.command == "query":
                    result = query_surface(model, args.horizon, _decode(_read(args.values)))
                elif args.command == "section":
                    result = section_surfaces(model, _decode(_read(args.values)))
                else:
                    result = extrude_solids(model)
                _fresh_write(args.output, _canonical(result) + b"\n")
        summary = result
        for key in ("solids", "pieces", "points"):
            if key in result:
                summary = {"source_sha256": result["source_sha256"], "output": str(args.output), f"{key}_count": len(result[key])}
                if "total_volume_m3" in result:
                    summary["total_volume_m3"] = result["total_volume_m3"]
                break
        print(json.dumps(summary, sort_keys=True))
        return 0
    except (SurfaceError, OSError) as exc:
        parser.exit(2, f"surface error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
