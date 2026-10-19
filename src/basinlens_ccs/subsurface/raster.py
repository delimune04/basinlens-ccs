"""Bounded, explicit-metadata rasters; no CRS conversion or original-GMS claim.

Raster row zero is north; shared-project row zero is south. Values are samples
at pixel centres, not cell averages. Bilinear interpolation never fills NODATA.
"""
from __future__ import annotations

import argparse
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
from types import MappingProxyType

from .schema import (CANONICAL_AXES, PROPERTY_UNITS, FieldSupport, Quantity,
                     RockProperty, SubsurfaceProject)

SCHEMA = "basinlens-raster-v1"
MAX_CELLS = 100_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_QUERIES = 100_000
QUANTITY_UNITS = {**PROPERTY_UNITS, "elevation": "m", "head": "m", "recharge": "m/day"}
GEOMETRY_KEYS = {"nrow", "ncol", "xllcorner_m", "yllcorner_m", "dx_m", "dy_m"}
METADATA_KEYS = {"asset_id", "crs", "vertical_datum", "coordinate_unit", "quantity", "unit", "provenance"}


class RasterError(ValueError):
    """Invalid metadata, unsupported operation, bounded I/O failure or mismatch."""


def _object(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RasterError(f"{name}: expected exactly {sorted(keys)}")
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RasterError(f"{name}: expected finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise RasterError(f"{name}: expected finite number") from None
    if not math.isfinite(result):
        raise RasterError(f"{name}: expected finite number")
    return result


def _text(value, name, limit=1000):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > limit or any(ord(c) < 32 for c in value)):
        raise RasterError(f"{name}: expected bounded trimmed text")
    return value


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RasterError("asset_id: expected 1..128 safe identifier characters")
    return value


def _geometry(value):
    if isinstance(value, MappingProxyType):
        value = dict(value)
    value = _object(value, GEOMETRY_KEYS, "geometry")
    for key in ("nrow", "ncol"):
        if type(value[key]) is not int or not 1 <= value[key] <= 10_000:
            raise RasterError(f"geometry.{key}: expected integer 1..10000")
    if value["nrow"] * value["ncol"] > MAX_CELLS:
        raise RasterError(f"geometry: maximum {MAX_CELLS} cells")
    result = dict(value)
    for key in GEOMETRY_KEYS - {"nrow", "ncol"}:
        result[key] = _number(value[key], "geometry." + key)
    for key in ("dx_m", "dy_m"):
        if not 1e-6 <= result[key] <= 1e6:
            raise RasterError(f"geometry.{key}: expected 1e-6..1e6 m")
    for origin, step, count in (("xllcorner_m", "dx_m", "ncol"), ("yllcorner_m", "dy_m", "nrow")):
        a, delta = result[origin], result[step]
        b = a + delta * result[count]
        if (abs(a) > 1e9 or abs(b) > 1e9 or max(math.ulp(a), math.ulp(b)) > delta * 1e-8
                or not a < a + delta / 2 < a + delta < b + delta):
            raise RasterError("geometry: extent/centre precision exceeds supported local grid")
    return result


def _metadata(value):
    value = _object(value, METADATA_KEYS, "metadata")
    _identifier(value["asset_id"])
    for key in ("crs", "vertical_datum"):
        _text(value[key], key)
    if value["coordinate_unit"] != "m":
        raise RasterError("coordinate_unit: requires m; convert coordinates explicitly")
    if (not isinstance(value["quantity"], str) or value["quantity"] not in QUANTITY_UNITS
            or QUANTITY_UNITS[value["quantity"]] != value["unit"]):
        raise RasterError("quantity/unit: unsupported explicit pair")
    if not isinstance(value["provenance"], (list, tuple)) or not 1 <= len(value["provenance"]) <= 64:
        raise RasterError("provenance: expected 1..64 source/operation statements")
    return {**value, "provenance": tuple(_text(v, "provenance") for v in value["provenance"])}


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise RasterError(f"JSON duplicate key: {key}")
        obj[key] = value
    return obj


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates,
                          parse_constant=lambda x: (_ for _ in ()).throw(RasterError("JSON nonfinite value")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RasterError(f"invalid UTF-8 JSON: {exc}") from exc


def _safe_path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (*reversed(path.parents), path):
        try:
            if stat.S_ISLNK(item.lstat().st_mode):
                raise RasterError(f"symlink path refused: {item}")
        except FileNotFoundError:
            pass
    return path


def _read(path):
    path = _safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_FILE_BYTES:
                raise RasterError("input: expected nonempty regular file <=16 MiB")
            raw = handle.read(MAX_FILE_BYTES + 1)
            after = os.fstat(handle.fileno())
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            current = path.lstat()
            if (signature(before) != signature(after) or signature(after) != signature(current)
                    or len(raw) != before.st_size):
                raise RasterError("input changed during read")
            return raw
    except OSError as exc:
        raise RasterError(f"input read failed: {exc}") from exc


def _write(path, raw):
    path = _safe_path(path)
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise RasterError("output exceeds 16 MiB limit")
    if not path.parent.is_dir():
        raise RasterError("output parent must be an existing directory")
    # Publish a complete flushed file with an atomic no-replace hard link.
    # This also refuses a concurrently created path or dangling symlink.
    stage = None
    try:
        fd, stage = tempfile.mkstemp(prefix=".raster-file-", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(stage, path)
    except OSError as exc:
        raise RasterError(f"fresh output write failed: {exc}") from exc
    finally:
        if stage is not None:
            os.unlink(stage)
    return path


@dataclass(frozen=True)
class RasterGrid:
    asset_id: str
    geometry: dict
    values: tuple
    crs: str
    vertical_datum: str
    quantity: str
    unit: str
    provenance: tuple[str, ...]
    nodata: float = -9999.0
    coordinate_unit: str = "m"
    row_axis: str = "north_to_south"
    schema: str = SCHEMA

    def __post_init__(self):
        if self.schema != SCHEMA or self.row_axis != "north_to_south":
            raise RasterError("requires raster-v1 and north_to_south row axis")
        meta = _metadata({key: getattr(self, key) for key in METADATA_KEYS})
        geometry = _geometry(self.geometry)
        nodata = _number(self.nodata, "nodata")
        if not isinstance(self.values, (list, tuple)) or len(self.values) != geometry["nrow"]:
            raise RasterError("values: expected exactly nrow arrays")
        rows = []
        for row in self.values:
            if not isinstance(row, (list, tuple)) or len(row) != geometry["ncol"]:
                raise RasterError("values: expected exactly ncol entries per row")
            result = tuple(None if v is None else _number(v, "values") for v in row)
            if nodata in result:
                raise RasterError("nodata sentinel collides with a valid value; represent missing values as null")
            rows.append(result)
        # Freeze nested geometry; to_dict returns a fresh mutable JSON object.
        object.__setattr__(self, "geometry", MappingProxyType(dict(geometry)))
        object.__setattr__(self, "values", tuple(rows))
        object.__setattr__(self, "provenance", meta["provenance"])
        object.__setattr__(self, "nodata", nodata)

    @classmethod
    def from_dict(cls, value):
        keys = METADATA_KEYS | {"geometry", "values", "nodata", "row_axis", "schema"}
        return cls(**_object(value, keys, "raster"))

    def to_dict(self):
        return {"schema": self.schema, **{key: getattr(self, key) for key in METADATA_KEYS},
                "geometry": dict(self.geometry), "values": [list(row) for row in self.values],
                "nodata": self.nodata, "row_axis": self.row_axis,
                "provenance": list(self.provenance)}

    @property
    def extent(self):
        g = _geometry(self.geometry)
        return [g["xllcorner_m"], g["yllcorner_m"], g["xllcorner_m"] + g["ncol"] * g["dx_m"],
                g["yllcorner_m"] + g["nrow"] * g["dy_m"]]


def _valid(grid):
    if not isinstance(grid, RasterGrid):
        raise RasterError("expected RasterGrid")
    return RasterGrid.from_dict(grid.to_dict())


def load_raster(path):
    return RasterGrid.from_dict(_json(_read(path)))


def save_raster(grid, path):
    return _write(path, _canonical(_valid(grid).to_dict()))


def _ascii_bytes(grid):
    grid = _valid(grid)
    g = grid.geometry
    if g["dx_m"] != g["dy_m"]:
        raise RasterError("Esri ASCII CELLSIZE requires square pixels; resample explicitly")
    header = [f"NCOLS {g['ncol']}", f"NROWS {g['nrow']}", f"XLLCORNER {g['xllcorner_m']:.17g}",
              f"YLLCORNER {g['yllcorner_m']:.17g}", f"CELLSIZE {g['dx_m']:.17g}", f"NODATA_VALUE {grid.nodata:.17g}"]
    rows = [" ".join(format(grid.nodata if v is None else v, ".17g") for v in row) for row in grid.values]
    return ("\n".join(header + rows) + "\n").encode("ascii")


def read_ascii(path, *, metadata):
    """Read official corner/centre ASCII syntax with required external metadata.

    Header-only information cannot establish CRS, datum or value units. The
    caller supplies exactly METADATA_KEYS; no filename or .prj inference occurs.
    """
    meta = _metadata(metadata)
    try:
        tokens = _read(path).decode("ascii").split()
    except UnicodeError as exc:
        raise RasterError("ASCII raster must contain ASCII text") from exc
    keys = {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}
    header = {}
    cursor = 0
    while cursor < len(tokens) and tokens[cursor].lower() in keys:
        key = tokens[cursor].lower()
        if key in header or cursor + 1 >= len(tokens):
            raise RasterError("ASCII duplicate or truncated header")
        try:
            header[key] = float(tokens[cursor + 1])
        except (ValueError, OverflowError):
            raise RasterError("ASCII header requires numeric values") from None
        if not math.isfinite(header[key]):
            raise RasterError("ASCII header requires finite values")
        cursor += 2
    corner = {"ncols", "nrows", "xllcorner", "yllcorner", "cellsize"}
    centre = {"ncols", "nrows", "xllcenter", "yllcenter", "cellsize"}
    if set(header) - {"nodata_value"} not in (corner, centre):
        raise RasterError("ASCII requires ncols/nrows, matching x/y corner or centre, cellsize, optional nodata")
    for key in ("ncols", "nrows"):
        if not header[key].is_integer() or not 1 <= header[key] <= 10_000:
            raise RasterError("ASCII dimensions must be positive bounded integers")
    nr, nc = int(header["nrows"]), int(header["ncols"])
    if nr * nc > MAX_CELLS or len(tokens) - cursor != nr * nc:
        raise RasterError("ASCII cell count mismatch or bound exceeded")
    size = header["cellsize"]
    x = header.get("xllcorner", header.get("xllcenter", 0) - size / 2)
    y = header.get("yllcorner", header.get("yllcenter", 0) - size / 2)
    nodata = header.get("nodata_value", -9999.0)
    values = []
    for token in tokens[cursor:]:
        try:
            v = float(token)
        except (ValueError, OverflowError):
            raise RasterError("ASCII cell requires finite numeric value") from None
        if not math.isfinite(v):
            raise RasterError("ASCII nonfinite cells are unsupported; use declared finite NODATA")
        values.append(None if v == nodata else v)
    return RasterGrid(**meta, geometry={"nrow": nr, "ncol": nc, "xllcorner_m": x,
                      "yllcorner_m": y, "dx_m": size, "dy_m": size},
                      values=[values[r * nc:(r + 1) * nc] for r in range(nr)], nodata=nodata)


def export_ascii_bundle(grid, output_dir):
    """Publish a new directory only after both ASCII and hash-bound metadata exist."""
    grid = _valid(grid)
    output = _safe_path(output_dir)
    if output.exists() or not output.parent.is_dir():
        raise RasterError("ASCII bundle requires fresh output and existing parent")
    raw = _ascii_bytes(grid)
    meta = grid.to_dict()
    del meta["values"]
    payload = {"schema": "basinlens-raster-ascii-v1", "ascii_sha256": hashlib.sha256(raw).hexdigest(), "raster": meta}
    stage = Path(tempfile.mkdtemp(prefix=".raster-stage-", dir=output.parent))
    try:
        _write(stage / "grid.asc", raw)
        _write(stage / "metadata.json", _canonical(payload))
        if open_ascii_bundle(stage).to_dict() != grid.to_dict():
            raise RasterError("ASCII bundle verification failed")
        # Reserve destination exclusively before moving owned files. Readers see
        # absence or incomplete bundle (rejected), never a success receipt early.
        output.mkdir()
        for name in ("grid.asc", "metadata.json"):
            os.rename(stage / name, output / name)
        return output
    except OSError as exc:
        raise RasterError(f"ASCII publish failed: {exc}; incomplete output is never accepted") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def open_ascii_bundle(root):
    root = _safe_path(root)
    if not root.is_dir() or {p.name for p in root.iterdir()} != {"grid.asc", "metadata.json"}:
        raise RasterError("ASCII bundle requires exact grid.asc + metadata.json inventory")
    payload = _object(_json(_read(root / "metadata.json")), {"schema", "ascii_sha256", "raster"}, "ASCII sidecar")
    if payload["schema"] != "basinlens-raster-ascii-v1":
        raise RasterError("unsupported ASCII sidecar schema")
    raw = _read(root / "grid.asc")
    if payload["ascii_sha256"] != hashlib.sha256(raw).hexdigest():
        raise RasterError("ASCII hash mismatch")
    declared = payload["raster"]
    _object(declared, METADATA_KEYS | {"schema", "geometry", "row_axis", "nodata"}, "ASCII raster metadata")
    grid = read_ascii(root / "grid.asc", metadata={k: declared[k] for k in METADATA_KEYS})
    expected = grid.to_dict()
    del expected["values"]
    RasterGrid.from_dict({**declared, "values": [list(row) for row in grid.values]})
    if expected != declared:
        raise RasterError("ASCII geometry/metadata mismatch")
    return grid


def _xy(points):
    if not isinstance(points, (list, tuple)) or len(points) > MAX_QUERIES:
        raise RasterError("points: expected at most 100000 [x_m,y_m] pairs")
    result = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise RasterError("points: expected [x_m,y_m]")
        result.append(tuple(_number(v, "point") for v in point))
    return result


def _pixel_position(coordinate, origin, width, centre=False):
    # Called only for bounded source-relative coordinates. Snap only exact
    # represented grid centres/boundaries; a nextafter neighbour never snaps.
    offset = .5 if centre else 0.
    index = (coordinate - origin) / width - offset
    nearest = round(index)
    if coordinate == origin + (nearest + offset) * width:
        return float(nearest)
    return index


def sample_raster(grid, points, *, method):
    """Centre sample; nearest supports extent half-open [W,E)x[S,N).

    Bilinear supports the closed centre rectangle; it returns null beyond it or
    where a positive-weight contributing cell is NODATA. No extrapolation,
    averaging across NODATA, projection, or inferred vertical transform occurs.
    Tied nearest centres use the eastern/northern cell (physical coordinate tie).
    Accepted origins/endpoints have ULP <=1e-8 pixel; exact represented grid
    centres/boundaries snap to their indices without admitting nearby points.
    """
    grid = _valid(grid)
    points = _xy(points)
    if method not in ("nearest", "bilinear"):
        raise RasterError("method must be nearest or bilinear")
    g = grid.geometry
    xmin, ymin, xmax, ymax = grid.extent
    result = []
    for x, y in points:
        if method == "nearest":
            supported = xmin <= x < xmax and ymin <= y < ymax
        else:
            supported = (xmin + .5 * g["dx_m"] <= x <= xmin + (g["ncol"] - .5) * g["dx_m"]
                         and ymin + .5 * g["dy_m"] <= y <= ymin + (g["nrow"] - .5) * g["dy_m"])
        if not supported:
            result.append(None)
            continue
        # Southwest row indices make physical tie direction deterministic.
        u = _pixel_position(x, xmin, g["dx_m"], True)
        v = _pixel_position(y, ymin, g["dy_m"], True)
        if method == "nearest":
            if not xmin <= x < xmax or not ymin <= y < ymax:
                result.append(None)
                continue
            c = min(g["ncol"] - 1, int(math.floor(_pixel_position(x, xmin, g["dx_m"]))))
            south = min(g["nrow"] - 1, int(math.floor(_pixel_position(y, ymin, g["dy_m"]))))
            result.append(grid.values[g["nrow"] - 1 - south][c])
        else:
            if not (xmin + .5 * g["dx_m"] <= x <= xmin + (g["ncol"] - .5) * g["dx_m"]
                    and ymin + .5 * g["dy_m"] <= y <= ymin + (g["nrow"] - .5) * g["dy_m"]):
                result.append(None)
                continue
            u = max(0., min(g["ncol"] - 1., u))
            v = max(0., min(g["nrow"] - 1., v))
            c0, r0 = int(math.floor(u)), int(math.floor(v))
            c1, r1 = min(c0 + 1, g["ncol"] - 1), min(r0 + 1, g["nrow"] - 1)
            tx, ty = u - c0, v - r0
            total = 0.0
            missing = False
            for r, wy in ((r0, 1 - ty), (r1, ty)):
                for c, wx in ((c0, 1 - tx), (c1, tx)):
                    weight = wx * wy
                    if weight == 0:
                        continue
                    value = grid.values[g["nrow"] - 1 - r][c]
                    if value is None:
                        missing = True
                    else:
                        total += value * weight
            if not math.isfinite(total):
                raise RasterError("bilinear arithmetic overflow")
            result.append(None if missing else total)
    return result


def _derived(grid, *, geometry, values, statement, asset_id=None):
    data = grid.to_dict()
    data.update(geometry=geometry, values=values, asset_id=asset_id or grid.asset_id,
                provenance=[*grid.provenance, statement])
    return RasterGrid.from_dict(data)


def resample_raster(grid, geometry, *, method, asset_id=None):
    grid = _valid(grid)
    g = _geometry(geometry)
    points = [[g["xllcorner_m"] + (c + .5) * g["dx_m"],
               g["yllcorner_m"] + (g["nrow"] - r - .5) * g["dy_m"]]
              for r in range(g["nrow"]) for c in range(g["ncol"])]
    vals = sample_raster(grid, points, method=method)
    return _derived(grid, geometry=g, values=[vals[r * g["ncol"]:(r + 1) * g["ncol"]] for r in range(g["nrow"])],
                    statement=f"Resampled pixel centres with {method}; outside/unsupported cells remain NODATA", asset_id=asset_id)


def clip_raster(grid, bbox, *, asset_id=None):
    """Select every source cell with positive-area overlap with bbox; never resample."""
    grid = _valid(grid)
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise RasterError("bbox requires [xmin,ymin,xmax,ymax] metres")
    x0, y0, x1, y1 = [_number(v, "bbox") for v in bbox]
    if x0 >= x1 or y0 >= y1:
        raise RasterError("bbox must have positive area")
    g = grid.geometry
    xmin, ymin, xmax, ymax = grid.extent
    left, right, bottom, top = max(x0, xmin), min(x1, xmax), max(y0, ymin), min(y1, ymax)
    if left >= right or bottom >= top:
        raise RasterError("bbox has no positive-area raster intersection")
    c0 = max(0, math.floor(_pixel_position(left, xmin, g["dx_m"])))
    c1 = min(g["ncol"], math.ceil(_pixel_position(right, xmin, g["dx_m"])))
    s0 = max(0, math.floor(_pixel_position(bottom, ymin, g["dy_m"])))
    s1 = min(g["nrow"], math.ceil(_pixel_position(top, ymin, g["dy_m"])))
    geom = {**g, "nrow": s1 - s0, "ncol": c1 - c0, "xllcorner_m": xmin + c0 * g["dx_m"],
            "yllcorner_m": ymin + s0 * g["dy_m"]}
    rows = [list(row[c0:c1]) for row in grid.values[g["nrow"] - s1:g["nrow"] - s0]]
    return _derived(grid, geometry=geom, values=rows,
                    statement=f"Clipped positive-area cell intersections with bbox {bbox}; full source cells retained", asset_id=asset_id)


def merge_rasters(grids, *, conflict_policy, asset_id):
    """Aligned tiles; NODATA never overwrites valid data; all valid overlaps follow policy.

    Policies: error (reject unequal valid overlaps), first, last. Gaps remain null.
    """
    if not isinstance(grids, (list, tuple)) or not 1 <= len(grids) <= 64:
        raise RasterError("merge requires 1..64 rasters")
    if conflict_policy not in ("error", "first", "last"):
        raise RasterError("conflict_policy requires error, first or last")
    grids = [_valid(g) for g in grids]
    if sum(g.geometry["nrow"] * g.geometry["ncol"] for g in grids) > MAX_CELLS:
        raise RasterError("merge total source cells exceeds 100000")
    _identifier(asset_id)
    base = grids[0]
    meta = (base.crs, base.vertical_datum, base.quantity, base.unit)
    bg = base.geometry
    for grid in grids:
        if (grid.crs, grid.vertical_datum, grid.quantity, grid.unit) != meta:
            raise RasterError("merge requires exact literal CRS/datum/quantity/unit agreement")
        for step in ("dx_m", "dy_m"):
            if grid.geometry[step] != bg[step]:
                raise RasterError("merge requires identical pixel sizes")
        for origin, step in (("xllcorner_m", "dx_m"), ("yllcorner_m", "dy_m")):
            offset = (grid.geometry[origin] - bg[origin]) / bg[step]
            if grid.geometry[origin] != bg[origin] + round(offset) * bg[step]:
                raise RasterError("merge requires pixel-aligned origins; resample explicitly")
    extents = [grid.extent for grid in grids]
    xmin, ymin = min(e[0] for e in extents), min(e[1] for e in extents)
    xmax, ymax = max(e[2] for e in extents), max(e[3] for e in extents)
    geom = _geometry({**bg, "xllcorner_m": xmin, "yllcorner_m": ymin,
                      "ncol": int(round((xmax - xmin) / bg["dx_m"])),
                      "nrow": int(round((ymax - ymin) / bg["dy_m"]))})
    vals = [[None] * geom["ncol"] for _ in range(geom["nrow"])]
    for grid in grids:
        c0 = int(round((grid.extent[0] - xmin) / bg["dx_m"]))
        r0 = int(round((ymax - grid.extent[3]) / bg["dy_m"]))
        for r, row in enumerate(grid.values):
            for c, value in enumerate(row):
                old = vals[r0 + r][c0 + c]
                if value is None:
                    continue
                if old is not None and old != value and conflict_policy == "error":
                    raise RasterError(f"unequal valid overlap at row={r0+r}, col={c0+c}")
                if old is None or conflict_policy == "last":
                    vals[r0 + r][c0 + c] = value
    provenance = list(dict.fromkeys(p for grid in grids for p in grid.provenance))
    data = base.to_dict()
    data.update(asset_id=asset_id, geometry=geom, values=vals,
                provenance=[*provenance, f"Merged aligned tiles {[g.asset_id for g in grids]} with {conflict_policy}; NODATA never overwrites valid data"])
    return RasterGrid.from_dict(data)


def raster_to_scatter(grid):
    grid = _valid(grid)
    g = grid.geometry
    return {"schema": "basinlens-raster-scatter-v1", "source_asset_id": grid.asset_id,
            "source_raster_sha256": hashlib.sha256(_canonical(grid.to_dict())).hexdigest(),
            "crs": grid.crs, "vertical_datum": grid.vertical_datum, "coordinate_unit": "m",
            "quantity": grid.quantity, "unit": grid.unit, "support": "pixel_centres",
            "provenance": list(grid.provenance), "points": [
                {"row": r, "column": c, "x_m": g["xllcorner_m"] + (c + .5) * g["dx_m"],
                 "y_m": g["yllcorner_m"] + (g["nrow"] - r - .5) * g["dy_m"], "value": value}
                for r, row in enumerate(grid.values) for c, value in enumerate(row) if value is not None]}


def sample_project_property(grid, project, name, *, method, source_asset_id):
    """Return a typed complete cell field, repeating sampled XY through layers.

    This operation does not mutate/assimilate the project. The source asset must
    already be registered and its hash must bind this exact canonical raster.
    """
    grid = _valid(grid)
    if not isinstance(project, SubsurfaceProject):
        raise RasterError("expected typed SubsurfaceProject")
    sr, g = project.spatial_reference, project.geometry
    if sr.local_axes != CANONICAL_AXES or (sr.crs, sr.vertical_datum, sr.length_unit) != (grid.crs, grid.vertical_datum, "m"):
        raise RasterError("project requires exact CRS/datum/metre/canonical-axis agreement; no inferred transform")
    if name != grid.quantity or name not in PROPERTY_UNITS or PROPERTY_UNITS[name] != grid.unit:
        raise RasterError("raster quantity/unit does not match requested typed property")
    _text(source_asset_id, "source_asset_id")
    assets = {asset.asset_id: asset for asset in project.assets}
    canonical_hash = hashlib.sha256(_canonical(grid.to_dict())).hexdigest()
    if source_asset_id not in assets or assets[source_asset_id].sha256 != canonical_hash:
        raise RasterError("registered source asset must bind exact canonical raster JSON bytes")
    points = [[g.origin_x_m + (c + .5) * g.delr_m, g.origin_y_m + (r + .5) * g.delc_m]
              for r in range(g.nrow) for c in range(g.ncol)]
    vals = sample_raster(grid, points, method=method)
    if any(v is None for v in vals):
        raise RasterError("model cell centres outside raster support or intersect NODATA; complete field refused")
    indices = tuple((k, r, c) for k in range(g.nlay) for r in range(g.nrow) for c in range(g.ncol))
    try:
        return RockProperty(name, Quantity(tuple(vals * g.nlay), grid.unit), FieldSupport("cell", indices),
                            source_asset_ids=(source_asset_id,), basis="interpreted")
    except ValueError as exc:
        raise RasterError(f"sampled property invalid: {exc}") from exc


def create_catalog(assets, output):
    """Capture exact JSON raster asset bytes and decoded extents; paths remain local.

    Relative paths are resolved from catalogue parent. Reopening rehashes and
    reparses every asset. A catalogue never permits arbitrary external formats.
    """
    output = _safe_path(output)
    if not isinstance(assets, (list, tuple)) or not 1 <= len(assets) <= 64:
        raise RasterError("catalogue requires 1..64 raster JSON paths")
    entries, ids, paths = [], set(), set()
    total_bytes, total_cells = 0, 0
    for path in assets:
        path = _safe_path(path)
        try:
            rel = path.relative_to(output.parent).as_posix()
        except ValueError:
            raise RasterError("catalogue assets must be inside catalogue parent directory") from None
        if rel in paths or path == output:
            raise RasterError("duplicate/catalogue-self asset path")
        raw = _read(path)
        grid = RasterGrid.from_dict(_json(raw))
        total_bytes += len(raw)
        total_cells += grid.geometry["nrow"] * grid.geometry["ncol"]
        if total_bytes > 64 * 1024 * 1024 or total_cells > 1_000_000:
            raise RasterError("catalogue aggregate exceeds 64 MiB or 1000000 cells")
        if grid.asset_id in ids:
            raise RasterError("duplicate catalogue asset_id")
        ids.add(grid.asset_id)
        paths.add(rel)
        entries.append({"asset_id": grid.asset_id, "relative_path": rel, "sha256": hashlib.sha256(raw).hexdigest(),
                        "size_bytes": len(raw), "extent_m": grid.extent, "crs": grid.crs,
                        "vertical_datum": grid.vertical_datum, "quantity": grid.quantity, "unit": grid.unit})
    return _write(output, _canonical({"schema": "basinlens-raster-catalog-v1", "assets": entries}))


def open_catalog(path):
    path = _safe_path(path)
    data = _object(_json(_read(path)), {"schema", "assets"}, "catalogue")
    if data["schema"] != "basinlens-raster-catalog-v1" or not isinstance(data["assets"], list) or not 1 <= len(data["assets"]) <= 64:
        raise RasterError("unsupported/empty/bounded catalogue")
    result, ids, paths = [], set(), set()
    keys = {"asset_id", "relative_path", "sha256", "size_bytes", "extent_m", "crs", "vertical_datum", "quantity", "unit"}
    total = 0
    total_cells = 0
    for entry in data["assets"]:
        _object(entry, keys, "catalogue asset")
        if (type(entry["size_bytes"]) is not int or not 0 < entry["size_bytes"] <= MAX_FILE_BYTES
                or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or not isinstance(entry["extent_m"], list) or len(entry["extent_m"]) != 4):
            raise RasterError("invalid catalogue size/hash/extent metadata")
        for coordinate in entry["extent_m"]:
            _number(coordinate, "catalogue extent")
        rel = entry["relative_path"]
        if (not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel or rel.startswith("/")
                or any(p in ("", ".", "..") for p in rel.split("/")) or rel in paths):
            raise RasterError("unsafe/duplicate catalogue asset path")
        raw = _read(path.parent / rel)
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise RasterError("catalogue total decoded bytes exceeds 64 MiB")
        grid = RasterGrid.from_dict(_json(raw))
        total_cells += grid.geometry["nrow"] * grid.geometry["ncol"]
        if total_cells > 1_000_000:
            raise RasterError("catalogue aggregate exceeds 1000000 cells")
        expected = {"asset_id": grid.asset_id, "relative_path": rel, "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw), "extent_m": grid.extent, "crs": grid.crs,
                    "vertical_datum": grid.vertical_datum, "quantity": grid.quantity, "unit": grid.unit}
        if entry != expected or grid.asset_id in ids:
            raise RasterError("catalogue asset content/hash/metadata mismatch or duplicate identity")
        ids.add(grid.asset_id)
        paths.add(rel)
        result.append(grid)
    return result


def verify_roundtrip(grid):
    """Actually write/reopen own JSON and metadata-bound ASCII; no solver/GMS run."""
    grid = _valid(grid)
    with tempfile.TemporaryDirectory(prefix="basinlens-raster-check-") as tmp:
        root = Path(tmp)
        save_raster(grid, root / "raster.json")
        loaded = load_raster(root / "raster.json")
        export_ascii_bundle(loaded, root / "ascii")
        reopened = open_ascii_bundle(root / "ascii")
        if reopened.to_dict() != grid.to_dict():
            raise RasterError("raster JSON/ASCII roundtrip changed metadata or values")
        return {"schema": "basinlens-raster-roundtrip-v1", "asset_id": grid.asset_id,
                "canonical_raster_sha256": hashlib.sha256(_canonical(grid.to_dict())).hexdigest(),
                "json_equal": True, "ascii_values_and_metadata_equal": True,
                "original_gms_comparison": "NOT_OBSERVED", "cells": grid.geometry["nrow"] * grid.geometry["ncol"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-ascii"); p.add_argument("input"); p.add_argument("metadata"); p.add_argument("output")
    p = sub.add_parser("export-ascii"); p.add_argument("input"); p.add_argument("output")
    p = sub.add_parser("open-ascii"); p.add_argument("input"); p.add_argument("output")
    p = sub.add_parser("roundtrip"); p.add_argument("input"); p.add_argument("output")
    p = sub.add_parser("resample"); p.add_argument("input"); p.add_argument("geometry"); p.add_argument("output"); p.add_argument("--method", choices=("nearest", "bilinear"), required=True)
    p = sub.add_parser("clip"); p.add_argument("input"); p.add_argument("output"); p.add_argument("--bbox", nargs=4, type=float, required=True)
    p = sub.add_parser("merge"); p.add_argument("output"); p.add_argument("inputs", nargs="+"); p.add_argument("--asset-id", required=True); p.add_argument("--conflict-policy", choices=("error", "first", "last"), required=True)
    p = sub.add_parser("scatter"); p.add_argument("input"); p.add_argument("output")
    p = sub.add_parser("query"); p.add_argument("input"); p.add_argument("points"); p.add_argument("output"); p.add_argument("--method", choices=("nearest", "bilinear"), required=True)
    p = sub.add_parser("catalog"); p.add_argument("output"); p.add_argument("inputs", nargs="+")
    p = sub.add_parser("verify-catalog"); p.add_argument("input")
    args = parser.parse_args(argv)
    try:
        if args.command == "import-ascii":
            save_raster(read_ascii(args.input, metadata=_json(_read(args.metadata))), args.output)
        elif args.command == "export-ascii": export_ascii_bundle(load_raster(args.input), args.output)
        elif args.command == "open-ascii": save_raster(open_ascii_bundle(args.input), args.output)
        elif args.command == "roundtrip": _write(args.output, _canonical(verify_roundtrip(load_raster(args.input))))
        elif args.command == "resample": save_raster(resample_raster(load_raster(args.input), _json(_read(args.geometry)), method=args.method), args.output)
        elif args.command == "clip": save_raster(clip_raster(load_raster(args.input), args.bbox), args.output)
        elif args.command == "merge": save_raster(merge_rasters([load_raster(p) for p in args.inputs], conflict_policy=args.conflict_policy, asset_id=args.asset_id), args.output)
        elif args.command == "scatter": _write(args.output, _canonical(raster_to_scatter(load_raster(args.input))))
        elif args.command == "query":
            grid = load_raster(args.input)
            points = _xy(_json(_read(args.points)))
            _write(args.output, _canonical({"schema": "basinlens-raster-query-v1", "asset_id": grid.asset_id,
                "quantity": grid.quantity, "unit": grid.unit, "crs": grid.crs, "vertical_datum": grid.vertical_datum,
                "method": args.method, "points_m": points, "values": sample_raster(grid, points, method=args.method)}))
        elif args.command == "catalog": create_catalog(args.inputs, args.output)
        elif args.command == "verify-catalog": print(json.dumps({"verified_assets": [g.asset_id for g in open_catalog(args.input)]}))
    except (RasterError, OSError) as exc:
        parser.exit(2, f"raster error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
