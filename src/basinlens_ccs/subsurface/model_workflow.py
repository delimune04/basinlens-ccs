"""Explicit stratigraphy/materials to a confined, single-phase MF6 water model.

This independent synthetic-workflow format is not GPR and establishes no GMS
parity. Native execution and artifact verification belong to native_run.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import tempfile

import numpy as np

from ..groundwater.gms_native import _parse_records, import_native_simulation
from ..groundwater.native_run import run_native_simulation, verify_native_run

SCHEMA = "basinlens-model-workflow-v1"
EXPORT_SCHEMA = "basinlens-model-workflow-export-v1"
UNITS = {"length": "m", "time": "day", "head": "m", "conductivity": "m/day",
         "specific_storage": "1/m", "porosity": "1", "water_rate": "m3/day",
         "recharge": "m/day", "conductance": "m2/day"}
MAX_CELLS = 20_000
MAX_VALUES = 2_000_000
CASE_BYTES = 8 * 1024 * 1024
INPUT_BYTES = 32 * 1024 * 1024
KINDS = {"CHD": ("head_m",), "RCH": ("rate_m_day",), "WEL": ("rate_m3_day",),
         "GHB": ("head_m", "conductance_m2_day"),
         "DRN": ("elevation_m", "conductance_m2_day"),
         "RIV": ("stage_m", "conductance_m2_day", "bottom_m")}
_HEADER = struct.Struct("<iidd16siii")


class WorkflowError(ValueError):
    """Unsupported, inconsistent, oversized or altered workflow evidence."""


def _keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise WorkflowError(f"{name}: requires exactly {sorted(keys)}")


def _number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowError(f"{name}: finite number required")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise WorkflowError(f"{name}: finite number required") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise WorkflowError(f"{name}: must be in [{lo}, {hi}]")
    return value


def _integer(value, name, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise WorkflowError(f"{name}: integer in [{lo}, {hi}] required")
    return value


def _text(value, name, *, identifier=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > 500
            or any(ord(c) < 32 for c in value)):
        raise WorkflowError(f"{name}: bounded nonempty text required")
    if identifier and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", value) is None:
        raise WorkflowError(f"{name}: identifier must match [A-Za-z][A-Za-z0-9_-]{{0,39}}")
    return value


def _bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise WorkflowError("Duplicate JSON key")
            result[key] = value
        return result
    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise WorkflowError("Nonfinite JSON number")
        return value
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_float=number, parse_constant=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise WorkflowError(f"Invalid workflow JSON: {error}") from error


def _read(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise WorkflowError(f"Regular bounded file required: {path.name}")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise WorkflowError("File grew beyond the read limit")
    return raw


def _cell(raw, shape):
    if not isinstance(raw, list) or len(raw) != 3:
        raise WorkflowError("cell: explicit zero-based [layer,row,column] required")
    return tuple(_integer(v, "cell index", 0, extent - 1) for v, extent in zip(raw, shape))


@dataclass(frozen=True)
class WorkflowCase:
    """Immutable validated canonical JSON; to_dict returns an independent copy."""

    _json: str

    @classmethod
    def from_dict(cls, value):
        try:
            _validate(value)
            raw = _bytes(value)
        except (TypeError, KeyError, OverflowError, RecursionError) as error:
            raise WorkflowError(f"Invalid workflow structure: {error}") from error
        if len(raw) > CASE_BYTES:
            raise WorkflowError("Workflow case exceeds 8 MiB")
        return cls(raw.decode("utf-8"))

    def to_dict(self):
        value = _decode(self._json.encode("utf-8"))
        _validate(value)
        return value

    @property
    def shape(self):
        grid = self.to_dict()["grid"]
        return len(grid["layer_surfaces_m"]) - 1, grid["nrow"], grid["ncol"]


def _validate(data):
    _keys(data, {"schema", "project", "grid", "strata", "materials", "assignments",
                 "initial_head_m", "periods", "boundaries"}, "workflow")
    if data["schema"] != SCHEMA:
        raise WorkflowError("Unsupported workflow schema")
    project = data["project"]
    _keys(project, {"id", "name", "domain", "flow_role", "units", "crs", "vertical_datum", "provenance"}, "project")
    _text(project["id"], "project.id", identifier=True)
    _text(project["name"], "project.name")
    if project["domain"] not in ("groundwater", "ccs", "oil_exploration"):
        raise WorkflowError("Unsupported project domain")
    if project["flow_role"] != "background_water":
        raise WorkflowError("Only explicit background_water physics is implemented")
    if project["units"] != UNITS:
        raise WorkflowError("Exact workflow SI/day units required; no automatic conversion")
    for field in ("crs", "vertical_datum"):
        _text(project[field], field)  # The literal 'unknown' remains unknown, never guessed.
    if not isinstance(project["provenance"], list) or not 1 <= len(project["provenance"]) <= 32:
        raise WorkflowError("One to 32 explicit provenance statements required")
    for statement in project["provenance"]:
        _text(statement, "provenance")
    grid = data["grid"]
    _keys(grid, {"nrow", "ncol", "dx_m", "dy_m", "x_origin_m", "y_origin_m", "rotation_degrees", "row_axis", "layer_surfaces_m"}, "grid")
    if grid["row_axis"] != "south_to_north":
        raise WorkflowError("grid.row_axis must explicitly equal south_to_north")
    nr = _integer(grid["nrow"], "nrow", 1, 200)
    nc = _integer(grid["ncol"], "ncol", 1, 1000)
    for name in ("dx_m", "dy_m"):
        _number(grid[name], name, 1e-3, 1e5)
    for name in ("x_origin_m", "y_origin_m"):
        _number(grid[name], name, -1e9, 1e9)
    if _number(grid["rotation_degrees"], "rotation_degrees", 0, 0) != 0:
        raise WorkflowError("Only an unrotated structured grid is supported")
    surfaces = grid["layer_surfaces_m"]
    if not isinstance(surfaces, list) or not 2 <= len(surfaces) <= 21:
        raise WorkflowError("Two to 21 explicit flat layer surfaces required")
    for value in surfaces:
        _number(value, "layer_surfaces_m", -1e5, 1e5)
    if any(a - b < 1e-3 for a, b in zip(surfaces, surfaces[1:])):
        raise WorkflowError("Flat layer surfaces must strictly descend with >=1e-3 m thickness")
    shape = len(surfaces) - 1, nr, nc
    count = math.prod(shape)
    if count > MAX_CELLS:
        raise WorkflowError("Grid exceeds 20,000 cells")
    strata = data["strata"]
    if not isinstance(strata, list) or not 1 <= len(strata) <= shape[0]:
        raise WorkflowError("Named strata must explicitly cover every layer")
    stratum_layers, layer_owner = {}, {}
    for item in strata:
        _keys(item, {"id", "name", "layer_indices"}, "stratum")
        sid = _text(item["id"], "stratum.id", identifier=True)
        _text(item["name"], "stratum.name")
        layers = item["layer_indices"]
        if sid in stratum_layers or not isinstance(layers, list) or not layers:
            raise WorkflowError("Unique strata and nonempty layer_indices required")
        stratum_layers[sid] = set()
        for layer in layers:
            layer = _integer(layer, "layer_indices", 0, shape[0] - 1)
            if layer in layer_owner:
                raise WorkflowError("Stratigraphic layer overlap")
            layer_owner[layer] = sid
            stratum_layers[sid].add(layer)
    if set(layer_owner) != set(range(shape[0])):
        raise WorkflowError("Strata leave uncovered layers")
    materials = data["materials"]
    if not isinstance(materials, list) or not 1 <= len(materials) <= 256:
        raise WorkflowError("One to 256 explicit rock materials required")
    mids = set()
    for item in materials:
        _keys(item, {"id", "name", "kx_m_day", "ky_m_day", "kz_m_day", "ss_per_m", "porosity"}, "material")
        mid = _text(item["id"], "material.id", identifier=True)
        _text(item["name"], "material.name")
        if mid in mids:
            raise WorkflowError("Duplicate material id")
        mids.add(mid)
        for name in ("kx_m_day", "ky_m_day", "kz_m_day"):
            _number(item[name], name, 1e-6, 1e6)
        _number(item["ss_per_m"], "ss_per_m", 1e-12, 0.1)
        _number(item["porosity"], "porosity", 0.001, 1)
    assignments = data["assignments"]
    if not isinstance(assignments, list) or not 1 <= len(assignments) <= count:
        raise WorkflowError("Explicit complete per-cell material assignments required")
    covered, used_materials = set(), set()
    for item in assignments:
        _keys(item, {"material_id", "stratum_id", "cells"}, "assignment")
        mid, sid = item["material_id"], item["stratum_id"]
        if mid not in mids or sid not in stratum_layers:
            raise WorkflowError("Assignment references an unknown material or stratum")
        cells = item["cells"]
        if not isinstance(cells, list) or not cells or len(cells) > count:
            raise WorkflowError("Assignment needs bounded explicit cells")
        used_materials.add(mid)
        for raw in cells:
            cell = _cell(raw, shape)
            if cell in covered or cell[0] not in stratum_layers[sid]:
                raise WorkflowError("Assignment overlaps or disagrees with named stratigraphy")
            covered.add(cell)
    if len(covered) != count or used_materials != mids:
        raise WorkflowError("Assignments must cover every cell and use every declared material")
    initial = data["initial_head_m"]
    if not isinstance(initial, list) or len(initial) != count:
        raise WorkflowError("initial_head_m: one value per C-order [layer,row,column] cell required")
    for index, value in enumerate(initial):
        _number(value, "initial_head_m", surfaces[index // (nr * nc)], 1e6)
    periods = data["periods"]
    if not isinstance(periods, list) or not 1 <= len(periods) <= 100:
        raise WorkflowError("One to 100 explicit stress periods required")
    total_steps = 0
    for period in periods:
        _keys(period, {"duration_day", "nsteps", "steady"}, "period")
        _number(period["duration_day"], "duration_day", 1e-8, 1e6)
        total_steps += _integer(period["nsteps"], "nsteps", 1, 2000)
        if type(period["steady"]) is not bool:
            raise WorkflowError("period.steady: explicit boolean required")
    if total_steps > 2000 or total_steps * count > MAX_VALUES:
        raise WorkflowError("Saved schedule exceeds 2,000 steps or 2,000,000 head values")
    boundaries = data["boundaries"]
    if not isinstance(boundaries, list) or len(boundaries) > min(100_000, count * len(periods) * 3):
        raise WorkflowError("Bounded explicit boundary table required")
    supports, anchors = {}, set()
    for item in boundaries:
        _keys(item, {"kind", "period", "cell", "values", "label"}, "boundary")
        kind = item["kind"]
        if kind not in KINDS:
            raise WorkflowError("Unsupported boundary kind")
        period = _integer(item["period"], "boundary.period", 0, len(periods) - 1)
        cell = _cell(item["cell"], shape)
        _text(item["label"], "boundary.label", identifier=True)
        _keys(item["values"], KINDS[kind], f"{kind}.values")
        prior = supports.setdefault((period, cell), set())
        if kind in prior or (prior and (kind == "CHD" or "CHD" in prior)):
            raise WorkflowError("Duplicate boundary or CHD overlap on the same cell/period")
        if kind in {"GHB", "DRN", "RIV"} and prior & {"GHB", "DRN", "RIV"}:
            raise WorkflowError("Conflicting head-dependent boundary supports")
        prior.add(kind)
        for field, value in item["values"].items():
            lo, hi = (-1e5, 1e6)
            if field == "conductance_m2_day":
                lo, hi = 1e-10, 1e10
            elif field == "rate_m_day":
                lo, hi = 0, 100
            elif field == "rate_m3_day":
                lo, hi = -1e9, 1e9
            _number(value, field, lo, hi)
        if kind == "RCH" and cell[0] != 0:
            raise WorkflowError("Explicit list recharge supports only top-layer cells")
        if kind == "RIV" and item["values"]["stage_m"] <= item["values"]["bottom_m"]:
            raise WorkflowError("RIV stage must exceed river bottom")
        if kind in ("CHD", "GHB"):
            anchors.add(period)
    # Drains may close; a river below its bottom becomes a fixed flux, not a head reference.
    if any(p["steady"] and i not in anchors for i, p in enumerate(periods)):
        raise WorkflowError("Every steady period requires CHD or GHB support")


def load_workflow_case(path):
    return WorkflowCase.from_dict(_decode(_read(path, CASE_BYTES)))


def preview_grid(case):
    """Project row increases south to north; export reverses native MF6 row IDs."""
    data = case.to_dict()
    grid = data["grid"]
    shape = case.shape
    materials = {m["id"]: m for m in data["materials"]}
    assignments = {tuple(c): (a["stratum_id"], a["material_id"])
                   for a in data["assignments"] for c in a["cells"]}
    cells = []
    for k, r, c in np.ndindex(shape):
        sid, mid = assignments[k, r, c]
        cells.append({"layer": k, "row": r, "column": c,
            "x_m": grid["x_origin_m"] + (c + 0.5) * grid["dx_m"],
            "y_m": grid["y_origin_m"] + (r + 0.5) * grid["dy_m"],
            "top_m": grid["layer_surfaces_m"][k],
            "bottom_m": grid["layer_surfaces_m"][k + 1],
            "stratum_id": sid, "material_id": mid,
            **{name: value for name, value in materials[mid].items() if name not in ("id", "name")}})
    return {"schema": "basinlens-workflow-grid-preview-v1", "shape": list(shape),
            "units": dict(UNITS), "crs": data["project"]["crs"],
            "vertical_datum": data["project"]["vertical_datum"], "cells": cells,
            "geometry_scope": "flat layers, uniform horizontal spacing, all cells active; no rotation",
            "row_mapping": "project row r -> native MF6 row nrow-1-r; physical XY coordinates preserved"}


def _flopy():
    try:
        import flopy
    except ImportError as error:
        raise WorkflowError("Install optional groundwater dependencies; no solver is downloaded") from error
    return flopy


def _format(sim):
    sim.simulation_data.write_headers = False
    sim.simulation_data.float_precision = 17
    sim.simulation_data.float_characters = 26
    sim.simulation_data.set_sci_note_upper_thres(0.0)


def _build(case, folder):
    data = case.to_dict()
    grid = data["grid"]
    cells = preview_grid(case)["cells"]
    shape = case.shape
    flopy = _flopy()
    sim = flopy.mf6.MFSimulation(sim_name="workflow", sim_ws=str(folder))
    _format(sim)
    flopy.mf6.ModflowTdis(sim, time_units="DAYS", nper=len(data["periods"]), perioddata=[
        (p["duration_day"], p["nsteps"], 1.0) for p in data["periods"]])
    model = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims", linear_acceleration="CG",
        outer_maximum=100, inner_maximum=500, outer_dvclose=1e-10, inner_dvclose=1e-11,
        rcloserecord=1e-9)
    sim.register_ims_package(ims, [model.name])
    flopy.mf6.ModflowGwfdis(model, length_units="METERS", nlay=shape[0], nrow=shape[1], ncol=shape[2],
        delr=grid["dx_m"], delc=grid["dy_m"], top=grid["layer_surfaces_m"][0],
        botm=np.broadcast_to(np.asarray(grid["layer_surfaces_m"][1:])[:, None, None], shape).copy(),
        xorigin=grid["x_origin_m"], yorigin=grid["y_origin_m"], angrot=0.0, idomain=1)
    def field(name):
        return np.asarray([c[name] for c in cells], dtype=float).reshape(shape)[:, ::-1, :].copy()
    flopy.mf6.ModflowGwfic(model, strt=np.asarray(data["initial_head_m"]).reshape(shape)[:, ::-1, :].copy())
    flopy.mf6.ModflowGwfnpf(model, icelltype=0, k=field("kx_m_day"), k22=field("ky_m_day"), k33=field("kz_m_day"))
    flopy.mf6.ModflowGwfsto(model, iconvert=0, ss=field("ss_per_m"), sy=0.0,
        steady_state={i: True for i, p in enumerate(data["periods"]) if p["steady"]},
        transient={i: True for i, p in enumerate(data["periods"]) if not p["steady"]})
    for kind, names in KINDS.items():
        rows = [b for b in data["boundaries"] if b["kind"] == kind]
        if not rows:
            continue
        # Explicit zero-length records prevent the native last-period carry-forward rule.
        spd = {i: [tuple([(b["cell"][0], shape[1] - 1 - b["cell"][1], b["cell"][2])] + [b["values"][n] for n in names] + [b["label"]])
                   for b in rows if b["period"] == i] for i in range(len(data["periods"]))}
        cls = getattr(flopy.mf6, "ModflowGwf" + kind.lower())
        cls(model, pname=kind, filename="flow." + kind.lower(), boundnames=True,
            stress_period_data=spd, save_flows=True)
    flopy.mf6.ModflowGwfoc(model, head_filerecord="flow.hds", budget_filerecord="flow.cbc",
        budgetcsv_filerecord="flow-budget.csv", saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
    sim.write_simulation(silent=True)


def _inventory(folder):
    result, total = {}, 0
    for index, path in enumerate(sorted(Path(folder).iterdir()), 1):
        if index > 64:
            raise WorkflowError("Export exceeds 64 files")
        if path.name == "settings.json":
            continue
        raw = _read(path, INPUT_BYTES)
        total += len(raw)
        if total > INPUT_BYTES:
            raise WorkflowError("Export exceeds 32 MiB aggregate native input limit")
        result[path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def _token(token):
    # These decks have fixed lower-case native filenames. Paths are case sensitive.
    if "." in token and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z0-9_-]+", token):
        return "FILE:" + token
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError:
        return "TEXT:" + token.upper()
    if not math.isfinite(value):
        raise WorkflowError("Nonfinite native numeric token")
    return "NUMBER:" + format(value, ".17g")


def _signature(folder, inventory):
    records = {name: [[_token(t) for t in words] for _, words in _parse_records(Path(folder) / name)]
               for name in sorted(inventory)}
    return hashlib.sha256(_bytes(records)).hexdigest()


def _native_graph(folder, inventory):
    report = import_native_simulation(folder, allowed_root=folder, database_row_limit=0)
    if report.get("issues") or report.get("native_inputs_resolved") is not True:
        raise WorkflowError("Generated native file graph is unresolved")
    if {f["path"] for f in report["files"]} != set(inventory):
        raise WorkflowError("Native graph and captured input inventory differ")
    return report


def _record(case, folder):
    inventory = _inventory(folder)
    _native_graph(folder, inventory)
    return {"schema": EXPORT_SCHEMA, "case": case.to_dict(), "flopy_version": _flopy().__version__,
        "compiler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "native_inputs": inventory, "native_token_semantics_sha256": _signature(folder, inventory),
        "semantics_scope": "complete ordered token rows of this compiler subset; comments/keyword case/numeric text only normalized"}


def _fresh(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or path.exists():
        raise FileExistsError("Choose a fresh workflow directory")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def export_workflow(case, output_dir):
    case.to_dict()
    folder = _fresh(output_dir)
    _build(case, folder)
    (folder / "settings.json").write_bytes(_bytes(_record(case, folder)))
    return folder


def _bound_record(record):
    expected = {"schema", "case", "flopy_version", "compiler_sha256", "native_inputs",
                "native_token_semantics_sha256", "semantics_scope"}
    _keys(record, expected, "workflow export")
    if record["schema"] != EXPORT_SCHEMA:
        raise WorkflowError("Not a workflow export")
    case = WorkflowCase.from_dict(record["case"])
    if record["flopy_version"] != _flopy().__version__:
        raise WorkflowError("Use the recorded FloPy version to reconstruct this export")
    if record["compiler_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise WorkflowError("Use the recorded workflow compiler source to verify this export")
    with tempfile.TemporaryDirectory(prefix="basinlens-workflow-bind-") as temporary:
        _build(case, temporary)
        if _signature(temporary, _inventory(temporary)) != record["native_token_semantics_sha256"]:
            raise WorkflowError("Recorded case does not reconstruct native solver semantics")
    return case


def verify_workflow_export(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise WorkflowError("Regular workflow export directory required")
    record = _decode(_read(folder / "settings.json", CASE_BYTES + 1024 * 1024))
    case = _bound_record(record)
    inventory = _inventory(folder)
    if inventory != record["native_inputs"] or _signature(folder, inventory) != record["native_token_semantics_sha256"]:
        raise WorkflowError("Workflow native files differ from the exact captured inventory/semantics")
    _native_graph(folder, inventory)
    return case


def run_workflow(case, output_dir, *, exe_name="mf6", timeout_seconds=300):
    with tempfile.TemporaryDirectory(prefix="basinlens-workflow-source-") as temporary:
        source = export_workflow(case, Path(temporary) / "export")
        return run_native_simulation(source, output_dir, exe_name=exe_name,
            timeout_seconds=timeout_seconds, max_output_bytes=256 * 1024 * 1024)


def _schedule(case):
    result, total = [], 0.0
    for period, p in enumerate(case.to_dict()["periods"]):
        for step in range(p["nsteps"]):
            pertim = p["duration_day"] * (step + 1) / p["nsteps"]
            result.append((step + 1, period + 1, pertim, total + pertim))
        total += p["duration_day"]
    return result


def _heads(path, case):
    shape, schedule = case.shape, _schedule(case)
    expected = len(schedule) * shape[0] * (_HEADER.size + shape[1] * shape[2] * 8)
    raw = _read(path, expected)
    if len(raw) != expected:
        raise WorkflowError("Head binary does not cover the complete case schedule")
    values = np.empty((len(schedule), *shape), dtype=float)
    offset = 0
    for index, (step, period, pt, tt) in enumerate(schedule):
        for layer in range(shape[0]):
            ks, kp, pertim, totim, text, nc, nr, kl = _HEADER.unpack_from(raw, offset)
            if ((ks, kp, text.strip(), nc, nr, kl) != (step, period, b"HEAD", shape[2], shape[1], layer + 1)
                    or not math.isclose(pertim, pt, rel_tol=1e-10, abs_tol=1e-10)
                    or not math.isclose(totim, tt, rel_tol=1e-10, abs_tol=1e-10)):
                raise WorkflowError("Unsupported/inconsistent head binary header")
            offset += _HEADER.size
            values[index, layer] = np.frombuffer(raw, dtype="<f8", count=nr * nc, offset=offset).reshape(nr, nc)
            offset += nr * nc * 8
    if not np.isfinite(values).all() or (np.abs(values) > 1e20).any():
        raise WorkflowError("Nonfinite/dry/inactive head values are outside this all-active confined contract")
    return values[:, :, ::-1, :].copy()  # Native row reversal back to project row IDs.


def _budget(path, case):
    schedule = _schedule(case)
    try:
        reader = csv.DictReader(io.StringIO(_read(path, 2 * 1024 * 1024).decode("ascii")))
        fields = reader.fieldnames
        kinds = [kind for kind in KINDS if any(b["kind"] == kind for b in case.to_dict()["boundaries"])]
        terms = ["STO-SS(STORAGE)"] + [f"{kind}({kind})" for kind in kinds]
        expected = ["time"] + [name + "_IN" for name in terms] + [name + "_OUT" for name in terms] + ["TOTAL_IN", "TOTAL_OUT", "PERCENT_DIFFERENCE"]
        if (not fields or len(fields) != len(expected) or len(set(fields)) != len(fields)
                or set(fields) != set(expected) or fields[0] != "time"
                or fields[-3:] != ["TOTAL_IN", "TOTAL_OUT", "PERCENT_DIFFERENCE"]):
            raise WorkflowError("Unexpected budget columns; no guessed package semantics")
        rows = []
        for row in reader:
            if len(rows) >= len(schedule) or set(row) != set(fields) or None in row.values():
                raise WorkflowError("Unexpected native budget shape")
            rows.append([float(row[f]) for f in fields])
        values = np.asarray(rows)
    except (ValueError, UnicodeError) as error:
        raise WorkflowError(f"Invalid native budget: {error}") from error
    if values.shape != (len(schedule), len(fields)) or not np.isfinite(values).all():
        raise WorkflowError("Incomplete/nonfinite native budget")
    if not np.allclose(values[:, 0], [s[3] for s in schedule], rtol=1e-10, atol=1e-10):
        raise WorkflowError("Budget times disagree with the captured case")
    if (values[:, 1:-1] < -1e-9).any():
        raise WorkflowError("Negative budget in/out magnitude")
    return {f: values[:, i] for i, f in enumerate(fields)}


@dataclass
class WorkflowResult:
    case: WorkflowCase
    times_day: np.ndarray
    heads_m: np.ndarray
    budget: dict
    summary: dict


def _read_native_outputs(folder, case):
    return _heads(Path(folder) / "flow.hds", case), _budget(Path(folder) / "flow-budget.csv", case)


def _boundary_checks(case, heads, budget):
    data = case.to_dict()
    errors, scales, chd_error = [], [], 0.0
    kinds = {b["kind"] for b in data["boundaries"]} - {"CHD"}
    for index, schedule in enumerate(_schedule(case)):
        period = schedule[1] - 1
        rates = {kind: [] for kind in kinds}
        for boundary in data["boundaries"]:
            if boundary["period"] != period:
                continue
            kind, v = boundary["kind"], boundary["values"]
            h = float(heads[(index, *boundary["cell"])])
            if kind == "CHD":
                chd_error = max(chd_error, abs(h - v["head_m"]))
                continue
            if kind == "WEL":
                q = v["rate_m3_day"]
            elif kind == "RCH":
                q = v["rate_m_day"] * data["grid"]["dx_m"] * data["grid"]["dy_m"]
            elif kind == "GHB":
                q = v["conductance_m2_day"] * (v["head_m"] - h)
            elif kind == "DRN":
                q = -v["conductance_m2_day"] * max(h - v["elevation_m"], 0.0)
            else:
                q = v["conductance_m2_day"] * (v["stage_m"] - max(h, v["bottom_m"]))
            rates[kind].append(q)
        for kind, values in rates.items():
            for direction, expected in (("IN", sum(max(q, 0.0) for q in values)),
                                        ("OUT", sum(max(-q, 0.0) for q in values))):
                actual = float(budget[f"{kind}({kind})_{direction}"][index])
                errors.append(abs(actual - expected))
                scales.append(max(abs(actual), abs(expected)))
    passed = all(e <= 1e-8 + 1e-7 * scale for e, scale in zip(errors, scales)) and chd_error <= 1e-8
    return {"boundary_rates_passed": bool(passed),
            "maximum_boundary_rate_error_m3_day": max(errors, default=0.0),
            "maximum_prescribed_head_error_m": chd_error}


def read_workflow_results(workspace):
    root = Path(workspace)
    metadata = verify_native_run(root)
    if metadata["status"] != "completed" or metadata.get("simulation") != "mfsim.nam":
        raise WorkflowError("Completed root-level workflow run required")
    record = _decode(_read(root / "source_sidecars/settings.json", CASE_BYTES + 1024 * 1024))
    case = _bound_record(record)
    if (metadata["source_snapshot"]["inputs"] != record["native_inputs"]
            or set(metadata["source_snapshot"]["sidecars"]) != {"settings.json"}
            or _signature(root / "native", record["native_inputs"]) != record["native_token_semantics_sha256"]):
        raise WorkflowError("Captured case and native simulation differ")
    heads, budget = _read_native_outputs(root / "native", case)
    residual = np.abs(budget["TOTAL_IN"] - budget["TOTAL_OUT"])
    scale = np.maximum(budget["TOTAL_IN"], budget["TOTAL_OUT"])
    gate = 1e-8 + 1e-7 * scale
    top = np.asarray(case.to_dict()["grid"]["layer_surfaces_m"][:-1])[:, None, None]
    saturated = bool(np.all(heads >= top - 1e-8))
    checks = _boundary_checks(case, heads, budget)
    summary = {"schema": "basinlens-model-workflow-result-v1", "engine": "MODFLOW 6 GWF",
        "solver": metadata["solver"], "units": dict(UNITS), "shape": list(case.shape),
        "saved_steps": len(heads), "head_min_m": float(heads.min()), "head_max_m": float(heads.max()),
        "maximum_water_balance_residual_m3_day": float(residual.max()),
        "water_balance_passed": bool(np.all(residual <= gate)), **checks,
        "confined_saturation_support_passed": saturated,
        "validation_scope": "synthetic confined single-phase water; case-specific analytic tests only",
        "gms_parity_established": False, "co2_or_multiphase_physics": False,
        "porosity_role": "preserved geological metadata; not a flow/storage coefficient in confined GWF"}
    return WorkflowResult(case, np.asarray([s[3] for s in _schedule(case)]), heads, budget, summary)


def verify_workflow_roundtrip(source, output_dir, *, exe_name=None, timeout_seconds=300):
    """Fresh FloPy native load/write, complete token equality and optional reruns.

    This conservatively verifies this compiler's native subset. Original case
    metadata is preserved by our sidecar, not inferred from solver inputs.
    """
    source = Path(source).resolve()
    source_settings = _read(source / "settings.json", CASE_BYTES + 1024 * 1024)
    case = verify_workflow_export(source)
    if _read(source / "settings.json", CASE_BYTES + 1024 * 1024) != source_settings:
        raise WorkflowError("Original workflow metadata changed during initial verification")
    original_record = _decode(source_settings)
    folder = _fresh(output_dir)
    receipt = {"schema": "basinlens-model-workflow-roundtrip-v1", "status": "prepared",
               "native_runs_performed": False, "gms_parity_established": False}
    (folder / "roundtrip.json").write_bytes(_bytes(receipt))
    try:
        rewritten = folder / "rewritten"
        rewritten.mkdir()
        before = _inventory(source)
        if before != original_record["native_inputs"] or original_record["case"] != case.to_dict():
            raise WorkflowError("Original source changed after verification")
        def unchanged():
            if (_inventory(source) != before or
                    _read(source / "settings.json", CASE_BYTES + 1024 * 1024) != source_settings):
                raise WorkflowError("Original native inputs or workflow metadata changed during roundtrip")
        sim = _flopy().mf6.MFSimulation.load(sim_ws=str(source), verbosity_level=0)
        sim.set_sim_path(str(rewritten))
        _format(sim)
        sim.write_simulation(silent=True)
        record = _record(case, rewritten)
        equal = record["native_token_semantics_sha256"] == original_record["native_token_semantics_sha256"]
        if not equal:
            raise WorkflowError("Native rewrite changed complete ordered token semantics; outputs retained")
        (rewritten / "settings.json").write_bytes(_bytes(record))
        verify_workflow_export(rewritten)
        unchanged()
        receipt = {"schema": "basinlens-model-workflow-roundtrip-v1", "status": "completed", "case_metadata_preserved": True,
            "source_native_inputs": before, "source_settings_sha256": hashlib.sha256(source_settings).hexdigest(),
            "rewritten_native_inputs": record["native_inputs"],
            "native_token_semantics_equal": equal, "native_token_semantics_sha256": record["native_token_semantics_sha256"],
            "flopy_version": _flopy().__version__, "compiler_sha256": record["compiler_sha256"],
            "native_runs_performed": False, "numerical_roundtrip_passed": None,
            "gms_project_roundtrip": False, "gms_parity_established": False}
        if exe_name is not None:
            runs = []
            receipt.update(status="running_native", native_runs_requested=0, native_runs_completed=0)
            for native_source, name in ((source, "original-run"), (rewritten, "rewritten-run")):
                receipt["native_runs_requested"] += 1
                receipt["native_runs_performed"] = None  # Until a completed runner result is returned.
                (folder / "roundtrip.json").write_bytes(_bytes(receipt))
                runs.append(run_native_simulation(native_source, folder / name, exe_name=exe_name,
                    timeout_seconds=timeout_seconds, max_output_bytes=256 * 1024 * 1024))
                receipt["native_runs_completed"] += 1
                receipt["native_runs_performed"] = True
                (folder / "roundtrip.json").write_bytes(_bytes(receipt))
            results = [read_workflow_results(r.workspace) for r in runs]
            head_error = float(np.max(np.abs(results[0].heads_m - results[1].heads_m)))
            budget_error = max(float(np.max(np.abs(results[0].budget[k] - results[1].budget[k]))) for k in results[0].budget)
            receipt.update(status="completed", native_runs_performed=True, maximum_head_difference_m=head_error,
                maximum_budget_column_difference=budget_error,
                numerical_roundtrip_passed=bool(head_error <= 1e-9 and budget_error <= 1e-9
                    and all(r.summary[k] for r in results for k in ("water_balance_passed",
                        "boundary_rates_passed", "confined_saturation_support_passed"))),
                both_runs_water_balance_passed=all(r.summary["water_balance_passed"] for r in results),
                both_runs_boundary_rates_passed=all(r.summary["boundary_rates_passed"] for r in results),
                both_runs_confined_saturation_support_passed=all(r.summary["confined_saturation_support_passed"] for r in results),
                solver=results[0].summary["solver"])
        unchanged()
        (folder / "roundtrip.json").write_bytes(_bytes(receipt))
        return receipt
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
        (folder / "roundtrip.json").write_bytes(_bytes(receipt))
        raise



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "export", "run"):
        item = sub.add_parser(command)
        item.add_argument("case", type=Path)
        if command != "preview":
            item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--exe", default="mf6")
    item = sub.add_parser("roundtrip")
    item.add_argument("source", type=Path)
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--exe", default=None, help="Explicit solver enables both real numerical reruns")
    for command in ("verify-export", "results"):
        sub.add_parser(command).add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            result = preview_grid(load_workflow_case(args.case))
        elif args.command == "export":
            result = {"export": str(export_workflow(load_workflow_case(args.case), args.output)), "engine_executed": False}
        elif args.command == "run":
            run = run_workflow(load_workflow_case(args.case), args.output, exe_name=args.exe)
            result = read_workflow_results(run.workspace).summary
        elif args.command == "roundtrip":
            result = verify_workflow_roundtrip(args.source, args.output, exe_name=args.exe)
        elif args.command == "verify-export":
            result = {"case": verify_workflow_export(args.workspace).to_dict(), "verified": True}
        else:
            result = read_workflow_results(args.workspace).summary
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Workflow operation failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if (args.command == "roundtrip" and args.exe is not None
            and result.get("numerical_roundtrip_passed") is not True):
        parser.exit(2, "Workflow numerical roundtrip failed its equality/physical support gates; receipt and outputs retained\n")


if __name__ == "__main__":
    main()
