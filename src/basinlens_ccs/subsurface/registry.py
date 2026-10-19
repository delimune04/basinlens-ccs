"""Capability-gated adapters; unavailable engines never return synthetic success."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Protocol

from .schema import (CANONICAL_AXES, FieldSupport, ModelSpec, ProjectProvenance, ProjectValidationError,
                     Quantity, RockProperty, SpatialReference, StructuredGeometry,
                     SubsurfaceProject, Well, load_project, save_project, verify_assets,
                     _relative_path, _number, _object, _strings, _text)
from .coordinates import coordinate_contract

SOURCE_ASSET_POLICY = "Source assets are verified at asset_root and referenced by hash; raw files are not copied into the run bundle"


class UnsupportedPhysicsError(ProjectValidationError):
    """An engine cannot implement the requested physics, role or field support."""


class EngineUnavailableError(RuntimeError):
    """Implementation, dependency or executable is absent; no result was made."""


@dataclass(frozen=True)
class EngineDescriptor:
    engine_id: str
    name: str
    implementation_status: str
    physics: tuple[str, ...]
    roles: tuple[str, ...]
    domains: tuple[str, ...]
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self):
        for name in ("engine_id", "name", "implementation_status"):
            _text(getattr(self, name), "engine_descriptor." + name)
        if self.implementation_status not in ("IMPLEMENTED", "NOT_AVAILABLE"):
            raise ProjectValidationError("engine descriptor has unsupported implementation status")
        for name in ("physics", "roles", "domains", "capabilities", "limitations"):
            values = _strings(getattr(self, name), "engine_descriptor." + name)
            if not values or len(values) != len(set(values)):
                raise ProjectValidationError("engine descriptor fields must be nonempty unique strings")
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class EngineAvailability:
    export_available: bool
    run_available: bool
    reason: str

    def __post_init__(self):
        if type(self.export_available) is not bool or type(self.run_available) is not bool:
            raise ProjectValidationError("engine availability markers must be booleans")
        _text(self.reason, "engine_availability.reason")


@dataclass
class SubsurfaceRunResult:
    workspace: Path
    engine_id: str
    physics: str
    role: str
    summary: dict
    engine_result: Any


class EngineAdapter(Protocol):
    """Trusted Python extension point; no dynamic loading from project JSON."""
    def availability(self, exe_name: str) -> EngineAvailability: ...
    def prepare(self, project: SubsurfaceProject) -> tuple[Any, dict]: ...
    def export(self, prepared: Any, output: Path) -> Any: ...
    def run(self, prepared: Any, output: Path, exe_name: str) -> Any: ...


GROUNDWATER_FIELDS = {
    "hydraulic_conductivity_x": "kx_m_per_day", "hydraulic_conductivity_y": "ky_m_per_day",
    "hydraulic_conductivity_z": "kz_m_per_day", "specific_storage": "specific_storage_per_m",
}


class Modflow6Adapter:
    def availability(self, exe_name="mf6") -> EngineAvailability:
        if importlib.util.find_spec("flopy") is None:
            return EngineAvailability(False, False, "FloPy is missing; install the groundwater extra explicitly")
        program = shutil.which(str(exe_name))
        if program is None or not Path(program).is_file() or not os.access(program, os.X_OK):
            return EngineAvailability(True, False, f"MODFLOW 6 executable unavailable: {exe_name}")
        return EngineAvailability(True, True, f"FloPy and executable found: {program}; solver version is recorded when run")

    def prepare(self, project):
        from basinlens_ccs.groundwater import GroundwaterCase

        if project.spatial_reference.local_axes != CANONICAL_AXES:
            raise UnsupportedPhysicsError("MODFLOW adapter requires the declared canonical project axes; alternative project axis contracts are not implemented")
        if project.domain in ("ccs", "oil_exploration") and project.model.role != "background_water":
            raise UnsupportedPhysicsError("MODFLOW in CCS/oil projects requires role=background_water; water flow is not CO2 or petroleum physics")
        g = project.geometry
        properties = {}
        fields = {prop.name: prop for prop in project.rock_properties}
        for name, target in GROUNDWATER_FIELDS.items():
            if name not in fields:
                raise ProjectValidationError(f"MODFLOW requires rock property {name}")
            prop = fields[name]
            if prop.support.kind == "global":
                properties[target] = prop.quantity.value
            elif prop.support.kind == "layer" and set(prop.support.indices) == set(range(g.nlay)):
                ordered = dict(zip(prop.support.indices, prop.quantity.value))
                properties[target] = [ordered[i] for i in range(g.nlay)]
            else:
                raise UnsupportedPhysicsError(f"MODFLOW adapter requires global or complete layer support for {name}; cell fields are not converted implicitly")
        if any(well.fluid != "water" for well in project.wells):
            raise UnsupportedPhysicsError("MODFLOW adapter accepts only explicitly water wells")
        allowed = {"boundaries", "recharge_m_per_day", "periods", "initial_head_m"}
        if set(project.model.options) - allowed:
            raise UnsupportedPhysicsError(f"unhandled MODFLOW options: {sorted(set(project.model.options) - allowed)}")
        case_data = {
            "schema_version": 1, "case_id": project.project_id, "name": project.name,
            "grid": {key: value for key, value in asdict(g).items() if key not in ("kind", "origin_x_m", "origin_y_m")},
            "properties": properties,
            "wells": [{"name": w.name, "layer": w.cell[0], "row": w.cell[1], "column": w.cell[2], "rate_m3_per_day": w.rate.value} for w in project.wells],
            "provenance": {"source": project.provenance.source,
                "crs": project.spatial_reference.crs, "vertical_datum": project.spatial_reference.vertical_datum,
                "assumptions": list(project.provenance.assumptions)},
            **project.model.options,
        }
        case_data["grid"]["layer_bottoms_m"] = list(case_data["grid"]["layer_bottoms_m"])
        case = GroundwaterCase.from_dict(case_data)
        mapping = {
            "mapping_schema_version": 2, "engine_id": "modflow6", "physics": project.model.physics,
            "domain": project.domain, "role": project.model.role,
            "property_mapping": dict(GROUNDWATER_FIELDS), "unit_conversion": "none",
            "crs_conversion": "none", "datum_conversion": "none",
            "crs_validation": "project-owner declaration; no CRS database lookup or coordinate reprojection",
            "vertical_datum_validation": "project-owner declaration; no geodetic transformation",
            "local_axes": project.spatial_reference.local_axes,
            **coordinate_contract(project),
            "well_rate_convention": "positive water injection, negative water abstraction; m3/day",
            "period_well_overrides": "native groundwater options; all overridden rates are water m3/day",
            "unused_rock_properties": sorted(set(fields) - set(GROUNDWATER_FIELDS)),
            "observations_assimilated": False, "observation_count": len(project.observations),
            "reference_mesh_assets_used_as_geometry": False,
            "stratigraphy_role": "named metadata on structured layers; no automatic property inference",
            "groundwater_case_sha256": hashlib.sha256(json.dumps(case.to_dict(), sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest(),
            "limitations": ["Single-phase constant-density confined water only",
                "No CO2-brine plume, petroleum discovery, black-oil PVT, seismic inversion, geomechanics or observation assimilation"],
        }
        return case, mapping

    def export(self, prepared, output):
        from basinlens_ccs.groundwater import export_case
        return export_case(prepared, output)

    def run(self, prepared, output, exe_name):
        from basinlens_ccs.groundwater import run_case
        return run_case(prepared, output, exe_name=exe_name)


class EngineRegistry:
    def __init__(self):
        self._entries: dict[str, tuple[EngineDescriptor, EngineAdapter | None]] = {}

    def register(self, descriptor: EngineDescriptor, adapter: EngineAdapter | None = None) -> None:
        if descriptor.engine_id in self._entries:
            raise ValueError(f"engine already registered: {descriptor.engine_id}")
        if descriptor.implementation_status not in ("IMPLEMENTED", "NOT_AVAILABLE"):
            raise ValueError("implementation_status must be IMPLEMENTED or NOT_AVAILABLE")
        if (descriptor.implementation_status == "IMPLEMENTED") != (adapter is not None):
            raise ValueError("implemented descriptors require an adapter; unavailable descriptors cannot have one")
        self._entries[descriptor.engine_id] = descriptor, adapter

    def engines(self, *, exe_name="mf6") -> list[dict]:
        records = []
        for engine_id in sorted(self._entries):
            descriptor, adapter = self._entries[engine_id]
            availability = adapter.availability(exe_name) if adapter else EngineAvailability(False, False, "Adapter is not implemented or integrated")
            records.append({**asdict(descriptor), "availability": asdict(availability)})
        return records

    def validate(self, project: SubsurfaceProject) -> dict:
        project = SubsurfaceProject.from_dict(project.to_dict())
        descriptor, adapter = self._compatible(project)
        if adapter is None:
            raise EngineUnavailableError(f"{descriptor.engine_id}: NOT_AVAILABLE; no implemented adapter")
        _, mapping = adapter.prepare(project)
        return mapping

    def _compatible(self, project):
        if project.model.engine_id not in self._entries:
            raise UnsupportedPhysicsError(f"unknown engine: {project.model.engine_id}")
        descriptor, adapter = self._entries[project.model.engine_id]
        for value, supported, label in ((project.model.physics, descriptor.physics, "physics"),
                (project.model.role, descriptor.roles, "role"), (project.domain, descriptor.domains, "domain")):
            if value not in supported:
                raise UnsupportedPhysicsError(f"{descriptor.engine_id} does not support {label}={value!r}")
        return descriptor, adapter

    def export(self, project: SubsurfaceProject, output: str | Path, *, asset_root=None) -> SubsurfaceRunResult:
        return self._execute(project, output, execute=False, exe_name="mf6", asset_root=asset_root)

    def run(self, project: SubsurfaceProject, output: str | Path, *, exe_name="mf6", asset_root=None) -> SubsurfaceRunResult:
        return self._execute(project, output, execute=True, exe_name=exe_name, asset_root=asset_root)

    def _execute(self, project, output, *, execute, exe_name, asset_root):
        project = SubsurfaceProject.from_dict(project.to_dict())
        descriptor, adapter = self._compatible(project)
        if adapter is None:
            raise EngineUnavailableError(f"{descriptor.engine_id}: NOT_AVAILABLE; adapter not implemented")
        prepared, mapping = adapter.prepare(project)
        availability = adapter.availability(exe_name)
        if not (availability.run_available if execute else availability.export_available):
            raise EngineUnavailableError(availability.reason)
        if project.assets and asset_root is None:
            raise ProjectValidationError("asset_root is required to verify referenced project assets before export/run")
        verified = verify_assets(project, asset_root) if project.assets else {}
        root = Path(output).expanduser().absolute()
        if root.exists() or root.is_symlink():
            raise FileExistsError(f"output already exists: {root}")
        root.mkdir(parents=True, exist_ok=False)
        save_project(project, root / "project.json")
        _write_json(root / "mapping.json", mapping)
        status = "running" if execute else "exporting"
        try:
            engine_result = adapter.run(prepared, root / "engine", exe_name) if execute else adapter.export(prepared, root / "engine")
            status = "completed" if execute else "exported"
            summary = {
                "project_id": project.project_id, "domain": project.domain, "engine_id": descriptor.engine_id,
                "physics": project.model.physics, "role": project.model.role, "status": status,
                "assets_verified": verified, "observations_assimilated": False,
                "source_asset_policy": SOURCE_ASSET_POLICY,
                "engine_summary": engine_result.summary if execute else None,
                "limitations": list(descriptor.limitations),
            }
            _write_json(root / "project_summary.json", summary)
            _manifest(root, status, descriptor.engine_id)
            return SubsurfaceRunResult(root, descriptor.engine_id, project.model.physics, project.model.role, summary, engine_result)
        except Exception as exc:
            _write_json(root / "project_failure.json", {"status": "failed", "engine_id": descriptor.engine_id, "error_type": type(exc).__name__, "message": str(exc)})
            _manifest(root, "failed", descriptor.engine_id)
            raise


def _write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _manifest(root: Path, status: str, engine_id: str):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProjectValidationError("project bundle symbolic links are refused")
        if path.is_file() and path.name != "project_run_metadata.json":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files[path.relative_to(root).as_posix()] = {"sha256": digest, "size_bytes": path.stat().st_size}
    _write_json(root / "project_run_metadata.json", {"schema_version": 1, "status": status, "engine_id": engine_id, "files": files})


def _read_bundle_json(path: Path):
    if path.stat().st_size > 2_000_000:
        raise ProjectValidationError(f"bundle JSON exceeds 2 MB: {path.name}")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProjectValidationError(f"duplicate bundle JSON key {key!r}")
            result[key] = value
        return result
    def reject_constant(value):
        raise ProjectValidationError(f"nonfinite bundle JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
        parse_constant=reject_constant, parse_float=lambda value: _number(float(value), "bundle JSON number"))


def verify_project_bundle(root: str | Path, *, registry: EngineRegistry | None = None) -> dict:
    """Check the outer project bundle and its engine bundle, not source authenticity.

    Source assets remain external references. Recheck those separately with
    ``verify_assets(project, original_asset_root)`` when original bytes are present.
    """
    from basinlens_ccs.groundwater import verify_bundle
    if registry is not None and not isinstance(registry, EngineRegistry):
        raise ProjectValidationError("registry must be an EngineRegistry")
    root = Path(root).absolute()
    manifest_path = root / "project_run_metadata.json"
    if root.is_symlink() or manifest_path.is_symlink():
        raise ProjectValidationError("project bundle symbolic links are refused")
    try:
        metadata = _read_bundle_json(manifest_path)
        if (not isinstance(metadata, dict) or set(metadata) != {"schema_version", "status", "engine_id", "files"}
                or type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1
                or metadata["status"] not in ("completed", "exported")):
            raise ProjectValidationError("expected completed/exported project manifest version 1")
        _text(metadata["engine_id"], "project manifest engine_id")
        files = metadata["files"]
        required = {"project.json", "mapping.json", "project_summary.json"}
        if metadata["engine_id"] == "modflow6":
            required.update({"engine/case.json", "engine/run_metadata.json"})
        if not isinstance(files, dict) or required - set(files):
            raise ProjectValidationError("project manifest omits required files")
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ProjectValidationError("project bundle symbolic links are refused")
            if path.is_file() and path != manifest_path:
                actual.add(path.relative_to(root).as_posix())
        if actual != set(files):
            raise ProjectValidationError("project manifest and actual file set disagree")
        for relative, record in files.items():
            _relative_path(relative)
            if (not isinstance(record, dict) or set(record) != {"sha256", "size_bytes"}
                    or type(record["size_bytes"]) is not int or record["size_bytes"] < 0
                    or not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
                raise ProjectValidationError("malformed project file checksum record")
            path = root / relative
            if path.stat().st_size != record["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ProjectValidationError(f"project bundle integrity failed: {relative}")
        project = load_project(root / "project.json", check_assets=False)
        summary = _object(_read_bundle_json(root / "project_summary.json"), "project summary",
            {"project_id", "domain", "engine_id", "physics", "role", "status", "assets_verified",
             "observations_assimilated", "source_asset_policy", "engine_summary", "limitations"})
        for key, expected in (("project_id", project.project_id), ("engine_id", project.model.engine_id), ("physics", project.model.physics),
                ("role", project.model.role), ("domain", project.domain), ("status", metadata["status"])):
            if summary.get(key) != expected:
                raise ProjectValidationError(f"project summary disagrees with project: {key}")
        if metadata["engine_id"] != project.model.engine_id:
            raise ProjectValidationError("project manifest engine disagrees with project")
        if type(summary["observations_assimilated"]) is not bool or summary["observations_assimilated"] is not False:
            raise ProjectValidationError("project summary must declare observations_assimilated=false")
        expected_assets = {asset.asset_id: asset.sha256 for asset in project.assets}
        if not isinstance(summary["assets_verified"], dict) or summary["assets_verified"] != expected_assets:
            raise ProjectValidationError("project summary asset verification markers disagree with registered assets")
        if summary["source_asset_policy"] != SOURCE_ASSET_POLICY:
            raise ProjectValidationError("project summary must disclose external source asset policy")
        registry = default_registry() if registry is None else registry
        expected_mapping = registry.validate(project)
        mapping = _read_bundle_json(root / "mapping.json")
        # JSON booleans must not compare equal to integer schema versions/counts.
        if not isinstance(mapping, dict) or json.dumps(mapping, sort_keys=True, allow_nan=False) != json.dumps(expected_mapping, sort_keys=True, allow_nan=False):
            raise ProjectValidationError("project mapping disagrees with prepared project and adapter")
        descriptor, _ = registry._compatible(project)
        if not isinstance(summary["limitations"], list) or summary["limitations"] != list(descriptor.limitations):
            raise ProjectValidationError("project summary limitations disagree with engine descriptor")
        if metadata["status"] == "exported" and summary["engine_summary"] is not None:
            raise ProjectValidationError("export-only project cannot claim a numerical engine summary")
        if metadata["status"] == "completed" and not isinstance(summary["engine_summary"], dict):
            raise ProjectValidationError("completed project requires an engine summary object")
        if metadata["engine_id"] == "modflow6":
            inner = verify_bundle(root / "engine")
            if inner["status"] != metadata["status"]:
                raise ProjectValidationError("inner engine and outer project statuses disagree")
            native_case = _read_bundle_json(root / "engine/case.json")
            native_case_hash = hashlib.sha256(json.dumps(native_case, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
            if native_case_hash != expected_mapping["groundwater_case_sha256"]:
                raise ProjectValidationError("native groundwater case disagrees with project mapping")
            if metadata["status"] == "completed":
                native_summary = _read_bundle_json(root / "engine/summary.json")
                if json.dumps(summary["engine_summary"], sort_keys=True, allow_nan=False) != json.dumps(native_summary, sort_keys=True, allow_nan=False):
                    raise ProjectValidationError("outer engine summary disagrees with native result")
        return metadata
    except ProjectValidationError:
        raise
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, RecursionError) as exc:
        raise ProjectValidationError(f"cannot verify project bundle: {exc}") from exc


def default_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(EngineDescriptor("modflow6", "MODFLOW 6 confined groundwater", "IMPLEMENTED",
        ("single_phase_confined_groundwater",), ("groundwater_flow", "background_water"),
        ("groundwater", "ccs", "oil_exploration"),
        ("structured_grid", "layer_hydraulic_properties", "water_wells", "head", "water_budget"),
        ("Synthetic benchmark scope only; no site safety determination",
         "CCS/oil usage is background water only; no CO2 or petroleum discovery")), Modflow6Adapter())
    for engine_id, name, physics, roles, domains, capabilities in (
        ("opm_flow_co2", "OPM Flow CO2-brine adapter", "co2_brine_multiphase", ("co2_storage",), ("ccs",), ("co2_brine_flow",)),
        ("opm_flow_blackoil", "OPM Flow black-oil adapter", "black_oil", ("petroleum_reservoir",), ("oil_exploration",), ("black_oil_reservoir_flow",)),
        ("seismic_interpretation", "Seismic interpretation adapter", "seismic_interpretation", ("observation_interpretation",), ("ccs", "oil_exploration"), ("seismic_observation_interpretation",)),
    ):
        registry.register(EngineDescriptor(engine_id, name, "NOT_AVAILABLE", (physics,), roles, domains,
            capabilities, ("Descriptor of a future extension only; no adapter, numerical integration or validation exists",)))
    return registry


def project_from_groundwater(case, *, domain="groundwater") -> SubsurfaceProject:
    """Preserve values/indices/CRS/datum under the canonical project axis contract.

    Native MF6 local y is reflected when reporting canonical project point
    coordinates. This does not establish an external geodetic placement.
    """
    from basinlens_ccs.groundwater import GroundwaterCase
    case = GroundwaterCase.from_dict(case.to_dict())
    g = case.grid
    properties = tuple(RockProperty(name, Quantity(tuple(case.properties[target]), "1/m" if name == "specific_storage" else "m/day"),
        FieldSupport("layer", tuple(range(g["nlay"]))), basis="synthetic" if "synthetic" in case.provenance["source"].lower() else "assumed")
        for name, target in GROUNDWATER_FIELDS.items())
    options = {"boundaries": case.boundaries, "recharge_m_per_day": case.recharge_m_per_day,
        "periods": case.periods, "initial_head_m": case.initial_head_m}
    return SubsurfaceProject(case.case_id, case.name, domain,
        SpatialReference(case.provenance["crs"], case.provenance["vertical_datum"]),
        StructuredGeometry(**g), properties,
        ModelSpec("modflow6", "single_phase_confined_groundwater", "groundwater_flow" if domain == "groundwater" else "background_water", options),
        ProjectProvenance(case.provenance["source"], tuple(case.provenance["assumptions"])),
        wells=tuple(Well(w["name"], (w["layer"], w["row"], w["column"]), "water", Quantity(w["rate_m3_per_day"], "m3/day")) for w in case.wells))
