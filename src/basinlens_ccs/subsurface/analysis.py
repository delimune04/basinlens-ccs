"""Source-bound structured-volume sampling and manual head comparisons.

These independent tools operate on the existing flat-layer water workflow.
Unsupported coordinates are masked; no extrapolation, CRS conversion, fitted
parameters, isosurfaces or original GMS equivalence are implied.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat

import numpy as np

from .model_workflow import WorkflowCase, preview_grid, read_workflow_results
from ..groundwater.native_run import verify_native_run

MAX_POINTS = 100_000
MAX_OBSERVATIONS = 5_000
MAX_BYTES = 32 * 1024 * 1024
FIELDS = {"head_m": "m", "kx_m_day": "m/day", "ky_m_day": "m/day",
          "kz_m_day": "m/day", "ss_per_m": "1/m", "porosity": "1"}


class AnalysisError(ValueError):
    """Unsupported support, inconsistent evidence or bounded-input failure."""


def _raw(value):
    try:
        return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                           allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise AnalysisError(f"Finite JSON data required: {error}") from error


def _decode(raw):
    if len(raw) > MAX_BYTES:
        raise AnalysisError("JSON exceeds the 32 MiB read budget")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AnalysisError("Duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise AnalysisError("Nonfinite JSON number")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
        _raw(value)  # Also rejects finite-looking JSON exponents that overflow.
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise AnalysisError(f"Invalid JSON: {error}") from error


def _read(path, limit=MAX_BYTES):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AnalysisError("Symbolic links are outside analysis file support")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise AnalysisError("Bounded regular file required")
            result = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(result) > limit or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AnalysisError("Input changed or exceeded the read budget")
        return result
    except OSError as error:
        raise AnalysisError(f"Cannot read bounded input: {path.name}: {error}") from error


def _number(value, name, *, minimum=-1e12, maximum=1e12):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise AnalysisError(f"{name}: finite numeric value required")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise AnalysisError(f"{name}: finite numeric value required") from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise AnalysisError(f"{name}: finite number in [{minimum}, {maximum}] required")
    return number


def _array(value, name, *, dimensions=None, maximum=MAX_POINTS):
    pending = [value]
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > maximum * 4 + 1000:
            raise AnalysisError(f"{name}: bounded numeric array required")
        if isinstance(item, (bool, np.bool_)):
            raise AnalysisError(f"{name}: boolean values are not coordinates or fields")
        if isinstance(item, (list, tuple)):
            if len(item) > maximum:
                raise AnalysisError(f"{name}: bounded numeric array required")
            pending.extend(item)
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in "iuf" or raw.size > maximum:
            raise AnalysisError(f"{name}: bounded real numeric array required")
        array = raw.astype(float)
    except (ValueError, TypeError, OverflowError) as error:
        raise AnalysisError(f"{name}: bounded real numeric array required") from error
    if dimensions is not None and array.ndim != dimensions:
        raise AnalysisError(f"{name}: requires {dimensions} dimensions")
    if not np.isfinite(array).all() or (np.abs(array) > 1e12).any():
        raise AnalysisError(f"{name}: finite values with magnitude <= 1e12 required")
    return array


def _text(value, name):
    if (not isinstance(value, str) or not value.strip() or len(value) > 500
            or any(ord(c) < 32 for c in value)):
        raise AnalysisError(f"{name}: explicit bounded nonempty text required")
    return value


def _immutable(array):
    values = np.asarray(array, dtype="<f8", order="C")
    return np.frombuffer(values.tobytes(), dtype="<f8").reshape(values.shape)


class AnalysisVolume:
    """Immutable captured arrays; construct manual fixtures via ``from_arrays``.

    Public array construction is labelled authored arrays, never solver evidence.
    Verified runs are loaded with ``load_analysis_run`` and their original case
    cannot be replaced by a caller-supplied project.
    """

    def __init__(self, case, times_day, heads_m, *, provenance):
        self._initialize(case, times_day, heads_m, {
            "kind": "AUTHORED_ARRAYS", "provenance": _text(provenance, "provenance"),
            "solver_execution_verified": False})

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("AnalysisVolume is an immutable captured snapshot")
        object.__setattr__(self, name, value)

    @classmethod
    def from_arrays(cls, case, times_day, heads_m, *, provenance):
        return cls(case, times_day, heads_m, provenance=provenance)

    def _initialize(self, case, times_day, heads_m, source):
        if not isinstance(case, WorkflowCase):
            raise AnalysisError("Validated WorkflowCase required")
        data = case.to_dict()
        times = _array(times_day, "times_day", dimensions=1, maximum=1000)
        if not len(times) or (times < 0).any() or (np.diff(times) <= 0).any():
            raise AnalysisError("Strictly increasing nonnegative saved times required")
        heads = _array(heads_m, "heads_m", dimensions=4, maximum=2_000_000)
        if heads.shape != (len(times), *case.shape):
            raise AnalysisError("Heads must cover every captured time and project cell")
        self._case_json = _raw(data)
        self._times = _immutable(times)
        self._heads = _immutable(heads)
        source = {**source, "case_sha256": hashlib.sha256(self._case_json).hexdigest(),
                  "heads_array_sha256": hashlib.sha256(self._heads.tobytes()).hexdigest(),
                  "times_day": times.tolist()}
        self._source_json = _raw(source)
        self._preview_json = _raw(preview_grid(case))
        self._sealed = True

    @property
    def case(self):
        return WorkflowCase.from_dict(_decode(self._case_json))

    @property
    def source(self):
        return _decode(self._source_json)

    @property
    def times_day(self):
        return self._times.copy()

    @property
    def case_sha256(self):
        return self.source["case_sha256"]

    @property
    def _preview(self):
        return _decode(self._preview_json)

    def _field(self, field, time_day, temporal_method):
        if field not in FIELDS:
            raise AnalysisError(f"Unsupported field; choose {sorted(FIELDS)}")
        if temporal_method not in ("exact", "linear"):
            raise AnalysisError("temporal_method must be exact or linear")
        if field != "head_m":
            if time_day is not None:
                raise AnalysisError("Static material fields require time_day=None")
            values = np.asarray([c[field] for c in self._preview["cells"]]).reshape(self.case.shape)
            return values, {"kind": "static_material_metadata", "time_day": None}
        time = float(self._times[-1]) if time_day is None else _number(time_day, "time_day", minimum=0)
        hits = np.flatnonzero(self._times == time)
        if len(hits):
            index = int(hits[0])
            return self._heads[index], {"kind": "saved_time", "time_day": time, "saved_indices": [index]}
        if temporal_method != "linear" or not self._times[0] < time < self._times[-1]:
            raise AnalysisError("Requested time is not saved or lies outside interpolation support")
        upper = int(np.searchsorted(self._times, time))
        lower = upper - 1
        weight = (time - self._times[lower]) / (self._times[upper] - self._times[lower])
        return (1 - weight) * self._heads[lower] + weight * self._heads[upper], {
            "kind": "declared_linear_temporal_interpolation", "time_day": time,
            "saved_indices": [lower, upper], "saved_times_day": self._times[[lower, upper]].tolist(),
            "upper_weight": float(weight)}

    def _result(self, operation, field, temporal_support, rows, **metadata):
        return {"schema": "basinlens-structured-analysis-v1", "operation": operation,
                "field": field, "value_unit": FIELDS[field], "coordinate_unit": "m",
                "crs": self._preview["crs"], "vertical_datum": self._preview["vertical_datum"],
                "temporal_support": temporal_support, "source": self.source, "rows": rows,
                "geometry_scope": "uniform unrotated XY; flat layers; all cells active; Z upward",
                "gms_parity_established": False, "field_validation_established": False,
                **metadata}

    def query(self, points_xyz_m, *, field="head_m", time_day=None,
              spatial_method="cell", temporal_method="exact"):
        """Sample containing cells or interpolate within the centre convex box.

        Cell ownership is [xmin,xmax), [ymin,ymax), (bottom,top]. Layer
        interfaces belong to the layer below. Centre interpolation supports a
        singleton axis only within 1e-9 m of its centre. No value is extrapolated.
        """
        points = _array(points_xyz_m, "points_xyz_m", dimensions=2, maximum=3 * MAX_POINTS)
        if points.shape[1:] != (3,) or not 1 <= len(points) <= MAX_POINTS:
            raise AnalysisError("One to 100,000 explicit XYZ points required")
        values, temporal = self._field(field, time_day, temporal_method)
        grid = self.case.to_dict()["grid"]
        shape = self.case.shape
        x, y, z = points.T
        col = np.floor((x - grid["x_origin_m"]) / grid["dx_m"]).astype(np.int64)
        row = np.floor((y - grid["y_origin_m"]) / grid["dy_m"]).astype(np.int64)
        layer = np.searchsorted(-np.asarray(grid["layer_surfaces_m"]), -z, side="right") - 1
        cells = np.column_stack((layer, row, col))
        owned = np.all((cells >= 0) & (cells < np.asarray(shape)), axis=1)
        sampled = np.zeros(len(points))
        support = owned.copy()
        if spatial_method == "cell":
            sampled[support] = values[layer[support], row[support], col[support]]
        elif spatial_method == "linear_centres":
            axes = (grid["x_origin_m"] + (np.arange(shape[2]) + .5) * grid["dx_m"],
                    grid["y_origin_m"] + (np.arange(shape[1]) + .5) * grid["dy_m"],
                    (np.asarray(grid["layer_surfaces_m"][:-1]) + np.asarray(grid["layer_surfaces_m"][1:]))[::-1] / 2)
            lower, upper, weights = [], [], []
            support = np.ones(len(points), dtype=bool)
            for axis, coords in zip(axes, points.T):
                if len(axis) == 1:
                    support &= np.abs(coords - axis[0]) <= 1e-9
                    lo = hi = np.zeros(len(points), dtype=int)
                    weight = np.zeros(len(points))
                else:
                    support &= (coords >= axis[0]) & (coords <= axis[-1])
                    hi = np.clip(np.searchsorted(axis, coords, side="right"), 1, len(axis) - 1)
                    lo = hi - 1
                    weight = (coords - axis[lo]) / (axis[hi] - axis[lo])
                lower.append(lo); upper.append(hi); weights.append(weight)
            ascending = values[::-1]
            # Evaluate only supported points; no out-of-support weight is used.
            indices = np.flatnonzero(support)
            for bx in (0, 1):
                for by in (0, 1):
                    for bz in (0, 1):
                        bits = (bx, by, bz)
                        ijk = [(upper[d] if bits[d] else lower[d])[indices] for d in range(3)]
                        weight = np.ones(len(indices))
                        for d, bit in enumerate(bits):
                            weight *= (weights[d] if bit else 1 - weights[d])[indices]
                        sampled[indices] += weight * ascending[ijk[2], ijk[1], ijk[0]]
        else:
            raise AnalysisError("spatial_method must be cell or linear_centres")
        rows = [{"point_index": i, "x_m": float(p[0]), "y_m": float(p[1]), "z_m": float(p[2]),
                 "supported": bool(support[i]), "value": float(sampled[i]) if support[i] else None,
                 "layer": int(layer[i]) if owned[i] else None,
                 "row": int(row[i]) if owned[i] else None,
                 "column": int(col[i]) if owned[i] else None} for i, p in enumerate(points)]
        return self._result("query", field, temporal, rows, spatial_method=spatial_method,
            spatial_support="containing cell: [xmin,xmax), [ymin,ymax), (bottom,top]" if spatial_method == "cell"
                else "cell-centre convex box; singleton axes require centre +/-1e-9 m; no extrapolation",
            interpolation_cell_indices="reported cell is containing cell, not all interpolation vertices")

    def section(self, polyline_xy_m, z_m, spacing_m, **query_options):
        """Sample regular chainage plus every vertex/end point at explicit Zs."""
        line = _array(polyline_xy_m, "polyline_xy_m", dimensions=2, maximum=2000)
        z = _array(z_m, "z_m", dimensions=1, maximum=1000)
        spacing = _number(spacing_m, "spacing_m", minimum=1e-6)
        if line.shape[1:] != (2,) or len(line) < 2 or not len(z):
            raise AnalysisError("Polyline needs 2..1000 XY vertices and 1..1000 explicit Z selections")
        lengths = np.linalg.norm(np.diff(line, axis=0), axis=1)
        if (lengths <= 0).any():
            raise AnalysisError("Consecutive section vertices must differ")
        chain = np.r_[0., np.cumsum(lengths)]
        if not math.isfinite(float(chain[-1])) or math.ceil(chain[-1] / spacing) + len(chain) > MAX_POINTS // len(z):
            raise AnalysisError("Section exceeds the 100,000-point budget")
        distances = np.unique(np.r_[np.arange(0., chain[-1], spacing), chain])
        if len(distances) * len(z) > MAX_POINTS:
            raise AnalysisError("Section exceeds the 100,000-point budget")
        segments = np.minimum(np.searchsorted(chain, distances, side="right") - 1, len(lengths) - 1)
        fraction = (distances - chain[segments]) / lengths[segments]
        xy = line[segments] + fraction[:, None] * (line[segments + 1] - line[segments])
        points = np.column_stack((np.repeat(xy, len(z), axis=0), np.tile(z, len(xy))))
        result = self.query(points, **query_options)
        for row, distance, segment in zip(result["rows"], np.repeat(distances, len(z)), np.repeat(segments, len(z))):
            row.update(chainage_m=float(distance), segment_index=int(segment))
        result.update(operation="section", polyline_xy_m=line.tolist(), z_selections_m=z.tolist(),
                      spacing_m=spacing, sampling="regular chainage plus exact vertices and end point")
        return result

    def clip(self, *, field="head_m", time_day=None, temporal_method="exact",
             scalar_min=None, scalar_max=None, plane=None, visibility=None):
        """AND cell-centre plane/scalar/boolean masks; no cut-cell mesh is made."""
        values, temporal = self._field(field, time_day, temporal_method)
        flat = values.reshape(-1)
        visible = np.ones(len(flat), dtype=bool)
        low = None if scalar_min is None else _number(scalar_min, "scalar_min")
        high = None if scalar_max is None else _number(scalar_max, "scalar_max")
        if low is not None and high is not None and low > high:
            raise AnalysisError("scalar_min must not exceed scalar_max")
        if low is not None:
            visible &= flat >= low
        if high is not None:
            visible &= flat <= high
        centres = np.asarray([[c["x_m"], c["y_m"], (c["top_m"] + c["bottom_m"]) / 2]
                              for c in self._preview["cells"]])
        plane_list = None
        if plane is not None:
            p = _array(plane, "plane", dimensions=1, maximum=4)
            if p.shape != (4,) or not np.any(p[:3] != 0):
                raise AnalysisError("Plane needs nonzero normal and [nx,ny,nz,offset_m] coefficients")
            visible &= centres @ p[:3] + p[3] >= 0
            plane_list = p.tolist()
        if visibility is not None:
            mask = np.asarray(visibility)
            if mask.dtype.kind != "b" or mask.shape not in ((len(flat),), self.case.shape):
                raise AnalysisError("visibility must be an exact flat or project-shaped boolean mask")
            visible &= mask.reshape(-1)
        rows = [{"layer": c["layer"], "row": c["row"], "column": c["column"],
                 "x_m": float(xyz[0]), "y_m": float(xyz[1]), "z_m": float(xyz[2]),
                 "value": float(value), "visible": bool(show)}
                for c, xyz, value, show in zip(self._preview["cells"], centres, flat, visible)]
        return self._result("clip", field, temporal, rows, scalar_min=low, scalar_max=high,
            plane=plane_list, plane_rule="nx*x_m+ny*y_m+nz*z_m+offset_m >= 0",
            explicit_visibility_applied=visibility is not None,
            visible_cells=int(visible.sum()), clipping_scope="whole-cell visibility by cell centres; no geometric intersection")

    def section_frames(self, frames, **query_options):
        """Generate bounded sampled moving-section data, without rendering video."""
        if not isinstance(frames, list) or not 1 <= len(frames) <= 100:
            raise AnalysisError("One to 100 explicit section frames required")
        output, count = [], 0
        # Each temporary section is bounded by MAX_POINTS. Combined output is
        # checked before retaining it, so at most one additional bounded frame
        # is computed beyond the accepted combined budget.
        for item in frames:
            if not isinstance(item, dict) or set(item) != {"polyline_xy_m", "z_m", "spacing_m", "time_day"}:
                raise AnalysisError("Each frame requires polyline_xy_m,z_m,spacing_m,time_day")
            result = self.section(item["polyline_xy_m"], item["z_m"], item["spacing_m"],
                                  time_day=item["time_day"], **query_options)
            count += len(result["rows"])
            if count > MAX_POINTS:
                raise AnalysisError("Combined frames exceed 100,000 sampled points")
            output.append(result)
        return {"schema": "basinlens-section-frames-v1", "source": self.source,
                "frames": output, "frame_count": len(output), "sample_count": count,
                "scope": "sampled section data; no video or original GMS animation", "gms_parity_established": False}

    def compare_observations(self, observations, *, temporal_method="exact"):
        """Manual residual diagnostics, never parameter fitting or field validation."""
        required = {"schema", "project_id", "case_sha256", "crs", "vertical_datum", "units", "observations"}
        if not isinstance(observations, dict) or set(observations) != required:
            raise AnalysisError("Observation document requires exact versioned metadata and records")
        data = self.case.to_dict()
        expected = {"schema": "basinlens-head-observations-v1", "project_id": data["project"]["id"],
                    "case_sha256": self.case_sha256, "crs": data["project"]["crs"],
                    "vertical_datum": data["project"]["vertical_datum"], "units": {"head": "m", "time": "day"}}
        if any(observations.get(k) != v for k, v in expected.items()):
            raise AnalysisError("Observations must match captured case identity, literal CRS/datum and exact m/day units")
        records = observations["observations"]
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_OBSERVATIONS:
            raise AnalysisError("One to 5,000 explicit manual observations required")
        rows, identifiers, supports = [], set(), []
        for record in records:
            if not isinstance(record, dict) or set(record) != {"id", "time_day", "cell", "head_m", "sigma_m", "basis", "provenance"}:
                raise AnalysisError("Observation requires id,time_day,cell,head_m,sigma_m,basis,provenance")
            oid = _text(record["id"], "observation.id")
            if oid in identifiers:
                raise AnalysisError("Observation identifiers must be unique")
            identifiers.add(oid)
            if record["basis"] not in ("synthetic", "measured", "interpreted"):
                raise AnalysisError("Observation basis must be synthetic, measured or interpreted")
            _text(record["provenance"], "observation.provenance")
            cell = record["cell"]
            if (not isinstance(cell, list) or len(cell) != 3 or
                    any(type(i) is not int or not 0 <= i < n for i, n in zip(cell, self.case.shape))):
                raise AnalysisError("Observation requires a valid explicit [layer,row,column] support cell")
            observed = _number(record["head_m"], "head_m")
            sigma = _number(record["sigma_m"], "sigma_m", minimum=1e-12)
            time = _number(record["time_day"], "observation.time_day", minimum=0)
            values, support = self._field("head_m", time, temporal_method)
            simulated = float(values[tuple(cell)])
            residual = simulated - observed
            rows.append({"id": oid, "time_day": support["time_day"], "layer": cell[0], "row": cell[1], "column": cell[2],
                         "observed_head_m": observed, "simulated_head_m": simulated, "sigma_m": sigma,
                         "residual_m": residual, "normalized_residual": residual / sigma,
                         "basis": record["basis"], "provenance": record["provenance"],
                         "temporal_support_kind": support["kind"]})
            supports.append({"id": oid, **support})
        residuals = np.asarray([r["residual_m"] for r in rows])
        sigma = np.asarray([r["sigma_m"] for r in rows])
        weights = 1 / sigma ** 2
        objective = float(np.sum((residuals / sigma) ** 2))
        metrics = {"count": len(rows), "bias_m": float(np.mean(residuals)),
                   "rmse_m": float(np.sqrt(np.mean(residuals ** 2))),
                   "mae_m": float(np.mean(np.abs(residuals))),
                   "weighted_rmse_m": float(np.sqrt(np.sum(weights * residuals ** 2) / np.sum(weights))),
                   "normalized_rmse": float(math.sqrt(objective / len(rows))), "objective_chi_square": objective}
        return self._result("manual_observation_comparison", "head_m", {"method": temporal_method}, rows,
            metrics=metrics, observation_sha256=hashlib.sha256(_raw(observations)).hexdigest(),
            observation_temporal_support=supports, residual_convention="simulated minus observed",
            objective_definition="sum((residual_m/sigma_m)^2); diagnostics only; no parameter fit or statistical acceptance",
            metadata_scope="literal CRS/datum equality; an unknown label remains unknown; explicit indexed cell support",
            parameter_fit_performed=False, pest_implemented=False)


def load_analysis_run(workspace):
    """Capture arrays only after existing native/case verification, then recheck."""
    root = Path(workspace).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise AnalysisError("Run path must not traverse symbolic links")
    before = verify_native_run(root)
    result = read_workflow_results(root)
    after = verify_native_run(root)
    if _raw(before) != _raw(after):
        raise AnalysisError("Run inventory changed while capturing analysis arrays")
    source = {"kind": "VERIFIED_WORKFLOW_RUN", "workspace": str(root),
              "solver_execution_verified": True, "solver": result.summary["solver"],
              "run_metadata_sha256": hashlib.sha256(_raw(after)).hexdigest(),
              "captured_settings_sha256": hashlib.sha256(_read(root / "source_sidecars/settings.json")).hexdigest(),
              "native_head_sha256": hashlib.sha256(_read(root / "native/flow.hds")).hexdigest(),
              "native_inputs": after["source_snapshot"]["inputs"],
              "model_validation_scope": result.summary["validation_scope"],
              "gms_parity_established": False}
    volume = object.__new__(AnalysisVolume)
    volume._initialize(result.case, result.times_day, result.heads_m, source)
    # Files used in the identity must still agree with the final native inventory.
    if _raw(verify_native_run(root)) != _raw(after):
        raise AnalysisError("Run changed while capturing source identity")
    return volume


def _csv_bytes(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_POINTS:
        raise AnalysisError("Bundle requires 1..100,000 flat rows")
    if not isinstance(rows[0], dict):
        raise AnalysisError("CSV requires scalar row dictionaries")
    fields = sorted(rows[0])
    if any(not isinstance(row, dict) or sorted(row) != fields or
           any(isinstance(v, (dict, list)) for v in row.values()) for row in rows):
        raise AnalysisError("CSV requires consistently ordered scalar-only row fields")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_analysis_bundle(result, output_dir):
    """Write a fresh CSV/JSON bundle; reject altered captured solver sources."""
    if not isinstance(result, dict) or result.get("schema") != "basinlens-structured-analysis-v1":
        raise AnalysisError("Structured analysis result required; frame bundles must be exported individually")
    raw = _raw(result)
    if len(raw) > MAX_BYTES:
        raise AnalysisError("Analysis result exceeds the 32 MiB output budget")
    csv_raw = _csv_bytes(result.get("rows"))
    source = result.get("source", {})
    folder = Path(output_dir).absolute()
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise AnalysisError("Output path must not traverse symbolic links")
    if source.get("kind") == "VERIFIED_WORKFLOW_RUN":
        root = Path(source["workspace"])
        if folder == root or root in folder.parents:
            raise AnalysisError("Analysis output must be outside the immutable source run")
        if hashlib.sha256(_raw(verify_native_run(root))).hexdigest() != source["run_metadata_sha256"]:
            raise AnalysisError("Captured source run changed before analysis export")
    folder.mkdir(parents=True, exist_ok=False)
    files = {"analysis.json": raw, "samples.csv": csv_raw}
    for name, payload in files.items():
        (folder / name).write_bytes(payload)
    manifest = {"schema": "basinlens-analysis-bundle-v1", "source": source,
                "analysis_module_sha256": hashlib.sha256(_read(__file__)).hexdigest(),
                "files": {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                          for name, payload in files.items()}}
    (folder / "manifest.json").write_bytes(_raw(manifest))
    verify_analysis_bundle(folder)
    return folder


def verify_analysis_bundle(folder):
    folder = Path(folder)
    manifest = _decode(_read(folder / "manifest.json"))
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "source", "analysis_module_sha256", "files"}
            or manifest["schema"] != "basinlens-analysis-bundle-v1"
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != {"analysis.json", "samples.csv"}
            or {p.name for p in folder.iterdir()} != {"manifest.json", "analysis.json", "samples.csv"}):
        raise AnalysisError("Incomplete, extra or unsupported analysis bundle inventory")
    files = {name: _read(folder / name) for name in manifest["files"]}
    for name, payload in files.items():
        if manifest["files"][name] != {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}:
            raise AnalysisError("Analysis artifact changed")
    result = _decode(files["analysis.json"])
    if (not isinstance(result, dict) or result.get("schema") != "basinlens-structured-analysis-v1"
            or result.get("source") != manifest["source"] or _csv_bytes(result.get("rows")) != files["samples.csv"]):
        raise AnalysisError("Analysis JSON/CSV/source identities differ")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("query", "section", "clip", "compare"):
        item = commands.add_parser(command)
        item.add_argument("workspace", type=Path)
        item.add_argument("--output", type=Path, required=True)
        item.add_argument("--temporal", choices=("exact", "linear"), default="exact")
        if command == "compare":
            item.add_argument("observations", type=Path)
        else:
            item.add_argument("--field", choices=sorted(FIELDS), default="head_m")
            item.add_argument("--time", type=float)
        if command in ("query", "section"):
            item.add_argument("--method", choices=("cell", "linear_centres"), default="cell")
        if command == "query":
            item.add_argument("--points", required=True, help="JSON [[x_m,y_m,z_m],...]")
        elif command == "section":
            item.add_argument("--polyline", required=True, help="JSON [[x_m,y_m],...]")
            item.add_argument("--z", required=True, help="JSON [z_m,...]")
            item.add_argument("--spacing", required=True, type=float)
        elif command == "clip":
            item.add_argument("--scalar-min", type=float)
            item.add_argument("--scalar-max", type=float)
            item.add_argument("--plane", help="JSON [nx,ny,nz,offset]")
    args = parser.parse_args(argv)
    try:
        volume = load_analysis_run(args.workspace)
        options = {"temporal_method": args.temporal}
        if args.command != "compare":
            options.update(field=args.field, time_day=args.time)
        if args.command in ("query", "section"):
            options["spatial_method"] = args.method
        if args.command == "query":
            result = volume.query(_decode(args.points.encode()), **options)
        elif args.command == "section":
            result = volume.section(_decode(args.polyline.encode()), _decode(args.z.encode()), args.spacing, **options)
        elif args.command == "clip":
            result = volume.clip(scalar_min=args.scalar_min, scalar_max=args.scalar_max,
                                 plane=None if args.plane is None else _decode(args.plane.encode()), **options)
        else:
            result = volume.compare_observations(_decode(_read(args.observations)), **options)
        print(json.dumps({"output": str(write_analysis_bundle(result, args.output)),
                          "operation": result["operation"], "rows": len(result["rows"])}, sort_keys=True))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(2, f"analysis failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
