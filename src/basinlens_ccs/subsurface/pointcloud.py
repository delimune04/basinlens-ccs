"""Bounded LAS 1.2 (uncompressed formats 0--3) and point-cloud operations.

Opaque VLRs and original encoded point records are retained byte for byte.
Owner-supplied coordinates/units are literal, never inferred from VLRs.
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
import struct
from typing import Any

SCHEMA = "basinlens-pointcloud-v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 96 * 1024 * 1024
MAX_POINTS = 200_000
MAX_CELLS = 200_000
MAX_VLRS = 256
LENGTHS = {0: 20, 1: 28, 2: 26, 3: 34}


class PointCloudError(ValueError):
    """Unsupported, inconsistent, or out-of-budget input."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _strict_json(raw: bytes) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise PointCloudError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(PointCloudError(f"nonfinite JSON: {x}")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as e:
        raise PointCloudError(f"invalid point-cloud JSON: {e}") from e


def _read(path: str | Path, limit: int) -> bytes:
    p = Path(path)
    # O_NONBLOCK prevents an attacker-controlled FIFO from blocking before fstat.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(p, flags)
        with os.fdopen(fd, "rb") as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise PointCloudError("input must be a bounded regular file")
            raw = f.read(limit + 1)
            after = os.fstat(f.fileno())
            if len(raw) != before.st_size or len(raw) > limit or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise PointCloudError("input changed or exceeded read budget")
            return raw
    except OSError as e:
        raise PointCloudError(f"cannot read input: {e}") from e


def _write(path: str | Path, raw: bytes, limit: int = MAX_BYTES) -> Path:
    p = Path(path)
    if len(raw) > limit:
        raise PointCloudError("output exceeds byte budget")
    if not p.parent.is_dir():
        raise PointCloudError("output parent must exist")
    # Exclusive file creation; remove only our own incomplete output on failure.
    created = False
    try:
        with p.open("xb") as f:
            created = True
            f.write(raw)
        return p
    except OSError as e:
        if created:
            p.unlink(missing_ok=True)
        raise PointCloudError(f"fresh output required: {e}") from e


def _number(x: Any, label: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise PointCloudError(f"{label} must be a finite number")
    try:
        value = float(x)
    except (OverflowError, ValueError):
        raise PointCloudError(f"{label} must be a finite number") from None
    if not math.isfinite(value):
        raise PointCloudError(f"{label} must be a finite number")
    return value


def _int(x: Any, low: int, high: int, label: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or not low <= x <= high:
        raise PointCloudError(f"{label} must be an integer in [{low}, {high}]")
    return x


def _metadata(data: Any) -> dict:
    keys = {"crs", "horizontal_unit", "vertical_unit", "vertical_datum", "provenance"}
    if not isinstance(data, dict) or set(data) != keys:
        raise PointCloudError(f"metadata requires exactly {sorted(keys)}")
    for name in ("crs", "vertical_datum"):
        if not isinstance(data[name], str) or not 1 <= len(data[name]) <= 1000 or any(ord(c) < 32 for c in data[name]):
            raise PointCloudError(f"{name} must be literal nonempty text; use unknown when unknown")
    for name in ("horizontal_unit", "vertical_unit"):
        if data[name] not in ("m", "ft", "unknown"):
            raise PointCloudError(f"{name} must be m, ft, or unknown")
    prov = data["provenance"]
    if not isinstance(prov, list) or not 1 <= len(prov) <= 32 or any(not isinstance(v, str) or not 1 <= len(v) <= 1000 for v in prov):
        raise PointCloudError("provenance requires 1..32 bounded literal descriptions")
    return json.loads(_json(data))


def _decode(raw: bytes) -> tuple[bytes, bytes]:
    if not isinstance(raw, bytes) or not 227 <= len(raw) <= MAX_BYTES or raw[:4] != b"LASF":
        raise PointCloudError("bounded LASF file with a complete header required")
    if raw[24:26] != b"\x01\x02":
        raise PointCloudError("only LAS 1.2 is supported")
    encoding = struct.unpack_from("<H", raw, 6)[0]
    if encoding & ~1:
        raise PointCloudError("LAS 1.2 global encoding reserved bits must be zero")
    header_size, offset, vlr_count = struct.unpack_from("<HII", raw, 94)
    fmt = raw[104]
    if fmt not in LENGTHS:
        raise PointCloudError("compressed LAZ and point formats outside 0..3 are unsupported")
    record_size, count = struct.unpack_from("<HI", raw, 105)
    if header_size != 227 or record_size != LENGTHS[fmt]:
        raise PointCloudError("extended headers and extra point bytes are unsupported")
    if count > MAX_POINTS or vlr_count > MAX_VLRS or not 227 <= offset <= len(raw):
        raise PointCloudError("point count, VLR count or point offset exceeds bounded layout")
    if offset + count * record_size != len(raw):
        raise PointCloudError("point count/offset/record length does not exactly match file; trailing data unsupported")
    scales = struct.unpack_from("<3d", raw, 131)
    offsets = struct.unpack_from("<3d", raw, 155)
    bounds = struct.unpack_from("<6d", raw, 179)
    if any(not math.isfinite(v) for v in scales + offsets + bounds) or any(v <= 0 for v in scales):
        raise PointCloudError("scales must be positive; scales, offsets and bounds must be finite")
    pos = 227
    for _ in range(vlr_count):
        if pos + 54 > offset:
            raise PointCloudError("truncated VLR header")
        size = struct.unpack_from("<H", raw, pos + 20)[0]
        pos += 54 + size
        if pos > offset:
            raise PointCloudError("VLR payload overlaps point data")
    prefix, records = raw[:offset], raw[offset:]
    returns = [0] * 5
    extents = [[math.inf, -math.inf] for _ in range(3)]
    for index in range(count):
        start = index * record_size
        ints = struct.unpack_from("<3i", records, start)
        bits = records[start + 14]
        number, total = bits & 7, (bits >> 3) & 7
        # LAS 1.2 has five return counters. This supported subset uses returns 1..5.
        if not 1 <= number <= total <= 5:
            raise PointCloudError("only valid LAS return numbers 1..5 are supported")
        returns[number - 1] += 1
        scan = struct.unpack_from("<b", records, start + 16)[0]
        if not -90 <= scan <= 90:
            raise PointCloudError("LAS 1.2 scan angle rank must be -90..90")
        if fmt in (1, 3) and not math.isfinite(struct.unpack_from("<d", records, start + 20)[0]):
            raise PointCloudError("GPS time must be finite")
        for a in range(3):
            value = ints[a] * scales[a] + offsets[a]
            if not math.isfinite(value):
                raise PointCloudError("decoded point coordinates overflow")
            extents[a][0] = min(extents[a][0], value)
            extents[a][1] = max(extents[a][1], value)
    if tuple(returns) != struct.unpack_from("<5I", prefix, 111):
        raise PointCloudError("header return counts disagree with actual points")
    expected = tuple(v for lowhigh in extents for v in (lowhigh[1], lowhigh[0])) if count else (0.,) * 6
    if bounds != expected:
        raise PointCloudError("header bounds disagree with decoded point extrema")
    return prefix, records


@dataclass(frozen=True)
class PointCloud:
    """Immutable encoded storage; view decimation never modifies these bytes."""
    prefix: bytes
    records: bytes
    identities: tuple[str, ...]
    metadata_json: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, bytes) or not isinstance(self.records, bytes) or not isinstance(self.metadata_json, bytes) or len(self.metadata_json) > 64_000:
            raise PointCloudError("bounded immutable encoded bytes required")
        _decode(self.prefix + self.records)
        try:
            _metadata(_strict_json(self.metadata_json))
        except (ValueError, UnicodeError) as e:
            raise PointCloudError(f"invalid point metadata: {e}") from e
        if not isinstance(self.identities, tuple) or any(not isinstance(x, str) or not 1 <= len(x) <= 100 for x in self.identities):
            raise PointCloudError("point identities must be a tuple of bounded literal strings")
        if len(self.identities) != self.count or len(set(self.identities)) != self.count:
            raise PointCloudError("every point requires a unique retained source identity")

    @property
    def count(self) -> int:
        return len(self.records) // LENGTHS[self.point_format]

    @property
    def point_format(self) -> int:
        return self.prefix[104]

    @property
    def metadata(self) -> dict:
        return _strict_json(self.metadata_json)

    @property
    def scales(self) -> tuple[float, ...]:
        return struct.unpack_from("<3d", self.prefix, 131)

    @property
    def offsets(self) -> tuple[float, ...]:
        return struct.unpack_from("<3d", self.prefix, 155)

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "metadata": self.metadata, "prefix_hex": self.prefix.hex(), "records_hex": self.records.hex(), "identities": list(self.identities)}

    @classmethod
    def from_dict(cls, data: dict) -> "PointCloud":
        if not isinstance(data, dict) or set(data) != {"schema", "metadata", "prefix_hex", "records_hex", "identities"} or data.get("schema") != SCHEMA:
            raise PointCloudError("unsupported point-cloud schema or fields")
        if not isinstance(data["identities"], list) or len(data["identities"]) > MAX_POINTS:
            raise PointCloudError("bounded point identity array required")
        for key in ("prefix_hex", "records_hex"):
            value = data[key]
            if not isinstance(value, str) or len(value) > MAX_BYTES * 2 or any(c not in "0123456789abcdef" for c in value):
                raise PointCloudError(f"{key} must be bounded lowercase hexadecimal")
        try:
            return cls(bytes.fromhex(data["prefix_hex"]), bytes.fromhex(data["records_hex"]), tuple(data["identities"]), _json(_metadata(data["metadata"])))
        except (ValueError, TypeError) as e:
            raise PointCloudError(f"invalid encoded point cloud: {e}") from e


def read_las(path: str | Path, *, metadata: dict) -> PointCloud:
    raw = _read(path, MAX_BYTES)
    prefix, records = _decode(raw)
    count = struct.unpack_from("<I", prefix, 107)[0]
    source_hash = _hash(raw)
    return PointCloud(prefix, records, tuple(f"{source_hash}:{i}" for i in range(count)), _json(_metadata(metadata)))


def write_las(cloud: PointCloud, path: str | Path) -> Path:
    cloud = PointCloud.from_dict(cloud.to_dict())
    return _write(path, cloud.prefix + cloud.records)


def save_pointcloud(cloud: PointCloud, path: str | Path) -> Path:
    cloud = PointCloud.from_dict(cloud.to_dict())
    return _write(path, _json(cloud.to_dict()), MAX_JSON_BYTES)


def load_pointcloud(path: str | Path) -> PointCloud:
    return PointCloud.from_dict(_strict_json(_read(path, MAX_JSON_BYTES)))


def points(cloud: PointCloud, *, indices: list[int] | None = None) -> list[dict]:
    result = []
    size = LENGTHS[cloud.point_format]
    if indices is None:
        indices = list(range(cloud.count))
    elif not isinstance(indices, list) or len(indices) > MAX_POINTS:
        raise PointCloudError("bounded point index list required")
    for i in indices:
        _int(i, 0, cloud.count - 1, "point index")
        identity = cloud.identities[i]
        start = i * size
        x, y, z, intensity, bits, classification, scan, user, source = struct.unpack_from("<iiiHBBbBH", cloud.records, start)
        xyz = [v * s + o for v, s, o in zip((x, y, z), cloud.scales, cloud.offsets)]
        record = {"index": i, "identity": identity, "raw_xyz": [x, y, z], "x": xyz[0], "y": xyz[1], "z": xyz[2], "intensity": intensity,
                  "return_number": bits & 7, "number_of_returns": (bits >> 3) & 7, "scan_direction": bool(bits & 64), "edge_of_flight_line": bool(bits & 128),
                  "classification": classification & 31, "synthetic": bool(classification & 32), "key_point": bool(classification & 64), "withheld": bool(classification & 128),
                  "scan_angle_rank": scan, "user_data": user, "point_source_id": source}
        if cloud.point_format in (1, 3):
            record["gps_time"] = struct.unpack_from("<d", cloud.records, start + 20)[0]
        if cloud.point_format in (2, 3):
            record["rgb"] = list(struct.unpack_from("<3H", cloud.records, start + (28 if cloud.point_format == 3 else 20)))
        result.append(record)
    return result


def _subset(cloud: PointCloud, indices: list[int]) -> PointCloud:
    size = LENGTHS[cloud.point_format]
    records = b"".join(cloud.records[i * size:(i + 1) * size] for i in indices)
    prefix = bytearray(cloud.prefix)
    prefix[26:58] = b"EXTRACTION".ljust(32, b"\x00")
    prefix[58:90] = b"BasinLens pointcloud-v1".ljust(32, b"\x00")
    struct.pack_into("<I", prefix, 107, len(indices))
    counts = [0] * 5
    xyz = []
    for i in indices:
        start = i * size
        counts[(cloud.records[start + 14] & 7) - 1] += 1
        xyz.append([v * s + o for v, s, o in zip(struct.unpack_from("<3i", cloud.records, start), cloud.scales, cloud.offsets)])
    struct.pack_into("<5I", prefix, 111, *counts)
    bounds = [v for a in range(3) for v in (max(p[a] for p in xyz), min(p[a] for p in xyz))] if xyz else [0.] * 6
    struct.pack_into("<6d", prefix, 179, *bounds)
    return PointCloud(bytes(prefix), records, tuple(cloud.identities[i] for i in indices), cloud.metadata_json)


def filter_points(cloud: PointCloud, *, classifications: list[int] | None = None, bbox: list[float] | None = None,
                  height: list[float] | None = None, returns: list[int] | None = None, include_withheld: bool = True) -> PointCloud:
    """Inclusive XYZ bounds; classification ignores the independent flags."""
    if not isinstance(include_withheld, bool):
        raise PointCloudError("include_withheld must be boolean")
    for name, values, lo, hi in (("classifications", classifications, 0, 31), ("returns", returns, 1, 5)):
        if values is not None:
            if not isinstance(values, list) or not values or len(values) > hi + 1  or any(isinstance(v, (list, dict)) for v in values) or len(set(values)) != len(values):
                raise PointCloudError(f"{name} must be a bounded unique nonempty list")
            for v in values:
                _int(v, lo, hi, name)
    for name, values, n in (("bbox", bbox, 4), ("height", height, 2)):
        if values is not None:
            if not isinstance(values, (list, tuple)) or len(values) != n:
                raise PointCloudError(f"{name} requires {n} finite values")
            for v in values:
                _number(v, name)
            if (n == 4 and (values[0] > values[2] or values[1] > values[3])) or (n == 2 and values[0] > values[1]):
                raise PointCloudError(f"{name} minimum exceeds maximum")
    selected = [p["index"] for p in points(cloud) if
                (classifications is None or p["classification"] in classifications) and
                (returns is None or p["return_number"] in returns) and
                (bbox is None or bbox[0] <= p["x"] <= bbox[2] and bbox[1] <= p["y"] <= bbox[3]) and
                (height is None or height[0] <= p["z"] <= height[1]) and
                (include_withheld or not p["withheld"])]
    result = _subset(cloud, selected)
    meta = result.metadata
    meta["provenance"].append("Filtered original encoded points with " + json.dumps(dict(classifications=classifications, bbox=bbox, height=height, returns=returns, include_withheld=include_withheld), sort_keys=True, separators=(",", ":")))
    return PointCloud(result.prefix, result.records, result.identities, _json(_metadata(meta)))


def merge_pointclouds(clouds: list[PointCloud]) -> PointCloud:
    if not isinstance(clouds, list) or not 1 <= len(clouds) <= 32:
        raise PointCloudError("merge requires 1..32 clouds")
    first = clouds[0]
    # Prefix metadata other than totals/bounds must be identical: no implicit
    # reprojection, rescaling, GPS-time reinterpretation or unknown VLR discard.
    def contract(c):
        p = bytearray(c.prefix)
        p[107:131] = bytes(24)
        p[179:227] = bytes(48)
        metadata = c.metadata
        del metadata["provenance"]
        return bytes(p), metadata
    target = contract(first)
    if any(contract(c) != target for c in clouds):
        raise PointCloudError("merge requires identical metadata, LAS header contract, scales, offsets and opaque VLR bytes")
    total = sum(c.count for c in clouds)
    if total > MAX_POINTS:
        raise PointCloudError("merged point budget exceeded")
    ids = tuple(i for c in clouds for i in c.identities)
    if len(set(ids)) != len(ids):
        raise PointCloudError("merge would duplicate original point identities")
    # Build the aggregate as encoded points, then update the exact header totals.
    raw = b"".join(c.records for c in clouds)
    prefix = bytearray(first.prefix)
    prefix[26:58] = b"MERGE".ljust(32, b"\x00")
    prefix[58:90] = b"BasinLens pointcloud-v1".ljust(32, b"\x00")
    struct.pack_into("<I", prefix, 107, total)
    counts = [sum(struct.unpack_from("<5I", c.prefix, 111)[i] for c in clouds) for i in range(5)]
    struct.pack_into("<5I", prefix, 111, *counts)
    nonempty = [c for c in clouds if c.count]
    bounds = []
    for a in range(3):
        bounds.extend((max(struct.unpack_from("<6d", c.prefix, 179)[2 * a] for c in nonempty), min(struct.unpack_from("<6d", c.prefix, 179)[2 * a + 1] for c in nonempty)) if nonempty else (0., 0.))
    struct.pack_into("<6d", prefix, 179, *bounds)
    metadata = first.metadata
    metadata["provenance"] = list(dict.fromkeys(statement for cloud in clouds for statement in cloud.metadata["provenance"]))
    metadata["provenance"].append(f"Merged {len(clouds)} compatible point clouds; retained original point identities and encoded attributes; no reprojection or rescaling")
    return PointCloud(bytes(prefix), raw, ids, _json(_metadata(metadata)))


def aggregate_grid(cloud: PointCloud, *, x_origin: float, y_origin: float, dx: float, dy: float,
                   nrow: int, ncol: int, crs: str, horizontal_unit: str, vertical_datum: str,
                   statistic: str = "mean", field: str = "z") -> dict:
    """South-to-north cells; half-open outer domain, internal edges go upper/right.

    No interpolation/extrapolation. Unsupported cells have null, zero count and
    false support. Count is an actual point count, not an elevation estimate.
    """
    _int(nrow, 1, MAX_CELLS, "nrow"); _int(ncol, 1, MAX_CELLS, "ncol")
    if nrow * ncol > MAX_CELLS:
        raise PointCloudError("grid cell budget exceeded")
    x_origin = _number(x_origin, "x_origin"); y_origin = _number(y_origin, "y_origin")
    dx = _number(dx, "dx"); dy = _number(dy, "dy")
    if dx <= 0 or dy <= 0 or not math.isfinite(x_origin + ncol * dx) or not math.isfinite(y_origin + nrow * dy):
        raise PointCloudError("positive finite grid extent required")
    if any(max(math.ulp(origin), math.ulp(origin + count * step)) > step * 1e-8 for origin, count, step in ((x_origin, ncol, dx), (y_origin, nrow, dy))):
        raise PointCloudError("grid origin/step precision is insufficient for reliable point binning")
    if cloud.metadata["crs"] == "unknown" or crs != cloud.metadata["crs"] or horizontal_unit == "unknown" or horizontal_unit != cloud.metadata["horizontal_unit"] or vertical_datum != cloud.metadata["vertical_datum"]:
        raise PointCloudError("grid and point cloud require identical explicit CRS, horizontal unit and vertical datum")
    if statistic not in ("mean", "min", "max", "count") or field not in ("z", "intensity"):
        raise PointCloudError("supported statistics mean/min/max/count; fields z/intensity")
    bins = [[] for _ in range(nrow * ncol)]
    retained = [[] for _ in bins]
    excluded = []
    for p in points(cloud):
        # Explicit domain comparison avoids rounding an outside point inside.
        if not (x_origin <= p["x"] < x_origin + ncol * dx and y_origin <= p["y"] < y_origin + nrow * dy):
            excluded.append(p["identity"]); continue
        def cell(value, origin, step, count):
            fraction = (value - origin) / step
            nearest = round(fraction)
            if 0 <= nearest <= count and value == origin + nearest * step:
                fraction = nearest
            return min(count - 1, math.floor(fraction))
        c = cell(p["x"], x_origin, dx, ncol)
        r = cell(p["y"], y_origin, dy, nrow)
        index = r * ncol + c
        bins[index].append(p[field]); retained[index].append(p["identity"])
    values = []
    for b in bins:
        value = None if not b else (len(b) if statistic == "count" else min(b) if statistic == "min" else max(b) if statistic == "max" else math.fsum(v / len(b) for v in b))
        if value is not None and not math.isfinite(value):
            raise PointCloudError("aggregated value overflow")
        values.append(value)
    return {"schema": "basinlens-pointcloud-grid-v1", "metadata": cloud.metadata, "grid": {"x_origin": x_origin, "y_origin": y_origin, "dx": dx, "dy": dy, "nrow": nrow, "ncol": ncol, "row_axis": "south_to_north", "domain": "half_open_max"},
            "statistic": statistic, "field": field, "value_unit": "1" if statistic == "count" else cloud.metadata["vertical_unit"] if field == "z" else "LAS intensity unsigned integer",
            "values": [values[r * ncol:(r + 1) * ncol] for r in range(nrow)], "counts": [[len(b) for b in bins[r * ncol:(r + 1) * ncol]] for r in range(nrow)],
            "support": [[bool(b) for b in bins[r * ncol:(r + 1) * ncol]] for r in range(nrow)], "point_identities": [retained[r * ncol:(r + 1) * ncol] for r in range(nrow)], "excluded_identities": excluded}


def render_points(cloud: PointCloud, max_points: int = 10_000) -> dict:
    _int(max_points, 1, 20_000, "max_points")
    indices = list(range(cloud.count)) if cloud.count <= max_points else [(i * cloud.count) // max_points for i in range(max_points)]
    return {"points": points(cloud, indices=indices), "stored_count": cloud.count, "rendered_count": len(indices), "decimation": "deterministic index stride; stored encoded points unchanged"}


def inspect_pointcloud(cloud: PointCloud) -> dict:
    return {"schema": SCHEMA, "point_count": cloud.count, "point_format": cloud.point_format, "scales": list(cloud.scales), "offsets": list(cloud.offsets),
            "bounds_max_min_xyz": list(struct.unpack_from("<6d", cloud.prefix, 179)), "vlr_count": struct.unpack_from("<I", cloud.prefix, 100)[0],
            "opaque_prefix_sha256": _hash(cloud.prefix), "encoded_points_sha256": _hash(cloud.records), "metadata": cloud.metadata,
            "scope": "LAS 1.2 uncompressed formats 0..3, returns 1..5; no GMS equivalence or CRS interpretation"}


def verify_pointcloud_roundtrip(cloud: PointCloud, output_dir: str | Path) -> dict:
    out = Path(output_dir)
    try:
        out.mkdir()
    except OSError as e:
        raise PointCloudError(f"fresh roundtrip directory required: {e}") from e
    # An incomplete owned directory remains diagnostic if any subsequent I/O fails.
    las = write_las(cloud, out / "points.las")
    native = save_pointcloud(cloud, out / "points.json")
    a, b = read_las(las, metadata=cloud.metadata), load_pointcloud(native)
    if a.prefix != cloud.prefix or a.records != cloud.records or b.to_dict() != cloud.to_dict():
        raise PointCloudError("point-cloud roundtrip mismatch")
    receipt = {"schema": "basinlens-pointcloud-roundtrip-v1", "las_sha256": _hash(_read(las, MAX_BYTES)), "json_sha256": _hash(_read(native, MAX_JSON_BYTES)),
               "point_count": cloud.count, "encoded_point_bytes_equal": True, "opaque_prefix_bytes_equal": True, "native_json_identities_equal": True,
               "las_identity_note": "LAS has no field for the retained per-point source identities; points.json preserves them", "original_gms_comparison": "NOT_OBSERVED"}
    _write(out / "receipt.json", _json(receipt))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "filter", "export", "roundtrip", "rasterize"):
        p = sub.add_parser(name); p.add_argument("input", type=Path)
        if name != "inspect": p.add_argument("output", type=Path)
        if name == "filter":
            p.add_argument("--classes", type=int, nargs="+"); p.add_argument("--bbox", type=float, nargs=4); p.add_argument("--height", type=float, nargs=2); p.add_argument("--returns", type=int, nargs="+")
        if name == "rasterize": p.add_argument("--grid", type=Path, required=True)
    p = sub.add_parser("import-las"); p.add_argument("input", type=Path); p.add_argument("output", type=Path); p.add_argument("--metadata", type=Path, required=True)
    p = sub.add_parser("merge"); p.add_argument("output", type=Path); p.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "import-las":
            cloud = read_las(args.input, metadata=_strict_json(_read(args.metadata, 64_000))); save_pointcloud(cloud, args.output)
        elif args.command == "merge":
            save_pointcloud(merge_pointclouds([load_pointcloud(p) for p in args.inputs]), args.output)
        else:
            cloud = load_pointcloud(args.input)
            if args.command == "inspect": print(json.dumps(inspect_pointcloud(cloud), indent=2))
            elif args.command == "export": write_las(cloud, args.output)
            elif args.command == "filter": save_pointcloud(filter_points(cloud, classifications=args.classes, bbox=args.bbox, height=args.height, returns=args.returns), args.output)
            elif args.command == "roundtrip": print(json.dumps(verify_pointcloud_roundtrip(cloud, args.output), indent=2))
            elif args.command == "rasterize": _write(args.output, _json(aggregate_grid(cloud, **_strict_json(_read(args.grid, 64_000)))))
        return 0
    except (PointCloudError, ValueError, TypeError, RecursionError) as e:
        parser.exit(2, f"pointcloud: {e}\n")


if __name__ == "__main__":
    raise SystemExit(main())
