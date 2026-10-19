"""Small stationary Gaussian geostatistics with explicit support and units.

No variogram fitting, measurement-noise assimilation, automatic drift model,
GMS equivalence, or field uncertainty certification is implied.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import itertools
import json
import math
import os
import stat
from pathlib import Path
from statistics import NormalDist
import tempfile

import numpy as np

from .scatter import ScatterDataset, ScatterError, load_scatter
from .scatter import _write as _write_scatter

MODEL_SCHEMA = "basinlens-covariance-v1"
RESULT_SCHEMA = "basinlens-geostatistics-result-v1"
CSV_PREFIX = "# " + RESULT_SCHEMA + " "
MAX_OBSERVATIONS = 64
MAX_TARGETS = 256
MAX_MATRIX = 256
MAX_NEIGHBORS = 32
MAX_DRAW_VALUES = 65_536
MAX_BYTES = 8 * 1024 * 1024
CONDITION_LIMIT = 1e10
HULL_TOLERANCE = 1e-10


class GeostatisticsError(ValueError):
    """Invalid, unsupported, over-budget or ill-conditioned statistical problem."""


def _number(v, label, *, limit=1e50):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise GeostatisticsError(f"{label}: finite number required")
    try: value = float(v)
    except (ValueError, OverflowError): raise GeostatisticsError(f"{label}: finite number required") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise GeostatisticsError(f"{label}: finite value within +/-{limit:g} required")
    return value


def _integer(v, low, high, label):
    if type(v) is not int or not low <= v <= high:
        raise GeostatisticsError(f"{label}: integer {low}..{high} required")
    return v


def _text(v, label, limit=500):
    if not isinstance(v, str) or not 1 <= len(v) <= limit or v != v.strip() or any(ord(c) < 32 for c in v):
        raise GeostatisticsError(f"{label}: bounded trimmed text required")
    return v


def _keys(v, keys, label):
    if not isinstance(v, dict) or set(v) != set(keys):
        raise GeostatisticsError(f"{label}: exact keys {sorted(keys)} required")
    return v


def _json_bytes(v):
    try: raw = (json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()
    except (ValueError, TypeError, RecursionError) as e: raise GeostatisticsError(f"invalid JSON: {e}") from e
    if len(raw) > MAX_BYTES: raise GeostatisticsError("JSON exceeds 8 MiB budget")
    return raw


def _json(raw):
    def pairs(values):
        d = {}
        for k, v in values:
            if k in d: raise GeostatisticsError(f"duplicate JSON key: {k}")
            d[k] = v
        return d
    try:
        if len(raw) > MAX_BYTES: raise GeostatisticsError("input exceeds 8 MiB budget")
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda v: (_ for _ in ()).throw(GeostatisticsError(f"nonfinite JSON: {v}")))
    except (ValueError, UnicodeError, RecursionError) as e:
        if isinstance(e, GeostatisticsError): raise
        raise GeostatisticsError(f"invalid JSON: {e}") from e


def _read(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise GeostatisticsError("symlink paths refused")
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))
        with os.fdopen(fd,"rb") as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_BYTES:raise GeostatisticsError("regular input <=8 MiB required")
            raw=f.read(MAX_BYTES+1);after=os.fstat(f.fileno())
        identity=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
        if len(raw)!=before.st_size or identity(before)!=identity(after) or identity(after)!=identity(path.lstat()):raise GeostatisticsError("input changed during read")
        return raw
    except OSError as e:raise GeostatisticsError(f"cannot read bounded input: {e}") from e


def _write(path, raw):
    if len(raw) > MAX_BYTES: raise GeostatisticsError("output exceeds 8 MiB budget")
    try: return _write_scatter(Path(path), raw)
    except ScatterError as e: raise GeostatisticsError(str(e)) from e


def _coordinates(v, dim, label, maximum=MAX_TARGETS):
    if not isinstance(v, list) or not 1 <= len(v) <= maximum:
        raise GeostatisticsError(f"{label}: 1..{maximum} coordinates required")
    result = []
    for p in v:
        if not isinstance(p, list) or len(p) != dim: raise GeostatisticsError(f"{label}: dimension mismatch")
        result.append([_number(x, label, limit=1e9) for x in p])
    return np.asarray(result, dtype=float)


def _model(v):
    _keys(v, {"schema", "dimension", "kind", "partial_sill", "nugget", "value_unit", "ranges_m", "rotation"}, "covariance model")
    if v["schema"] != MODEL_SCHEMA or type(v["dimension"]) is not int or v["dimension"] not in (2, 3): raise GeostatisticsError("covariance requires v1, dimension 2 or 3")
    if v["kind"] not in ("exponential", "gaussian", "spherical"): raise GeostatisticsError("unsupported covariance family")
    dim = v["dimension"]
    sill = _number(v["partial_sill"], "partial_sill", limit=1e20)
    nugget = _number(v["nugget"], "nugget", limit=1e20)
    if not 1e-20 <= sill <= 1e20 or nugget < 0 or sill + nugget > 1e20: raise GeostatisticsError("positive partial sill and nonnegative nugget, total <=1e20 required")
    if not isinstance(v["ranges_m"], list) or len(v["ranges_m"]) != dim: raise GeostatisticsError("one principal range per dimension required")
    ranges = [_number(x, "range", limit=1e9) for x in v["ranges_m"]]
    if any(x < 1e-6 for x in ranges): raise GeostatisticsError("ranges require 1e-6..1e9 metres")
    rotation = _coordinates(v["rotation"], dim, "rotation", maximum=dim)
    if rotation.shape != (dim, dim) or not np.allclose(rotation.T @ rotation, np.eye(dim), atol=1e-12, rtol=0) or not math.isclose(float(np.linalg.det(rotation)), 1., abs_tol=1e-12):
        raise GeostatisticsError("rotation requires a right-handed orthonormal matrix (columns are principal axes)")
    return {**v, "partial_sill": sill, "nugget": nugget, "ranges_m": ranges, "rotation": rotation.tolist(), "value_unit": _text(v["value_unit"], "value_unit", 128)}


@dataclass(frozen=True)
class CovarianceModel:
    _json: str

    @classmethod
    def from_dict(cls, v): return cls(_json_bytes(_model(v)).decode())
    def to_dict(self):
        if not isinstance(self._json,str):raise GeostatisticsError("immutable canonical covariance JSON required")
        return _model(_json(self._json.encode()))


def covariance(model: CovarianceModel, a: list, b: list | None = None) -> np.ndarray:
    """C(x,y)=partial_sill*rho(h)+nugget*I[x==y], process nugget.

    h=norm((x-y)@rotation/ranges_m). Exponential exp(-h), Gaussian
    exp(-h²), spherical max(0,1-1.5h+0.5h³) for h<1. No practical-range factor 3.
    """
    m = model.to_dict(); dim = m["dimension"]
    x = _coordinates(a, dim, "covariance a", maximum=MAX_MATRIX)
    y = x if b is None else _coordinates(b, dim, "covariance b", maximum=MAX_MATRIX)
    delta = x[:, None, :] - y[None, :, :]
    h = np.linalg.norm((delta @ np.asarray(m["rotation"])) / np.asarray(m["ranges_m"]), axis=2)
    if m["kind"] == "exponential": rho = np.exp(-h)
    elif m["kind"] == "gaussian": rho = np.exp(-(h * h))
    else:
        t = np.minimum(h, 1.)
        rho = np.where(h < 1, 1 - 1.5*t + .5*t*t*t, 0.)
    equal = np.all(x[:, None, :] == y[None, :, :], axis=2)
    result = m["partial_sill"] * rho + m["nugget"] * equal
    if not np.isfinite(result).all(): raise GeostatisticsError("covariance arithmetic overflow")
    return result


def _observations(dataset, model):
    if not isinstance(dataset, ScatterDataset): raise GeostatisticsError("typed ScatterDataset required")
    try: d = dataset.to_dict()
    except ScatterError as e: raise GeostatisticsError(str(e)) from e
    m = model.to_dict()
    if d["dimension"] != m["dimension"] or d["value_unit"] != m["value_unit"]:
        raise GeostatisticsError("dataset dimension/value unit must exactly match covariance model")
    if d["crs"] == "unknown" or d["vertical_datum"] == "unknown": raise GeostatisticsError("explicit dataset CRS and datum required")
    valid = [p for p in d["points"] if p["value"] is not None]
    if not 1 <= len(valid) <= MAX_OBSERVATIONS: raise GeostatisticsError("1..64 valued observations required; no hidden downsampling")
    for p in valid: _number(p["value"], "observation value")
    return d, valid, np.asarray([p["coordinates_m"] for p in valid]), np.asarray([p["value"] for p in valid])


def _solve(matrix, rhs):
    try:condition = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError as e:raise GeostatisticsError(f"condition estimate failed: {e}") from e
    if not math.isfinite(condition) or condition > CONDITION_LIMIT: raise GeostatisticsError(f"ill-conditioned system: condition={condition:g}, limit={CONDITION_LIMIT:g}; no jitter added")
    try: result = np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError as e: raise GeostatisticsError(f"singular covariance system: {e}") from e
    if not np.isfinite(result).all(): raise GeostatisticsError("linear solve produced nonfinite values")
    return result, condition


def _bounds(v, dim):
    if not isinstance(v, list) or len(v) != dim: raise GeostatisticsError("domain_bounds_m requires one [min,max] per dimension")
    result = []
    for pair in v:
        if not isinstance(pair, list) or len(pair) != 2: raise GeostatisticsError("domain bounds require [min,max]")
        lo, hi = [_number(x, "domain bound", limit=1e9) for x in pair]
        if lo > hi: raise GeostatisticsError("domain minimum exceeds maximum")
        result.append([lo, hi])
    return result


def _hull_mask(x, query):
    """Actual affine/convex hull in <=3D, bounded <=64 data; normalized tolerance."""
    centre = x[0]
    scale = max(float(np.max(np.ptp(x, axis=0))), 1e-100)
    p = (x - centre) / scale
    q = (query - centre) / scale
    _, singular, vt = np.linalg.svd(p, full_matrices=True)
    threshold = max(p.shape) * np.finfo(float).eps * max(float(singular[0]), 1.) * 100
    rank = int(np.sum(singular > threshold))
    basis = vt[:rank].T
    p2, q2 = p @ basis, q @ basis
    residual = q - q2 @ basis.T
    mask = np.linalg.norm(residual, axis=1) <= HULL_TOLERANCE
    if rank == 0: return mask
    if rank == 1: return mask & (q2[:, 0] >= p2[:, 0].min()-HULL_TOLERANCE) & (q2[:, 0] <= p2[:, 0].max()+HULL_TOLERANCE)
    if rank == 2:
        ordered = sorted(set(map(tuple, p2)))
        def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        lower=[]; upper=[]
        for row in ordered:
            while len(lower)>=2 and cross(lower[-2],lower[-1],row)<=0: lower.pop()
            lower.append(row)
        for row in reversed(ordered):
            while len(upper)>=2 and cross(upper[-2],upper[-1],row)<=0: upper.pop()
            upper.append(row)
        polygon=lower[:-1]+upper[:-1]
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            edge_length=math.hypot(b[0]-a[0],b[1]-a[1])
            mask &= ((b[0]-a[0])*(q2[:,1]-a[1])-(b[1]-a[1])*(q2[:,0]-a[0]))/edge_length >= -HULL_TOLERANCE
        return mask
    # All supporting planes from triples; C(64,3)=41664, no unbounded hull search.
    planes=[]
    for i,j,k in itertools.combinations(range(len(p2)),3):
        u,v=p2[j]-p2[i],p2[k]-p2[i]
        normal=np.cross(u,v); length=float(np.linalg.norm(normal))
        angular_tolerance=100*np.finfo(float).eps*float(np.linalg.norm(u))*float(np.linalg.norm(v))
        if length <= angular_tolerance: continue
        normal/=length; distance=(p2-p2[i])@normal
        if np.all(distance <= HULL_TOLERANCE): planes.append((normal,p2[i]))
        elif np.all(distance >= -HULL_TOLERANCE): planes.append((-normal,p2[i]))
    if not planes: raise GeostatisticsError("3D hull has no reliable supporting planes")
    for normal, origin in planes: mask &= ((q2-origin)@normal <= HULL_TOLERANCE)
    return mask


def _column(name, unit, kind="float"): return {"name": name, "unit": unit, "kind": kind}


def _result_validate(v):
    _keys(v,{"schema","operation","metadata","columns","rows"},"result")
    if v["schema"] != RESULT_SCHEMA or v["operation"] not in ("kriging","experimental_variogram","gaussian_field","latin_hypercube"): raise GeostatisticsError("unsupported result schema/operation")
    if not isinstance(v["metadata"],dict) or v["metadata"].get("original_gms_comparison") != "NOT_OBSERVED": raise GeostatisticsError("result must retain explicit NOT_OBSERVED original comparison")
    columns=v["columns"]
    if not isinstance(columns,list) or not 1<=len(columns)<=1032: raise GeostatisticsError("bounded column schema required")
    names=set()
    for c in columns:
        _keys(c,{"name","unit","kind"},"column");name=_text(c["name"],"column name",128);_text(c["unit"],"column unit",128)
        if name in names or c["kind"] not in ("float","int","text","bool"): raise GeostatisticsError("unique columns and supported scalar kinds required")
        names.add(name)
    rows=v["rows"]
    if not isinstance(rows,list) or len(rows)>4096 or len(rows)*len(columns)>MAX_DRAW_VALUES+4096: raise GeostatisticsError("result table exceeds cell budget")
    parsed=[]
    for row in rows:
        if not isinstance(row,list) or len(row)!=len(columns): raise GeostatisticsError("ragged result table")
        out=[]
        for c,value in zip(columns,row):
            if value is None: out.append(None)
            elif c["kind"]=="float": out.append(_number(value,c["name"],limit=1e100))
            elif c["kind"]=="int": out.append(_integer(value,0,2**63-1,c["name"]))
            elif c["kind"]=="bool":
                if type(value)is not bool: raise GeostatisticsError("boolean result value required")
                out.append(value)
            else: out.append(_text(value,c["name"],500))
        parsed.append(out)
    # Validate finite/serializable metadata without interpreting it as observations.
    _json_bytes(v["metadata"])
    return {**v,"rows":parsed}


@dataclass(frozen=True)
class GeostatisticsResult:
    _json: str

    @classmethod
    def from_dict(cls,v): return cls(_json_bytes(_result_validate(v)).decode())
    def to_dict(self):
        if not isinstance(self._json,str):raise GeostatisticsError("immutable canonical result JSON required")
        return _result_validate(_json(self._json.encode()))
    @property
    def records(self):
        d=self.to_dict();names=[c["name"] for c in d["columns"]];return [dict(zip(names,row)) for row in d["rows"]]


def _result(operation,metadata,columns,rows):
    return GeostatisticsResult.from_dict(dict(schema=RESULT_SCHEMA,operation=operation,metadata={**metadata,"original_gms_comparison":"NOT_OBSERVED","evidence":"authored numerical/software checks; statistical assumptions require case review"},columns=columns,rows=rows))


def krige(dataset: ScatterDataset, queries_m: list, model: CovarianceModel, *, method: str,
          mean: float | None, radius_m: float, min_neighbors: int, max_neighbors: int,
          domain_bounds_m: list, allow_extrapolation: bool) -> GeostatisticsResult:
    """Point ordinary/simple kriging. Missing support is null, never filled."""
    d, valid, x, y = _observations(dataset,model);m=model.to_dict();dim=m["dimension"]
    q=_coordinates(queries_m,dim,"queries")
    if method not in ("ordinary","simple"): raise GeostatisticsError("method requires ordinary or simple")
    if method=="simple": mean=_number(mean,"known simple-kriging mean")
    elif mean is not None: raise GeostatisticsError("ordinary kriging requires mean=null; drift is unknown constant")
    radius=_number(radius_m,"radius_m",limit=1e10)
    if radius<=0: raise GeostatisticsError("positive search radius required")
    _integer(min_neighbors,1,MAX_NEIGHBORS,"min_neighbors");_integer(max_neighbors,min_neighbors,MAX_NEIGHBORS,"max_neighbors")
    bounds=_bounds(domain_bounds_m,dim)
    if type(allow_extrapolation)is not bool: raise GeostatisticsError("allow_extrapolation must be explicit boolean")
    hull=np.ones(len(q),dtype=bool) if allow_extrapolation else _hull_mask(x,q)
    scale=m["partial_sill"]+m["nugget"]
    columns=[_column("id","1","text")]+[_column(axis+"_m","m") for axis in ("x","y","z")[:dim]]+[_column("prediction",m["value_unit"]),_column("variance",f"({m['value_unit']})^2"),_column("supported","1","bool"),_column("reason","1","text")]
    rows=[];diagnostics=[]
    for index,point in enumerate(q):
        reason=None
        if any(not lo<=point[a]<=hi for a,(lo,hi) in enumerate(bounds)): reason="outside_owner_domain"
        elif not hull[index]: reason="outside_observation_affine_convex_hull"
        distances=np.linalg.norm(x-point,axis=1)
        neighbors=sorted((i for i,r in enumerate(distances) if r<=radius),key=lambda i:(distances[i],valid[i]["id"]))[:max_neighbors]
        if reason is None and len(neighbors)<min_neighbors: reason="insufficient_neighbors_in_radius"
        if reason is not None:
            rows.append([f"q{index}",*point.tolist(),None,None,False,reason]);diagnostics.append({"neighbor_ids":[],"weights":[],"condition_number":None});continue
        locations=x[neighbors].tolist();matrix=covariance(model,locations)/scale;cross=covariance(model,locations,[point.tolist()])[:,0]/scale
        if method=="ordinary":
            n=len(neighbors);system=np.block([[matrix,np.ones((n,1))],[np.ones((1,n)),np.zeros((1,1))]])
            solved,condition=_solve(system,np.r_[cross,1.]);weights=solved[:-1]
            prediction=float(weights@y[neighbors])
            if not math.isclose(float(weights.sum()),1.,abs_tol=1e-9): raise GeostatisticsError("ordinary weights violate constant-mean constraint")
        else:
            weights,condition=_solve(matrix,cross);prediction=float(mean+weights@(y[neighbors]-mean))
        variance=float((1.-2*weights@cross+weights@matrix@weights)*scale)
        if variance < -1e-9*scale or not math.isfinite(prediction): raise GeostatisticsError("invalid prediction or negative kriging variance")
        variance=max(0.,variance)
        rows.append([f"q{index}",*point.tolist(),prediction,variance,True,None]);diagnostics.append({"neighbor_ids":[valid[i]["id"] for i in neighbors],"weights":weights.tolist(),"condition_number":condition})
    metadata=dict(source_dataset=d,source_sha256=dataset.sha256,covariance_model=m,settings=dict(method=method,mean=mean,radius_m=radius,min_neighbors=min_neighbors,max_neighbors=max_neighbors,domain_bounds_m=bounds,allow_extrapolation=allow_extrapolation),diagnostics=diagnostics,
                  nugget_semantics="independent microscale process variance at distinct coordinates; same coordinate denotes same process value; no measurement error",variance_scope="point prediction error under specified stationary covariance and mean assumptions; not observed geological uncertainty",variance_roundoff_clip_relative=1e-9,hull_tolerance_relative=HULL_TOLERANCE,hull_tolerance_m=HULL_TOLERANCE*max(float(np.max(np.ptp(x,axis=0))),1e-100),hull_rank_threshold="max(n,dimension)*eps*max(largest_normalized_singular_value,1)*100",covariance_parameters_unit=f"({m['value_unit']})^2",condition_limit=CONDITION_LIMIT)
    return _result("kriging",metadata,columns,rows)


def kriging_to_scatter(result: GeostatisticsResult, *, dataset_id: str, field: str = "prediction") -> ScatterDataset:
    """Export one interpreted scalar field with null support and traceable source.

    This does not turn kriging variance into measured uncertainty or execute a
    prediction while loading a result. Duplicate query sites cannot become a
    scatter dataset under the existing duplicate-reject contract.
    """
    d=result.to_dict()
    if d["operation"]!="kriging" or field not in ("prediction","variance"):raise GeostatisticsError("kriging result and prediction/variance field required")
    try:
        source=ScatterDataset.from_dict(d["metadata"]["source_dataset"]).to_dict()
        model=CovarianceModel.from_dict(d["metadata"]["covariance_model"]).to_dict()
        if (source["dimension"],source["value_unit"])!=(model["dimension"],model["value_unit"]):raise GeostatisticsError("result source/model dimension or unit mismatch")
        data={**source,"id":_text(dataset_id,"dataset_id",128),"basis":"interpreted","value_unit":source["value_unit"] if field=="prediction" else f"({source['value_unit']})^2",
              "quantity":source["quantity"] if field=="prediction" else "kriging_prediction_error_variance",
              "provenance":[*source["provenance"],f"Derived {field} from geostatistics result SHA256 {hashlib.sha256(_json_bytes(d)).hexdigest()}; original GMS not observed", "Stationary covariance/mean assumptions; prediction error variance is not measured geological uncertainty"],"points":[]}
        for row in result.records:
            data["points"].append({"id":row["id"],"coordinates_m":[row[a+"_m"] for a in ("x","y","z")[:source["dimension"]]],"value":row[field],"missing_reason":None if row[field] is not None else row["reason"]})
        return ScatterDataset.from_dict(data)
    except (KeyError,TypeError,ScatterError) as e:raise GeostatisticsError(f"result cannot satisfy typed scatter contract: {e}") from e


def experimental_variogram(dataset: ScatterDataset, bin_edges_m: list) -> GeostatisticsResult:
    try:d=dataset.to_dict()
    except (AttributeError,ScatterError) as e:raise GeostatisticsError("typed scatter dataset required") from e
    valid=[p for p in d["points"] if p["value"] is not None]
    if not 2<=len(valid)<=MAX_OBSERVATIONS:raise GeostatisticsError("variogram requires 2..64 valued points")
    if not isinstance(bin_edges_m,list) or not 2<=len(bin_edges_m)<=65:raise GeostatisticsError("2..65 increasing bin edges required")
    edges=[_number(x,"bin edge",limit=1e10) for x in bin_edges_m]
    if edges[0]<0 or any(b<=a for a,b in zip(edges,edges[1:])):raise GeostatisticsError("nonnegative strictly increasing bins required")
    bins=[[] for _ in edges[:-1]];excluded=0
    for a,b in itertools.combinations(valid,2):
        distance=math.dist(a["coordinates_m"],b["coordinates_m"]);difference=_number(a["value"],"value")-_number(b["value"],"value")
        gamma=.5*difference*difference
        if not math.isfinite(gamma) or difference!=0 and gamma==0:raise GeostatisticsError("semivariance arithmetic overflow/underflow")
        index=int(np.searchsorted(edges,distance,side="right"))-1
        if distance==edges[-1]:index=len(bins)-1
        if 0<=index<len(bins):bins[index].append((distance,gamma,a["id"],b["id"]))
        else:excluded+=1
    rows=[]
    for i,b in enumerate(bins):rows.append([edges[i],edges[i+1],math.fsum(p[0]/len(b) for p in b) if b else None,math.fsum(p[1]/len(b) for p in b) if b else None,len(b)])
    return _result("experimental_variogram",dict(source_dataset=d,source_sha256=dataset.sha256,bin_policy="[lower,upper), final upper inclusive; Euclidean metre distance; unordered valued pairs once",excluded_pairs=excluded,pair_ids_by_bin=[[[p[2],p[3]] for p in b] for b in bins],model_fitting="not performed"),[_column("lower_m","m"),_column("upper_m","m"),_column("mean_distance_m","m"),_column("semivariance",f"({d['value_unit']})^2"),_column("pair_count","1","int")],rows)


def gaussian_field(coordinates_m: list, model: CovarianceModel, *, mean: float, seed: int,
                   realizations: int, metadata: dict, conditioning: ScatterDataset | None = None) -> GeostatisticsResult:
    """Exact small multivariate Gaussian draw, optionally zero-noise conditioned.

    Every target is an explicit owner-declared simulation site; there is no
    interpolation support inference. Nugget is part of the point process.
    """
    m=model.to_dict();q=_coordinates(coordinates_m,m["dimension"],"simulation sites")
    if len(set(map(tuple,q)))!=len(q):raise GeostatisticsError("duplicate simulation coordinates are rejected")
    _integer(seed,0,2**63-1,"seed");_integer(realizations,1,1024,"realizations")
    if realizations*len(q)>MAX_DRAW_VALUES:raise GeostatisticsError("simulation draw budget exceeded")
    mean=_number(mean,"mean")
    _keys(metadata,{"crs","vertical_datum","provenance"},"simulation metadata")
    for key in ("crs","vertical_datum"):
        _text(metadata[key],key,128)
        if metadata[key]=="unknown":raise GeostatisticsError("explicit simulation CRS/datum required")
    if not isinstance(metadata["provenance"],list) or not 1<=len(metadata["provenance"])<=32:raise GeostatisticsError("bounded simulation provenance required")
    for statement in metadata["provenance"]:_text(statement,"provenance")
    means=np.full(len(q),mean);conditional=covariance(model,q.tolist());source=None;condition_numbers=[];fixed={}
    if conditioning is not None:
        source,valid,x,y=_observations(conditioning,model)
        if (source["crs"],source["vertical_datum"])!=(metadata["crs"],metadata["vertical_datum"]):raise GeostatisticsError("conditioning and simulation CRS/datum mismatch")
        if len(x)+len(q)>MAX_MATRIX:raise GeostatisticsError("conditioning plus target sites exceeds 256-site matrix budget")
        c=covariance(model,x.tolist());scale=m["partial_sill"]+m["nugget"]
        cross=covariance(model,q.tolist(),x.tolist())
        alpha,condition=_solve(c/scale,(y-mean)/scale);condition_numbers.append(condition)
        solved,condition=_solve(c/scale,cross.T/scale);condition_numbers.append(condition)
        means=means+cross@alpha;conditional=conditional-cross@solved
        for i,point in enumerate(q):
            for j,observation in enumerate(x):
                if np.array_equal(point,observation):fixed[i]=float(y[j]);means[i]=y[j];conditional[i,:]=0.;conditional[:,i]=0.
    free=[i for i in range(len(q)) if i not in fixed]
    draws=np.tile(means,(realizations,1));conditional=(conditional+conditional.T)/2
    if free:
        for i in free:
            variance=float(conditional[i,i])
            if variance<=0 or math.ulp(float(means[i]))>math.sqrt(variance)*1e-8:
                raise GeostatisticsError("conditional standard deviation is unresolved at the simulated mean (ULP >1e-8 std); rescale explicitly")
        c=conditional[np.ix_(free,free)];scale=m["partial_sill"]+m["nugget"]
        _,condition=_solve(c/scale,np.zeros(len(free)));condition_numbers.append(condition)
        try:factor=np.linalg.cholesky(c/scale)*math.sqrt(scale)
        except np.linalg.LinAlgError as e:raise GeostatisticsError(f"conditional covariance is not positive definite; no jitter added: {e}") from e
        rng=np.random.Generator(np.random.PCG64(seed));draws[:,free]+=rng.standard_normal((realizations,len(free)))@factor.T
    if not np.isfinite(draws).all() or np.any(np.diag(conditional)<0):raise GeostatisticsError("invalid Gaussian simulation output/covariance")
    columns=[_column("site_id","1","text")]+[_column(axis+"_m","m") for axis in ("x","y","z")[:m["dimension"]]]+[_column("conditional_mean",m["value_unit"]),_column("conditional_variance",f"({m['value_unit']})^2")]+[_column(f"r{i:04d}",m["value_unit"]) for i in range(realizations)]
    rows=[[f"s{i}",*q[i].tolist(),float(means[i]),float(conditional[i,i]),*draws[:,i].tolist()] for i in range(len(q))]
    return _result("gaussian_field",dict(owner_metadata=metadata,coordinate_unit="m",vertical_axis="positive_up" if m["dimension"]==3 else "not_applicable",covariance_model=m,mean=mean,seed=seed,realizations=realizations,conditioning_dataset=source,conditional_covariance=conditional.tolist(),condition_numbers=condition_numbers,condition_limit=CONDITION_LIMIT,nugget_semantics="microscale process variance, not measurement error",covariance_parameters_unit=f"({m['value_unit']})^2",support="explicit owner-declared simulation sites; conditional predictions may extrapolate; no hull inferred",numpy_version=np.__version__,generator="explicit numpy.Generator(PCG64); Cholesky, no hidden jitter or fitting"),columns,rows)


def latin_hypercube(marginals: list, *, samples: int, seed: int) -> GeostatisticsResult:
    """One independent random stratum per scalar marginal; no copula/correlation."""
    _integer(samples,1,4096,"samples");_integer(seed,0,2**63-1,"seed")
    if not isinstance(marginals,list) or not 1<=len(marginals)<=32 or samples*len(marginals)>MAX_DRAW_VALUES:raise GeostatisticsError("1..32 marginals and <=65536 sampled values required")
    rng=np.random.Generator(np.random.PCG64(seed));columns=[_column("sample_id","1","int")];values=[];strata=[];names=set();parsed=[]
    for marginal in marginals:
        _keys(marginal,{"name","unit","distribution","parameters"},"marginal")
        name=_text(marginal["name"],"marginal name",128);unit=_text(marginal["unit"],"marginal unit",128)
        if name in names or name=="sample_id":raise GeostatisticsError("unique marginal names required")
        names.add(name);kind=marginal["distribution"];p=marginal["parameters"]
        if kind in ("uniform","triangular"):
            _keys(p,{"minimum","maximum"}|({"mode"} if kind=="triangular" else set()),"marginal parameters")
            lo=_number(p["minimum"],"minimum");hi=_number(p["maximum"],"maximum")
            if lo>=hi or max(math.ulp(lo),math.ulp(hi))>(hi-lo)*1e-10:raise GeostatisticsError("marginal range must be positive and numerically resolved")
            mode=None if kind=="uniform" else _number(p["mode"],"mode")
            if mode is not None and not lo<=mode<=hi:raise GeostatisticsError("triangular mode outside bounds")
        elif kind=="normal":
            _keys(p,{"mean","standard_deviation"},"normal parameters");mu=_number(p["mean"],"mean");sigma=_number(p["standard_deviation"],"standard_deviation")
            if sigma<=0 or math.ulp(mu)>sigma*1e-10:raise GeostatisticsError("positive numerically resolved normal standard deviation required")
        else:raise GeostatisticsError("supported marginals: uniform, normal, triangular")
        order=rng.permutation(samples);u=(order+rng.random(samples))/samples
        u=np.maximum(np.nextafter(0.,1.),np.minimum(np.nextafter(1.,0.),u))
        if kind=="uniform":draw=lo+(hi-lo)*u
        elif kind=="triangular":draw=np.where(u<(mode-lo)/(hi-lo),lo+(hi-lo)*np.sqrt(u*((mode-lo)/(hi-lo))),hi-(hi-lo)*np.sqrt((1-u)*((hi-mode)/(hi-lo))))
        else:draw=np.asarray([mu+sigma*NormalDist().inv_cdf(float(probability)) for probability in u])
        if not np.isfinite(draw).all():raise GeostatisticsError("marginal transformation overflow")
        columns.append(_column(name,unit));values.append(draw);strata.append(order.tolist());parsed.append(marginal)
    rows=[[i,*[float(v[i]) for v in values]] for i in range(samples)]
    return _result("latin_hypercube",dict(seed=seed,samples=samples,marginals=parsed,strata_by_marginal=strata,dependence="independent randomized marginal permutations; no target correlation or conditioning",numpy_version=np.__version__,generator="explicit numpy.Generator(PCG64)"),columns,rows)


def save_result(result: GeostatisticsResult, path: str | Path) -> Path:
    d=result.to_dict();path=Path(path)
    if path.suffix.lower()==".json":return _write(path,_json_bytes(d))
    if path.suffix.lower()!=".csv":raise GeostatisticsError("result extension must be .json or .csv")
    meta={k:v for k,v in d.items() if k!="rows"};out=io.StringIO(newline="");out.write(CSV_PREFIX+_json_bytes(meta).decode().rstrip()+"\n")
    writer=csv.writer(out,lineterminator="\n");writer.writerow([c["name"] for c in d["columns"]])
    for row in d["rows"]:writer.writerow([json.dumps(v,ensure_ascii=False,allow_nan=False) for v in row])
    return _write(path,out.getvalue().encode())


def load_result(path: str | Path) -> GeostatisticsResult:
    path=Path(path);raw=_read(path)
    if path.suffix.lower()==".json":return GeostatisticsResult.from_dict(_json(raw))
    if path.suffix.lower()!=".csv":raise GeostatisticsError("result extension must be .json or .csv")
    try:
        first,rest=raw.decode().split("\n",1)
        if not first.startswith(CSV_PREFIX):raise GeostatisticsError("CSV versioned metadata line required")
        meta=_json(first[len(CSV_PREFIX):].encode());_keys(meta,{"schema","operation","metadata","columns"},"CSV metadata")
        reader=csv.reader(io.StringIO(rest,newline=""),strict=True)
        if next(reader)!=[c["name"] for c in meta["columns"]]:raise GeostatisticsError("CSV header/schema mismatch")
        rows=[]
        for row in reader:
            if len(rows)>=4096:raise GeostatisticsError("CSV row budget exceeded")
            rows.append([_json(v.encode()) for v in row])
        return GeostatisticsResult.from_dict({**meta,"rows":rows})
    except (UnicodeError,ValueError,KeyError,TypeError,StopIteration,csv.Error) as e:
        if isinstance(e,GeostatisticsError):raise
        raise GeostatisticsError(f"invalid geostatistics CSV: {e}") from e


def verify_result_roundtrip(result: GeostatisticsResult) -> dict:
    d=result.to_dict();hashes={}
    with tempfile.TemporaryDirectory(prefix="geostatistics-roundtrip-") as tmp:
        for extension in ("json","csv"):
            path=Path(tmp)/("result."+extension);save_result(result,path)
            if load_result(path).to_dict()!=d:raise GeostatisticsError("result JSON/CSV semantic mismatch")
            hashes[extension]=hashlib.sha256(_read(path)).hexdigest()
    return {"schema":"basinlens-geostatistics-roundtrip-v1","operation":d["operation"],"rows":len(d["rows"]),"json_csv_semantic_equal":True,"file_sha256":hashes,"original_gms_comparison":"NOT_OBSERVED"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("krige");p.add_argument("dataset");p.add_argument("model");p.add_argument("queries");p.add_argument("settings");p.add_argument("output")
    p=sub.add_parser("variogram");p.add_argument("dataset");p.add_argument("bins");p.add_argument("output")
    p=sub.add_parser("simulate");p.add_argument("model");p.add_argument("sites");p.add_argument("settings");p.add_argument("output");p.add_argument("--conditioning")
    p=sub.add_parser("lhs");p.add_argument("marginals");p.add_argument("settings");p.add_argument("output")
    p=sub.add_parser("roundtrip");p.add_argument("input");p.add_argument("output")
    args=parser.parse_args(argv)
    try:
        if args.command=="krige":result=krige(load_scatter(args.dataset),_json(_read(args.queries)),CovarianceModel.from_dict(_json(_read(args.model))),**_json(_read(args.settings)))
        elif args.command=="variogram":result=experimental_variogram(load_scatter(args.dataset),_json(_read(args.bins)))
        elif args.command=="simulate":result=gaussian_field(_json(_read(args.sites)),CovarianceModel.from_dict(_json(_read(args.model))),conditioning=load_scatter(args.conditioning) if args.conditioning else None,**_json(_read(args.settings)))
        elif args.command=="lhs":result=latin_hypercube(_json(_read(args.marginals)),**_json(_read(args.settings)))
        else:_write(args.output,_json_bytes(verify_result_roundtrip(load_result(args.input))));return 0
        save_result(result,args.output);return 0
    except (GeostatisticsError,ScatterError,TypeError) as e:parser.exit(2,f"geostatistics: {e}\n")


if __name__=="__main__":raise SystemExit(main())
