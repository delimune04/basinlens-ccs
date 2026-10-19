"""Read one observed QuadtreeGrid3d v1 / XmUGrid v2 mesh representation.

Only level-zero, single-layer meshes made of closed six-quadrilateral-face
polyhedra are supported. QUAD arrays and wrapper origins remain uninterpreted;
physical coordinates come directly from embedded XmUGrid locations.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import re

import numpy as np

from .gpr_geometry import GprGeometryError, _Packet
from .gpr_hdf5 import GprInspectionError, MAX_GPR_BYTES, read_gpr_numeric_array

MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_CELLS = 100000
MAX_POINTS = 500000
MAX_OPAQUE_ITEMS = 2000000


class UnstructuredMeshError(GprInspectionError):
    """The packet or comparison exceeds the measured supported representation."""


def _check(condition, message):
    if not condition:
        raise UnstructuredMeshError(message)


def _vector(packet, key, dtype, *, maximum, count=None, width=1):
    position = packet.stream.tell()
    header = packet.line().split()
    _check(len(header) == 2 and header[0] == key and header[1].isascii() and header[1].isdigit()
           and 0 < int(header[1]) <= maximum, "Unsupported vector header or element count")
    packet.stream.seek(position)
    return packet.vector(key, dtype, count=count, width=width)


def _cycle_key(face):
    values = tuple(int(value) for value in face)
    return min(values[index:] + values[:index] for index in range(4))


@dataclass(frozen=True)
class QuadtreeMesh:
    points: np.ndarray
    faces: np.ndarray
    upper_faces: np.ndarray
    lower_faces: np.ndarray
    cell_tops: np.ndarray
    cell_bottoms: np.ndarray
    cell_layers: np.ndarray
    wrapper: dict
    topology: dict
    packet_sha256: str
    source: dict = field(default_factory=dict)

    @property
    def upper_polygons(self):
        return self.points[self.upper_faces]

    def receipt(self):
        return {"schema": "basinlens-gpr-quadtree-mesh-v1", "node_count": len(self.points),
                "cell_count": len(self.faces), "faces_per_cell": 6, "nodes_per_face": 4,
                "cell_type": "polyhedron_42", "single_layer": True, "refinement_levels": 0,
                "topology": self.topology, "packet_sha256": self.packet_sha256,
                "wrapper_quad_arrays_interpreted": False, "wrapper_origin_or_axis_transform_applied": False,
                "physical_coordinate_source": "embedded XmUGrid locations, unchanged",
                "coordinate_units": None, "crs": None, "vertical_datum": None,
                "raw_coordinates_included": False, "units_converted": False,
                "source": {key: self.source[key] for key in ("bytes", "sha256", "identity_verified_after_read") if key in self.source},
                "gms_runtime_executed": False,
                "scope": "One measured mesh representation only; no QUAD pointer semantics, project synchronization or full GMS equivalence."}


def _decode(data):
    _check(type(data) is bytes and 0 < len(data) <= MAX_PACKET_BYTES, "Packet byte budget exceeded")
    packet = _Packet(data)
    packet.expect("Binary QuadtreeGrid3d Version 1")
    packet.expect("DIMENSIONS 3")
    origin_record = packet.line().split()
    angle_record = packet.line().split()
    _check(len(origin_record) == 4 and origin_record[0] == "ORIGIN"
           and len(angle_record) == 2 and angle_record[0] == "ANGLE", "Unsupported wrapper origin/angle record")
    try:
        origin = np.array([float(value) for value in origin_record[1:]])
        angle = float(angle_record[1])
    except ValueError as error:
        raise UnstructuredMeshError("Invalid wrapper origin/angle") from error
    _check(np.isfinite(origin).all() and angle == 0, "Only finite-origin, unrotated wrappers are supported")
    packet.expect("NUMBERING KIJ")
    packet.expect("ORIENTATION Y_DECREASE X_INCREASE Z_DECREASE")
    axes = tuple(_vector(packet, "LOCATIONS_" + axis, "<f8", maximum=10000) for axis in "XYZ")
    _check(all(len(axis) >= 2 and np.all(np.diff(axis) > 0) for axis in axes)
           and len(axes[2]) == 2, "Only increasing axes and one vertical interval are supported")
    packet.expect("NUM_LEVELS 0")
    opaque_counts = (math.prod(len(axis) - 1 for axis in axes), math.prod(map(len, axes)))
    _check(max(opaque_counts) <= MAX_OPAQUE_ITEMS, "Opaque wrapper array budget exceeded")
    opaque = tuple(_vector(packet, key, "<i4", maximum=MAX_OPAQUE_ITEMS, count=count)
                   for key, count in zip(("QUAD_GRID_CELL_ARRAY", "QUAD_GRID_POINT_ARRAY"), opaque_counts))
    packet.expect("Binary XmUGrid Version 2")
    points = _vector(packet, "LOCATIONS", "<f8", maximum=MAX_POINTS, width=3)
    stream = _vector(packet, "CELL_STREAM", "<i4", maximum=MAX_CELLS * 32)
    _check(len(stream) % 32 == 0, "Only fixed six-quad polyhedron records are supported")
    cells = stream.reshape((-1, 32))
    count = len(cells)
    _check(np.all(cells[:, 0] == 42) and np.all(cells[:, 1] == 6)
           and np.all(cells[:, [2, 7, 12, 17, 22, 27]] == 4), "Only type-42 polyhedra with six quadrilateral faces are supported")
    faces = cells[:, np.array([3, 8, 13, 18, 23, 28])[:, None] + np.arange(4)]
    _check(np.all((faces >= 0) & (faces < len(points))), "Face node index out of range")
    record = packet.line()
    if record.startswith("CELL_ORDER "):
        _check(record == "CELL_ORDER INCREASING_DOWN", "Unsupported embedded cell order")
        record = packet.line()
    _check(re.fullmatch(r"UUID [0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", record), "Expected canonical UUID record")
    tops = _vector(packet, "CELL_TOPS", "<f8", maximum=MAX_CELLS, count=count)
    bottoms = _vector(packet, "CELL_BOTTOMS", "<f8", maximum=MAX_CELLS, count=count)
    layers = _vector(packet, "CELL_LAYERS", "<i4", maximum=MAX_CELLS, count=count)
    _check(packet.line(optional=True) is None, "Unsupported trailing packet records")
    _check(np.all(tops > bottoms) and np.all(layers == 1), "Only positive-thickness single-layer cells are supported")

    upper = np.empty((count, 4), dtype="i4")
    lower = np.empty((count, 4), dtype="i4")
    owners, directions, seen_cells = Counter(), {}, set()
    for index, cell in enumerate(faces):
        vertex_ids = tuple(sorted(set(int(value) for value in cell.flat)))
        _check(len(vertex_ids) == 8 and vertex_ids not in seen_cells, "Duplicate or non-eight-node cell")
        seen_cells.add(vertex_ids)
        edges, directed = Counter(), Counter()
        for face in cell:
            _check(len(set(face)) == 4, "Repeated node in a face")
            face_key = tuple(sorted(int(value) for value in face))
            forward = _cycle_key(face)
            backward = _cycle_key(face[::-1])
            if face_key in directions:
                _check(directions[face_key] == backward, "Shared face winding is inconsistent")
            else:
                directions[face_key] = forward
            owners[face_key] += 1
            _check(owners[face_key] <= 2, "Nonmanifold shared face")
            for first, second in zip(face, np.roll(face, -1)):
                edge = (int(first), int(second))
                directed[edge] += 1
                edges[tuple(sorted(edge))] += 1
        _check(len(edges) == 12 and set(edges.values()) == {2}
               and all(directed[(second, first)] == value for (first, second), value in directed.items()),
               "Cell faces are not a closed consistently wound hexahedral boundary")
        z = points[cell, 2]
        top_indices = np.flatnonzero(np.all(z == tops[index], axis=1))
        bottom_indices = np.flatnonzero(np.all(z == bottoms[index], axis=1))
        _check(len(top_indices) == len(bottom_indices) == 1, "Physical faces disagree with cell top/bottom elevations")
        top_face, bottom_face = cell[top_indices[0]], cell[bottom_indices[0]]
        upper[index], lower[index] = top_face, bottom_face
        top_xy, bottom_xy = points[top_face, :2], points[bottom_face, :2]
        _check(len(set(map(tuple, top_xy))) == 4 and set(map(tuple, top_xy)) == set(map(tuple, bottom_xy)),
               "Only extruded quadrilateral cell footprints are supported")
        edges_xy = np.roll(top_xy, -1, axis=0) - top_xy
        crosses = edges_xy[:, 0] * np.roll(edges_xy, -1, axis=0)[:, 1] - edges_xy[:, 1] * np.roll(edges_xy, -1, axis=0)[:, 0]
        _check(np.isfinite(crosses).all() and (np.all(crosses > 0) or np.all(crosses < 0)), "Only nondegenerate convex quadrilateral footprints are supported")
        bottom_by_xy = {tuple(points[node, :2]): int(node) for node in bottom_face}
        side_keys = set()
        for first, second in zip(top_face, np.roll(top_face, -1)):
            bottom_first = bottom_by_xy[tuple(points[first, :2])]
            bottom_second = bottom_by_xy[tuple(points[second, :2])]
            side_keys.add(tuple(sorted((int(first), int(second), bottom_first, bottom_second))))
        actual_sides = {tuple(sorted(int(value) for value in face)) for face in cell
                        if not np.array_equal(face, top_face) and not np.array_equal(face, bottom_face)}
        _check(side_keys == actual_sides, "Side faces do not connect corresponding footprint edges")
    topology = {"closed_cells_verified": count, "boundary_faces": sum(value == 1 for value in owners.values()),
                "shared_faces": sum(value == 2 for value in owners.values()), "maximum_face_owners": max(owners.values()),
                "unused_points": len(points) - len(np.unique(faces)), "face_winding_verified": True}
    for array in (points, faces, upper, lower, tops, bottoms, layers, origin, *axes, *opaque):
        array.flags.writeable = False
    wrapper = {"origin": origin, "angle": angle, "axes": axes, "opaque_quad_arrays": opaque}
    return QuadtreeMesh(points, faces, upper, lower, tops, bottoms, layers, wrapper, topology, hashlib.sha256(data).hexdigest())


def decode_quadtree_packet(data: bytes) -> QuadtreeMesh:
    try:
        return _decode(data)
    except GprGeometryError as error:
        raise UnstructuredMeshError(str(error)) from error


def _identity(path):
    _check(path.is_file() and path.stat().st_size <= MAX_GPR_BYTES, "Project file byte budget exceeded")
    value, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            size += len(block)
            _check(size <= MAX_GPR_BYTES, "Project file byte budget exceeded")
            value.update(block)
    return {"bytes": size, "sha256": value.hexdigest()}


def read_gpr_quadtree(path: str | Path, grid_group: str) -> QuadtreeMesh:
    path = Path(path).resolve(strict=True)
    before = _identity(path)
    array, storage = read_gpr_numeric_array(path, grid_group.rstrip("/") + "/Geometry.xmsgrid", max_bytes=MAX_PACKET_BYTES)
    _check(array.ndim == 1 and array.dtype.kind in "iu" and array.dtype.itemsize == 1, "Expected a one-dimensional geometry byte vector")
    mesh = decode_quadtree_packet(array.astype("u1", copy=False).tobytes())
    _check(before == _identity(path), "Project bytes changed during mesh inspection")
    object.__setattr__(mesh, "source", {**before, "identity_verified_after_read": True, "private_storage": storage})
    return mesh


def compare_with_disv(mesh: QuadtreeMesh, model) -> dict:
    """Compare stored cell order and literal coordinates; perform no repairs."""
    dis = getattr(model, "disv", None)
    _check(dis is not None and int(dis.nlay.get_data()) == 1, "A single-layer native DISV model is required")
    count, nvert = int(dis.ncpl.get_data()), int(dis.nvert.get_data())
    _check(count == len(mesh.faces) and 0 < nvert <= MAX_POINTS, "Native DISV cell/vertex counts are unsupported")
    vertices, records = dis.vertices.array, dis.cell2d.array
    _check(len(vertices) == nvert and len(records) == count, "Native DISV record counts disagree")
    ids = np.asarray(vertices["iv"])
    _check(np.issubdtype(ids.dtype, np.integer) and np.array_equal(np.sort(ids), np.arange(nvert)),
           "Unsupported native vertex ID type or domain")
    xy = np.empty((nvert, 2))
    native_grid = model.modelgrid
    transformed = native_grid.get_coords(vertices["xv"], vertices["yv"])
    xy[ids] = np.column_stack(transformed)
    _check(np.isfinite(xy).all(), "Non-finite native vertices")
    _check(np.issubdtype(records["icell2d"].dtype, np.integer)
           and np.array_equal(np.sort(records["icell2d"]), np.arange(count)), "Unsupported native cell ID type or domain")
    polygons = mesh.upper_polygons[:, :, :2]
    polygon_error, center_error = 0.0, 0.0
    for row in records:
        cell_id, corners = int(row["icell2d"]), int(row["ncvert"])
        _check(corners == 4 and len(row.dtype.names) >= 8, "Only four-vertex native DISV cells are supported")
        vertex_ids = np.array([int(row[name]) for name in row.dtype.names[4:8]])
        _check(np.all((vertex_ids >= 0) & (vertex_ids < nvert)) and len(set(vertex_ids)) == 4, "Invalid native cell polygon")
        native = xy[vertex_ids]
        error = min(float(np.max(np.abs(polygons[cell_id] - np.roll(cycle, shift, axis=0))))
                    for cycle in (native, native[::-1]) for shift in range(4))
        polygon_error = max(polygon_error, error)
        reference_center = native_grid.get_coords(float(row["xc"]), float(row["yc"]))
        _check(np.isfinite(reference_center).all(), "Non-finite native reference center")
        center_error = max(center_error, float(np.max(np.abs((polygons[cell_id] / 4).sum(axis=0) - reference_center))))
    mesh_xy, xy_multiplicity = np.unique(mesh.points[:, :2], axis=0, return_counts=True)
    native_xy = np.unique(xy, axis=0)
    same_count = len(mesh_xy) == len(native_xy) == nvert
    vertex_error = float(np.max(np.abs(mesh_xy - native_xy))) if same_count else None
    top, bottom = np.asarray(dis.top.array), np.asarray(dis.botm.array)
    _check(top.shape == (count,) and bottom.shape == (1, count) and np.isfinite(top).all() and np.isfinite(bottom).all(), "Unsupported native elevation arrays")
    upper_error = float(np.max(np.abs(mesh.points[mesh.upper_faces, 2] - top[:, None])))
    lower_error = float(np.max(np.abs(mesh.points[mesh.lower_faces, 2] - bottom[0, :, None])))
    _check(all(np.isfinite(value) for value in (polygon_error, center_error, upper_error, lower_error))
           and (vertex_error is None or np.isfinite(vertex_error)), "Non-finite coordinate comparison")
    footprint_match = polygon_error == 0
    vertex_match = same_count and vertex_error == 0
    # For this single-layer representation, shared horizontal connectivity also
    # requires one physical upper/lower node pair per native XY vertex. Equal
    # coordinates alone could hide disconnected duplicate nodes along cell edges.
    pair_topology_match = vertex_match and np.all(xy_multiplicity == 2) and mesh.topology["unused_points"] == 0
    z_match = upper_error == lower_error == 0
    return {"compared_cells": count, "native_xy_vertices": nvert, "gpr_unique_xy_vertices": len(mesh_xy),
            "cell_order": "GPR stream index versus declared native cell2d ID (FloPy zero-based)",
            "all_cell_footprints_match": footprint_match, "all_xy_vertices_match": vertex_match,
            "single_layer_xy_node_pair_topology_matches": bool(pair_topology_match),
            "maximum_nodes_per_xy_vertex": int(xy_multiplicity.max()),
            "all_face_corner_z_match": z_match,
            "full_3d_mesh_coordinate_match": bool(footprint_match and vertex_match and pair_topology_match and z_match),
            "max_absolute_coordinate_error": {"cell_polygon_xy": polygon_error,
                "lexicographic_unique_xy_vertices": vertex_error, "upper_corner_z_vs_cell_top": upper_error,
                "lower_corner_z_vs_cell_bottom": lower_error},
            "native_reference_center_vs_gpr_corner_mean_max_error": center_error,
            "native_reference_center_comparison_is_diagnostic_only": True,
            "native_origin_options_present": {name: getattr(dis, name).get_data() is not None for name in ("xorigin", "yorigin", "angrot")},
            "native_length_units": dis.length_units.get_data(), "gpr_coordinate_units": None,
            "units_converted": False, "origin_or_z_repair_applied": False,
            "physical_or_runtime_equivalence_claimed": False,
            "scope": "Literal same-index footprints, vertex set, and flat-face elevations only; unknown GPR units/CRS/datum remain unknown."}
