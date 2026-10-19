"""Portable spatial-workflow projects with one authoritative canonical case asset.

The outer typed project is an exact derived projection, never a second editable
source of solver settings. Native GMS GPR writing and parity are not established.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from . import project_package as package
from .model_workflow import CASE_BYTES, WorkflowCase, preview_grid
from .schema import (DataAsset, FieldSupport, ModelSpec, ProjectProvenance,
                     ProjectValidationError, Quantity, RockProperty,
                     SpatialReference, StratigraphicUnit, StructuredGeometry,
                     SubsurfaceProject)

WORKFLOW_ASSET_ID = "workflow_model"
WORKFLOW_ASSET_PATH = "workflow/model.json"
_PROPERTIES = (
    ("hydraulic_conductivity_x", "kx_m_day", "m/day"),
    ("hydraulic_conductivity_y", "ky_m_day", "m/day"),
    ("hydraulic_conductivity_z", "kz_m_day", "m/day"),
    ("specific_storage", "ss_per_m", "1/m"),
    ("porosity", "porosity", "1"),
)


@dataclass(frozen=True)
class LoadedWorkflowProject:
    case: WorkflowCase
    project: SubsurfaceProject
    view_state: dict
    receipt: dict
    root: Path
    asset_root: Path


def _canonical_case(case):
    if not isinstance(case, WorkflowCase):
        raise ProjectValidationError("workflow project requires a typed WorkflowCase")
    # to_dict revalidates even directly constructed WorkflowCase instances.
    data = case.to_dict()
    payload = (json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2,
                          allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > CASE_BYTES:
        raise ProjectValidationError("canonical workflow case exceeds its byte budget")
    return data, payload


def _property(name, key, unit, cells, shape):
    values = tuple(float(cell[key]) for cell in cells)
    if all(value == values[0] for value in values):
        quantity, support = Quantity(values[0], unit), FieldSupport("global")
    else:
        per_layer = shape[1] * shape[2]
        layers = tuple(values[layer * per_layer] for layer in range(shape[0]))
        if all(value == layers[index // per_layer] for index, value in enumerate(values)):
            quantity = Quantity(layers, unit)
            support = FieldSupport("layer", tuple(range(shape[0])))
        else:
            quantity = Quantity(values, unit)
            support = FieldSupport("cell", tuple((cell["layer"], cell["row"], cell["column"])
                                                  for cell in cells))
    return RockProperty(name, quantity, support, source_asset_ids=(WORKFLOW_ASSET_ID,),
                        basis="assumed")


def _shared_project(case):
    """Derive every supported outer field; complete forcing remains in the asset."""
    data, payload = _canonical_case(case)
    source, grid = data["project"], data["grid"]
    cells = preview_grid(case)["cells"]
    properties = tuple(_property(name, key, unit, cells, case.shape)
                       for name, key, unit in _PROPERTIES)
    asset = DataAsset(WORKFLOW_ASSET_ID, WORKFLOW_ASSET_PATH,
                     hashlib.sha256(payload).hexdigest(), "application/json",
                     "Owner-supplied workflow data; redistribution permission not inferred",
                     "Canonical BasinLens model workflow input")
    return SubsurfaceProject(
        source["id"], source["name"], source["domain"],
        SpatialReference(source["crs"], source["vertical_datum"]),
        StructuredGeometry(case.shape[0], grid["nrow"], grid["ncol"], grid["dx_m"],
                           grid["dy_m"], grid["layer_surfaces_m"][0],
                           tuple(grid["layer_surfaces_m"][1:]),
                           origin_x_m=grid["x_origin_m"], origin_y_m=grid["y_origin_m"]),
        properties,
        ModelSpec("modflow6_spatial", "single_phase_confined_groundwater", "background_water",
                  {"workflow_asset_id": WORKFLOW_ASSET_ID}),
        ProjectProvenance("Canonical BasinLens spatial workflow; not a native GMS project",
                          tuple(source["provenance"])),
        assets=(asset,),
        stratigraphy=tuple(StratigraphicUnit(item["id"], item["name"],
                                            tuple(item["layer_indices"]), (WORKFLOW_ASSET_ID,))
                           for item in data["strata"]),
    )


def save_workflow_project(case, output, *, view_state=None):
    """Save a new .blproj containing exact canonical case bytes and derived metadata."""
    _, payload = _canonical_case(case)
    project = _shared_project(case)
    with tempfile.TemporaryDirectory(prefix="basinlens-workflow-assets-") as temporary:
        asset_root = Path(temporary)
        target = asset_root / WORKFLOW_ASSET_PATH
        target.parent.mkdir()
        target.write_bytes(payload)
        return package.save_project_package(project, output, asset_root=asset_root,
                                            view_state=view_state)


def _load_authoritative_case(loaded):
    expected_options = {"workflow_asset_id": WORKFLOW_ASSET_ID}
    if loaded.project.model.options != expected_options:
        raise ProjectValidationError("workflow project has an unsupported case-asset declaration")
    payload = package._read_file(loaded.asset_root / WORKFLOW_ASSET_PATH, CASE_BYTES)
    # The backend loader rejects duplicate keys, nonfinite values and invalid physics.
    from .model_workflow import load_workflow_case
    case = load_workflow_case(loaded.asset_root / WORKFLOW_ASSET_PATH)
    _, canonical = _canonical_case(case)
    if payload != canonical:
        raise ProjectValidationError("workflow asset must contain exact canonical case JSON")
    expected = _shared_project(case)
    if loaded.project.to_dict() != expected.to_dict():
        raise ProjectValidationError("outer project metadata contradicts its authoritative workflow asset")
    return case, payload


def open_workflow_project(path, output_dir):
    """Validate package, canonical case and exact shared projection before publication.

    A valid generic package with contradictory workflow metadata is refused. Its
    temporary restored directory is removed and the final destination stays absent.
    Source/destination parents share the package API's trusted-writer boundary.
    """
    output = package._fresh_output(output_dir)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".workflow-partial-",
                                    dir=output.parent))
    try:
        loaded = package.open_project_package(path, staging / "project")
        case, payload = _load_authoritative_case(loaded)
        source_after = package._read_file(path, package.MAX_ARCHIVE_BYTES)
        source_after_sha256 = hashlib.sha256(source_after).hexdigest()
        if source_after_sha256 != loaded.receipt["source_archive_sha256_before"]:
            raise ProjectValidationError("workflow source archive changed before final publication")
        receipt = {**loaded.receipt,
                   "source_archive_sha256_after": source_after_sha256,
                   "workflow_schema": "basinlens-model-workflow-v1",
                   "workflow_case_sha256": hashlib.sha256(payload).hexdigest(),
                   "workflow_case_authority": "registered canonical workflow/model.json",
                   "workflow_shared_project_consistent": True,
                   "boundary_periods_preserved": True,
                   "solver_executed": False, "native_gpr_write_implemented": False,
                   "gms_parity_established": False}
        package._promote_directory(loaded.root, output)
        return LoadedWorkflowProject(case, loaded.project, dict(loaded.view_state), receipt,
                                     output, output / "assets")
    finally:
        shutil.rmtree(staging)


def verify_workflow_project_roundtrip(path):
    """Actually open, save from the authoritative case, reopen and compare bytes."""
    source = package._path_no_links(path)
    before = package._read_file(source, package.MAX_ARCHIVE_BYTES)
    with tempfile.TemporaryDirectory(prefix="basinlens-workflow-roundtrip-") as temporary:
        root = Path(temporary)
        first = open_workflow_project(source, root / "first")
        repacked = save_workflow_project(first.case, root / "repacked.blproj",
                                        view_state=first.view_state)
        second = open_workflow_project(repacked, root / "second")
        first_payload = package._read_file(first.asset_root / WORKFLOW_ASSET_PATH, CASE_BYTES)
        second_payload = package._read_file(second.asset_root / WORKFLOW_ASSET_PATH, CASE_BYTES)
        if (first.case.to_dict() != second.case.to_dict()
                or first.project.to_dict() != second.project.to_dict()
                or first.view_state != second.view_state or first_payload != second_payload):
            raise ProjectValidationError("workflow project changed during actual save/reopen round trip")
        after = package._read_file(source, package.MAX_ARCHIVE_BYTES)
        if before != after:
            raise ProjectValidationError("original workflow package changed during round trip")
        rewritten = package._read_file(repacked, package.MAX_ARCHIVE_BYTES)
        return {"format": package.FORMAT, "bundle_version": package.BUNDLE_VERSION,
                "operation": "workflow_open_save_reopen_compare", "roundtrip_verified": True,
                "workflow_case_equal": True, "project_semantics_equal": True,
                "view_state_equal": True, "asset_bytes_equal": True,
                "source_unchanged": True, "archive_bytes_equal": before == rewritten,
                "source_archive_sha256_before": hashlib.sha256(before).hexdigest(),
                "source_archive_sha256_after": hashlib.sha256(after).hexdigest(),
                "repacked_archive_sha256": hashlib.sha256(rewritten).hexdigest(),
                "workflow_case_sha256": hashlib.sha256(first_payload).hexdigest(),
                "boundary_periods_preserved": True, "solver_executed": False,
                "gms_project_roundtrip": False, "gms_parity_established": False}
