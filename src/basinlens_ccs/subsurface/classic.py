"""Explicit confined-water compilation to MODFLOW-2005 LPF or MODFLOW-NWT UPW.

This is an independent authored compiler subset, not a general legacy importer,
GMS reconstruction proof, or unconfined/drying model. Inputs never run on open.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import tempfile

import numpy as np

from . import project_package as package
from .model_workflow import (WorkflowCase, KINDS, UNITS, load_workflow_case,
                             preview_grid, _boundary_checks, _signature)
from ..groundwater.native_run import _execute

ENGINES = {"mf2005": "MODFLOW-2005", "mfnwt": "MODFLOW-NWT"}
PINNED = {
    "mf2005": {"member": "mf2005dbl", "bytes": 7546544,
               "sha256": "08e49f5abae8dcb33370444b5e6f6c922887254301312bc6cd3192604a0c0e85"},
    "mfnwt": {"member": "mfnwtdbl", "bytes": 8259552,
              "sha256": "7c9a54732f0dc936daaf6a8cf6749c51cb38480049db650250e7464d64bef8f4"},
}
SCHEMA = "basinlens-classic-water-v1"
INPUT_LIMIT = 32 * 1024 * 1024
OUTPUT_LIMIT = 256 * 1024 * 1024
HEAD_HEADER = struct.Struct("<ii dd 16s iii")
CBC_HEADER = struct.Struct("<ii16siii")
CBC_TIME = struct.Struct("<iddd")
TERMS = {"CHD": "CONSTANT HEAD", "WEL": "WELLS", "RCH": "RECHARGE",
         "GHB": "HEAD DEP BOUNDS", "DRN": "DRAINS", "RIV": "RIVER LEAKAGE"}
INTERNAL = {"FLOW RIGHT FACE", "FLOW FRONT FACE", "FLOW LOWER FACE"}


class ClassicError(ValueError):
    pass


def _json(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _sources():
    return {name: _digest(package._read_file(Path(__file__).with_name(name), 2 * 1024 * 1024))
            for name in ("classic.py", "model_workflow.py")}


def _decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ClassicError("Duplicate JSON key")
            out[key] = value
        return out
    def constant(value):
        raise ClassicError("Nonfinite JSON number")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        package._json_tree(value)
        return value
    except (UnicodeError, RecursionError) as error:
        raise ClassicError("Invalid bounded JSON") from error


def _engine(value):
    if not isinstance(value,str) or value not in ENGINES:
        raise ClassicError("Engine must be mf2005 or mfnwt")
    return value


def _linear_solver(engine,value):
    engine=_engine(engine)
    value=("pcg" if engine=="mf2005" else "xmd") if value is None else value
    allowed={"pcg"} if engine=="mf2005" else {"gmres","xmd"}
    if not isinstance(value,str) or value not in allowed:
        raise ClassicError("Choose pcg for mf2005, or explicitly gmres/xmd for mfnwt")
    return value


def _fresh(path):
    path = package._fresh_output(path)
    path.mkdir(exist_ok=False)
    return path


def _flopy():
    try:
        import flopy
        return flopy
    except ImportError as error:
        raise ClassicError("Install the optional groundwater dependencies") from error


def _array_format(model):
    """Use explicit free arrays from the first write; avoid constant expansion drift."""
    flopy=_flopy()
    def set_array(value):
        if isinstance(value,flopy.utils.Util2d):
            value.how="internal"
            value.format.free=True
            if np.issubdtype(value.dtype,np.floating):
                # FloPy 3.11's width setter ignores widths >= its default.
                # Parsing a descriptor sets both fields through its public API,
                # while retaining the FREE control record and separating tokens.
                value.format.fortran=f"({value.shape[-1]}E32.17)"
        elif isinstance(value,flopy.utils.Util3d):
            for child in value.util_2ds:set_array(child)
        elif isinstance(value,flopy.utils.Transient2d):
            for child in value.transient_2ds.values():set_array(child)
    for item in model.packagelist:
        for value in vars(item).values():set_array(value)


def _build(case, engine, folder,linear_solver=None):
    _engine(engine)
    linear_solver=_linear_solver(engine,linear_solver)
    data, shape = case.to_dict(), case.shape
    if math.prod(shape)<2:
        raise ClassicError("Pinned PCG/NWT engines eliminate isolated single cells; this classic subset requires at least two connected cells")
    chd_supports=[{tuple(b["cell"]) for b in data["boundaries"] if b["kind"]=="CHD" and b["period"]==i}
                  for i in range(len(data["periods"]))]
    if any(cells!=chd_supports[0] for cells in chd_supports):
        raise ClassicError("This classic subset requires unchanged CHD cell support across periods; use MF6 for changing support")
    grid, cells = data["grid"], preview_grid(case)["cells"]
    flopy = _flopy()
    model = flopy.modflow.Modflow("flow", version=engine, model_ws=str(folder), exe_name=None)
    flopy.modflow.ModflowDis(model, nlay=shape[0], nrow=shape[1], ncol=shape[2],
        nper=len(data["periods"]), delr=grid["dx_m"], delc=grid["dy_m"],
        top=grid["layer_surfaces_m"][0], botm=grid["layer_surfaces_m"][1:],
        perlen=[p["duration_day"] for p in data["periods"]],
        nstp=[p["nsteps"] for p in data["periods"]],
        steady=[p["steady"] for p in data["periods"]], itmuni=4, lenuni=2)
    flopy.modflow.ModflowBas(model, ibound=1,
        strt=np.asarray(data["initial_head_m"]).reshape(shape)[:, ::-1, :].copy())
    native_surfaces=np.concatenate((model.dis.top.array[None,:,:],model.dis.botm.array),axis=0)
    if not np.isfinite(native_surfaces).all() or np.any(np.diff(native_surfaces,axis=0)>=0):
        raise ClassicError("Legacy parameter precision collapses layer thickness; use another supported geometry/engine")
    def field(name):
        return np.asarray([c[name] for c in cells]).reshape(shape)[:, ::-1, :].copy()
    cls = flopy.modflow.ModflowLpf if engine == "mf2005" else flopy.modflow.ModflowUpw
    cls(model, laytyp=0, layavg=0, chani=0, hk=field("kx_m_day"),
        hani=field("ky_m_day") / field("kx_m_day"), vka=field("kz_m_day"),
        ss=field("ss_per_m"), sy=0.0, ipakcb=53)
    if engine == "mf2005":
        flopy.modflow.ModflowPcg(model, hclose=1e-10, rclose=1e-9, mxiter=200, iter1=1000)
    else:
        options=({"linmeth":1,"maxitinner":1000} if linear_solver=="gmres" else
                 {"linmeth":2,"iacl":2,"north":2,"hclosexmd":1e-10,"mxiterxmd":1000})
        flopy.modflow.ModflowNwt(model, headtol=1e-10, fluxtol=1e-9,
            maxiterout=200, options="SPECIFIED", **options)
    for kind, fields in KINDS.items():
        rows = [b for b in data["boundaries"] if b["kind"] == kind]
        if not rows:
            continue
        if kind == "RCH":
            values = {i: np.zeros(shape[1:]) for i in range(len(data["periods"]))}
            for b in rows:
                values[b["period"]][shape[1]-1-b["cell"][1], b["cell"][2]] = b["values"]["rate_m_day"]
            flopy.modflow.ModflowRch(model, nrchop=3, rech=values, ipakcb=53)
            continue
        spd = {i: [] for i in range(len(data["periods"]))}
        for b in rows:
            k, row, col = b["cell"]
            values = [b["values"][key] for key in fields]
            if kind == "CHD":
                values *= 2  # Constant start/end head in this period, not a ramp.
            spd[b["period"]].append([k, shape[1]-1-row, col, *values])
        # Zero explicitly shuts a package off; -1 would carry it forward.
        spd = {i: values if values else 0 for i, values in spd.items()}
        boundary_class=getattr(flopy.modflow, "Modflow" + kind.title())
        base_dtype=boundary_class.get_default_dtype()
        dtype=np.dtype([(name,"<f8" if np.issubdtype(base_dtype[name],np.floating) else base_dtype[name]) for name in base_dtype.names])
        boundary_class(model, stress_period_data=spd,dtype=dtype,
            **({} if kind == "CHD" else {"ipakcb": 53}))
    flopy.modflow.ModflowOc(model, compact=True, stress_period_data={
        (i, j): ["save head", "save budget"] for i, p in enumerate(data["periods"]) for j in range(p["nsteps"])})
    _array_format(model)
    model.write_input()
    loaded=flopy.modflow.Modflow("precision-check",model_ws=str(folder),version=engine,exe_name=None)
    with (Path(folder)/"flow.dis").open() as stream:
        flopy.modflow.ModflowDis.load(stream,loaded,check=False)
    written=np.concatenate((loaded.dis.top.array[None,:,:],loaded.dis.botm.array),axis=0)
    if not np.isfinite(written).all() or np.any(np.diff(written,axis=0)>=0):
        raise ClassicError("Written legacy text precision collapses layer thickness")
    source_thickness=-np.diff(np.asarray(grid["layer_surfaces_m"]))[:,None,None]
    actual_thickness=-np.diff(written,axis=0)
    if np.any(np.abs(actual_thickness-source_thickness)>1e-6*source_thickness):
        raise ClassicError("Legacy parameter precision changes layer thickness beyond 1e-6 relative support")
    # Text PERLEN is authoritative for actual legacy output times, not an
    # unrecorded float32 FloPy intermediate or original higher-precision number.
    rows = (Path(folder)/"flow.dis").read_text().splitlines()[-len(data["periods"]):]
    compiled = [float(row.split()[0].replace("D", "E")) for row in rows]
    if any(not math.isfinite(v) or v<=0 for v in compiled):
        raise ClassicError("Written legacy period duration lost finite positive support")
    return compiled


def _restore_list_precision(model,source,case):
    """Read our complete native list records as float64, not FloPy's default f4.

    Values come from the actual native file, never from the sidecar's values.
    This deliberately accepts only our generated no-parameter list grammar.
    """
    from ..groundwater.gms_native import _parse_records
    count=int(np.prod(case.shape));nper=len(case.to_dict()["periods"])
    for kind in KINDS:
        if kind=="RCH" or model.get_package(kind) is None:continue
        path=Path(source)/("flow."+kind.lower())
        records=[words for _,words in _parse_records(path)]
        header=records.pop(0)
        if len(header)!=(1 if kind=="CHD" else 2):raise ClassicError("Unsupported legacy list header")
        maxact=int(header[0])
        if not 0<=maxact<=count:raise ClassicError("Legacy list bound exceeds cell count")
        if kind!="CHD" and int(header[1])!=53:raise ClassicError("Unexpected budget output unit")
        item=model.get_package(kind);base=item.get_default_dtype()
        dtype=np.dtype([(name,"<f8" if np.issubdtype(base[name],np.floating) else base[name]) for name in base.names])
        periods={};index=0
        for period in range(nper):
            if index>=len(records) or len(records[index])!=2:raise ClassicError("Missing legacy list period control")
            size,parameters=map(int,records[index]);index+=1
            if parameters!=0 or not 0<=size<=maxact:raise ClassicError("Legacy list parameters/reuse unsupported")
            values=np.recarray(size,dtype=dtype)
            for row in range(size):
                if index>=len(records) or len(records[index])!=len(dtype.names):raise ClassicError("Truncated legacy list")
                tokens=records[index];index+=1
                cell=tuple(int(v)-1 for v in tokens[:3])
                if any(not 0<=v<dim for v,dim in zip(cell,case.shape)):raise ClassicError("Legacy list cell outside grid")
                numbers=[float(v.replace("D","E")) for v in tokens[3:]]
                if not all(math.isfinite(v) for v in numbers):raise ClassicError("Nonfinite legacy list value")
                values[row]=tuple([*cell,*numbers])
            periods[period]=values if size else 0
        if index!=len(records):raise ClassicError("Extra legacy list records")
        item.dtype=dtype
        item.stress_period_data=_flopy().utils.MfList(item,data=periods,dtype=dtype)


def _inventory(folder, exclude=()):
    result, total = {}, 0
    for path in sorted(Path(folder).iterdir()):
        if path.name in exclude:
            continue
        raw = package._read_file(path, OUTPUT_LIMIT)
        total += len(raw)
        if total > OUTPUT_LIMIT or len(result) >= 128:
            raise ClassicError("Classic workspace exceeds its file/byte budget")
        result[path.name] = {"bytes": len(raw), "sha256": _digest(raw)}
    return result


def export_classic(case, output_dir, *, engine="mf2005",linear_solver=None):
    if not isinstance(case, WorkflowCase):
        raise ClassicError("A validated WorkflowCase is required")
    case.to_dict()
    linear_solver=_linear_solver(engine,linear_solver)
    folder = _fresh(output_dir)
    durations = _build(case, engine, folder,linear_solver)
    inputs = _inventory(folder)
    if sum(x["bytes"] for x in inputs.values()) > INPUT_LIMIT:
        raise ClassicError("Classic native input exceeds 32 MiB")
    record = {"schema": SCHEMA, "case": case.to_dict(), "engine": engine,"linear_solver":linear_solver,
        "flopy_version": _flopy().__version__, "compiler_sources": _sources(),
        "inputs": inputs, "compiled_period_durations_day": durations,
        "compiler_token_semantics_sha256":_signature(folder,inputs),
        "scope": "All-active flat uniform-grid confined single-phase water; no drying/rewetting or original GMS comparison",
        "precision": "Pinned double-precision engine; FloPy legacy property/stress arrays and native text have finite parameter precision; result gates use explicit relative tolerances"}
    (folder/"settings.json").write_bytes(_json(record))
    return folder


def verify_classic_export(folder):
    folder = package._path_no_links(folder, directory=True)
    record = _decode(package._read_file(folder/"settings.json", 10 * 1024 * 1024))
    required = {"schema", "case", "engine", "linear_solver", "flopy_version", "compiler_sources", "inputs", "compiled_period_durations_day", "scope", "precision","compiler_token_semantics_sha256"}
    if not isinstance(record,dict) or set(record) != required or record["schema"] != SCHEMA:
        raise ClassicError("Not a supported classic compiler record")
    if record["linear_solver"]!=_linear_solver(record["engine"],record["linear_solver"]):
        raise ClassicError("Captured linear solver must be explicit")
    case = WorkflowCase.from_dict(record["case"])
    if record["compiler_sources"] != _sources() or record["flopy_version"] != _flopy().__version__:
        raise ClassicError("Use the recorded compiler source and FloPy version")
    if _inventory(folder, ("settings.json",)) != record["inputs"]:
        raise ClassicError("Classic inputs changed or include unregistered files")
    with tempfile.TemporaryDirectory(prefix="basinlens-classic-rebuild-") as tmp:
        durations = _build(case, record["engine"], tmp,record["linear_solver"])
        signature=_signature(tmp,_inventory(tmp))
        if (signature!=record["compiler_token_semantics_sha256"]
                or _signature(folder,record["inputs"])!=signature
                or durations != record["compiled_period_durations_day"]):
            raise ClassicError("Captured case does not reconstruct the complete native input")
    return case, record


def _solver(exe_name, engine):
    executable = shutil.which(str(exe_name))
    if executable is None:
        raise FileNotFoundError("Explicit classic executable not found")
    path = package._path_no_links(Path(executable))
    raw = package._read_file(path, 64 * 1024 * 1024)
    expected = PINNED[_engine(engine)]
    if len(raw) != expected["bytes"] or _digest(raw) != expected["sha256"]:
        raise ClassicError("This reader requires the exact pinned double-precision public engine")
    return path, {"engine": engine, **expected, "path": str(path)}


def run_classic(case, output_dir, *, engine, exe_name, timeout_seconds=300,linear_solver=None):
    return _run_classic(case,output_dir,engine=engine,exe_name=exe_name,timeout_seconds=timeout_seconds,linear_solver=linear_solver)


def _run_classic(case,output_dir,*,engine,exe_name,timeout_seconds=300,source=None,linear_solver=None):
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
        raise ClassicError("Timeout must be an integer from 1 through 1800 seconds")
    executable, identity = _solver(exe_name, engine)
    if source is not None:
        source=package._path_no_links(source,directory=True)
        target=Path(output_dir).absolute()
        if source.is_relative_to(target) or target.is_relative_to(source):
            raise ClassicError("Source export and run output must be separate")
        source_case,source_record=verify_classic_export(source)
        if source_record["engine"]!=engine:raise ClassicError("Captured engine mismatch")
        if linear_solver is not None and linear_solver!=source_record["linear_solver"]:
            raise ClassicError("Requested solver contradicts the captured native configuration")
        linear_solver=source_record["linear_solver"]
        if source_case.to_dict()!=case.to_dict():raise ClassicError("Prepared case mismatch")
        original=_inventory(source)
    root = _fresh(output_dir)
    record = {"schema": SCHEMA, "status": "failed", "engine": engine, "solver": identity}
    try:
        if source is None:
            native=export_classic(case,root/"native",engine=engine,linear_solver=linear_solver)
        else:
            native=root/"native";shutil.copytree(source,native)
            if _inventory(native)!=original or _inventory(source)!=original:
                raise ClassicError("Source or copied classic export changed")
        _, captured = verify_classic_export(native)
        record["captured_inputs"] = _inventory(native)
        returncode = _execute([str(executable), "flow.nam"], native, root/"stdout.log", root/"stderr.log",
                              timeout_seconds, OUTPUT_LIMIT, watch_root=root)
        stdout = package._read_file(root/"stdout.log", 8 * 1024 * 1024).decode("utf-8", errors="replace")
        listing = package._read_file(native/"flow.list", 32 * 1024 * 1024).decode("ascii", errors="replace")
        if (returncode != 0 or "normal termination of simulation" not in stdout.lower()
                or re.search(r"FAILED TO (?:MEET SOLVER CONVERGENCE|CONVERGE)", listing, re.I)):
            raise ClassicError("Classic solver failed or did not establish normal convergence")
        for name, item in record["captured_inputs"].items():
            if _inventory_file(native/name) != item:
                raise ClassicError("Solver changed a captured input")
        if _solver(executable, engine)[1] != identity:
            raise ClassicError("Executable changed during the run")
        if source is not None and _inventory(source)!=original:
            raise ClassicError("Source classic export changed during execution")
        record.update(status="completed", returncode=returncode, artifacts=_run_inventory(root))
        (root/"run.json").write_bytes(_json(record))
        return root
    except BaseException as error:
        record.update(error_type=type(error).__name__, error=str(error))
        try:
            record["artifacts"] = _run_inventory(root)
        except (ValueError, OSError) as inventory_error:
            record["artifact_inventory_error"] = str(inventory_error)
        (root/"run.json").write_bytes(_json(record))
        raise


def _inventory_file(path):
    raw = package._read_file(path, OUTPUT_LIMIT)
    return {"bytes": len(raw), "sha256": _digest(raw)}


def _run_inventory(root):
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ClassicError("Run artifact links refused")
        if path.is_dir() or path == root/"run.json":
            continue
        item = _inventory_file(path)
        total += item["bytes"]
        if total > OUTPUT_LIMIT or len(result) >= 256:
            raise ClassicError("Classic run exceeds bounded artifact budget")
        result[path.relative_to(root).as_posix()] = item
    return result


def _schedule(case, durations):
    rows, total = [], 0.0
    for period, (spec, duration) in enumerate(zip(case.to_dict()["periods"], durations)):
        for step in range(spec["nsteps"]):
            rows.append((step+1, period+1, duration*(step+1)/spec["nsteps"], total+duration*(step+1)/spec["nsteps"]))
        total += duration
    return rows


def _heads(path, case, schedule):
    nl, nr, nc = case.shape
    size = len(schedule)*nl*(HEAD_HEADER.size+nr*nc*8)
    raw = package._read_file(path, size)
    if len(raw) != size:
        raise ClassicError("Incomplete double-precision saved head schedule")
    values, offset = np.empty((len(schedule), nl, nr, nc)), 0
    for index, (step, period, pt, tt) in enumerate(schedule):
        for layer in range(nl):
            s, p, t1, t2, label, cols, rows, k = HEAD_HEADER.unpack_from(raw, offset)
            if ((s,p,label.strip(),cols,rows,k) != (step,period,b"HEAD",nc,nr,layer+1)
                    or not math.isclose(t1,pt,rel_tol=1e-8,abs_tol=1e-9)
                    or not math.isclose(t2,tt,rel_tol=1e-8,abs_tol=1e-9)):
                raise ClassicError("Unsupported or inconsistent classic head header")
            offset += HEAD_HEADER.size
            values[index,layer] = np.frombuffer(raw,dtype="<f8",count=nr*nc,offset=offset).reshape(nr,nc)
            offset += nr*nc*8
    if not np.isfinite(values).all() or (np.abs(values)>1e20).any():
        raise ClassicError("Dry/inactive/nonfinite heads outside this confined contract")
    return values[:,:,::-1,:].copy()


def _cbc(path, case, schedule):
    """Bounded reader for this compiler's compact double CBC methods 1/2/3/5."""
    raw = package._read_file(path, OUTPUT_LIMIT)
    offset, records = 0, {}
    nl,nr,nc = case.shape; count=nl*nr*nc
    case_data=case.to_dict()
    kinds={b["kind"] for b in case_data["boundaries"]}
    allowed=set(INTERNAL)|{TERMS[k] for k in kinds}|{"STORAGE","CONSTANT HEAD"}
    schedule_indices={s[:2]:i for i,s in enumerate(schedule)}
    def take(fmt):
        nonlocal offset
        if offset+fmt.size>len(raw): raise ClassicError("Truncated budget record")
        out=fmt.unpack_from(raw,offset);offset+=fmt.size;return out
    def array(dtype,n):
        nonlocal offset
        size=np.dtype(dtype).itemsize*n
        if n<0 or offset+size>len(raw):raise ClassicError("Budget payload exceeds bounds")
        out=np.frombuffer(raw,dtype=dtype,count=n,offset=offset).copy();offset+=size;return out
    while offset<len(raw):
        step,period,label,cols,rows,layers=take(CBC_HEADER)
        text=label.decode("ascii",errors="strict").strip()
        if (cols,rows,layers)!=(nc,nr,-nl) or text not in allowed:
            raise ClassicError("Unexpected budget geometry/term or noncompact precision")
        method,dt,pt,tt=take(CBC_TIME)
        match=schedule_indices.get((step,period))
        if match is None or not all(math.isfinite(t) for t in (dt,pt,tt)) or dt<=0:
            raise ClassicError("Unexpected budget schedule")
        expected_dt=schedule[match][2]/step
        if not all(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-9) for a,b in
                   ((dt,expected_dt),(pt,schedule[match][2]),(tt,schedule[match][3]))):
            raise ClassicError("Budget step, period and total times disagree")
        key=(match,text)
        if key in records or len(records)>len(schedule)*12: raise ClassicError("Duplicate/excessive budget records")
        if method==1:
            q=array("<f8",count)
        elif method==3:
            layer=array("<i4",nr*nc);q=array("<f8",nr*nc)
            if text!="RECHARGE" or np.any(layer!=1):
                raise ClassicError("Invalid recharge support")
        elif method in (2,5):
            if method==5 and take(struct.Struct("<i"))[0]!=1:
                raise ClassicError("Auxiliary budget columns outside this subset")
            length=take(struct.Struct("<i"))[0]
            if not 0<=length<=count:raise ClassicError("Budget list allocation exceeds cell count")
            data=array(np.dtype([("node","<i4"),("q","<f8")]),length)
            if np.any(data["node"]<1) or np.any(data["node"]>count):raise ClassicError("Budget node outside grid")
            q=data["q"]
        else:raise ClassicError("Unsupported classic compact budget method")
        if not np.isfinite(q).all(): raise ClassicError("Nonfinite budget flow")
        if text=="CONSTANT HEAD" and "CHD" not in kinds and np.any(q!=0.0):
            raise ClassicError("Nonzero constant-head flow without authored CHD support")
        incoming,outgoing=float(np.maximum(q,0).sum()),float(np.maximum(-q,0).sum())
        if not math.isfinite(incoming) or not math.isfinite(outgoing):
            raise ClassicError("Budget aggregate overflow")
        records[key]=(incoming,outgoing)
    rows=[]
    for i,s in enumerate(schedule):
        values={}
        for term in ["STORAGE",*[TERMS[k] for k in sorted(kinds)]]:
            if (i,term) not in records:
                active=any(b["period"]==s[1]-1 and TERMS[b["kind"]]==term for b in case_data["boundaries"])
                if active or (term=="STORAGE" and not case_data["periods"][s[1]-1]["steady"]):
                    raise ClassicError("Missing required saved budget term")
            incoming,outgoing=records.get((i,term),(0.0,0.0))
            values[term+"_IN"],values[term+"_OUT"]=incoming,outgoing
        values["TOTAL_IN"]=sum(v for k,v in values.items() if k.endswith("_IN"))
        values["TOTAL_OUT"]=sum(v for k,v in values.items() if k.endswith("_OUT"))
        if not math.isfinite(values["TOTAL_IN"]) or not math.isfinite(values["TOTAL_OUT"]):
            raise ClassicError("Total budget overflow")
        rows.append({"time_day":s[3],**values})
    return rows


@dataclass
class ClassicResult:
    case: WorkflowCase
    times_day: np.ndarray
    heads_m: np.ndarray
    budget: list[dict]
    summary: dict


def read_classic_results(workspace):
    root=package._path_no_links(workspace,directory=True)
    record=_decode(package._read_file(root/"run.json",2*1024*1024))
    if (not isinstance(record,dict) or set(record)!={"schema","status","engine","solver","captured_inputs","returncode","artifacts"}
            or record.get("schema")!=SCHEMA or record.get("status")!="completed" or record.get("returncode")!=0
            or type(record.get("returncode")) is not int or record.get("artifacts")!=_run_inventory(root)):
        raise ClassicError("Completed unchanged classic run required")
    engine=_engine(record["engine"])
    identity=record["solver"]
    if (not isinstance(identity,dict) or set(identity)!={"engine","member","bytes","sha256","path"}
            or identity["engine"]!=engine or any(identity.get(k)!=v for k,v in PINNED[engine].items())
            or not isinstance(identity["path"],str) or not identity["path"]):
        raise ClassicError("Classic executable identity disagrees with the pinned engine")
    raw=package._read_file(root/"native/settings.json",10*1024*1024)
    captured=_decode(raw);case=WorkflowCase.from_dict(captured["case"])
    with tempfile.TemporaryDirectory(prefix="basinlens-classic-bind-") as tmp:
        exported=export_classic(case,Path(tmp)/"expected",engine=record["engine"],linear_solver=captured["linear_solver"])
        if not isinstance(record["captured_inputs"],dict) or set(_inventory(exported))!=set(record["captured_inputs"]):
            raise ClassicError("Captured input membership disagrees with this compiler")
        snapshot=Path(tmp)/"captured";snapshot.mkdir()
        for name,item in record["captured_inputs"].items():
            payload=package._read_file(root/"native"/name,INPUT_LIMIT)
            if {"bytes":len(payload),"sha256":_digest(payload)}!=item:
                raise ClassicError("Captured input bytes changed")
            (snapshot/name).write_bytes(payload)
        bound_case,bound_record=verify_classic_export(snapshot)
        if bound_case.to_dict()!=case.to_dict():raise ClassicError("Captured classic case disagreement")
    for name,item in record["captured_inputs"].items():
        if _inventory_file(root/"native"/name)!=item:raise ClassicError("Captured input changed")
    schedule=_schedule(case,captured["compiled_period_durations_day"])
    heads=_heads(root/"native/flow.hds",case,schedule)
    budgets=_cbc(root/"native/flow.cbc",case,schedule)
    residual=np.asarray([abs(b["TOTAL_IN"]-b["TOTAL_OUT"]) for b in budgets])
    scale=np.asarray([max(b["TOTAL_IN"],b["TOTAL_OUT"]) for b in budgets])
    top=np.asarray(case.to_dict()["grid"]["layer_surfaces_m"][:-1])[:,None,None]
    mapped={f"{kind}({kind})_{direction}":np.asarray([b[TERMS[kind]+"_"+direction] for b in budgets])
            for kind in {b["kind"] for b in case.to_dict()["boundaries"]} for direction in ("IN","OUT")}
    checks=_boundary_checks(case,heads,mapped)
    summary={"engine":ENGINES[record["engine"]],"linear_solver":captured["linear_solver"],"solver":record["solver"],"saved_steps":len(heads),"shape":list(case.shape),
        "water_balance_passed":bool(np.all(residual<=1e-8+1e-7*scale)),
        "maximum_water_balance_residual_m3_day":float(residual.max()),
        **checks,
        "confined_saturation_support_passed":bool(np.all(heads>=top-1e-7)),
        "units":dict(UNITS),"native_period_durations_day":captured["compiled_period_durations_day"],
        "scope":"Authored confined-water subset; scalar input precision is limited by legacy FloPy/text; no original GMS or general legacy import equivalence",
        "gms_parity_established":False,"co2_or_oil_multiphase_physics":False}
    if _run_inventory(root)!=record["artifacts"]:
        raise ClassicError("Classic artifacts changed while reading results")
    return ClassicResult(case,np.asarray([s[3] for s in schedule]),heads,budgets,summary)


def verify_classic_roundtrip(source,output_dir,*,exe_name=None,timeout_seconds=300):
    source=package._path_no_links(source,directory=True)
    target=Path(output_dir).absolute()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ClassicError("Roundtrip requires separate source and fresh output")
    case,record=verify_classic_export(source);before=_inventory(source)
    root=_fresh(output_dir)
    receipt={"schema":"basinlens-classic-roundtrip-v1","status":"failed",
        "linear_solver":record["linear_solver"],
        "source_inputs":before,"source_unchanged":False,"native_runs_requested":2 if exe_name else 0,
        "native_runs_completed":0,"numerical_roundtrip_passed":None,
        "gms_project_roundtrip":False,"gms_parity_established":False}
    try:
        rewritten=root/"rewritten";rewritten.mkdir()
        model=_flopy().modflow.Modflow.load("flow.nam",model_ws=str(source),version=record["engine"],check=False,verbose=False,exe_name=None)
        if model is None:raise ClassicError("Native model load failed")
        _restore_list_precision(model,source,case)
        model.change_model_ws(str(rewritten),reset_external=True);_array_format(model);model.write_input()
        native=_inventory(rewritten)
        if _signature(rewritten,native)!=record["compiler_token_semantics_sha256"]:
            raise ClassicError("Legacy native rewrite changed ordered token semantics; artifacts retained")
        updated={**record,"inputs":native}
        (rewritten/"settings.json").write_bytes(_json(updated));verify_classic_export(rewritten)
        receipt.update(case_metadata_preserved=True,native_token_semantics_equal=True,rewritten_inputs=_inventory(rewritten))
        if exe_name is not None:
            results=[]
            for original,name in ((source,"original-run"),(rewritten,"rewritten-run")):
                run=_run_classic(case,root/name,engine=record["engine"],exe_name=exe_name,
                    timeout_seconds=timeout_seconds,source=original)
                result=read_classic_results(run);results.append(result)
                receipt["native_runs_completed"]+=1
                (root/"roundtrip.json").write_bytes(_json(receipt))
            head_error=float(np.max(np.abs(results[0].heads_m-results[1].heads_m)))
            budget_error=max(abs(a[key]-b[key]) for a,b in zip(results[0].budget,results[1].budget) for key in a)
            gates=[{k:r.summary[k] for k in ("water_balance_passed","boundary_rates_passed","confined_saturation_support_passed")} for r in results]
            receipt.update(maximum_head_difference_m=head_error,maximum_budget_column_difference=budget_error,
                run_validation_gates=gates,numerical_roundtrip_passed=bool(head_error<=1e-7 and budget_error<=1e-7 and all(all(g.values()) for g in gates)))
        if _inventory(source)!=before:raise ClassicError("Original export changed during roundtrip")
        receipt.update(status="completed",source_unchanged=True)
    except BaseException as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
        (root/"roundtrip.json").write_bytes(_json(receipt));raise
    (root/"roundtrip.json").write_bytes(_json(receipt));return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    for name in ("export","run"):
        p=sub.add_parser(name);p.add_argument("case",type=Path);p.add_argument("--engine",choices=ENGINES,required=True);p.add_argument("--output",type=Path,required=True)
        p.add_argument("--linear-solver",choices=("pcg","gmres","xmd"))
        if name=="run":p.add_argument("--exe",required=True)
    sub.add_parser("results").add_argument("workspace",type=Path)
    p=sub.add_parser("roundtrip");p.add_argument("source",type=Path);p.add_argument("--output",type=Path,required=True);p.add_argument("--exe")
    args=parser.parse_args(argv)
    try:
        if args.command=="export":result={"export":str(export_classic(load_workflow_case(args.case),args.output,engine=args.engine,linear_solver=args.linear_solver)),"engine_executed":False}
        elif args.command=="run":result=read_classic_results(run_classic(load_workflow_case(args.case),args.output,engine=args.engine,exe_name=args.exe,linear_solver=args.linear_solver)).summary
        elif args.command=="roundtrip":
            result=verify_classic_roundtrip(args.source,args.output,exe_name=args.exe)
            if args.exe is not None and result["numerical_roundtrip_passed"] is not True:
                raise ClassicError("Numerical roundtrip or physical validation gate failed; outputs retained")
        else:result=read_classic_results(args.workspace).summary
        if args.command in ("run","results") and not all(result.get(k) is True for k in
                ("water_balance_passed","boundary_rates_passed","confined_saturation_support_passed")):
            raise ClassicError("Physical validation gate failed; diagnostic run artifacts retained")
    except (OSError,RuntimeError,ValueError) as error:parser.exit(2,f"Classic workflow failed: {error}\n")
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=="__main__":main()
