"""Bounded one-dimensional conservative-solute transport, independent of GMS.

Export uses public FloPy GWF/GWT packages. Execution and run verification reuse
``native_run`` unchanged. This is saturated single-phase constant-density water;
it is not CO2, reactive transport, a GMS project writer or a parity claim.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import tempfile

import numpy as np

from .native_run import NativeRunError, run_native_simulation, verify_native_run

UNITS = {"length": "m", "time": "day", "concentration": "kg/m3",
         "darcy_flux": "m/day", "conductivity": "m/day", "diffusion": "m2/day",
         "porosity": "1", "mass": "kg", "mass_rate": "kg/day"}
MAX_VALUES = 2_000_000
CASE_SCHEMA = "basinlens-transport-1d-v1"
EXPORT_SCHEMA = "basinlens-transport-native-export-v1"
_HEADER = struct.Struct("<iidd16siii")


class TransportError(ValueError):
    """The narrow transport contract or recorded result is invalid."""


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransportError(f"{name}: expected a finite number")
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise TransportError(f"{name}: expected a finite number") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise TransportError(f"{name}: expected number in [{low}, {high}]")
    return value


def _json_bytes(data):
    return (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _read(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise TransportError(f"Expected a regular file within {limit} bytes: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise TransportError("File grew beyond the bounded read limit")
    return data


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TransportError("Duplicate JSON key")
            result[key] = value
        return result
    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise TransportError("Nonfinite JSON number")
        return value
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_float=number, parse_constant=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise TransportError(f"Invalid transport JSON: {error}") from error


@dataclass(frozen=True)
class TransportCase:
    """Uniform 1 x 1 x n grid; all initial values are cell concentrations.

    Positive Darcy flux enters the first cell through WEL and exits the last
    cell through CHD. Zero flux gives no external solute flux. Dispersion has
    zero diffusive/dispersive flux at both outer faces. Elevation is local:
    bottom=0, top=thickness, outlet hydraulic head=thickness+1 metre.
    """

    length_m: float
    width_m: float
    thickness_m: float
    ncol: int
    porosity: float
    conductivity_m_per_day: float
    darcy_flux_m_per_day: float
    longitudinal_dispersivity_m: float
    diffusion_m2_per_day: float
    initial_concentration_kg_m3: tuple
    inlet_concentration_kg_m3: float
    duration_day: float
    nsteps: int
    units: dict = field(default_factory=lambda: dict(UNITS))

    def __post_init__(self):
        self.validate()
        object.__setattr__(self, "initial_concentration_kg_m3",
                           tuple(float(v) for v in self.initial_concentration_kg_m3))

    def validate(self):
        if self.units != UNITS:
            raise TransportError(f"units must equal {UNITS}; no automatic conversion")
        if type(self.ncol) is not int or not 3 <= self.ncol <= 2000:
            raise TransportError("ncol: expected integer in [3,2000]")
        if type(self.nsteps) is not int or not 1 <= self.nsteps <= 2000:
            raise TransportError("nsteps: expected integer in [1,2000]")
        if self.ncol * self.nsteps > MAX_VALUES:
            raise TransportError("Saved concentration values exceed 2,000,000")
        for name in ("length_m", "width_m", "thickness_m"):
            _number(getattr(self, name), name, 1e-3, 1e6)
        _number(self.porosity, "porosity", 0.01, 1)
        _number(self.conductivity_m_per_day, "conductivity_m_per_day", 1e-6, 1e6)
        _number(self.darcy_flux_m_per_day, "darcy_flux_m_per_day", 0, 1000)
        _number(self.longitudinal_dispersivity_m, "longitudinal_dispersivity_m", 0, self.length_m)
        _number(self.diffusion_m2_per_day, "diffusion_m2_per_day", 0, 100)
        _number(self.duration_day, "duration_day", 1e-8, 1e6)
        _number(self.inlet_concentration_kg_m3, "inlet_concentration_kg_m3", 0, 1)
        if (not isinstance(self.initial_concentration_kg_m3, (tuple, list))
                or len(self.initial_concentration_kg_m3) != self.ncol):
            raise TransportError("initial_concentration_kg_m3 must contain ncol values")
        for value in self.initial_concentration_kg_m3:
            _number(value, "initial_concentration_kg_m3", 0, 1)
        if self.courant_number > 1 + 1e-12:
            raise TransportError("Advective Courant number must be <= 1; increase nsteps")
        if self.darcy_flux_m_per_day * self.length_m / self.conductivity_m_per_day > 1e6:
            raise TransportError("Hydraulic head drop exceeds the bounded 1e6 m range")

    @property
    def dx_m(self):
        return self.length_m / self.ncol

    @property
    def dt_day(self):
        return self.duration_day / self.nsteps

    @property
    def water_rate_m3_day(self):
        return self.darcy_flux_m_per_day * self.width_m * self.thickness_m

    @property
    def pore_velocity_m_day(self):
        return self.darcy_flux_m_per_day / self.porosity

    @property
    def dispersion_m2_day(self):
        return self.diffusion_m2_per_day + self.longitudinal_dispersivity_m * self.pore_velocity_m_day

    @property
    def courant_number(self):
        return self.pore_velocity_m_day * self.dt_day / self.dx_m

    def to_dict(self):
        self.validate()
        result = asdict(self)
        result["initial_concentration_kg_m3"] = list(self.initial_concentration_kg_m3)
        return {"schema": CASE_SCHEMA, **result}

    @classmethod
    def from_dict(cls, data):
        keys = set(cls.__dataclass_fields__) | {"schema"}
        if not isinstance(data, dict) or set(data) != keys or data["schema"] != CASE_SCHEMA:
            raise TransportError("Transport case requires exactly the versioned fields and explicit units")
        return cls(**{k: v for k, v in data.items() if k != "schema"})


def load_transport_case(path):
    return TransportCase.from_dict(_json(_read(path, 256 * 1024)))


def _dependencies():
    try:
        import flopy
    except ImportError as error:
        raise TransportError("Install the optional groundwater dependency; no solver is downloaded") from error
    return flopy


def _build(case, folder):
    """One deterministic exporter, also used to bind recorded case to native bytes."""
    case.validate()
    flopy = _dependencies()
    sim = flopy.mf6.MFSimulation(sim_name="transport", sim_ws=str(folder))
    sim.simulation_data.write_headers = False  # Omit FloPy wall-clock comments; deterministic native bytes.
    # FloPy's default eight decimal places can alter initial inventory. Preserve
    # double precision in arrays and lists, including moderate small values.
    sim.simulation_data.float_precision = 17
    sim.simulation_data.float_characters = 26
    sim.simulation_data.set_sci_note_upper_thres(0.0)
    flopy.mf6.ModflowTdis(sim, time_units="DAYS", perioddata=[(case.duration_day, case.nsteps, 1.0)])
    flow = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims", linear_acceleration="CG",
        outer_dvclose=1e-10, inner_dvclose=1e-11, rcloserecord=1e-10)
    sim.register_ims_package(ims, [flow.name])
    grid = dict(length_units="METERS", nlay=1, nrow=1, ncol=case.ncol,
                delr=case.dx_m, delc=case.width_m, top=case.thickness_m, botm=0.0)
    flopy.mf6.ModflowGwfdis(flow, **grid)
    head = case.thickness_m + 1.0
    start = head + (case.ncol - 1 - np.arange(case.ncol)) * case.dx_m * (
        case.darcy_flux_m_per_day / case.conductivity_m_per_day)
    flopy.mf6.ModflowGwfic(flow, strt=start.reshape(1, 1, -1))
    flopy.mf6.ModflowGwfnpf(flow, icelltype=0, k=case.conductivity_m_per_day)
    flopy.mf6.ModflowGwfwel(flow, auxiliary=["CONCENTRATION"], pname="INLET",
        stress_period_data=[((0, 0, 0), case.water_rate_m3_day, case.inlet_concentration_kg_m3)])
    flopy.mf6.ModflowGwfchd(flow, auxiliary=["CONCENTRATION"], pname="OUTLET",
        stress_period_data=[((0, 0, case.ncol - 1), head, 0.0)])
    flopy.mf6.ModflowGwfoc(flow, head_filerecord="flow.hds", budget_filerecord="flow.cbc",
        budgetcsv_filerecord="flow-budget.csv", saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
    solute = flopy.mf6.ModflowGwt(sim, modelname="solute", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="solute.ims", linear_acceleration="BICGSTAB",
        outer_dvclose=1e-10, inner_dvclose=1e-11, rcloserecord=1e-10,
        outer_maximum=100, inner_maximum=300)
    sim.register_ims_package(ims, [solute.name])
    flopy.mf6.ModflowGwtdis(solute, **grid)
    flopy.mf6.ModflowGwtic(solute, strt=np.asarray(case.initial_concentration_kg_m3).reshape(1, 1, -1))
    flopy.mf6.ModflowGwtmst(solute, porosity=case.porosity)
    flopy.mf6.ModflowGwtadv(solute, scheme="TVD")
    flopy.mf6.ModflowGwtdsp(solute, diffc=case.diffusion_m2_per_day,
                          alh=case.longitudinal_dispersivity_m, ath1=0.0, atv=0.0)
    flopy.mf6.ModflowGwtssm(solute, sources=[("INLET", "AUX", "CONCENTRATION"),
                                          ("OUTLET", "AUX", "CONCENTRATION")])
    flopy.mf6.ModflowGwtoc(solute, concentration_filerecord="solute.ucn",
        budget_filerecord="solute.cbc", budgetcsv_filerecord="solute-budget.csv",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")])
    flopy.mf6.ModflowGwfgwt(sim, exgmnamea="flow", exgmnameb="solute", filename="flow-solute.exg")
    sim.write_simulation(silent=True)


def _inventory(folder):
    result = {}
    total = 0
    for count, path in enumerate(Path(folder).iterdir(), 1):
        if count > 64:
            raise TransportError("Transport export exceeds the 64-file inventory limit")
        if path.name == "settings.json":
            continue
        if path.is_symlink() or not path.is_file():
            raise TransportError("Transport export must contain only regular flat files")
        data = _read(path, 2 * 1024 * 1024)
        total += len(data)
        if total > 8 * 1024 * 1024:
            raise TransportError("Transport export exceeds the 8 MiB aggregate input limit")
        result[path.name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return result


def export_transport(case: TransportCase, output_dir):
    """Write a fresh portable native deck; no execution or download occurs."""
    case.validate()
    requested = Path(output_dir).expanduser().absolute()
    if requested.is_symlink() or requested.exists():
        raise FileExistsError("Choose a fresh transport export directory")
    folder = requested.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    _build(case, folder)
    # settings.json is an opaque archived sidecar under the existing importer.
    # It has our schema, not a claimed GMS settings schema.
    record = {"schema": EXPORT_SCHEMA, "case": case.to_dict(),
              "flopy_version": _dependencies().__version__, "native_inputs": _inventory(folder),
              "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (folder / "settings.json").write_bytes(_json_bytes(record))
    return folder


def _bound_export(record):
    if (not isinstance(record, dict) or set(record) != {"schema", "case", "flopy_version",
            "native_inputs", "exporter_sha256"} or record["schema"] != EXPORT_SCHEMA):
        raise TransportError("Not a transport export from this bounded schema")
    case = TransportCase.from_dict(record["case"])
    if record["flopy_version"] != _dependencies().__version__:
        raise TransportError("Use the recorded FloPy version to verify/reconstruct the native deck")
    if record["exporter_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise TransportError("Use the recorded transport exporter revision to verify this result")
    with tempfile.TemporaryDirectory(prefix="basinlens-transport-bind-") as temporary:
        _build(case, temporary)
        if record["native_inputs"] != _inventory(temporary):
            raise TransportError("Recorded case does not reconstruct the captured native inputs")
    return case


def verify_transport_export(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise TransportError("Expected a regular transport export directory")
    record = _json(_read(folder / "settings.json", 256 * 1024))
    case = _bound_export(record)
    if _inventory(folder) != record["native_inputs"]:
        raise TransportError("Transport export files differ from the recorded exact input inventory")
    return case


def run_transport(case: TransportCase, output_dir, *, exe_name="mf6", timeout_seconds=300):
    """Use the existing isolated native runner; it owns execution and its manifest."""
    # Temporary source is preserved completely in the run's native/source_sidecars.
    with tempfile.TemporaryDirectory(prefix="basinlens-transport-source-") as temporary:
        source = export_transport(case, Path(temporary) / "export")
        return run_native_simulation(source, output_dir, exe_name=exe_name,
                                     timeout_seconds=timeout_seconds, max_output_bytes=256 * 1024 * 1024)


def _budget(path, case, fields):
    data = _read(path, 2 * 1024 * 1024)
    try:
        reader = csv.DictReader(io.StringIO(data.decode("ascii")))
        if reader.fieldnames != fields:
            raise TransportError("Unexpected native budget columns; no guessed budget semantics")
        rows = []
        for row in reader:
            if len(rows) >= case.nsteps or set(row) != set(fields) or None in row.values():
                raise TransportError("Unexpected native budget row count/shape")
            rows.append([float(row[key]) for key in fields])
        result = np.asarray(rows, dtype=float)
    except (ValueError, UnicodeError) as error:
        raise TransportError(f"Invalid native budget CSV: {error}") from error
    if result.shape != (case.nsteps, len(fields)) or not np.isfinite(result).all():
        raise TransportError("Incomplete or nonfinite native budget")
    times = np.arange(1, case.nsteps + 1) * case.dt_day
    if not np.allclose(result[:, 0], times, atol=1e-10, rtol=1e-10):
        raise TransportError("Native budget times differ from the recorded case")
    if (result[:, 1:-1] < -1e-9).any():
        raise TransportError("Native budget in/out magnitude has an unexpected negative sign")
    return {key: result[:, i] for i, key in enumerate(fields)}


@dataclass
class TransportResult:
    case: TransportCase
    times_day: np.ndarray
    x_m: np.ndarray
    concentrations_kg_m3: np.ndarray
    mass_kg: np.ndarray
    summary: dict


def read_transport_results(workspace) -> TransportResult:
    """Read only a verified matching native run, with its captured case authoritative.

    No external case argument can relabel a result. Reconstructing the export
    binds every case field to actual hashed solver inputs. Content hashes detect
    alteration; they are not authentication against someone replacing a bundle.
    """
    root = Path(workspace)
    metadata = verify_native_run(root)
    if metadata["status"] != "completed" or metadata.get("simulation") != "mfsim.nam":
        raise TransportError("A completed root-level transport native run is required")
    record = _json(_read(root / "source_sidecars/settings.json", 256 * 1024))
    case = _bound_export(record)
    if (metadata["source_snapshot"]["inputs"] != record["native_inputs"]
            or set(metadata["source_snapshot"]["sidecars"]) != {"settings.json"}):
        raise TransportError("Captured native file graph differs from the recorded transport export")
    expected_size = case.nsteps * (_HEADER.size + case.ncol * 8)
    raw = _read(root / "native/solute.ucn", expected_size)
    if len(raw) != expected_size:
        raise TransportError("Concentration binary size differs from the complete saved schedule")
    values = np.empty((case.nsteps, case.ncol), dtype=float)
    times = np.arange(1, case.nsteps + 1) * case.dt_day
    offset = 0
    for index, time in enumerate(times):
        step, period, pertim, totim, name, ncol, nrow, layer = _HEADER.unpack_from(raw, offset)
        if ((step, period, name.strip(), ncol, nrow, layer)
                != (index + 1, 1, b"CONCENTRATION", case.ncol, 1, 1)
                or not math.isclose(pertim, time, abs_tol=1e-10, rel_tol=1e-10)
                or not math.isclose(totim, time, abs_tol=1e-10, rel_tol=1e-10)):
            raise TransportError("Unsupported concentration header, dimensions or time schedule")
        offset += _HEADER.size
        values[index] = np.frombuffer(raw, dtype="<f8", count=case.ncol, offset=offset)
        offset += case.ncol * 8
    if not np.isfinite(values).all() or (values < -1e-8).any():
        raise TransportError("Nonfinite or materially negative concentration")
    flow_fields = ["time", "WEL(INLET)_IN", "CHD(OUTLET)_IN", "WEL(INLET)_OUT",
                   "CHD(OUTLET)_OUT", "TOTAL_IN", "TOTAL_OUT", "PERCENT_DIFFERENCE"]
    mass_fields = ["time", "STORAGE-AQUEOUS(MST)_IN", "WEL(SSM_INLET)_IN", "CHD(SSM_OUTLET)_IN",
        "STORAGE-AQUEOUS(MST)_OUT", "WEL(SSM_INLET)_OUT", "CHD(SSM_OUTLET)_OUT",
        "TOTAL_IN", "TOTAL_OUT", "PERCENT_DIFFERENCE"]
    flow = _budget(root / "native/flow-budget.csv", case, flow_fields)
    budget = _budget(root / "native/solute-budget.csv", case, mass_fields)
    q = case.water_rate_m3_day
    water_error = max(float(np.max(np.abs(flow[key] - expected))) for key, expected in (
        ("WEL(INLET)_IN", q), ("CHD(OUTLET)_OUT", q), ("CHD(OUTLET)_IN", 0), ("WEL(INLET)_OUT", 0)))
    pore_volume = case.porosity * case.dx_m * case.width_m * case.thickness_m
    mass = values.sum(axis=1) * pore_volume
    initial_mass = sum(case.initial_concentration_kg_m3) * pore_volume
    mass_in = q * case.inlet_concentration_kg_m3
    expected_rate = mass_in - q * values[:, -1]
    integrated = np.cumsum(expected_rate) * case.dt_day
    inventory_error = mass - initial_mass - integrated
    recorded_rate = budget["WEL(SSM_INLET)_IN"] + budget["CHD(SSM_OUTLET)_IN"] - (
        budget["WEL(SSM_INLET)_OUT"] + budget["CHD(SSM_OUTLET)_OUT"])
    rate_error = float(np.max(np.abs(recorded_rate - expected_rate)))
    storage_rate = budget["STORAGE-AQUEOUS(MST)_OUT"] - budget["STORAGE-AQUEOUS(MST)_IN"]
    storage_error = float(np.max(np.abs(storage_rate - np.diff(np.r_[initial_mass, mass]) / case.dt_day)))
    scale = max(initial_mass, float(np.max(np.abs(integrated))), mass_in * case.duration_day, 1e-30)
    max_error = float(np.max(np.abs(inventory_error)))
    gate = 1e-8 + 1e-7 * scale  # kg, project engineering gate, not a regulatory threshold.
    rate_scale = q * max(case.inlet_concentration_kg_m3, max(case.initial_concentration_kg_m3))
    summary = {"schema": "basinlens-transport-result-v1", "engine": "MODFLOW 6 GWF/GWT",
        "solver": metadata["solver"], "units": dict(UNITS), "ncol": case.ncol, "nsteps": case.nsteps,
        "darcy_flux_m_day": case.darcy_flux_m_per_day, "pore_velocity_m_day": case.pore_velocity_m_day,
        "nominal_interior_dispersion_m2_day": case.dispersion_m2_day, "courant_number": case.courant_number,
        "diffusion_number": case.dispersion_m2_day * case.dt_day / case.dx_m**2,
        "initial_mass_kg": initial_mass, "final_mass_kg": float(mass[-1]),
        "max_inventory_balance_error_kg": max_error, "inventory_balance_gate_kg": gate,
        "max_boundary_rate_error_kg_day": rate_error, "max_storage_rate_error_kg_day": storage_error,
        "max_water_boundary_error_m3_day": water_error,
        "conservation_passed": bool(max_error <= gate and rate_error <= 1e-8 + 1e-7 * rate_scale
                                  and storage_error * case.dt_day <= gate
                                  and water_error <= 1e-8 + 1e-7 * q),
        "concentration_min_kg_m3": float(values.min()), "concentration_max_kg_m3": float(values.max()),
        "concentration_bounds_passed": bool(values.min() >= -1e-8 and values.max() <=
            max(case.inlet_concentration_kg_m3, max(case.initial_concentration_kg_m3)) + 1e-8),
        "gms_parity_established": False, "co2_or_multiphase_physics": False,
        "validation_scope": "synthetic conservative-solute 1D cases; no field or GMS validation"}
    return TransportResult(case, times, (np.arange(case.ncol) + 0.5) * case.dx_m, values, mass, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "run"):
        item = sub.add_parser(command)
        item.add_argument("case", type=Path)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--exe", default="mf6")
            item.add_argument("--timeout", type=float, default=300)
    for command in ("verify-export", "results"):
        sub.add_parser(command).add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = {"export": str(export_transport(load_transport_case(args.case), args.output)), "engine_executed": False}
        elif args.command == "verify-export":
            result = {"verified_case": verify_transport_export(args.workspace).to_dict(), "engine_executed": False}
        elif args.command == "run":
            run = run_transport(load_transport_case(args.case), args.output,
                                exe_name=args.exe, timeout_seconds=args.timeout)
            result = read_transport_results(run.workspace).summary
        else:
            result = read_transport_results(args.workspace).summary
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Transport operation failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
