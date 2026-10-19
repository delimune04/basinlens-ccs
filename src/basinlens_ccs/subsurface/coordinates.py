"""Explicit local point mapping for canonical project rows and native MF6 rows.

Project row indices increase with project y. MF6's unrotated local DIS y
decreases with row. This local reflection/translation does not reproject a CRS.
"""
from __future__ import annotations

import math
import numpy as np

from .schema import CANONICAL_AXES, ProjectValidationError, SubsurfaceProject


def coordinate_contract(project: SubsurfaceProject) -> dict:
    if not isinstance(project, SubsurfaceProject):
        raise ProjectValidationError("expected a typed subsurface project")
    if project.spatial_reference.local_axes != CANONICAL_AXES:
        raise ProjectValidationError("local coordinate mapping requires the canonical project axes")
    g = project.geometry
    width, height = g.ncol * g.delr_m, g.nrow * g.delc_m
    if not all(math.isfinite(v) for v in (width, height, g.origin_x_m + width, g.origin_y_m + height)):
        raise ProjectValidationError("project horizontal extents overflow finite coordinates")
    return {
        "project_grid_origin_m": {"x": g.origin_x_m, "y": g.origin_y_m},
        "project_grid_origin_definition": "outer edge before column 0 and row 0 in canonical project coordinates",
        "native_grid_origin_m": {"x": 0.0, "y": 0.0},
        "native_grid_height_m": height,
        "coordinate_mapping": "project x = origin_x_m + native x; project y = origin_y_m + nrow * delc_m - native y; elevations unchanged",
        "local_coordinate_transform": "x translation; y reflection followed by translation; cell indices unchanged",
        "coordinate_scope": "unrotated local MF6 DIS coordinates; no CRS, datum or unit transformation",
    }


def native_to_project_xy(project: SubsurfaceProject, x, y) -> tuple[np.ndarray, np.ndarray]:
    """Map equal-shaped finite local points in the exported unrotated DIS grid."""
    contract = coordinate_contract(project)
    raw_x, raw_y = np.asarray(x), np.asarray(y)
    if raw_x.dtype.kind not in "iuf" or raw_y.dtype.kind not in "iuf" or raw_x.shape != raw_y.shape:
        raise ProjectValidationError("native x/y must be equal-shaped numeric coordinates")
    x, y = np.asarray(raw_x, dtype=float), np.asarray(raw_y, dtype=float)
    g = project.geometry
    width, height = g.ncol * g.delr_m, contract["native_grid_height_m"]
    if (not np.isfinite(x).all() or not np.isfinite(y).all()
            or np.any(x < 0) or np.any(x > width) or np.any(y < 0) or np.any(y > height)):
        raise ProjectValidationError("native coordinates must be finite and within the local grid extent")
    return g.origin_x_m + x, g.origin_y_m + (height - y)


def project_cell_centres_xy(project: SubsurfaceProject) -> tuple[np.ndarray, np.ndarray]:
    """Return row/column centre coordinates in the declared project axes."""
    coordinate_contract(project)
    g = project.geometry
    return np.meshgrid(g.origin_x_m + (np.arange(g.ncol) + 0.5) * g.delr_m,
                       g.origin_y_m + (np.arange(g.nrow) + 0.5) * g.delc_m)
