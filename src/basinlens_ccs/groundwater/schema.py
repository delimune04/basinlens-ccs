"""Explicit metre/day contract for small, fully confined groundwater cases.

This model describes a synthetic rectangular, all-active, orthogonal grid.  Head
and elevation share the caller's stated vertical datum. Wells use zero-based
(layer, row, column) indices; positive rates inject water, negative rates pump.
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class GroundwaterValidationError(ValueError):
    """An input violates the bounded groundwater case contract."""


MAX_CELLS = 100_000
MAX_SAVED_VALUES = 2_000_000
UNITS = {"length": "METERS", "time": "DAYS", "head": "m", "conductivity": "m/day",
         "well_rate": "m3/day", "recharge": "m/day", "specific_storage": "1/m"}


def _number(value: Any, key: str, *, minimum=None, positive=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GroundwaterValidationError(f"{key}: expected a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise GroundwaterValidationError(f"{key}: expected a finite number") from None
    if not math.isfinite(result):
        raise GroundwaterValidationError(f"{key}: expected a finite number")
    if positive and result <= 0:
        raise GroundwaterValidationError(f"{key}: must be > 0")
    if minimum is not None and result < minimum:
        raise GroundwaterValidationError(f"{key}: must be >= {minimum}")
    return result


def _integer(value: Any, key: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GroundwaterValidationError(f"{key}: expected integer in [{minimum}, {maximum}]")
    return value


def _object(value, key, allowed, required=()):
    if not isinstance(value, dict):
        raise GroundwaterValidationError(f"{key}: expected an object")
    extra = set(value) - set(allowed)
    missing = set(required) - set(value)
    if extra or missing:
        raise GroundwaterValidationError(f"{key}: unknown fields {sorted(extra)}, missing fields {sorted(missing)}")
    return value


def _text(value, key):
    if not isinstance(value, str) or not value.strip():
        raise GroundwaterValidationError(f"{key}: expected a nonempty string")
    if len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise GroundwaterValidationError(f"{key}: invalid or excessively long text")
    return value.strip()


def _layers(value, key, nlay, *, positive=False, minimum=None):
    values = value if isinstance(value, list) else [value] * nlay
    if len(values) != nlay:
        raise GroundwaterValidationError(f"{key}: expected a scalar or {nlay} layer values")
    return [_number(v, f"{key}[{i}]", minimum=minimum, positive=positive) for i, v in enumerate(values)]


@dataclass
class GroundwaterCase:
    """Validated JSON-compatible case; revalidated before every export/run."""

    case_id: str
    name: str
    grid: dict
    properties: dict
    boundaries: dict
    periods: list
    recharge_m_per_day: float = 0.0
    wells: list = field(default_factory=list)
    initial_head_m: float | None = None
    provenance: dict = field(default_factory=lambda: {
        "source": "user-defined assumptions", "crs": "local Cartesian metres",
        "vertical_datum": "local elevation datum", "assumptions": []})
    schema_version: int = 1
    units: dict = field(default_factory=lambda: dict(UNITS))

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise GroundwaterValidationError("schema_version: only integer version 1 is supported")
        if self.units != UNITS:
            raise GroundwaterValidationError(f"units: must equal {UNITS}; convert values explicitly before import")
        self.case_id = _text(self.case_id, "case_id")
        self.name = _text(self.name, "name")
        g = _object(self.grid, "grid", {"nlay", "nrow", "ncol", "delr_m", "delc_m", "top_m", "layer_bottoms_m"},
                    {"nlay", "nrow", "ncol", "delr_m", "delc_m", "top_m", "layer_bottoms_m"})
        nl = _integer(g["nlay"], "grid.nlay", 1, 50)
        nr = _integer(g["nrow"], "grid.nrow", 1, 500)
        nc = _integer(g["ncol"], "grid.ncol", 3, 500)
        cells = nl * nr * nc
        if cells > MAX_CELLS:
            raise GroundwaterValidationError(f"grid: {cells} cells exceeds {MAX_CELLS}")
        g["delr_m"] = _number(g["delr_m"], "grid.delr_m", positive=True)
        g["delc_m"] = _number(g["delc_m"], "grid.delc_m", positive=True)
        g["top_m"] = _number(g["top_m"], "grid.top_m")
        bottoms = g["layer_bottoms_m"]
        if not isinstance(bottoms, list) or len(bottoms) != nl:
            raise GroundwaterValidationError(f"grid.layer_bottoms_m: expected {nl} elevations")
        previous = g["top_m"]
        for i, value in enumerate(bottoms):
            value = _number(value, f"grid.layer_bottoms_m[{i}]")
            if value >= previous:
                raise GroundwaterValidationError("grid.layer_bottoms_m: elevations must strictly descend below top_m")
            bottoms[i] = value
            previous = value
        p = _object(self.properties, "properties", {"kx_m_per_day", "ky_m_per_day", "kz_m_per_day", "specific_storage_per_m"},
                    {"kx_m_per_day", "ky_m_per_day", "kz_m_per_day", "specific_storage_per_m"})
        for key in ("kx_m_per_day", "ky_m_per_day", "kz_m_per_day"):
            p[key] = _layers(p[key], "properties." + key, nl, positive=True)
        p["specific_storage_per_m"] = _layers(p["specific_storage_per_m"], "properties.specific_storage_per_m", nl, minimum=0)
        b = _object(self.boundaries, "boundaries", {"left_head_m", "right_head_m"}, {"left_head_m", "right_head_m"})
        for key in b:
            b[key] = _number(b[key], "boundaries." + key, minimum=g["top_m"])
        self.recharge_m_per_day = _number(self.recharge_m_per_day, "recharge_m_per_day", minimum=0)
        if self.initial_head_m is not None:
            self.initial_head_m = _number(self.initial_head_m, "initial_head_m", minimum=g["top_m"])
        self.wells = self._wells(self.wells, "wells", nl, nr, nc)
        if not isinstance(self.periods, list) or not self.periods or len(self.periods) > 100:
            raise GroundwaterValidationError("periods: expected 1 to 100 stress periods")
        steps = 0
        for i, period in enumerate(self.periods):
            key = f"periods[{i}]"
            _object(period, key, {"length_days", "steps", "transient", "wells"}, {"length_days", "steps", "transient"})
            period["length_days"] = _number(period["length_days"], key + ".length_days", positive=True)
            steps += _integer(period["steps"], key + ".steps", 1, 1000)
            if type(period["transient"]) is not bool:
                raise GroundwaterValidationError(key + ".transient: expected boolean")
            if period["transient"] and not any(p["specific_storage_per_m"]):
                raise GroundwaterValidationError("properties.specific_storage_per_m: transient cases require positive storage in at least one layer")
            if "wells" in period:
                period["wells"] = self._wells(period["wells"], key + ".wells", nl, nr, nc)
        if steps > 1000 or steps * cells > MAX_SAVED_VALUES:
            raise GroundwaterValidationError(f"periods: at most 1000 steps and {MAX_SAVED_VALUES} saved cell-time values are supported")
        prov = _object(self.provenance, "provenance", {"source", "crs", "vertical_datum", "assumptions"},
                       {"source", "crs", "vertical_datum", "assumptions"})
        for key in ("source", "crs", "vertical_datum"):
            prov[key] = _text(prov[key], "provenance." + key)
        if not isinstance(prov["assumptions"], list):
            raise GroundwaterValidationError("provenance.assumptions: expected a list of strings")
        prov["assumptions"] = [_text(x, "provenance.assumptions") for x in prov["assumptions"]]

    @staticmethod
    def _wells(wells, key, nl, nr, nc):
        if not isinstance(wells, list) or len(wells) > 1000:
            raise GroundwaterValidationError(key + ": expected up to 1000 wells")
        names = set()
        cells = set()
        for i, well in enumerate(wells):
            k = f"{key}[{i}]"
            _object(well, k, {"name", "layer", "row", "column", "rate_m3_per_day"},
                    {"name", "layer", "row", "column", "rate_m3_per_day"})
            well["name"] = _text(well["name"], k + ".name")
            if well["name"] in names:
                raise GroundwaterValidationError(k + ".name: duplicate well name")
            names.add(well["name"])
            cell = tuple(_integer(well[f], k + "." + f, 0, size - 1)
                         for f, size in zip(("layer", "row", "column"), (nl, nr, nc)))
            if cell[-1] in (0, nc - 1):
                raise GroundwaterValidationError(k + ": wells cannot occupy constant-head boundary columns")
            if cell in cells:
                raise GroundwaterValidationError(k + ": multiple wells in one cell; combine rates explicitly")
            cells.add(cell)
            well["rate_m3_per_day"] = _number(well["rate_m3_per_day"], k + ".rate_m3_per_day")
        return wells

    @classmethod
    def from_dict(cls, data):
        allowed = set(cls.__dataclass_fields__)
        required = {"schema_version", "case_id", "name", "grid", "properties", "boundaries", "periods"}
        _object(data, "case", allowed, required)
        try:
            return cls(**copy.deepcopy(data))
        except TypeError as exc:
            raise GroundwaterValidationError(f"case: {exc}") from exc

    def to_dict(self):
        return copy.deepcopy({key: getattr(self, key) for key in self.__dataclass_fields__})


def load_case(path: str | Path) -> GroundwaterCase:
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise GroundwaterValidationError("case file: maximum size is 2 MB")
    def unique_pairs(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise GroundwaterValidationError(f"case JSON: duplicate key {k!r}")
            result[k] = v
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GroundwaterValidationError(f"case JSON: {exc}") from exc
    return GroundwaterCase.from_dict(data)


def demo_case() -> GroundwaterCase:
    return GroundwaterCase.from_dict({
        "schema_version": 1, "case_id": "synthetic-confined-3layer", "name": "Synthetic layered confined aquifer",
        "grid": {"nlay": 3, "nrow": 21, "ncol": 41, "delr_m": 25.0, "delc_m": 25.0,
                 "top_m": 0.0, "layer_bottoms_m": [-10.0, -25.0, -50.0]},
        "properties": {"kx_m_per_day": [10.0, 0.05, 5.0], "ky_m_per_day": [8.0, 0.05, 4.0],
                       "kz_m_per_day": [1.0, 0.005, 0.5], "specific_storage_per_m": [1e-5, 1e-5, 1e-5]},
        "boundaries": {"left_head_m": 12.0, "right_head_m": 10.0}, "recharge_m_per_day": 0.0001,
        "wells": [{"name": "water-injection", "layer": 2, "row": 10, "column": 20, "rate_m3_per_day": 100.0}],
        "periods": [{"length_days": 1.0, "steps": 1, "transient": False, "wells": []},
                    {"length_days": 30.0, "steps": 12, "transient": True}],
        "provenance": {"source": "BasinLens synthetic demonstration; no field observations", "crs": "local Cartesian metres",
                       "vertical_datum": "local aquifer top = 0 m; elevations increase upward",
                       "assumptions": ["Constant-density single-phase water; all cells confined and active",
                                       "No-flow north/south and base; left/right cell centres have fixed head",
                                       "Water injection is not CO2 injection; no multiphase transport or geomechanics"]}})
