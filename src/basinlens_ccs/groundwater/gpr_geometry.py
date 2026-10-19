"""Read a narrow, verified rectilinear Geometry.xmsgrid representation.

The block framing and embedded XmUGrid v2 are documented by public Aquaveo
xmscore/xmsgrid serializers. Rectilinear wrapper fields were observed in one
official tutorial. This original reader supports zero-origin, unrotated KIJ
hexahedra only; it is not a general GPR reader or a project writer.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import io
import math
from pathlib import Path
import re
import zlib

import numpy as np

from .gpr_hdf5 import GprInspectionError, MAX_GPR_BYTES, read_gpr_numeric_array


MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_BLOCK_BYTES = 1024 * 1024
MAX_CELLS = 1_000_000


class GprGeometryError(GprInspectionError):
    """The geometry lies outside the explicitly supported representation."""


def _require(condition, message):
    if not condition:
        raise GprGeometryError(message)


class _Packet:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.decoded_bytes = 0

    def line(self, *, optional=False):
        while True:
            raw = self.stream.readline(513)
            if not raw:
                _require(optional, "Truncated geometry packet")
                return None
            _require(len(raw) <= 512, "Geometry control line exceeds limit")
            try:
                text = raw.decode("ascii").strip()
            except UnicodeError as error:
                raise GprGeometryError("Non-ASCII geometry control line") from error
            if text:
                return text

    def expect(self, text):
        _require(self.line() == text, f"Expected supported control record: {text}")

    def vector(self, key, dtype, *, count=None, width=1):
        header = self.line().split()
        _require(len(header) == 2 and header[0] == key and header[1].isdigit(),
                 f"Expected vector record {key}")
        elements = int(header[1])
        _require(0 < elements <= MAX_CELLS * 10, "Vector element count exceeds limit")
        _require(count is None or elements == count, f"Unexpected {key} element count")
        size = elements * width * np.dtype(dtype).itemsize
        _require(self.decoded_bytes + size <= MAX_DECODED_BYTES, "Decoded geometry byte budget exceeded")
        self.decoded_bytes += size
        result = bytearray()
        while len(result) < size:
            header = self.line().split()
            _require(len(header) == 3 and header[0] == "BINARY_BLOCK"
                     and header[1].isdigit() and header[2].isdigit(), "Invalid binary block header")
            encoded_size, raw_size = map(int, header[1:])
            _require(0 < raw_size <= min(MAX_BLOCK_BYTES, size - len(result))
                     and 0 < encoded_size <= 2 * MAX_BLOCK_BYTES, "Binary block exceeds limit")
            encoded = self.stream.read(encoded_size)
            _require(len(encoded) == encoded_size, "Truncated binary block")
            _require(self.stream.readline(3) in (b"\n", b"\r\n"), "Missing binary block line ending")
            try:
                compressed = base64.b64decode(encoded + b"=" * (-len(encoded) % 4), validate=True)
                inflater = zlib.decompressobj()
                raw = inflater.decompress(compressed, raw_size + 1)
            except (ValueError, zlib.error) as error:
                raise GprGeometryError("Invalid base64 or deflate block") from error
            _require(len(raw) == raw_size and inflater.eof and not inflater.unused_data
                     and not inflater.unconsumed_tail, "Deflate block size or stream boundary mismatch")
            result.extend(raw)
        array = np.frombuffer(bytes(result), dtype=dtype)
        _require(np.isfinite(array).all(), f"Non-finite values in {key}")
        return array.reshape((elements, width)) if width != 1 else array


@dataclass(frozen=True)
class RectilinearGeometry:
    """Arrays use verified flat KIJ order: layer, decreasing Y row, increasing X column."""

    shape: tuple[int, int, int]
    points: np.ndarray
    cells: np.ndarray
    axes: tuple[np.ndarray, np.ndarray, np.ndarray]
    cell_tops: np.ndarray
    cell_bottoms: np.ndarray
    cell_layers: np.ndarray
    packet_sha256: str
    source: dict = field(default_factory=dict)

    @property
    def centers(self):
        return (self.points[self.cells] / 8).sum(axis=1).reshape((*self.shape, 3))

    def receipt(self):
        return {"schema": "basinlens-gpr-rectilinear-v1", "shape_kij": list(self.shape),
                "node_count": len(self.points), "cell_count": len(self.cells),
                "cell_type": "hexahedron", "flat_order": "C: layer,row,column",
                "orientation": ["Y_DECREASE", "X_INCREASE", "Z_DECREASE"],
                "bounds_xyz": [self.points.min(axis=0).tolist(), self.points.max(axis=0).tolist()],
                "parametric_z_axis": self.axes[2].tolist(),
                "physical_z_source": "embedded points and explicit cell elevations",
                "coordinate_units": None, "crs": None, "vertical_datum": None,
                "units_converted": False, "packet_sha256": self.packet_sha256,
                "source": self.source, "gms_runtime_executed": False,
                "scope": "Supported geometry only; no complete project reconstruction or runtime equivalence."}


def decode_rectilinear_packet(data: bytes) -> RectilinearGeometry:
    """Decode bounded little-endian v1/v2 geometry; reject unsupported mappings."""
    _require(type(data) is bytes and 0 < len(data) <= MAX_PACKET_BYTES, "Geometry packet byte limit exceeded")
    packet = _Packet(data)
    packet.expect("Binary RectilinearGrid3d Version 1")
    packet.expect("DIMENSIONS 3")
    origin = packet.line().split()
    angle = packet.line().split()
    try:
        _require(len(origin) == 4 and origin[0] == "ORIGIN"
                 and all(float(value) == 0 for value in origin[1:]), "Only zero origin is supported")
        _require(len(angle) == 2 and angle[0] == "ANGLE" and float(angle[1]) == 0,
                 "Only unrotated geometry is supported")
    except ValueError as error:
        raise GprGeometryError("Invalid origin or angle") from error
    packet.expect("NUMBERING KIJ")
    packet.expect("ORIENTATION Y_DECREASE X_INCREASE Z_DECREASE")
    axes = tuple(packet.vector("LOCATIONS_" + name, "<f8") for name in "XYZ")
    _require(all(len(axis) >= 2 and np.all(np.diff(axis) > 0) for axis in axes),
             "Expected increasing parametric axes")
    nx, ny, nz = map(len, axes)
    shape = (nz - 1, ny - 1, nx - 1)
    cell_count = math.prod(shape)
    _require(0 < cell_count <= MAX_CELLS, "Cell count exceeds limit")
    packet.expect("Binary XmUGrid Version 2")
    points = packet.vector("LOCATIONS", "<f8", count=nx * ny * nz, width=3)
    stream = packet.vector("CELL_STREAM", "<i4", count=cell_count * 10).reshape((cell_count, 10))
    _require(np.all(stream[:, 0] == 12) and np.all(stream[:, 1] == 8), "Only hexahedron cells are supported")
    cells = stream[:, 2:]
    _require(np.all((cells >= 0) & (cells < len(points))), "Cell node index out of range")
    record = packet.line()
    if record.startswith("CELL_ORDER "):
        _require(record == "CELL_ORDER INCREASING_DOWN", "Unsupported embedded cell ordering")
        record = packet.line()
    _require(re.fullmatch(r"UUID [0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", record),
             "Expected geometry UUID")
    elevations = packet.vector("POINT_ELEVATIONS", "<f8", count=len(points))
    tops = packet.vector("CELL_TOPS", "<f8", count=cell_count)
    bottoms = packet.vector("CELL_BOTTOMS", "<f8", count=cell_count)
    layers = packet.vector("CELL_LAYERS", "<i4", count=cell_count)
    _require(packet.line(optional=True) is None, "Unexpected trailing geometry records")

    # Verify every record before assigning structured-array meaning to the packet.
    k, row, col = np.indices(shape).reshape(3, -1)
    first = k * ny * nx + row * nx + col
    offsets = np.array([0, 1, nx + 1, nx, ny * nx, ny * nx + 1,
                        ny * nx + nx + 1, ny * nx + nx])
    _require(np.array_equal(cells, first[:, None] + offsets), "Connectivity is inconsistent with KIJ mapping")
    node_grid = points.reshape((nz, ny, nx, 3))
    _require(np.array_equal(node_grid[..., 0], np.broadcast_to(axes[0], (nz, ny, nx)))
             and np.array_equal(node_grid[..., 1], np.broadcast_to(axes[1][::-1][None, :, None], (nz, ny, nx))),
             "Physical XY coordinates disagree with supported rectilinear axes")
    _require(np.array_equal(elevations, points[:, 2]), "Point elevations disagree with embedded coordinates")
    _require(np.all(np.diff(node_grid[..., 2], axis=0) < 0), "Physical layers must decrease in elevation")
    _require(np.array_equal(layers, k + 1), "Cell layer metadata disagrees with KIJ connectivity")
    corners = points[cells, 2]
    _require(np.allclose(tops, (corners[:, :4] / 4).sum(axis=1), rtol=0, atol=1e-9)
             and np.allclose(bottoms, (corners[:, 4:] / 4).sum(axis=1), rtol=0, atol=1e-9),
             "Cell elevations disagree with physical corner coordinates")
    for array in (points, cells, *axes, tops, bottoms, layers):
        array.flags.writeable = False
    return RectilinearGeometry(shape, points, cells, axes, tops.reshape(shape), bottoms.reshape(shape),
                               layers.reshape(shape), hashlib.sha256(data).hexdigest())


def _identity(path):
    _require(path.is_file() and path.stat().st_size <= MAX_GPR_BYTES, "GPR file byte limit exceeded")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            _require(size <= MAX_GPR_BYTES, "GPR file byte limit exceeded")
            digest.update(chunk)
    return {"file": path.name, "bytes": size, "sha256": digest.hexdigest()}


def read_gpr_rectilinear(path: str | Path, grid_group: str) -> RectilinearGeometry:
    """Read one explicit hard-linked geometry packet and bind it to immutable input bytes."""
    path = Path(path).resolve(strict=True)
    before = _identity(path)
    dataset_path = grid_group.rstrip("/") + "/Geometry.xmsgrid"
    array, storage = read_gpr_numeric_array(path, dataset_path, max_bytes=MAX_PACKET_BYTES)
    _require(array.ndim == 1 and array.dtype.kind in "iu" and array.dtype.itemsize == 1,
             "Geometry.xmsgrid must be a one-dimensional byte array")
    geometry = decode_rectilinear_packet(array.astype("u1", copy=False).tobytes())
    after = _identity(path)
    _require(before == after, "GPR bytes changed during geometry inspection")
    object.__setattr__(geometry, "source", {**before, "identity_verified_after_read": True,
                                           "dataset_storage": storage})
    return geometry


def compare_with_dis(geometry: RectilinearGeometry, model) -> dict:
    """Compare all geometry cells with an independently loaded native MF6 DIS model.

    XY vertices include native offsets/rotation. DIS supplies cell top/bottom
    elevations, not a unique shared-node Z surface: compare every GPR face
    corner with its native cell's scalar elevation, using a flat-cell-face
    interpretation. No interpolated native Z vertices are invented. Exact
    correspondence also requires those corner comparisons to match.
    This does not establish GPR units, vertical datum, or runtime equivalence.
    """
    _require(getattr(model, "dis", None) is not None, "A structured native DIS model is required")
    dis = model.dis
    native_bottoms = np.asarray(dis.botm.array)
    _require(native_bottoms.shape == geometry.shape, "Native DIS shape differs from geometry")
    native_tops = np.concatenate((np.asarray(dis.top.array)[None], native_bottoms[:-1]), axis=0)
    centers = geometry.centers
    native_grid = model.modelgrid
    expected = (np.broadcast_to(native_grid.xcellcenters, geometry.shape),
                np.broadcast_to(native_grid.ycellcenters, geometry.shape), native_grid.zcellcenters)
    errors = {axis: float(np.max(np.abs(centers[..., index] - values)))
              for index, (axis, values) in enumerate(zip(("center_x", "center_y", "center_z"), expected))}
    errors.update(top=float(np.max(np.abs(geometry.cell_tops - native_tops))),
                  bottom=float(np.max(np.abs(geometry.cell_bottoms - native_bottoms))))
    node_shape = tuple(size + 1 for size in geometry.shape)
    points = geometry.points.reshape((*node_shape, 3))
    native_x, native_y = native_grid.xyzvertices[:2]
    errors.update(vertex_x=float(np.max(np.abs(points[..., 0] - np.broadcast_to(native_x, node_shape)))),
                  vertex_y=float(np.max(np.abs(points[..., 1] - np.broadcast_to(native_y, node_shape)))))
    corners = geometry.points[geometry.cells, 2]
    errors.update(upper_corner_z_vs_cell_top=float(np.max(np.abs(corners[:, :4] - native_tops.reshape(-1, 1)))),
                  lower_corner_z_vs_cell_bottom=float(np.max(np.abs(corners[:, 4:] - native_bottoms.reshape(-1, 1)))))
    _require(all(np.isfinite(value) for value in errors.values()), "Non-finite native DIS geometry")
    return {"shape_kij": list(geometry.shape), "compared_cells": int(np.prod(geometry.shape)),
            "compared_xy_nodes": len(geometry.points), "compared_face_corner_elevations": len(geometry.cells) * 8,
            "max_absolute_coordinate_error": errors, "exact_coordinate_match": all(v == 0 for v in errors.values()),
            "vertical_comparison": "Each physical GPR face corner versus the native cell top/bottom scalar; flat-cell-face interpretation.",
            "native_shared_vertex_z_constructed": False,
            "gpr_coordinate_units": None, "native_length_units": dis.length_units.get_data(),
            "units_converted": False,
            "scope": "Literal centers, XY vertices, and flat-cell face-elevation comparison; no unique native shared-node Z surface or GMS runtime parity claim."}
