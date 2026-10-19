"""Explicit project/evidence metadata and fail-closed subsurface engine registry."""
from .schema import (DataAsset, FieldSupport, ModelSpec, Observation, ProjectProvenance,
                     ProjectValidationError, Quantity, RockProperty, SpatialReference,
                     StratigraphicUnit, StructuredGeometry, SubsurfaceProject,
                     Well, load_project, save_project, verify_assets)
from .registry import (EngineAdapter, EngineAvailability, EngineDescriptor, EngineRegistry,
                       EngineUnavailableError, Modflow6Adapter, SubsurfaceRunResult,
                       UnsupportedPhysicsError, default_registry, project_from_groundwater,
                       verify_project_bundle)

__all__ = ["DataAsset", "FieldSupport", "ModelSpec", "Observation", "ProjectProvenance",
    "ProjectValidationError", "Quantity", "RockProperty", "SpatialReference", "StratigraphicUnit",
    "StructuredGeometry", "SubsurfaceProject", "Well", "load_project", "save_project", "verify_assets",
    "EngineAdapter", "EngineAvailability", "EngineDescriptor", "EngineRegistry", "EngineUnavailableError",
    "Modflow6Adapter", "SubsurfaceRunResult", "UnsupportedPhysicsError", "default_registry", "project_from_groundwater", "verify_project_bundle"]
