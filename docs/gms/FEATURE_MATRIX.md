# GMS workflow reconstruction: scope and evidence

This is an original BasinLens implementation of a **bounded groundwater modeling
workflow**, not Aquaveo GMS, a complete GMS clone, or a compatibility-certified
replacement. It is a separate optional module from conceptual CCS capacity.

## Feature boundary

| GMS workflow | This implementation | Verification / limitation |
|---|---|---|
| Model/project management | Versioned JSON case import, edit, export | Synthetic projects; native `.gpr` not supported |
| Structured groundwater grid | Uniform horizontal spacing, multiple flat layers | All cells active, confined aquifer only |
| Hydraulic properties | Per-layer anisotropic K and specific storage | Constant within each layer |
| Boundary conditions | Left/right constant head; other outside faces no-flow | General GIS boundaries, rivers and drains not implemented |
| Stress periods | Steady or transient; optional well overrides | Constant recharge and fixed heads throughout the run |
| Wells / recharge | Injection/extraction and uniform recharge | Cell-based sources; no wellbore or multiphase model |
| Numerical engine | Genuine USGS MODFLOW 6 through FloPy | Separately installed executable; no synthetic fallback solver |
| Input-file export | Standalone MODFLOW 6 text inputs | Files can be run directly by MODFLOW; GMS import not tested |
| Results | Layer/time head maps, contours, 3D surfaces, time series | Head surfaces are not CO2 plume surfaces |
| Reproducibility | Input JSON, solver outputs, budgets, hashes and versions | Synthetic numerical checks; no field validation |
| GIS / CAD / boreholes | Not implemented | No shapefile/CAD/CRS transformation claims |
| Unstructured meshes / solids | Not implemented | No grid refinement or stratigraphic interpolation |
| Solute transport / particles | Not implemented | No GWT, MT3D or MODPATH adapter yet |
| Calibration / uncertainty inversion | Not implemented | Existing volumetric Monte Carlo stays separate |
| CO2–brine multiphase flow | Not implemented | Requires an appropriate OPM/DuMux-class solver and benchmarks |
| Native GMS UI / binary behavior | Not reproduced or compared | Static inspection does not prove runtime behavior |

## Primary references consulted, 2026-10-19

- [GMS introduction](https://aquaveo.com/software/gms/introduction): documented
  conceptual/grid workflows, supported data and 3D visualization.
- [Official GMS downloads](https://aquaveo.com/downloads-gms): GMS 10.9.7 x64,
  build 13 October 2026; Windows release selected for static investigation.
- [REA official repository](https://github.com/morluto/rea) and
  [CLI/evidence contracts](https://github.com/morluto/rea/blob/main/docs/cli.md).
- [USGS MODFLOW 6](https://www.usgs.gov/software/modflow-6-usgs-modular-hydrologic-model)
  and [source/documentation](https://github.com/MODFLOW-ORG/modflow6).
- [FloPy official source and documentation](https://github.com/modflowpy/flopy).

The published module contains original code and synthetic inputs. It does not
redistribute GMS executables, installer files, extracted resources, logos or
decompiled implementation. See `REA_FINDINGS.md` for the actual observation
boundary and `REPRODUCE.md` for execution.
