"""Bounded authored planar meshes, conforming local refinement and flat prisms.

These are BasinLens geometry operations, not a GMS mesh decoder or parity proof.
Planar rings are counterclockwise. The explicit DISV converter reverses them to
MODFLOW 6's documented clockwise convention without reflecting physical XY.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile

SCHEMA = "basinlens-planar-mesh-v1"
MAX_CELLS = 10000
MAX_VERTICES = 40000
MAX_EDGES = 100000
MAX_PAIRS = 2000000
MAX_GEOMETRY_COMPARISONS = 20000000
MAX_BYTES = 16 * 1024 * 1024


class MeshError(ValueError):
    """A mesh is invalid or exceeds its declared geometry/operation budget."""


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise MeshError(f"{label}: expected exact fields {sorted(keys)}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or "\0" in value:
        raise MeshError(f"{label}: expected a nonempty literal string of at most 500 characters")
    return value


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e9 or not math.isfinite(value):
        raise MeshError(f"{label}: expected a finite numeric coordinate within +/-1e9 m")
    return float(value)


def _integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MeshError(f"{label}: integer must be in [{low}, {high}]")
    return value


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False) + "\n").encode()


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _area_centroid(points):
    # Translating the shoelace sum avoids cancellation at large literal origins.
    ox, oy = points[0]
    translated = [(x - ox, y - oy) for x, y in points]
    terms = [a[0] * b[1] - b[0] * a[1] for a, b in zip(translated, translated[1:] + translated[:1])]
    twice = math.fsum(terms)
    if twice <= 0:
        raise MeshError("Cell ring must have positive counterclockwise area")
    cx = math.fsum((a[0] + b[0]) * t for a, b, t in zip(translated, translated[1:] + translated[:1], terms)) / (3 * twice)
    cy = math.fsum((a[1] + b[1]) * t for a, b, t in zip(translated, translated[1:] + translated[:1], terms)) / (3 * twice)
    return twice / 2, (ox + cx, oy + cy)


def _on_segment(point, a, b, tol):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return (abs(_cross(a, b, point)) <= tol * length and
            min(a[0], b[0]) - tol <= point[0] <= max(a[0], b[0]) + tol and
            min(a[1], b[1]) - tol <= point[1] <= max(a[1], b[1]) + tol)


def _overlap_interior(a, b, tol):
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            nx, ny = -(q[1] - p[1]), q[0] - p[0]
            length = math.hypot(nx, ny)
            pa = [(x - p[0]) * nx + (y - p[1]) * ny for x, y in a]
            pb = [(x - p[0]) * nx + (y - p[1]) * ny for x, y in b]
            if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= tol * length:
                return False
    return True


def _validate(value):
    _keys(value, ("schema", "length_unit", "crs", "vertices", "cells", "provenance"), "mesh")
    if value["schema"] != SCHEMA or value["length_unit"] != "m":
        raise MeshError("Only the version-1 meter mesh schema is supported; units are never inferred")
    _text(value["crs"], "crs")
    if value["crs"].strip().upper() in {"EPSG:4326", "EPSG:4269", "EPSG:4258", "EPSG:4979", "OGC:CRS84", "CRS:84"}:
        raise MeshError("Known geographic angular CRS contradicts meter XY; explicitly project coordinates first")
    provenance = value["provenance"]
    if not isinstance(provenance, list) or not 1 <= len(provenance) <= 64:
        raise MeshError("provenance requires 1..64 literal source/operation notes")
    for item in provenance:
        _text(item, "provenance")
    vertices, cells = value["vertices"], value["cells"]
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= MAX_VERTICES:
        raise MeshError("vertices exceed count budget or contain fewer than three vertices")
    if not isinstance(cells, list) or not 1 <= len(cells) <= MAX_CELLS:
        raise MeshError("cells exceed count budget or are empty")
    xy = []
    for index, vertex in enumerate(vertices):
        _keys(vertex, ("id", "x_m", "y_m"), "vertex")
        if _integer(vertex["id"], 0, MAX_VERTICES - 1, "vertex id") != index:
            raise MeshError("Vertex IDs must be consecutive zero-based integers in list order")
        xy.append((_number(vertex["x_m"], "x_m"), _number(vertex["y_m"], "y_m")))
    if len(set(xy)) != len(xy):
        raise MeshError("Duplicate XY coordinates must use one shared vertex ID")
    span = max(max(p[k] for p in xy) - min(p[k] for p in xy) for k in (0, 1))
    tol = max(1e-10, span * 1e-12)
    used, rings, boxes, areas, centres, edges = set(), [], [], [], [], {}
    edge_count, geometry_comparisons = 0, 0
    for index, cell in enumerate(cells):
        _keys(cell, ("id", "vertices", "material_id"), "cell")
        if _integer(cell["id"], 0, MAX_CELLS - 1, "cell id") != index:
            raise MeshError("Cell IDs must be consecutive zero-based integers in list order")
        _text(cell["material_id"], "material_id")
        ids = cell["vertices"]
        if not isinstance(ids, list) or not 3 <= len(ids) <= 256 or len(set(map(str, ids))) != len(ids):
            raise MeshError("Cell ring requires 3..256 distinct vertex IDs, with no repeated closing vertex")
        ids = [_integer(v, 0, len(xy) - 1, "cell vertex") for v in ids]
        points = [xy[v] for v in ids]
        local = max(math.dist(a, b) for a, b in zip(points, points[1:] + points[:1]))
        positive = False
        for a, b, c in zip(points, points[1:] + points[:1], points[2:] + points[:2]):
            if math.dist(a, b) <= 10 * tol:
                raise MeshError("Cell edge is too short for the coordinate precision")
            turn = _cross(a, b, c)
            if turn < -tol * local:
                raise MeshError("Cells must be convex and counterclockwise; concave/self-crossing rings are unsupported")
            positive |= turn > tol * local
        if not positive:
            raise MeshError("Degenerate cell polygon")
        area, centre = _area_centroid(points)
        if area <= tol * local:
            raise MeshError("Cell area is below the geometry precision budget")
        geometry_comparisons += len(points) ** 2
        if geometry_comparisons > MAX_GEOMETRY_COMPARISONS:
            raise MeshError("Mesh polygon comparison budget exceeded")
        # Convexity with every vertex, not only local turns, rejects multiply wound stars.
        for a, b in zip(points, points[1:] + points[:1]):
            if any(_cross(a, b, c) < -tol * local for c in points):
                raise MeshError("Cell is self-crossing or not convex")
        for a, b in zip(ids, ids[1:] + ids[:1]):
            key = tuple(sorted((a, b)))
            owners = edges.setdefault(key, [])
            owners.append((index, a, b))
            if len(owners) > 2 or len(owners) == 2 and owners[0][1:] != (b, a):
                raise MeshError("A face must have at most two owners with opposite orientation")
        used.update(ids)
        edge_count += len(ids)
        if edge_count > MAX_EDGES:
            raise MeshError("Mesh exceeds edge count budget")
        rings.append(points)
        boxes.append((min(p[0] for p in points), max(p[0] for p in points), min(p[1] for p in points), max(p[1] for p in points)))
        areas.append(area)
        centres.append(centre)
    if used != set(range(len(xy))):
        raise MeshError("Unused vertices are unsupported; every declared vertex must belong to a cell")
    # Sweep in X; bound candidate cell pairs as well as topology comparisons.
    active, pair_count, comparisons, sweep_count = [], 0, 0, 0
    for i in sorted(range(len(cells)), key=lambda n: boxes[n][0]):
        left, right, bottom, top = boxes[i]
        active = [j for j in active if boxes[j][1] >= left - tol]
        for j in active:
            sweep_count += 1
            if sweep_count > MAX_PAIRS:
                raise MeshError("Mesh sweep comparison budget exceeded")
            if boxes[j][3] < bottom - tol or boxes[j][2] > top + tol:
                continue
            pair_count += 1
            if pair_count > MAX_PAIRS:
                raise MeshError("Mesh topology candidate-pair budget exceeded")
            geometry_comparisons += (len(rings[i]) + len(rings[j])) ** 2
            if geometry_comparisons > MAX_GEOMETRY_COMPARISONS:
                raise MeshError("Mesh geometric overlap comparison budget exceeded")
            if _overlap_interior(rings[i], rings[j], tol):
                raise MeshError(f"Cell interiors overlap: {j}, {i}")
            # Every point on an interface edge must be explicitly present in both
            # rings, including quadtree hanging nodes. No split-face guessing.
            for owner, other in ((i, j), (j, i)):
                ids = cells[owner]["vertices"]
                others = set(cells[other]["vertices"])
                for vertex_id in others - set(ids):
                    for a, b in zip(ids, ids[1:] + ids[:1]):
                        comparisons += 1
                        if comparisons > MAX_PAIRS * 8:
                            raise MeshError("Mesh interface comparison budget exceeded")
                        if _on_segment(xy[vertex_id], xy[a], xy[b], tol):
                            raise MeshError("Nonconforming interface: insert the shared hanging vertex into both cell rings")
        active.append(i)
    return {"areas_m2": areas, "centres_m": centres, "tolerance_m": tol,
            "boundary_edges": [list(k) for k, owners in edges.items() if len(owners) == 1],
            "interior_edges": [list(k) for k, owners in edges.items() if len(owners) == 2],
            "candidate_pairs": pair_count}


@dataclass(frozen=True)
class PlanarMesh:
    """Immutable validated canonical JSON; direct construction is revalidated by operations."""
    _json: str

    @classmethod
    def from_dict(cls, value):
        _validate(value)
        return cls(_canonical(value).decode())

    def to_dict(self):
        value = json.loads(self._json)
        _validate(value)
        return value


def topology(mesh):
    value = mesh.to_dict()
    report = _validate(value)
    return {"schema": "basinlens-mesh-topology-v1", "cells": len(value["cells"]),
            "vertices": len(value["vertices"]), "area_m2": math.fsum(report["areas_m2"]), **report,
            "original_gms_comparison": "NOT_OBSERVED", "crs_transform_performed": False}


def _mesh_from_rings(rings, materials, crs, provenance):
    coordinates, lookup, cells = [], {}, []
    for ring, material in zip(rings, materials):
        ids = []
        for coordinate in ring:
            coordinate = tuple(coordinate)
            if coordinate not in lookup:
                lookup[coordinate] = len(coordinates)
                coordinates.append({"id": len(coordinates), "x_m": coordinate[0], "y_m": coordinate[1]})
            ids.append(lookup[coordinate])
        cells.append({"id": len(cells), "vertices": ids, "material_id": material})
    return PlanarMesh.from_dict({"schema": SCHEMA, "length_unit": "m", "crs": crs,
                                 "vertices": coordinates, "cells": cells, "provenance": provenance})


def _edges(values, label):
    if not isinstance(values, (list, tuple)) or not 2 <= len(values) <= 1001:
        raise MeshError(f"{label} requires 2..1001 coordinates")
    values = [_number(v, label) for v in values]
    if any(b <= a for a, b in zip(values, values[1:])):
        raise MeshError(f"{label} must be strictly increasing")
    return values


def structured_mesh(x_edges_m, y_edges_m, *, crs, material_id="unassigned", triangulate=None):
    """Nonuniform rectangular frame; optional explicit SW-NE or NW-SE diagonal."""
    xs, ys = _edges(x_edges_m, "x_edges_m"), _edges(y_edges_m, "y_edges_m")
    _text(crs, "crs")
    _text(material_id, "material_id")
    if triangulate not in (None, "sw_ne", "nw_se"):
        raise MeshError("triangulate must be null, sw_ne or nw_se")
    count = (len(xs) - 1) * (len(ys) - 1) * (2 if triangulate else 1)
    if count > MAX_CELLS:
        raise MeshError("Structured generation exceeds cell budget")
    rings = []
    for south, north in zip(ys, ys[1:]):
        for west, east in zip(xs, xs[1:]):
            sw, se, ne, nw = (west, south), (east, south), (east, north), (west, north)
            rings.extend([[sw, se, ne], [sw, ne, nw]] if triangulate == "sw_ne" else
                         [[sw, se, nw], [se, ne, nw]] if triangulate == "nw_se" else [[sw, se, ne, nw]])
    return _mesh_from_rings(rings, [material_id] * count, crs,
                            ["Authored synthetic nonuniform structured frame; no inferred geology or original GMS data"])


def refine_quadtree(mesh, *, levels=1, bbox_m=None, points_m=(), max_cells=MAX_CELLS):
    """Split selected axis-aligned rectangle leaves; conform interfaces explicitly.

    Levels count additional recursive splits, not absolute depth. No 2:1 balance
    is imposed. Point selection includes every leaf touching the literal point.
    """
    data = mesh.to_dict()
    _integer(levels, 1, 8, "levels")
    _integer(max_cells, 1, MAX_CELLS, "max_cells")
    if bbox_m is not None:
        if not isinstance(bbox_m, (tuple, list)) or len(bbox_m) != 4:
            raise MeshError("bbox_m requires [xmin, ymin, xmax, ymax]")
        bbox_m = [_number(v, "bbox_m") for v in bbox_m]
        if bbox_m[0] >= bbox_m[2] or bbox_m[1] >= bbox_m[3]:
            raise MeshError("bbox_m must have positive width and height")
    if not isinstance(points_m, (list, tuple)) or len(points_m) > 1000:
        raise MeshError("points_m exceeds point budget")
    points = []
    for point in points_m:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise MeshError("Each point requires exactly two meter coordinates")
        points.append(tuple(_number(v, "points_m") for v in point))
    operation = _canonical({"operation": "rectangle_refinement", "additional_levels": levels,
                            "bbox_m": bbox_m, "points_m": points, "max_cells": max_cells, "balancing": "none",
                            "source_mesh_sha256": hashlib.sha256(_canonical(data)).hexdigest()}).decode().strip()
    chunks = [operation[i:i + 450] for i in range(0, len(operation), 450)]
    notes = [f"Refinement record JSON {i + 1}/{len(chunks)}: {chunk}" for i, chunk in enumerate(chunks)]
    if len(data["provenance"]) + len(notes) > 64:
        raise MeshError("Refinement selector/history exceeds provenance note budget")
    coordinates = [(v["x_m"], v["y_m"]) for v in data["vertices"]]
    leaves = []
    for cell in data["cells"]:
        ring = [coordinates[v] for v in cell["vertices"]]
        west, east = min(x for x, y in ring), max(x for x, y in ring)
        south, north = min(y for x, y in ring), max(y for x, y in ring)
        if not all(x in (west, east) or y in (south, north) for x, y in ring) or any(
                a[0] != b[0] and a[1] != b[1] for a, b in zip(ring, ring[1:] + ring[:1])):
            raise MeshError("Quadtree refinement requires axis-aligned rectangular cells, including optional collinear interface vertices")
        if not all(corner in ring for corner in ((west, south), (east, south), (east, north), (west, north))):
            raise MeshError("Rectangular cells must contain all four corners")
        leaves.append((west, south, east, north, cell["material_id"]))
    if len(leaves) > max_cells:
        raise MeshError("Existing mesh exceeds max_cells")
    for _ in range(levels):
        refined = []
        for west, south, east, north, material in leaves:
            selected = ((bbox_m is None and not points) or
                        bbox_m is not None and west < bbox_m[2] and east > bbox_m[0] and south < bbox_m[3] and north > bbox_m[1] or
                        any(west <= x <= east and south <= y <= north for x, y in points))
            if selected:
                mx, my = (west + east) / 2, (south + north) / 2
                refined.extend((w, s, e, n, material) for w, s, e, n in
                               ((west, south, mx, my), (mx, south, east, my), (mx, my, east, north), (west, my, mx, north)))
            else:
                refined.append((west, south, east, north, material))
            if len(refined) > max_cells:
                raise MeshError("Quadtree refinement exceeds max_cells; source mesh is unchanged")
        leaves = refined
    vertices = {(x, y) for w, s, e, n, _ in leaves for x, y in ((w, s), (e, s), (e, n), (w, n))}
    horizontal, vertical = {}, {}
    for x, y in vertices:
        horizontal.setdefault(y, []).append(x)
        vertical.setdefault(x, []).append(y)
    for axis in (horizontal, vertical):
        for line in axis.values():
            line.sort()
    rings, materials = [], []
    for w, s, e, n, material in leaves:
        bottom = horizontal[s][bisect_left(horizontal[s], w):bisect_left(horizontal[s], e)]
        right = vertical[e][bisect_left(vertical[e], s):bisect_left(vertical[e], n)]
        top = horizontal[n][bisect_right(horizontal[n], w):bisect_right(horizontal[n], e)]
        left = vertical[w][bisect_right(vertical[w], s):bisect_right(vertical[w], n)]
        rings.append([(x, s) for x in bottom] + [(e, y) for y in right] +
                     [(x, n) for x in reversed(top)] + [(w, y) for y in reversed(left)])
        materials.append(material)
    return _mesh_from_rings(rings, materials, data["crs"], data["provenance"] + notes)


def _surfaces(values, ncells):
    if not isinstance(values, (tuple, list)) or not 2 <= len(values) <= 65:
        raise MeshError("layer_surfaces_m requires 2..65 explicit flat descending elevations")
    surfaces = [_number(value, "layer surface") for value in values]
    if any(a - b < 1e-6 for a, b in zip(surfaces, surfaces[1:])):
        raise MeshError("Layer elevations must strictly descend with thickness >= 1e-6 m")
    if (len(surfaces) - 1) * ncells > 100000:
        raise MeshError("Extrusion exceeds prism cell budget")
    return surfaces


def extrude_mesh(mesh, layer_surfaces_m, *, vertical_datum, material_ids=None):
    """Explicit flat layers and outward oriented closed convex prism shells."""
    data = mesh.to_dict()
    _text(vertical_datum, "vertical_datum")
    surfaces = _surfaces(layer_surfaces_m, len(data["cells"]))
    count = (len(surfaces) - 1) * len(data["cells"])
    if material_ids is None:
        material_ids = [cell["material_id"] for _ in surfaces[:-1] for cell in data["cells"]]
    if not isinstance(material_ids, (list, tuple)) or len(material_ids) != count:
        raise MeshError("material_ids must map every prism in layer-major/cell order")
    for value in material_ids:
        _text(value, "material_id")
    if (len(surfaces) - 1) * sum(len(cell["vertices"]) for cell in data["cells"]) * 8 > 2000000:
        raise MeshError("Extrusion exceeds face/node connectivity budget")
    nvertex = len(data["vertices"])
    if nvertex * len(surfaces) > 300000:
        raise MeshError("Extrusion exceeds node count budget")
    nodes = [{"id": level * nvertex + v["id"], "x_m": v["x_m"], "y_m": v["y_m"], "z_m": elevation}
             for level, elevation in enumerate(surfaces) for v in data["vertices"]]
    report, prisms, ownership = _validate(data), [], {}
    node_materials = [set() for _ in nodes]
    for layer in range(len(surfaces) - 1):
        for cell in data["cells"]:
            top = [layer * nvertex + v for v in cell["vertices"]]
            bottom = [(layer + 1) * nvertex + v for v in cell["vertices"]]
            faces = [top, list(reversed(bottom))] + [[bottom[i], bottom[(i + 1) % len(top)], top[(i + 1) % len(top)], top[i]] for i in range(len(top))]
            for face in faces:
                key = tuple(sorted(face))
                owners = ownership.setdefault(key, [])
                owners.append(face)
                if len(owners) > 2:
                    raise MeshError("Extruded face has more than two owners")
                if len(owners) == 2:
                    reversed_other = list(reversed(owners[0]))
                    start = reversed_other.index(face[0])
                    if reversed_other[start:] + reversed_other[:start] != face:
                        raise MeshError("Extruded shared face orientations disagree")
            # Each cell shell independently requires two opposite oriented uses
            # per edge, not just a volume computed from area times thickness.
            shell_edges = {}
            for face in faces:
                for a, b in zip(face, face[1:] + face[:1]):
                    shell_edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
            if any(len(owners) != 2 or owners[0] != owners[1][::-1] for owners in shell_edges.values()):
                raise MeshError("Extruded cell shell is not closed and consistently oriented")
            index = len(prisms)
            for node_id in top + bottom:
                node_materials[node_id].add(material_ids[index])
            prisms.append({"id": index, "layer": layer, "planar_cell_id": cell["id"], "node_ids": top + bottom,
                           "faces": faces, "volume_m3": report["areas_m2"][cell["id"]] * (surfaces[layer] - surfaces[layer + 1]),
                           "material_id": material_ids[index]})
    for node, materials in zip(nodes, node_materials):
        node["material_ids"] = sorted(materials)
    return {"schema": "basinlens-flat-prism-mesh-v1", "length_unit": "m", "crs": data["crs"],
            "vertical_datum": vertical_datum, "layer_surfaces_m": surfaces, "nodes": nodes, "cells": prisms,
            "planar_mesh_sha256": hashlib.sha256(_canonical(data)).hexdigest(), "provenance": data["provenance"],
            "total_volume_m3": math.fsum(cell["volume_m3"] for cell in prisms),
            "boundary_faces": sum(len(owners) == 1 for owners in ownership.values()),
            "interior_faces": sum(len(owners) == 2 for owners in ownership.values()),
            "original_gms_comparison": "NOT_OBSERVED", "horizon_interpolation_performed": False}


def to_disv(mesh, layer_surfaces_m):
    """Return zero-based FloPy DISV kwargs with clockwise shared-vertex rings.

    Callers writing through FloPy must set simulation_data.float_precision=17
    and float_characters=26 and verify a reload before executing. Defaults can
    round large-origin coordinates by millimeters; no tolerance is widened here.
    """
    data = mesh.to_dict()
    surfaces = _surfaces(layer_surfaces_m, len(data["cells"]))
    report = _validate(data)
    return {"length_units": "METERS", "nlay": len(surfaces) - 1, "ncpl": len(data["cells"]),
            "nvert": len(data["vertices"]), "vertices": [[v["id"], v["x_m"], v["y_m"]] for v in data["vertices"]],
            "cell2d": [[cell["id"], *report["centres_m"][cell["id"]], len(cell["vertices"]), *reversed(cell["vertices"])] for cell in data["cells"]],
            "top": [surfaces[0]] * len(data["cells"]),
            "botm": [[elevation] * len(data["cells"]) for elevation in surfaces[1:]]}


def render_data(mesh):
    """Explicit closed XY rings and labels; no implicit raster or CRS conversion."""
    data = mesh.to_dict()
    report = _validate(data)
    vertices = [(v["x_m"], v["y_m"]) for v in data["vertices"]]
    return {"schema": "basinlens-mesh-render-v1", "length_unit": "m", "crs": data["crs"],
            "cells": [{"id": cell["id"], "material_id": cell["material_id"],
                       "ring_m": [list(vertices[v]) for v in cell["vertices"] + cell["vertices"][:1]],
                       "centre_m": list(report["centres_m"][cell["id"]]), "area_m2": report["areas_m2"][cell["id"]]}
                      for cell in data["cells"]]}


def _safe_path(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise MeshError("Mesh paths must not traverse symbolic links")
    return path


def _read(path):
    path = _safe_path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise MeshError("Mesh input must be a bounded regular file")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > MAX_BYTES or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise MeshError("Mesh source changed during reading or exceeds byte budget")
    return raw


def _write(value, output):
    output = _safe_path(output)
    raw = _canonical(value)
    if len(raw) > MAX_BYTES:
        raise MeshError("Serialized mesh artifact exceeds byte budget")
    if output.exists():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise MeshError("Output parent must already exist")
    fd, temporary = tempfile.mkstemp(prefix=".mesh-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)  # Atomic exclusive publication, no overwrites.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output


def read_mesh(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MeshError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        data = json.loads(_read(path), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(MeshError("Nonfinite JSON constant")))
        return PlanarMesh.from_dict(data)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MeshError(f"Invalid mesh JSON: {type(exc).__name__}") from exc


def write_mesh(mesh, output):
    return _write(mesh.to_dict(), output)


def verify_mesh_roundtrip(path):
    raw = _read(path)
    source = read_mesh(path)
    with tempfile.TemporaryDirectory(prefix="basinlens-mesh-roundtrip-") as folder:
        moved = write_mesh(source, Path(folder) / "relocated.mesh.json")
        loaded = read_mesh(moved)
        if source.to_dict() != loaded.to_dict():
            raise MeshError("Mesh roundtrip changed data")
    if _read(path) != raw:
        raise MeshError("Source changed during roundtrip verification")
    return {"schema": "basinlens-mesh-roundtrip-v1", "source_sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_sha256": hashlib.sha256(_canonical(source.to_dict())).hexdigest(),
            "exact_semantic_roundtrip": True, "source_unchanged": True,
            "topology": topology(source), "original_gms_comparison": "NOT_OBSERVED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--x-edges", type=float, nargs="+", required=True)
    generate.add_argument("--y-edges", type=float, nargs="+", required=True)
    generate.add_argument("--crs", required=True)
    generate.add_argument("--material-id", default="unassigned")
    generate.add_argument("--triangulate", choices=("sw_ne", "nw_se"))
    generate.add_argument("--output", required=True)
    for name in ("refine", "extrude", "verify", "render-data", "disv-data"):
        command = commands.add_parser(name)
        command.add_argument("source")
        if name != "verify":
            command.add_argument("--output", required=True)
        if name == "refine":
            command.add_argument("--levels", type=int, default=1)
            command.add_argument("--bbox", type=float, nargs=4)
            command.add_argument("--point", type=float, nargs=2, action="append", default=[])
            command.add_argument("--max-cells", type=int, default=MAX_CELLS)
        if name in ("extrude", "disv-data"):
            command.add_argument("--surfaces", type=float, nargs="+", required=True)
        if name == "extrude":
            command.add_argument("--vertical-datum", required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        mesh = structured_mesh(args.x_edges, args.y_edges, crs=args.crs, material_id=args.material_id, triangulate=args.triangulate)
        result = {"output": str(write_mesh(mesh, args.output)), "topology": topology(mesh)}
    else:
        mesh = read_mesh(args.source)
        if args.command == "verify":
            result = verify_mesh_roundtrip(args.source)
        elif args.command == "refine":
            refined = refine_quadtree(mesh, levels=args.levels, bbox_m=args.bbox, points_m=args.point, max_cells=args.max_cells)
            result = {"output": str(write_mesh(refined, args.output)), "topology": topology(refined)}
        else:
            value = extrude_mesh(mesh, args.surfaces, vertical_datum=args.vertical_datum) if args.command == "extrude" else to_disv(mesh, args.surfaces) if args.command == "disv-data" else render_data(mesh)
            result = {"output": str(_write(value, args.output))}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
