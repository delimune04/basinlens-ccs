"""Optional FloPy/MODFLOW 6 adapter and auditable file bundles."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .schema import GroundwaterCase, GroundwaterValidationError, UNITS, load_case


class GroundwaterDependencyError(RuntimeError):
    """An optional dependency or solver is not installed."""


class GroundwaterRunError(RuntimeError):
    """The solver failed, or its outputs did not meet operational checks."""


@dataclass
class GroundwaterResult:
    heads: np.ndarray
    times_days: np.ndarray
    summary: dict
    workspace: Path


def _flopy():
    try:
        import flopy
    except ImportError as exc:
        raise GroundwaterDependencyError("Groundwater export/run needs FloPy: pip install 'basinlens-ccs[groundwater]' (or pip install flopy)") from exc
    return flopy


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _case(case):
    # Copy and revalidate even mutable dataclasses before using a snapshot.
    return GroundwaterCase.from_dict(case.to_dict() if isinstance(case, GroundwaterCase) else case)


def _prepare_output(output_dir):
    root = Path(output_dir).expanduser().absolute()
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"Output already exists; choose a new directory: {root}")
    root.mkdir(parents=True, exist_ok=False)
    return root


def _versions():
    try:
        package = importlib.metadata.version("basinlens-ccs")
    except importlib.metadata.PackageNotFoundError:
        package = "source checkout"
    return {"python": platform.python_version(), "numpy": np.__version__, "flopy": _flopy().__version__, "basinlens_ccs": package}


def _metadata(root, status, **extra):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "run_metadata.json":
            files[str(path.relative_to(root))] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    source_files = sorted(Path(__file__).parent.glob("*.py"))
    _json(root / "run_metadata.json", {
        "manifest_schema_version": 1, "status": status, "created_utc": datetime.now(timezone.utc).isoformat(),
        "case_sha256": _sha(root / "case.json"), "versions": _versions(),
        "adapter_source_sha256": {p.name: _sha(p) for p in source_files}, "files": files, **extra})


def _build(case, root, exe_name="mf6"):
    flopy = _flopy()
    g, p, b = case.grid, case.properties, case.boundaries
    nl, nr, nc = g["nlay"], g["nrow"], g["ncol"]
    shape = (nl, nr, nc)
    sim = flopy.mf6.MFSimulation(sim_name="basinlens", version="mf6", exe_name=str(exe_name), sim_ws=str(root / "model"))
    flopy.mf6.ModflowTdis(sim, time_units="DAYS", nper=len(case.periods),
        perioddata=[(x["length_days"], x["steps"], 1.0) for x in case.periods])
    flopy.mf6.ModflowIms(sim, print_option="SUMMARY", complexity="MODERATE", linear_acceleration="BICGSTAB",
        outer_dvclose=1e-8, inner_dvclose=1e-9, rcloserecord=1e-6, outer_maximum=100, inner_maximum=300)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="aquifer", save_flows=True)
    flopy.mf6.ModflowGwfdis(gwf, length_units="METERS", nlay=nl, nrow=nr, ncol=nc,
        delr=g["delr_m"], delc=g["delc_m"], top=g["top_m"], botm=g["layer_bottoms_m"])
    def layer_array(key):
        return np.broadcast_to(np.array(p[key], dtype=float)[:, None, None], shape).copy()
    initial = np.broadcast_to(np.linspace(b["left_head_m"], b["right_head_m"], nc), shape).copy()
    if case.initial_head_m is not None:
        initial.fill(case.initial_head_m)
    flopy.mf6.ModflowGwfic(gwf, strt=initial)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=layer_array("kx_m_per_day"), k22=layer_array("ky_m_per_day"),
        k33=layer_array("kz_m_per_day"), save_specific_discharge=True, save_flows=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=layer_array("specific_storage_per_m"), sy=0.0,
        steady_state={i: True for i, x in enumerate(case.periods) if not x["transient"]},
        transient={i: True for i, x in enumerate(case.periods) if x["transient"]}, save_flows=True)
    chd = [((layer, row, col), head) for layer in range(nl) for row in range(nr)
           for col, head in ((0, b["left_head_m"]), (nc - 1, b["right_head_m"]))]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd}, save_flows=True)
    if case.recharge_m_per_day:
        # Make the model's recharge support explicit: exclude CHD columns.
        # MF6 can skip recharge on fixed-head cells; do not infer a CHD recharge
        # contribution from the full rectangular top area.
        # Exclude both CHD columns to keep the reported forcing unambiguous.
        recharge = np.full((nr, nc), case.recharge_m_per_day)
        recharge[:, [0, -1]] = 0.0
        flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge, save_flows=True)
    well_data = {}
    for i, period in enumerate(case.periods):
        well_data[i] = [((w["layer"], w["row"], w["column"]), w["rate_m3_per_day"])
                        for w in period.get("wells", case.wells)]
    if any(well_data.values()):
        flopy.mf6.ModflowGwfwel(gwf, stress_period_data=well_data, save_flows=True)
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="aquifer.hds", budget_filerecord="aquifer.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")], printrecord=[("BUDGET", "ALL")])
    sim.write_simulation(silent=True)
    _json(root / "case.json", case.to_dict())
    _json(root / "input_provenance.json", {"schema_version": 1, "case_sha256": _sha(root / "case.json"),
        "units": UNITS, "provenance": case.provenance,
        "coordinate_convention": {"indices": "zero-based layer,row,column", "x": "column increases east",
            "y": "row 0 is north; row index increases south", "z": "elevation increases upward",
            "fixed_heads": "at centres of first/last columns, not exterior grid faces"},
        "recharge_support": "top layer; excludes constant-head first/last columns",
        "well_sign": "positive=injection of water; negative=extraction",
        "validation_level": "input contract checked; numerical benchmark status is separate"})
    return sim


def export_case(case, output_dir) -> Path:
    """Export portable MF6 inputs, without downloading or executing a solver."""
    case = _case(case)
    _flopy()
    root = _prepare_output(output_dir)
    try:
        _build(case, root)
        _metadata(root, "exported", engine="MODFLOW 6", solver_executed=False)
    except Exception as exc:
        _json(root / "failure.json", {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)})
        raise
    return root


def _resolve_executable(exe_name):
    executable = shutil.which(str(exe_name))
    if executable is None:
        candidate = Path(exe_name).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            executable = str(candidate.resolve())
    if executable is None:
        raise GroundwaterDependencyError(
            f"MODFLOW 6 executable not found or not executable: {exe_name}. Install it separately and pass --exe /path/to/mf6. "
            "Export needs no solver. Optional opt-in download: python tools/install_mf6.py --accept-download --destination /path/to/bin")
    return str(Path(executable).resolve())


def _engine_version(executable):
    try:
        result = subprocess.run([executable, "-v"], capture_output=True, text=True, timeout=10, check=False)
        return (result.stdout + result.stderr).strip()[:1000]
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (version probe failed)"


def _budget(root, expected_times):
    flopy = _flopy()
    listing = flopy.utils.Mf6ListBudget(root / "model" / "aquifer.lst", timeunit="days")
    incremental = listing.get_incremental()
    if incremental is None or len(incremental) == 0:
        raise GroundwaterRunError("MODFLOW listing contains no water-budget records")
    keys = list(incremental.dtype.names)
    with (root / "water_budget_listing.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(keys)
        writer.writerows([[float(row[key]) for key in keys] for row in incremental])
    discrepancy_key = next((x for x in keys if "PERCENT_DISCREPANCY" in x), None)
    if discrepancy_key is None:
        raise GroundwaterRunError("Water budget lacks PERCENT_DISCREPANCY")
    if not all(np.all(np.isfinite(incremental[x])) for x in keys):
        raise GroundwaterRunError("Water budget contains non-finite values")
    listing_error = float(np.max(np.abs(incremental[discrepancy_key])))
    # The listing rounds percentages. Aggregate actual external/storage q terms
    # from double-precision CBC records for the conservation acceptance gate.
    # FLOW-JA-FACE is internal exchange; DATA-SPDIS is a diagnostic vector.
    binary = flopy.utils.CellBudgetFile(root / "model" / "aquifer.cbc", precision="double")
    records = []
    try:
        times = np.asarray(binary.get_times(), dtype=float)
        if times.shape != expected_times.shape or not np.allclose(times, expected_times, rtol=0, atol=1e-10):
            raise GroundwaterRunError("Binary budget times do not match saved heads")
        terms = [x.strip() for x in binary.get_unique_record_names(decode=True)
                 if x.strip() not in ("FLOW-JA-FACE", "DATA-SPDIS")]
        for i, time in enumerate(times):
            row = {"totim": float(time), "time_index": i}
            total_in = total_out = 0.0
            for term in terms:
                arrays = binary.get_data(text=term, totim=float(time))
                q = np.concatenate([np.asarray(a["q"] if a.dtype.names and "q" in a.dtype.names else a,
                                               dtype=float).ravel() for a in arrays]) if arrays else np.array([])
                if not np.all(np.isfinite(q)):
                    raise GroundwaterRunError("Binary water budget contains non-finite rates")
                inflow = float(q[q > 0].sum())
                outflow = float(-q[q < 0].sum())
                row[term + "_IN"], row[term + "_OUT"] = inflow, outflow
                total_in += inflow
                total_out += outflow
            residual = total_in - total_out
            scale = 0.5 * (total_in + total_out)
            # A relative residual is ill-conditioned near zero flow. Accept by
            # either 1e-6 m3/day absolute tolerance OR 0.1% relative tolerance;
            # retain the raw percentage (possibly large) as context, never 0%.
            percentage = 100.0 * residual / scale if scale > 0 else None
            tolerance = max(1e-6, 0.001 * scale)
            if abs(residual) > tolerance:
                raise GroundwaterRunError(f"Binary water budget residual {residual:.6g} m3/day exceeds combined tolerance {tolerance:.6g} m3/day")
            row.update({"TOTAL_IN": total_in, "TOTAL_OUT": total_out, "IN-OUT": residual,
                        "PERCENT_DISCREPANCY": percentage, "GATE_TOLERANCE_M3_PER_DAY": tolerance,
                        "ACCEPTED_BY_ABSOLUTE_TOLERANCE": abs(residual) <= 1e-6})
            records.append(row)
    finally:
        binary.close()
    with (root / "water_budget.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    percentages = [abs(row["PERCENT_DISCREPANCY"]) for row in records if row["PERCENT_DISCREPANCY"] is not None]
    max_error = max(percentages) if percentages else None
    return {"max_abs_percent_discrepancy": max_error, "gate_percent": 0.1,
        "listing_max_abs_percent_discrepancy": listing_error,
        "source": "double-precision binary external and storage rates; internal face flows excluded",
        "absolute_gate_m3_per_day": 1e-6,
        "gate_passed": True, "gate_rule": "abs(in-out) <= max(1e-6 m3/day, 0.001 * mean(total_in,total_out)); percentages near zero flow are contextual",
        "max_abs_residual_m3_per_day": max(abs(row["IN-OUT"]) for row in records),
        "unit": "flow terms m3/day; percent discrepancy %; totim days", "records": len(records),
        "final_record": records[-1]}


def run_case(case, output_dir, exe_name="mf6") -> GroundwaterResult:
    """Run an explicitly installed MF6. Never downloads or changes physics on retry."""
    case = _case(case)
    flopy = _flopy()
    # Refuse reused outputs before invoking any executable.
    if Path(output_dir).expanduser().exists() or Path(output_dir).expanduser().is_symlink():
        raise FileExistsError(f"Output already exists; choose a new directory: {output_dir}")
    executable = _resolve_executable(exe_name)
    root = _prepare_output(output_dir)
    version = _engine_version(executable)
    engine_info = {"engine": "MODFLOW 6", "engine_version": version, "executable_sha256": _sha(executable),
                   "solver_executed": False, "command": [executable], "timeout_seconds": 120}
    try:
        _build(case, root, executable)
        try:
            process = subprocess.run([executable], cwd=root / "model", capture_output=True, text=True, timeout=120, check=False)
            engine_info["solver_executed"] = True
        except subprocess.TimeoutExpired as exc:
            engine_info["solver_executed"] = True
            (root / "solver.stdout.log").write_text((exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""), encoding="utf-8")
            raise GroundwaterRunError("MODFLOW 6 exceeded the 120 second bounded run timeout") from exc
        (root / "solver.stdout.log").write_text(process.stdout, encoding="utf-8")
        (root / "solver.stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode or "normal termination of simulation" not in process.stdout.lower():
            raise GroundwaterRunError(f"MODFLOW 6 failed (exit={process.returncode}); inspect {root / 'solver.stdout.log'}")
        reader = flopy.utils.HeadFile(root / "model" / "aquifer.hds", precision="double")
        try:
            times = np.asarray(reader.get_times(), dtype=float)
            heads = np.asarray(reader.get_alldata(), dtype=float)
        finally:
            reader.close()
        g = case.grid
        expected_shape = (sum(x["steps"] for x in case.periods), g["nlay"], g["nrow"], g["ncol"])
        if heads.shape != expected_shape or not np.all(np.isfinite(heads)) or np.any(np.abs(heads) > 1e20):
            raise GroundwaterRunError(f"Missing/invalid head fields: expected {expected_shape}, got {heads.shape}")
        if len(times) != len(heads) or np.any(np.diff(times) <= 0) or not np.isclose(times[-1], sum(x["length_days"] for x in case.periods)):
            raise GroundwaterRunError("Output time coordinates do not match the requested schedule")
        budget = _budget(root, times)
        np.savez_compressed(root / "heads.npz", heads=heads, times_days=times, units_head=np.array("m"), units_time=np.array("days"))
        with (root / "head_times.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_index", "time_days", "head_min_m", "head_max_m"])
            writer.writerows((i, float(t), float(heads[i].min()), float(heads[i].max())) for i, t in enumerate(times))
        confined_valid = bool(np.min(heads) >= g["top_m"] - 1e-7)
        if not confined_valid:
            raise GroundwaterRunError("Computed head falls below aquifer top: fully confined assumption violated; raw solver outputs retained")
        summary = {"schema_version": 1, "case_id": case.case_id, "engine": "MODFLOW 6", "engine_version": version,
            "mode": "single-phase confined groundwater", "head_min_m": float(heads.min()), "head_max_m": float(heads.max()),
            "final_head_min_m": float(heads[-1].min()), "final_head_max_m": float(heads[-1].max()),
            "cell_count": g["nlay"] * g["nrow"] * g["ncol"], "time_steps": len(times), "final_time_days": float(times[-1]),
            "water_budget": budget, "confined_head_above_top": confined_valid,
            "validation_level": "synthetic operational checks; no real-site validation",
            "limitations": ["Constant-density single-phase water; no CO2, multiphase plume, transport, geochemistry or geomechanics",
                "Rectangular all-active grid; homogeneous tensor per layer; no-flow north/south/base",
                "Fixed heads occupy first/last cell centres; recharge excludes these columns",
                "Positive wells inject water; no wellbore or near-well injectivity correction",
                "Software benchmark evidence is not site suitability or containment validation"]}
        _json(root / "summary.json", summary)
        _metadata(root, "completed", **engine_info)
        return GroundwaterResult(heads=heads, times_days=times, summary=summary, workspace=root)
    except Exception as exc:
        _json(root / "failure.json", {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)})
        if (root / "case.json").exists():
            _metadata(root, "failed", **engine_info)
        if isinstance(exc, (GroundwaterRunError, GroundwaterValidationError)):
            raise
        raise GroundwaterRunError(f"Groundwater run failed: {exc}; diagnostics retained in {root}") from exc


def verify_bundle(root):
    """Check structural completeness and bytes; not an authenticity guarantee."""
    root = Path(root).expanduser().resolve()
    try:
        manifest_path = root / "run_metadata.json"
        if manifest_path.is_symlink():
            raise GroundwaterValidationError("Manifest must not be a symbolic link")
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or type(metadata.get("manifest_schema_version")) is not int or metadata["manifest_schema_version"] != 1:
            raise GroundwaterValidationError("Manifest must be an object with manifest_schema_version=1")
        status = metadata.get("status")
        if not isinstance(status, str) or status not in ("completed", "exported"):
            raise GroundwaterValidationError("Bundle is not a completed run or successful export")
        files = metadata.get("files")
        if not isinstance(files, dict) or not files:
            raise GroundwaterValidationError("Manifest files must be a nonempty object")
        required = {"case.json", "input_provenance.json", "model/mfsim.nam", "model/aquifer.nam",
                    "model/aquifer.dis", "model/aquifer.npf", "model/aquifer.ic", "model/aquifer.chd",
                    "model/aquifer.sto", "model/aquifer.oc", "model/basinlens.tdis", "model/basinlens.ims"}
        if status == "completed":
            required.update({"heads.npz", "head_times.csv", "water_budget.csv", "water_budget_listing.csv", "summary.json",
                             "solver.stdout.log", "solver.stderr.log", "model/aquifer.hds", "model/aquifer.cbc", "model/aquifer.lst"})
        missing = required - set(files)
        if missing:
            raise GroundwaterValidationError(f"Manifest omits required artifacts: {sorted(missing)}")
        for relative, expected in files.items():
            if (not isinstance(relative, str) or not relative or "\\" in relative or relative.startswith("/")
                    or any(part in ("", ".", "..") for part in relative.split("/")) or ":" in relative):
                raise GroundwaterValidationError("Manifest contains an unsafe relative path")
            if (not isinstance(expected, dict) or type(expected.get("size_bytes")) is not int
                    or expected["size_bytes"] < 0 or not isinstance(expected.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None):
                raise GroundwaterValidationError(f"Malformed file record: {relative}")
            path = root
            for part in relative.split("/"):
                path = path / part
                if path.is_symlink():
                    raise GroundwaterValidationError(f"Bundle symbolic links are refused: {relative}")
            if root not in path.resolve().parents:
                raise GroundwaterValidationError("Manifest contains an unsafe relative path")
            if not path.is_file() or path.stat().st_size != expected["size_bytes"] or _sha(path) != expected["sha256"]:
                raise GroundwaterValidationError(f"Bundle integrity check failed: {relative}")
        if metadata.get("case_sha256") != files["case.json"]["sha256"]:
            raise GroundwaterValidationError("Manifest case_sha256 disagrees with its case artifact")
        case = load_case(root / "case.json")
        conditional = set()
        if case.recharge_m_per_day:
            conditional.add("model/aquifer.rcha")
        if any(period.get("wells", case.wells) for period in case.periods):
            conditional.add("model/aquifer.wel")
        if conditional - set(files):
            raise GroundwaterValidationError("Manifest omits case-specific recharge or well inputs")
        return metadata
    except GroundwaterValidationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise GroundwaterValidationError(f"Cannot verify groundwater bundle: {exc}") from exc
