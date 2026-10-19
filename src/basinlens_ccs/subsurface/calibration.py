"""Bounded authored parameter fitting using actual verified MF6 water runs.

This is a deterministic coordinate/bracket optimizer, not PEST. Synthetic fits
and local sensitivity rank do not establish unique field parameters or GMS parity.
Importing, validating or opening a project never executes this module's solver.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

import numpy as np

from .analysis import AnalysisVolume, load_analysis_run
from .model_workflow import WorkflowCase, run_workflow
from ..groundwater.native_run import verify_native_run

SCHEMA = "basinlens-calibration-v1"
PARAMETER_UNITS = {"kx_m_day": "m/day", "ky_m_day": "m/day", "kz_m_day": "m/day", "ss_per_m": "1/m"}
MAX_BYTES = 8 * 1024 * 1024
MAX_WORKSPACE_BYTES = 512 * 1024 * 1024
MAX_WORKSPACE_FILES = 20_000


class CalibrationError(ValueError):
    """Unsupported problem, failed run, unidentifiable data or altered evidence."""


def _raw(value):
    try:
        raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise CalibrationError(f"finite bounded JSON required: {type(exc).__name__}") from exc
    if len(raw) > MAX_BYTES:
        raise CalibrationError("one calibration document exceeds 8 MiB")
    return raw


def _decode(raw):
    if not isinstance(raw, bytes) or not len(raw) <= MAX_BYTES:
        raise CalibrationError("bounded immutable UTF-8 document bytes required")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CalibrationError("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda x: (_ for _ in ()).throw(CalibrationError("nonfinite JSON number")))
        _raw(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CalibrationError):
            raise
        raise CalibrationError(f"invalid calibration JSON: {type(exc).__name__}") from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise CalibrationError("symbolic-link paths are outside calibration file support")
    return path


def _read(path, maximum=MAX_BYTES):
    path = _path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise CalibrationError("bounded regular input file required")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(raw) != before.st_size or signature(before) != signature(after) or signature(after) != signature(path.lstat()):
            raise CalibrationError("input changed during read")
        return raw
    except OSError as exc:
        raise CalibrationError(f"cannot read input: {exc}") from exc


def _write(path, raw):
    path = _path(path)
    if len(raw) > MAX_BYTES or not path.parent.is_dir():
        raise CalibrationError("bounded output and existing parent required")
    stage = None
    try:
        fd, stage = tempfile.mkstemp(prefix=".calibration-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(stage, path)
    except OSError as exc:
        raise CalibrationError(f"fresh output required: {exc}") from exc
    finally:
        if stage is not None:
            os.unlink(stage)
    return path


def _number(value, name, lo=-1e12, hi=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationError(f"{name}: finite number required")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise CalibrationError(f"{name}: finite number required") from None
    if not math.isfinite(result) or not lo <= result <= hi:
        raise CalibrationError(f"{name}: expected [{lo}, {hi}]")
    return result


def _text(value, name):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise CalibrationError(f"{name}: bounded trimmed text required")
    return value


def _keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CalibrationError(f"{name}: requires exactly {sorted(keys)}")


def _integer(value, name, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise CalibrationError(f"{name}: integer [{lo}, {hi}] required")
    return value


def default_settings(parameters, training_ids, *, withheld_ids=()):
    """Explicit bounded defaults; validate with CalibrationProblem before use."""
    return {"schema": SCHEMA, "parameters": parameters, "training_ids": list(training_ids),
            "withheld_ids": list(withheld_ids), "max_evaluations": 40, "max_total_seconds": 300,
            "per_run_timeout_seconds": 20, "fd_step_fraction": .01, "coordinate_tolerance": .001,
            "max_sweeps": 2, "minimum_sensitivity_norm": 1e-6, "rank_rtol": 1e-6,
            "provenance": "Explicit bounded authored calibration experiment; no field validation"}


def _times(case):
    result, total = [], 0.
    for period in case.to_dict()["periods"]:
        result += [total + period["duration_day"] * (i + 1) / period["nsteps"] for i in range(period["nsteps"])]
        total += period["duration_day"]
    return result


def _validate(case, observations, settings):
    if not isinstance(case, WorkflowCase):
        raise CalibrationError("typed WorkflowCase required")
    data = case.to_dict()
    count = math.prod(case.shape)
    times = _times(case)
    if count > 2000 or len(times) > 100 or count * len(times) > 100_000:
        raise CalibrationError("calibration supports <=2000 cells, <=100 saved steps, <=100000 head values")
    try:
        # Reuse the exact observation contract, not an approximate parallel schema.
        # These zero arrays validate support only and are never used as engine evidence.
        volume = AnalysisVolume.from_arrays(case, times, np.zeros((len(times), *case.shape)),
            provenance="Observation-contract validation only; zeros are not a simulated state")
        volume.compare_observations(observations, temporal_method="exact")
    except (ValueError, RuntimeError) as exc:
        raise CalibrationError(f"invalid source-bound head observations: {exc}") from exc
    if len(observations["observations"]) > 200:
        raise CalibrationError("calibration accepts at most 200 explicit observations")
    keys = {"schema", "parameters", "training_ids", "withheld_ids", "max_evaluations", "max_total_seconds",
            "per_run_timeout_seconds", "fd_step_fraction", "coordinate_tolerance", "max_sweeps",
            "minimum_sensitivity_norm", "rank_rtol", "provenance"}
    _keys(settings, keys, "settings")
    if settings["schema"] != SCHEMA:
        raise CalibrationError("unsupported calibration schema")
    _text(settings["provenance"], "provenance")
    params = settings["parameters"]
    if not isinstance(params, list) or not 1 <= len(params) <= 3:
        raise CalibrationError("one to three explicit material parameters required")
    materials = {m["id"]: m for m in data["materials"]}
    seen, identifiers = set(), set()
    for parameter in params:
        _keys(parameter, {"id", "material_id", "field", "unit", "lower", "upper", "initial", "scale", "prior"}, "parameter")
        pid = _text(parameter["id"], "parameter.id")
        mid = _text(parameter["material_id"], "parameter.material_id")
        field = _text(parameter["field"], "parameter.field")
        if pid in identifiers or (mid, field) in seen or mid not in materials or field not in PARAMETER_UNITS or parameter["unit"] != PARAMETER_UNITS[field]:
            raise CalibrationError("duplicate/unknown material parameter or inconsistent unit")
        identifiers.add(pid); seen.add((mid, field))
        lower_bound, upper_bound = (1e-12, .1) if field == "ss_per_m" else (1e-6, 1e6)
        lower = _number(parameter["lower"], "parameter.lower", lower_bound, upper_bound)
        upper = _number(parameter["upper"], "parameter.upper", lower_bound, upper_bound)
        initial = _number(parameter["initial"], "parameter.initial", lower, upper)
        if (lower >= upper or max(math.ulp(lower), math.ulp(upper)) > (upper-lower)*1e-8
                or initial != materials[mid][field] or parameter["scale"] not in ("linear", "log")):
            raise CalibrationError("ordered parameter bounds, source-case initial value and linear/log scale required")
        prior = parameter["prior"]
        if prior is not None:
            _keys(prior, {"value", "sigma", "unit"}, "prior")
            _number(prior["value"], "prior.value", lower, upper)
            _number(prior["sigma"], "prior.sigma", 1e-12, 1e12)
            if prior["unit"] != parameter["unit"]:
                raise CalibrationError("prior value/sigma units must equal parameter units")
    all_ids = {row["id"] for row in observations["observations"]}
    groups = []
    for name in ("training_ids", "withheld_ids"):
        values = settings[name]
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values) or set(values) - all_ids:
            raise CalibrationError(f"{name}: unique registered observation IDs required")
        groups.append(set(values))
    if not groups[0] or len(groups[0]) < len(params) or groups[0] & groups[1] or groups[0] | groups[1] != all_ids:
        raise CalibrationError("every observation must be assigned once; >=parameter-count training rows and disjoint withheld IDs required")
    _integer(settings["max_evaluations"], "max_evaluations", 8 + 4 * len(params), 100)
    _integer(settings["max_sweeps"], "max_sweeps", 1, 4)
    _number(settings["max_total_seconds"], "max_total_seconds", 1, 3600)
    _number(settings["per_run_timeout_seconds"], "per_run_timeout_seconds", .1, 120)
    _number(settings["fd_step_fraction"], "fd_step_fraction", 1e-4, .1)
    _number(settings["coordinate_tolerance"], "coordinate_tolerance", 1e-5, .1)
    _number(settings["minimum_sensitivity_norm"], "minimum_sensitivity_norm", 1e-12, 1e6)
    _number(settings["rank_rtol"], "rank_rtol", 1e-12, .01)
    return data, observations, settings


@dataclass(frozen=True)
class CalibrationProblem:
    """Original immutable document bytes; JSON views are independent copies."""
    case_document: bytes
    observations_document: bytes
    settings_document: bytes

    def __post_init__(self):
        self.documents()

    @classmethod
    def from_documents(cls, case, observations, settings):
        if not isinstance(case, WorkflowCase):
            raise CalibrationError("typed WorkflowCase required")
        return cls(_raw(case.to_dict()), _raw(observations), _raw(settings))

    def documents(self):
        try:
            case = WorkflowCase.from_dict(_decode(self.case_document))
            observations, settings = _decode(self.observations_document), _decode(self.settings_document)
            _validate(case, observations, settings)
            return case, observations, settings
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            if isinstance(exc, CalibrationError):
                raise
            raise CalibrationError(f"invalid calibration problem: {exc}") from exc


def load_calibration_problem(case_path, observations_path, settings_path):
    paths = [case_path, observations_path, settings_path]
    originals = [_read(p) for p in paths]
    problem = CalibrationProblem(*originals)
    if any(_read(path) != raw for path, raw in zip(paths, originals)):
        raise CalibrationError("original calibration source changed while loading")
    return problem


def _physical(parameter, u):
    lo, hi = parameter["lower"], parameter["upper"]
    if u == 0: return float(lo)
    if u == 1: return float(hi)
    return math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo))) if parameter["scale"] == "log" else lo + u * (hi - lo)


def _scaled(parameter, value):
    lo, hi = parameter["lower"], parameter["upper"]
    return (math.log(value) - math.log(lo)) / (math.log(hi) - math.log(lo)) if parameter["scale"] == "log" else (value - lo) / (hi - lo)


def parameter_case(case, parameters, values):
    """Copy only declared physical material fields; never mutate source/control data."""
    if not isinstance(values, (list, tuple)) or len(values) != len(parameters):
        raise CalibrationError("one physical value required for each parameter")
    data = case.to_dict()
    original = case.to_dict()
    materials = {m["id"]: m for m in data["materials"]}
    for parameter, value in zip(parameters, values):
        value = _number(value, "trial value", parameter["lower"], parameter["upper"])
        materials[parameter["material_id"]][parameter["field"]] = value
    result = WorkflowCase.from_dict(data)
    # Revert declared fields before asserting all geometry, controls, metadata and
    # undeclared material fields still match the source observation reference.
    reverted = result.to_dict()
    for parameter in parameters:
        index = next(i for i, m in enumerate(original["materials"]) if m["id"] == parameter["material_id"])
        reverted["materials"][index][parameter["field"]] = original["materials"][index][parameter["field"]]
    if reverted != original:
        raise CalibrationError("trial changed non-parameter model contract")
    return result


def sensitivity_diagnostics(jacobian, *, minimum_norm=1e-6, rank_rtol=1e-6):
    """Local weighted-data Jacobian only; priors are deliberately excluded."""
    try:
        if isinstance(jacobian,(list,tuple)):
            for row in jacobian:
                if isinstance(row,(list,tuple)) and any(isinstance(v,(bool,np.bool_)) for v in row):
                    raise CalibrationError("boolean values are not sensitivity derivatives")
        arr = np.asarray(jacobian)
        if arr.dtype.kind not in "iuf" or arr.ndim != 2 or not 1 <= arr.shape[1] <= 3 or not arr.shape[1] <= arr.shape[0] <= 200:
            raise CalibrationError("bounded real [training observations,parameters] Jacobian required")
        arr = arr.astype(float)
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, CalibrationError): raise
        raise CalibrationError("invalid finite sensitivity Jacobian") from exc
    if not np.isfinite(arr).all() or (np.abs(arr)>1e100).any():
        raise CalibrationError("nonfinite sensitivity Jacobian")
    minimum_norm = _number(minimum_norm, "minimum_norm", 1e-12, 1e6)
    rank_rtol = _number(rank_rtol, "rank_rtol", 1e-12, .01)
    singular = np.linalg.svd(arr, compute_uv=False)
    norms = np.linalg.norm(arr, axis=0)
    rank = int(np.sum(singular > max(minimum_norm, singular[0] * rank_rtol)))
    return {"jacobian": arr.tolist(), "derivative": "d(simulated_head_m/sigma_m)/d(normalized_parameter_coordinate)",
            "column_norms": norms.tolist(), "singular_values": singular.tolist(), "rank": rank,
            "parameter_count": arr.shape[1], "locally_identifiable": bool(rank == arr.shape[1] and np.all(norms > minimum_norm)),
            "priors_used_in_rank": False, "scope": "local finite-difference sensitivity; no proof of global uniqueness or parameter uncertainty"}


def _metrics(rows):
    if not rows: return {"count": 0, "data_sse": None, "rmse_m": None, "rows": []}
    return {"count": len(rows), "data_sse": math.fsum(r["normalized_residual"] ** 2 for r in rows),
            "rmse_m": math.sqrt(math.fsum(r["residual_m"] ** 2 for r in rows) / len(rows)), "rows": rows}


def _comparison(volume, base, observations, settings):
    projection = json.loads(_raw(observations))
    projection["case_sha256"] = volume.case_sha256
    compared = volume.compare_observations(projection, temporal_method="exact")
    lookup = {r["id"]: r for r in compared["rows"]}
    training = _metrics([lookup[oid] for oid in settings["training_ids"]])
    withheld = _metrics([lookup[oid] for oid in settings["withheld_ids"]])
    return {"training": training, "withheld": withheld,
            "observation_binding": {"source_observations_sha256": _sha(_raw(observations)),
                "base_case_sha256": _sha(_raw(base.to_dict())), "trial_case_sha256": volume.case_sha256,
                "projection": "reference base-case observation support retained; only declared physical material fields may change",
                "source_observations_mutated": False},
            "objective_definition": "training sum((simulated_head_m-observed_head_m)^2/sigma_m^2) + parameter prior SSE",
            "weights_unit": "1/m2", "objective_unit": "1", "withheld_used_in_objective": False}


def _directories(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir() and not p.is_symlink())


def _inventory(root):
    files, total = {}, 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink(): raise CalibrationError("symbolic-link calibration artifact refused")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode): continue
        if not stat.S_ISREG(mode): raise CalibrationError("nonregular calibration artifact refused")
        if path.name == "manifest.json" and path.parent == root: continue
        info = path.stat()
        total += info.st_size
        if len(files) >= MAX_WORKSPACE_FILES or total > MAX_WORKSPACE_BYTES:
            raise CalibrationError("calibration workspace exceeds 20000 files /512 MiB")
        # Solver outputs use the native-run bound; hash in chunks, not an 8 MiB JSON read.
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
        files[path.relative_to(root).as_posix()] = {"bytes": info.st_size, "sha256": digest.hexdigest()}
    return files


def run_calibration(problem, output_dir, *, exe_name="mf6"):
    """Execute explicitly requested bounded runs; existing directories are refused.

    Every attempted model evaluation consumes budget, including failed runs.
    Completed evaluations also compute withheld residuals without a second solve.
    No source observation/control/geometry is changed and no auto-resume occurs.
    """
    if not isinstance(problem, CalibrationProblem): raise CalibrationError("typed CalibrationProblem required")
    case, observations, settings = problem.documents()
    parameters = settings["parameters"]
    executable = shutil.which(os.fspath(exe_name))
    if executable is None: raise CalibrationError("trusted MF6 executable unavailable; none downloaded")
    executable = Path(executable).resolve()
    engine_hash = _sha(_read(executable, 128 * 1024 * 1024))
    root = _path(output_dir)
    if not root.parent.is_dir(): raise CalibrationError("output parent must already exist")
    try: root.mkdir()
    except OSError as exc: raise CalibrationError(f"fresh calibration output required: {exc}") from exc
    for directory in ("source", "attempts", "evaluations", "runs", "checkpoints"):
        (root / directory).mkdir()
    source = {"case.json": problem.case_document, "observations.json": problem.observations_document, "settings.json": problem.settings_document}
    for name, raw in source.items(): _write(root / "source" / name, raw)
    started = time.monotonic()
    records, cache, checkpoints = [], {}, 0
    state = {"schema": SCHEMA, "status": "running", "engine": {"name": executable.name, "sha256": engine_hash},
             "source": {name: {"bytes": len(raw), "sha256": _sha(raw)} for name, raw in source.items()},
             "source_case_canonical_sha256": _sha(_raw(case.to_dict())),
             "calibration_module_sha256": _sha(_read(__file__)), "max_evaluations": settings["max_evaluations"],
             "optimizer": "authored deterministic bounded golden-section coordinate search; not PEST",
             "source_observations_mutated": False, "gms_parity_established": False, "field_validation_established": False}
    def checkpoint(event, **details):
        nonlocal checkpoints
        checkpoints += 1
        _write(root / "checkpoints" / f"{checkpoints:04d}.json", _raw({"event": event, "evaluations_consumed": len(records), **details}))
    checkpoint("prepared", source=state["source"], settings=settings)
    def evaluate(u, purpose):
        values = [_physical(p, x) for p, x in zip(parameters, u)]
        key = tuple(values)
        if key in cache: return cache[key]
        if len(records) >= settings["max_evaluations"]: raise CalibrationError("evaluation budget exhausted")
        remaining = settings["max_total_seconds"] - (time.monotonic() - started)
        if remaining <= 0: raise CalibrationError("total calibration time budget exhausted")
        _inventory(root)
        identifier = len(records) + 1
        record = {"evaluation": identifier, "purpose": purpose, "parameters": dict(zip([p["id"] for p in parameters], values)),
                  "normalized_coordinates": list(u), "status": "started", "engine_sha256": engine_hash}
        records.append(record)
        _write(root / "attempts" / f"{identifier:04d}.json", _raw(record))
        interrupted = None
        try:
            trial = parameter_case(case, parameters, values)
            run_calibration_case = run_workflow  # Explicit trusted compiler; no injected/selected callable.
            run_calibration_case(trial, root / "runs" / f"{identifier:04d}", exe_name=str(executable),
                timeout_seconds=min(settings["per_run_timeout_seconds"], remaining))
            volume = load_analysis_run(root / "runs" / f"{identifier:04d}")
            if volume.case.to_dict() != trial.to_dict() or volume.source["solver"]["sha256"] != engine_hash:
                raise CalibrationError("captured solver/case differs from requested evaluation")
            summary = volume.source
            # The reader validates exact native inputs and arrays. Explicit physical
            # support gates still need to pass before accepting a calibration value.
            from .model_workflow import read_workflow_results
            gates = read_workflow_results(root / "runs" / f"{identifier:04d}").summary
            if not all(gates[k] for k in ("water_balance_passed", "boundary_rates_passed", "confined_saturation_support_passed")):
                raise CalibrationError("evaluation failed water/boundary/confined-support gates")
            if time.monotonic()-started > settings["max_total_seconds"]:
                raise CalibrationError("total calibration time budget exceeded during evaluation; native diagnostics retained")
            compared = _comparison(volume, case, observations, settings)
            prior_sse = math.fsum(((v - p["prior"]["value"]) / p["prior"]["sigma"]) ** 2
                                 for p, v in zip(parameters, values) if p["prior"] is not None)
            record.update(status="completed", **compared, prior_sse=prior_sse,
                objective=compared["training"]["data_sse"] + prior_sse,
                case_sha256=volume.case_sha256, verified_source=summary,
                physical_support_gates={k: gates[k] for k in ("water_balance_passed", "boundary_rates_passed", "confined_saturation_support_passed")})
            cache[key] = record
        except BaseException as exc:
            record.update(status="failed", objective=None, error={"type": type(exc).__name__, "message": str(exc)[:2000]})
            cache[key] = None
            if isinstance(exc,(KeyboardInterrupt,SystemExit)): interrupted = exc
        _write(root / "evaluations" / f"{identifier:04d}.json", _raw(record))
        checkpoint("evaluation_finished", evaluation=identifier, status=record["status"])
        _inventory(root)
        if interrupted is not None: raise interrupted
        return cache[key]
    def sensitivity(u, purpose):
        columns, probes = [], []
        for j in range(len(parameters)):
            left, right = list(u), list(u)
            left[j] = max(0., u[j] - settings["fd_step_fraction"])
            right[j] = min(1., u[j] + settings["fd_step_fraction"])
            low, high = evaluate(left, purpose), evaluate(right, purpose)
            if low is None or high is None: raise CalibrationError("failed finite-difference probe; sensitivity not established")
            lv = np.asarray([r["simulated_head_m"] / r["sigma_m"] for r in low["training"]["rows"]])
            hv = np.asarray([r["simulated_head_m"] / r["sigma_m"] for r in high["training"]["rows"]])
            columns.append((hv - lv) / (right[j] - left[j]))
            probes.append({"parameter": parameters[j]["id"], "lower_evaluation": low["evaluation"], "upper_evaluation": high["evaluation"],
                           "lower_coordinate": left[j], "upper_coordinate": right[j]})
        result = sensitivity_diagnostics(np.column_stack(columns), minimum_norm=settings["minimum_sensitivity_norm"], rank_rtol=settings["rank_rtol"])
        result["probes"] = probes
        result["reference_coordinates"] = list(u)
        checkpoint(purpose, **result)
        if not result["locally_identifiable"]:
            raise CalibrationError("training observations are locally unidentifiable/flat; priors cannot supply missing data sensitivity")
        return result
    try:
        current_u = [_scaled(p, p["initial"]) for p in parameters]
        current = evaluate(current_u, "initial")
        if current is None: raise CalibrationError("initial solver evaluation failed; see immutable evaluation/native diagnostics")
        state["initial_sensitivity"] = sensitivity(current_u, "initial_sensitivity")
        current = min((r for r in records if r["status"] == "completed"), key=lambda r: (r["objective"],r["evaluation"]))
        current_u = list(current["normalized_coordinates"])
        stop = "max_sweeps"
        reserve = 2 * len(parameters)
        for sweep in range(settings["max_sweeps"]):
            changed = False
            for j in range(len(parameters)):
                a, b = 0., 1.
                ratio = (math.sqrt(5.) - 1) / 2
                x1, x2 = b - ratio * (b - a), a + ratio * (b - a)
                # Hold every other coordinate fixed throughout this bracket.
                fixed_u = list(current_u)
                def bracket_score(x):
                    nonlocal current, current_u, changed
                    if len(records) >= settings["max_evaluations"] - reserve: return None
                    candidate_u = list(fixed_u); candidate_u[j] = x
                    value = evaluate(candidate_u, "coordinate_search")
                    if value is not None and value["objective"] < current["objective"]:
                        current, current_u, changed = value, candidate_u, True
                    return value
                f1, f2 = bracket_score(x1), bracket_score(x2)
                while b - a > settings["coordinate_tolerance"] and len(records) < settings["max_evaluations"] - reserve:
                    if (math.inf if f1 is None else f1["objective"]) <= (math.inf if f2 is None else f2["objective"]):
                        b, x2, f2 = x2, x1, f1
                        x1 = b - ratio * (b - a); f1 = bracket_score(x1)
                    else:
                        a, x1, f1 = x1, x2, f2
                        x2 = a + ratio * (b - a); f2 = bracket_score(x2)
                # Explicitly inspect both physical bounds; golden-section interiors
                # alone cannot identify a constrained optimum exactly at a bound.
                bracket_score(0.); bracket_score(1.)
                checkpoint("coordinate_finished", sweep=sweep, parameter=parameters[j]["id"],
                           best_evaluation=current["evaluation"], bracket=[a,b])
                if len(records) >= settings["max_evaluations"] - reserve:
                    stop = "evaluation_budget"; break
            if stop == "evaluation_budget": break
            if not changed:
                stop = "no_coordinate_improvement"; break
        state["final_sensitivity"] = sensitivity(current_u, "final_sensitivity")
        # Diagnostic probes are real evaluations too. If one improves the result,
        # retain it and state the local sensitivity anchor explicitly.
        current = min((r for r in records if r["status"] == "completed"), key=lambda r: (r["objective"],r["evaluation"]))
        current_u = list(current["normalized_coordinates"])
        state["final_sensitivity"]["solution_offset_from_reference"] = [v-a for v,a in zip(current_u,state["final_sensitivity"]["reference_coordinates"])]
        if any(abs(v) > settings["fd_step_fraction"] + 1e-12 for v in state["final_sensitivity"]["solution_offset_from_reference"]):
            raise CalibrationError("best sampled solution lies outside final local sensitivity neighbourhood")
        if time.monotonic()-started > settings["max_total_seconds"]:
            raise CalibrationError("total calibration time budget exhausted before accepting result")
        state.update(status="completed", stop_reason=stop, best_evaluation=current["evaluation"],
            best_parameters=current["parameters"], training=current["training"], withheld=current["withheld"],
            prior_sse=current["prior_sse"], objective=current["objective"],
            engine=current["verified_source"]["solver"],
            optimization_convergence_claim="bounded coordinate result only; no global optimum or statistical acceptance established")
        fitted = parameter_case(case, parameters, [current["parameters"][p["id"]] for p in parameters])
        _write(root / "fitted_case.json", _raw(fitted.to_dict()))
    except BaseException as exc:
        state.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)[:2000]},
                     recovery="Original inputs and all attempted runs retained. Inspect evaluations/native logs, correct the cause and use a fresh output path; auto-resume is not implemented.")
        state["evaluations_consumed"] = len(records)
        state["successful_evaluations"] = sum(r["status"] == "completed" for r in records)
        state["failed_evaluations"] = sum(r["status"] == "failed" for r in records)
        _write(root / "result.json", _raw(state))
        manifest = {"schema": "basinlens-calibration-bundle-v1", "status": "failed", "files": _inventory(root), "directories": _directories(root)}
        _write(root / "manifest.json", _raw(manifest))
        if isinstance(exc, (KeyboardInterrupt, SystemExit)): raise
        raise CalibrationError(f"calibration stopped after {len(records)} evaluations: {exc}; saved at {root}") from exc
    state["evaluations_consumed"] = len(records)
    state["successful_evaluations"] = sum(r["status"] == "completed" for r in records)
    state["failed_evaluations"] = sum(r["status"] == "failed" for r in records)
    _write(root / "result.json", _raw(state))
    _write(root / "manifest.json", _raw({"schema": "basinlens-calibration-bundle-v1", "status": "completed", "files": _inventory(root), "directories": _directories(root)}))
    verify_calibration_bundle(root)
    return state


def verify_calibration_bundle(folder):
    """Verify exact persisted sources, every attempted record and native output.

    No engine is executed. For completed evaluations residuals/objectives are
    independently recomputed from verified captured native arrays and observations.
    """
    root = _path(folder)
    manifest = _decode(_read(root / "manifest.json"))
    _keys(manifest, {"schema", "status", "files", "directories"}, "manifest")
    if manifest["schema"] != "basinlens-calibration-bundle-v1" or manifest["status"] not in ("completed", "failed") or manifest["files"] != _inventory(root) or manifest["directories"] != _directories(root):
        raise CalibrationError("calibration inventory/hash/status mismatch")
    problem = load_calibration_problem(root / "source/case.json", root / "source/observations.json", root / "source/settings.json")
    case, observations, settings = problem.documents()
    result = _decode(_read(root / "result.json"))
    if result.get("schema") != SCHEMA or result.get("status") != manifest["status"]:
        raise CalibrationError("result status/schema mismatch")
    if result["source"] != {name: {"bytes": len(_read(root / "source" / name)), "sha256": _sha(_read(root / "source" / name))} for name in ("case.json", "observations.json", "settings.json")}:
        raise CalibrationError("captured source identity mismatch")
    paths = sorted((root / "evaluations").iterdir())
    if len(paths) != result["evaluations_consumed"] or len(paths) > settings["max_evaluations"]:
        raise CalibrationError("attempt count/evaluation budget mismatch")
    if len(list((root / "attempts").iterdir())) != len(paths):
        raise CalibrationError("missing/unaccounted attempt history")
    records = {}
    for i, path in enumerate(paths, 1):
        if path.name != f"{i:04d}.json": raise CalibrationError("nonconsecutive evaluation history")
        record = _decode(_read(path))
        start = _decode(_read(root / "attempts" / path.name))
        if record.get("evaluation") != i or start.get("evaluation") != i or record.get("engine_sha256") != result["engine"]["sha256"]:
            raise CalibrationError("evaluation engine/identity mismatch")
        if any(record.get(k) != v for k,v in start.items() if k != "status") or start.get("status") != "started":
            raise CalibrationError("attempt start and final evaluation differ")
        coordinates = record.get("normalized_coordinates")
        pids = [p["id"] for p in settings["parameters"]]
        if (not isinstance(coordinates,list) or len(coordinates) != len(pids)
                or not isinstance(record.get("parameters"),dict) or set(record["parameters"]) != set(pids)
                or record.get("purpose") not in ("initial","initial_sensitivity","coordinate_search","final_sensitivity")):
            raise CalibrationError("invalid evaluation coordinate/parameter/purpose contract")
        for p,u in zip(settings["parameters"],coordinates):
            u = _number(u,"normalized coordinate",0.,1.)
            if _physical(p,u) != record["parameters"][p["id"]]:
                raise CalibrationError("normalized coordinates differ from actual physical parameters")
        if record.get("status") == "completed":
            trial = parameter_case(case, settings["parameters"], [record["parameters"][p["id"]] for p in settings["parameters"]])
            volume = load_analysis_run(root / "runs" / f"{i:04d}")
            if volume.case.to_dict() != trial.to_dict() or volume.source["solver"]["sha256"] != result["engine"]["sha256"]:
                raise CalibrationError("evaluated native case/engine mismatch")
            compared = _comparison(volume, case, observations, settings)
            if any(record[k] != compared[k] for k in compared):
                raise CalibrationError("persisted residuals/observation binding differ from native result")
            prior = math.fsum(((record["parameters"][p["id"]]-p["prior"]["value"])/p["prior"]["sigma"])**2 for p in settings["parameters"] if p["prior"] is not None)
            if record["prior_sse"] != prior or record["objective"] != compared["training"]["data_sse"] + prior:
                raise CalibrationError("persisted objective differs from actual native residuals/prior")
        elif record.get("status") != "failed" or record.get("objective") is not None:
            raise CalibrationError("unsupported evaluation status")
        records[i] = record
    if result["status"] == "completed":
        best = records.get(result["best_evaluation"])
        if best is None or best["status"] != "completed" or any(result[k] != best[k] for k in ("objective","prior_sse","training","withheld")) or result["best_parameters"] != best["parameters"]:
            raise CalibrationError("best-result metadata differs from selected evaluation")
        if result["objective"] != min(r["objective"] for r in records.values() if r["status"] == "completed"):
            raise CalibrationError("reported best objective is not smallest observed objective")
        fitted = WorkflowCase.from_dict(_decode(_read(root / "fitted_case.json")))
        expected = parameter_case(case, settings["parameters"], [best["parameters"][p["id"]] for p in settings["parameters"]])
        if fitted.to_dict() != expected.to_dict(): raise CalibrationError("fitted case changed unrelated source fields")
        for name in ("initial_sensitivity","final_sensitivity"):
            reported = result[name]
            if not isinstance(reported,dict): raise CalibrationError("typed sensitivity report required")
            reference = reported.get("reference_coordinates")
            probes = reported.get("probes")
            if not isinstance(reference,list) or len(reference) != len(settings["parameters"]) or not isinstance(probes,list) or len(probes) != len(reference):
                raise CalibrationError("invalid sensitivity reference/probe inventory")
            reference = [_number(v,"sensitivity reference coordinate",0.,1.) for v in reference]
            if name == "initial_sensitivity" and reference != [_scaled(p,p["initial"]) for p in settings["parameters"]]:
                raise CalibrationError("initial sensitivity anchor differs from source initial parameters")
            columns = []
            for j,(parameter,probe) in enumerate(zip(settings["parameters"],probes)):
                _keys(probe,{"parameter","lower_evaluation","upper_evaluation","lower_coordinate","upper_coordinate"},"sensitivity probe")
                if probe["parameter"] != parameter["id"]:
                    raise CalibrationError("sensitivity parameter order differs")
                _integer(probe["lower_evaluation"],"lower probe evaluation",1,len(records))
                _integer(probe["upper_evaluation"],"upper probe evaluation",1,len(records))
                low,high = records.get(probe["lower_evaluation"]),records.get(probe["upper_evaluation"])
                if low is None or high is None or low["status"] != "completed" or high["status"] != "completed":
                    raise CalibrationError("missing/failed sensitivity probe")
                expected_low,expected_high = list(reference),list(reference)
                expected_low[j] = max(0.,reference[j]-settings["fd_step_fraction"])
                expected_high[j] = min(1.,reference[j]+settings["fd_step_fraction"])
                if (low["normalized_coordinates"] != expected_low or high["normalized_coordinates"] != expected_high
                        or probe["lower_coordinate"] != expected_low[j] or probe["upper_coordinate"] != expected_high[j]):
                    raise CalibrationError("sensitivity probes changed unrelated coordinates or declared step")
                lv=np.asarray([row["simulated_head_m"]/row["sigma_m"] for row in low["training"]["rows"]])
                hv=np.asarray([row["simulated_head_m"]/row["sigma_m"] for row in high["training"]["rows"]])
                columns.append((hv-lv)/(expected_high[j]-expected_low[j]))
            expected_diagnostics=sensitivity_diagnostics(np.column_stack(columns),minimum_norm=settings["minimum_sensitivity_norm"],rank_rtol=settings["rank_rtol"])
            if any(_raw(reported.get(k)) != _raw(v) for k,v in expected_diagnostics.items()) or not expected_diagnostics["locally_identifiable"]:
                raise CalibrationError("local data sensitivity/rank differs from actual retained native probes")
            if name == "final_sensitivity":
                offset=[v-a for v,a in zip(best["normalized_coordinates"],reference)]
                if reported.get("solution_offset_from_reference") != offset or any(abs(v)>settings["fd_step_fraction"]+1e-12 for v in offset):
                    raise CalibrationError("solution lies outside reported final sensitivity neighbourhood")
    completed = sum(r["status"] == "completed" for r in records.values())
    return {"schema": manifest["schema"], "status": result["status"], "evaluations_verified": len(records),
            "source_documents_preserved": True, "native_residuals_recomputed": completed > 0,
            "completed_native_evaluations_recomputed": completed, "solver_executed_by_verifier": False,
            "original_gms_comparison": "NOT_OBSERVED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "fit"):
        p = sub.add_parser(command); p.add_argument("case"); p.add_argument("observations"); p.add_argument("settings")
        if command == "fit": p.add_argument("--output", required=True); p.add_argument("--exe", default="mf6")
    p = sub.add_parser("verify"); p.add_argument("folder")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify": result = verify_calibration_bundle(args.folder)
        else:
            problem = load_calibration_problem(args.case, args.observations, args.settings)
            result = {"valid": True, "solver_executed": False} if args.command == "check" else run_calibration(problem, args.output, exe_name=args.exe)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"calibration: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
