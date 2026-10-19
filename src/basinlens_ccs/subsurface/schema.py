"""Versioned project/evidence contract, independent of any numerical engine.

All quantities carry explicit units. No implicit unit, CRS or datum conversion
is performed. Reference meshes and observations are recorded, not assimilated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

CANONICAL_AXES = "x increases with column; y increases with row; z increases upward"


class ProjectValidationError(ValueError):
    """Project metadata, units, spatial support or an asset is inconsistent."""


def _object(value: Any, name: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or set(value) - required - optional or required - set(value):
        raise ProjectValidationError(f"{name}: expected fields {sorted(required)}; optional {sorted(optional)}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProjectValidationError(f"{name}: expected nonempty trimmed text")
    if len(value) > 4000 or any(ord(c) < 32 for c in value):
        raise ProjectValidationError(f"{name}: invalid text")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectValidationError(f"{name}: expected finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ProjectValidationError(f"{name}: expected finite number") from None
    if not math.isfinite(result):
        raise ProjectValidationError(f"{name}: expected finite number")
    return result


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = 100_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProjectValidationError(f"{name}: expected integer in [{minimum}, {maximum}]")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 1000:
        raise ProjectValidationError(f"{name}: expected at most 1000 strings")
    return tuple(_text(item, name) for item in value)


def _relative_path(value: str) -> str:
    _text(value, "asset.relative_path")
    if ("\\" in value or ":" in value or value.startswith("/")
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ProjectValidationError("asset.relative_path: expected safe project-relative POSIX path")
    return value


@dataclass(frozen=True)
class Quantity:
    value: float | tuple[float, ...]
    unit: str

    def __post_init__(self):
        _text(self.unit, "quantity.unit")
        if isinstance(self.value, (list, tuple)):
            if not self.value or len(self.value) > 100_000:
                raise ProjectValidationError("quantity.value: expected 1 to 100000 values")
            object.__setattr__(self, "value", tuple(_number(v, "quantity.value") for v in self.value))
        else:
            object.__setattr__(self, "value", _number(self.value, "quantity.value"))

    @classmethod
    def from_dict(cls, value):
        return cls(**_object(value, "quantity", {"value", "unit"}))


@dataclass(frozen=True)
class SpatialReference:
    crs: str
    vertical_datum: str
    length_unit: str = "m"
    time_unit: str = "day"
    local_axes: str = CANONICAL_AXES

    def __post_init__(self):
        for name in ("crs", "vertical_datum", "local_axes"):
            _text(getattr(self, name), "spatial_reference." + name)
        if self.length_unit != "m" or self.time_unit != "day":
            raise ProjectValidationError("spatial_reference: this version requires m and day; convert explicitly")


@dataclass(frozen=True)
class StructuredGeometry:
    nlay: int
    nrow: int
    ncol: int
    delr_m: float
    delc_m: float
    top_m: float
    layer_bottoms_m: tuple[float, ...]
    kind: str = "structured"
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0

    def __post_init__(self):
        if self.kind != "structured":
            raise ProjectValidationError("geometry.kind: only structured geometry is implemented")
        for name, maximum in (("nlay", 50), ("nrow", 500), ("ncol", 500)):
            _integer(getattr(self, name), "geometry." + name, 1, maximum)
        if self.nlay * self.nrow * self.ncol > 100_000:
            raise ProjectValidationError("geometry: maximum 100000 cells")
        for name in ("delr_m", "delc_m", "top_m", "origin_x_m", "origin_y_m"):
            object.__setattr__(self, name, _number(getattr(self, name), "geometry." + name))
        if self.delr_m <= 0 or self.delc_m <= 0:
            raise ProjectValidationError("geometry: cell widths must be positive")
        if not isinstance(self.layer_bottoms_m, (list, tuple)) or len(self.layer_bottoms_m) != self.nlay:
            raise ProjectValidationError("geometry.layer_bottoms_m: expected nlay elevations")
        bottoms = tuple(_number(v, "geometry.layer_bottoms_m") for v in self.layer_bottoms_m)
        if any(b >= a for a, b in zip((self.top_m, *bottoms[:-1]), bottoms)):
            raise ProjectValidationError("geometry: bottom elevations must strictly descend below top")
        object.__setattr__(self, "layer_bottoms_m", bottoms)


@dataclass(frozen=True)
class FieldSupport:
    kind: str
    indices: tuple = ()

    def __post_init__(self):
        if self.kind not in ("global", "layer", "cell"):
            raise ProjectValidationError("support.kind: expected global, layer or cell")
        if not isinstance(self.indices, (list, tuple)):
            raise ProjectValidationError("support.indices: expected list")
        if self.kind == "global":
            if self.indices:
                raise ProjectValidationError("global support cannot specify indices")
            canonical = ()
        elif self.kind == "layer":
            canonical = tuple(_integer(v, "support.layer", maximum=49) for v in self.indices)
        else:
            canonical = []
            for cell in self.indices:
                if not isinstance(cell, (list, tuple)) or len(cell) != 3:
                    raise ProjectValidationError("support.cell: expected [layer,row,column]")
                canonical.append(tuple(_integer(v, "support.cell") for v in cell))
            canonical = tuple(canonical)
        if self.kind != "global" and (not canonical or len(canonical) > 100_000 or len(set(canonical)) != len(canonical)):
            raise ProjectValidationError("support.indices: expected nonempty, unique bounded indices")
        object.__setattr__(self, "indices", canonical)


PROPERTY_UNITS = {
    "hydraulic_conductivity_x": "m/day", "hydraulic_conductivity_y": "m/day",
    "hydraulic_conductivity_z": "m/day", "specific_storage": "1/m",
    "permeability_x": "m2", "permeability_y": "m2", "permeability_z": "m2",
    "porosity": "1", "bulk_density": "kg/m3", "compressibility": "1/Pa",
    "acoustic_velocity": "m/s",
}


@dataclass(frozen=True)
class RockProperty:
    name: str
    quantity: Quantity
    support: FieldSupport
    source_asset_ids: tuple[str, ...] = ()
    basis: str = "assumed"

    def __post_init__(self):
        if not isinstance(self.quantity, Quantity) or not isinstance(self.support, FieldSupport):
            raise ProjectValidationError("rock_property: expected typed Quantity and FieldSupport")
        _text(self.name, "rock_property.name")
        if self.name not in PROPERTY_UNITS or self.quantity.unit != PROPERTY_UNITS[self.name]:
            raise ProjectValidationError(f"rock_property: unsupported name/unit pair {self.name!r}/{self.quantity.unit!r}")
        if self.basis not in ("assumed", "measured", "interpreted", "synthetic"):
            raise ProjectValidationError("rock_property.basis: expected assumed, measured, interpreted or synthetic")
        object.__setattr__(self, "source_asset_ids", _strings(self.source_asset_ids, "rock_property.source_asset_ids"))
        values = self.quantity.value if isinstance(self.quantity.value, tuple) else (self.quantity.value,)
        if self.support.kind == "global" and isinstance(self.quantity.value, tuple):
            raise ProjectValidationError("global property support requires scalar quantity")
        if self.support.kind != "global" and (not isinstance(self.quantity.value, tuple) or len(values) != len(self.support.indices)):
            raise ProjectValidationError("property values must match explicitly ordered support indices")
        if any(v < 0 for v in values):
            raise ProjectValidationError("rock_property: negative values are unsupported")
        if self.name not in ("specific_storage", "porosity", "compressibility") and any(v <= 0 for v in values):
            raise ProjectValidationError("rock_property: this property must be positive")
        if self.name == "porosity" and any(v > 1 for v in values):
            raise ProjectValidationError("porosity must be a fraction in [0,1]")
        if self.basis == "measured" and not self.source_asset_ids:
            raise ProjectValidationError("measured rock properties require a source asset")


@dataclass(frozen=True)
class DataAsset:
    asset_id: str
    relative_path: str
    sha256: str
    media_type: str
    license: str
    source: str

    def __post_init__(self):
        for name in ("asset_id", "media_type", "license", "source"):
            _text(getattr(self, name), "asset." + name)
        _relative_path(self.relative_path)
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ProjectValidationError("asset.sha256: expected lowercase SHA-256 digest")


@dataclass(frozen=True)
class StratigraphicUnit:
    unit_id: str
    name: str
    layer_indices: tuple[int, ...]
    source_asset_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.unit_id, "stratigraphy.unit_id")
        _text(self.name, "stratigraphy.name")
        support = FieldSupport("layer", self.layer_indices)
        object.__setattr__(self, "layer_indices", support.indices)
        object.__setattr__(self, "source_asset_ids", _strings(self.source_asset_ids, "stratigraphy.source_asset_ids"))


@dataclass(frozen=True)
class Well:
    name: str
    cell: tuple[int, int, int]
    fluid: str
    rate: Quantity

    def __post_init__(self):
        _text(self.name, "well.name")
        if not isinstance(self.rate, Quantity):
            raise ProjectValidationError("well.rate: expected typed Quantity")
        if self.fluid not in ("water", "co2", "oil"):
            raise ProjectValidationError("well.fluid: expected water, co2 or oil")
        cell = FieldSupport("cell", (self.cell,)).indices[0]
        object.__setattr__(self, "cell", cell)
        if self.rate.unit != "m3/day" or isinstance(self.rate.value, tuple):
            raise ProjectValidationError("well.rate: expected scalar m3/day; density/reference state must be specified by a future fluid engine")


@dataclass(frozen=True)
class Observation:
    observation_id: str
    kind: str
    quantity: Quantity
    support: FieldSupport
    time: Quantity
    basis: str
    source_asset_ids: tuple[str, ...]

    def __post_init__(self):
        _text(self.observation_id, "observation.observation_id")
        _text(self.kind, "observation.kind")
        if not isinstance(self.quantity, Quantity) or not isinstance(self.time, Quantity) or not isinstance(self.support, FieldSupport):
            raise ProjectValidationError("observation: expected typed Quantity and FieldSupport")
        units = {"head": "m", "pressure": "Pa", "saturation": "1", "seismic_amplitude": "arbitrary"}
        if self.kind not in units or self.quantity.unit != units[self.kind]:
            raise ProjectValidationError("observation: invalid kind/unit pair")
        if self.time.unit != "day" or isinstance(self.time.value, tuple) or self.time.value < 0:
            raise ProjectValidationError("observation.time: expected nonnegative scalar day")
        if self.basis not in ("measurement", "synthetic", "interpretation"):
            raise ProjectValidationError("observation.basis: expected measurement, synthetic or interpretation")
        object.__setattr__(self, "source_asset_ids", _strings(self.source_asset_ids, "observation.source_asset_ids"))
        if self.basis != "synthetic" and not self.source_asset_ids:
            raise ProjectValidationError("nonsynthetic observations require source assets")
        values = self.quantity.value if isinstance(self.quantity.value, tuple) else (self.quantity.value,)
        if self.support.kind == "global" and isinstance(self.quantity.value, tuple):
            raise ProjectValidationError("global observation requires scalar quantity")
        if self.support.kind != "global" and (not isinstance(self.quantity.value, tuple) or len(values) != len(self.support.indices)):
            raise ProjectValidationError("observation values must match support indices")
        if self.kind == "saturation" and any(not 0 <= v <= 1 for v in values):
            raise ProjectValidationError("saturation observations require fractions in [0,1]")


@dataclass(frozen=True)
class ModelSpec:
    engine_id: str
    physics: str
    role: str
    options: dict = field(default_factory=dict)

    def __post_init__(self):
        for name in ("engine_id", "physics", "role"):
            _text(getattr(self, name), "model." + name)
        if not isinstance(self.options, dict):
            raise ProjectValidationError("model.options: expected object")
        # Reject NaN and non-JSON objects even when constructed directly.
        try:
            json.dumps(self.options, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ProjectValidationError("model.options: expected finite JSON data") from exc


@dataclass(frozen=True)
class ProjectProvenance:
    source: str
    assumptions: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.source, "provenance.source")
        object.__setattr__(self, "assumptions", _strings(self.assumptions, "provenance.assumptions"))


@dataclass(frozen=True)
class SubsurfaceProject:
    project_id: str
    name: str
    domain: str
    spatial_reference: SpatialReference
    geometry: StructuredGeometry
    rock_properties: tuple[RockProperty, ...]
    model: ModelSpec
    provenance: ProjectProvenance
    assets: tuple[DataAsset, ...] = ()
    stratigraphy: tuple[StratigraphicUnit, ...] = ()
    wells: tuple[Well, ...] = ()
    observations: tuple[Observation, ...] = ()
    reference_mesh_asset_ids: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ProjectValidationError("schema_version: only integer version 1 is supported")
        _text(self.project_id, "project_id")
        _text(self.name, "name")
        if self.domain not in ("groundwater", "ccs", "oil_exploration"):
            raise ProjectValidationError("domain: expected groundwater, ccs or oil_exploration")
        for name, expected in (("spatial_reference", SpatialReference), ("geometry", StructuredGeometry), ("model", ModelSpec), ("provenance", ProjectProvenance)):
            if not isinstance(getattr(self, name), expected):
                raise ProjectValidationError(f"{name}: expected {expected.__name__}")
        typed = {"rock_properties": RockProperty, "assets": DataAsset, "stratigraphy": StratigraphicUnit, "wells": Well, "observations": Observation}
        for name, expected in typed.items():
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or len(values) > 1000 or any(not isinstance(v, expected) for v in values):
                raise ProjectValidationError(f"{name}: expected at most 1000 {expected.__name__} records")
            object.__setattr__(self, name, tuple(values))
        for values, key in ((self.rock_properties, "name"), (self.assets, "asset_id"), (self.stratigraphy, "unit_id"), (self.wells, "name"), (self.observations, "observation_id")):
            identifiers = [getattr(v, key) for v in values]
            if len(set(identifiers)) != len(identifiers):
                raise ProjectValidationError(f"duplicate {key}")
        assets = {asset.asset_id for asset in self.assets}
        object.__setattr__(self, "reference_mesh_asset_ids", _strings(self.reference_mesh_asset_ids, "reference_mesh_asset_ids"))
        references = set(self.reference_mesh_asset_ids)
        for record in (*self.rock_properties, *self.stratigraphy, *self.observations):
            references.update(record.source_asset_ids)
        if references - assets:
            raise ProjectValidationError(f"unregistered asset references: {sorted(references - assets)}")
        for record in (*self.rock_properties, *self.observations):
            self._check_support(record.support)
        for unit in self.stratigraphy:
            self._check_support(FieldSupport("layer", unit.layer_indices))
        for well in self.wells:
            self._check_support(FieldSupport("cell", (well.cell,)))

    def _check_support(self, support):
        g = self.geometry
        if support.kind == "layer" and any(v >= g.nlay for v in support.indices):
            raise ProjectValidationError("layer support outside geometry")
        if support.kind == "cell" and any(any(v >= size for v, size in zip(cell, (g.nlay, g.nrow, g.ncol))) for cell in support.indices):
            raise ProjectValidationError("cell support outside geometry")

    def to_dict(self) -> dict:
        # Roundtrip gives plain JSON lists and copies mutable options.
        return json.loads(json.dumps(asdict(self), allow_nan=False))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> "SubsurfaceProject":
        required = {"schema_version", "project_id", "name", "domain", "spatial_reference", "geometry", "rock_properties", "model", "provenance"}
        optional = {"assets", "stratigraphy", "wells", "observations", "reference_mesh_asset_ids"}
        data = dict(_object(data, "project", required, optional))
        parsers = {
            "spatial_reference": (SpatialReference, {"crs", "vertical_datum", "length_unit", "time_unit", "local_axes"}),
            "geometry": (StructuredGeometry, {"kind", "nlay", "nrow", "ncol", "delr_m", "delc_m", "top_m", "layer_bottoms_m", "origin_x_m", "origin_y_m"}),
            "model": (ModelSpec, {"engine_id", "physics", "role", "options"}),
            "provenance": (ProjectProvenance, {"source", "assumptions"}),
        }
        for name, (constructor, fields) in parsers.items():
            data[name] = constructor(**_object(data[name], name, fields))
        collection_fields = {
            "assets": (DataAsset, {"asset_id", "relative_path", "sha256", "media_type", "license", "source"}),
            "stratigraphy": (StratigraphicUnit, {"unit_id", "name", "layer_indices", "source_asset_ids"}),
            "rock_properties": (RockProperty, {"name", "quantity", "support", "source_asset_ids", "basis"}),
            "wells": (Well, {"name", "cell", "fluid", "rate"}),
            "observations": (Observation, {"observation_id", "kind", "quantity", "support", "time", "basis", "source_asset_ids"}),
        }
        for name, (constructor, fields) in collection_fields.items():
            raw_records = data.get(name, [])
            if not isinstance(raw_records, list) or len(raw_records) > 1000:
                raise ProjectValidationError(f"{name}: expected bounded list")
            records = []
            for raw in raw_records:
                record = dict(_object(raw, name, fields))
                for key in ("quantity", "rate", "time"):
                    if key in record:
                        record[key] = Quantity.from_dict(record[key])
                if "support" in record:
                    record["support"] = FieldSupport(**_object(record["support"], "support", {"kind", "indices"}))
                records.append(constructor(**record))
            data[name] = tuple(records)
        return cls(**data)


def verify_assets(project: SubsurfaceProject, asset_root: str | Path) -> dict[str, str]:
    """Check local bytes without opening native formats or following remote URLs."""
    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir():
        raise ProjectValidationError("asset_root must be a directory")
    verified = {}
    for asset in project.assets:
        path = root.joinpath(*asset.relative_path.split("/"))
        # Refuse all symlinks, including links into the root: asset location stays explicit.
        current = root
        for part in asset.relative_path.split("/"):
            current = current / part
            if current.is_symlink():
                raise ProjectValidationError(f"asset symbolic links are refused: {asset.asset_id}")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ProjectValidationError(f"asset unavailable: {asset.asset_id}") from exc
        if root not in resolved.parents or not resolved.is_file():
            raise ProjectValidationError(f"asset outside project or not a regular file: {asset.asset_id}")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != asset.sha256:
            raise ProjectValidationError(f"asset checksum mismatch: {asset.asset_id}")
        verified[asset.asset_id] = asset.sha256
    return verified


def save_project(project: SubsurfaceProject, path: str | Path) -> Path:
    project = SubsurfaceProject.from_dict(project.to_dict())
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ProjectValidationError("project files must use .json; native formats are not imported")
    payload = project.to_json()
    if len(payload.encode("utf-8")) > 2_000_000:
        raise ProjectValidationError("project JSON must be no larger than 2 MB")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return path


def load_project(path: str | Path, *, check_assets: bool = True) -> SubsurfaceProject:
    path = Path(path)
    if path.suffix.lower() != ".json" or path.stat().st_size > 2_000_000:
        raise ProjectValidationError("expected a project .json file no larger than 2 MB")
    def unique_pairs(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ProjectValidationError(f"duplicate JSON key {key!r}")
            data[key] = value
        return data
    try:
        project = SubsurfaceProject.from_dict(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProjectValidationError):
            raise
        raise ProjectValidationError(f"cannot parse project JSON: {exc}") from exc
    if check_assets:
        verify_assets(project, path.parent)
    return project
