# GMS workflow reconstruction: scope and evidence

The requested objective is the complete GMS workbench with extensible CCS and
oil-exploration interfaces. That objective is **unfinished**. The current
BasinLens implementation contains the working components below, separate from
conceptual CCS capacity. The [reconstruction plan](RECONSTRUCTION_PLAN.md)
records the remaining product and evidence work.

## Feature boundary

| GMS workflow | This implementation | Verification / limitation |
|---|---|---|
| Model/project management | Versioned JSON case import, edit, export | Partial saved GPR tree/UUID graph, bounded array reads and anonymous summary; no native save/reopen round trip |
| Structured groundwater case builder | Uniform horizontal spacing, multiple flat layers | All cells active, confined aquifer only; native-input execution has a separate, broader contract |
| Hydraulic properties | Per-layer anisotropic K and specific storage | Constant within each layer |
| Case-builder boundary conditions | Left/right constant head; other outside faces no-flow | General GIS boundary editing is absent; existing native packages are retained by the native runner |
| Stress periods | Steady or transient; optional well overrides | Constant recharge and fixed heads throughout the run |
| Wells / recharge | Injection/extraction and uniform recharge | Cell-based sources; no wellbore or multiphase model |
| Numerical engine | Genuine USGS MODFLOW 6 through FloPy | Separately installed executable; no synthetic fallback solver |
| Input-file export | Standalone MODFLOW 6 text inputs | Files can be run directly by MODFLOW; GMS import not tested |
| Results | Layer/time head maps, contours, 3D surfaces, time series | Head surfaces are not CO2 plume surfaces |
| Reproducibility | Input JSON, solver outputs, budgets, hashes and versions | Synthetic numerical checks; no field validation |
| Shared subsurface projects | Versioned units/CRS/datum, geometry, properties, strata, wells, observations and asset hashes | Structured geometry; observations retained without assimilation |
| CCS / oil extension | Capability-gated registry and working MODFLOW background-water adapter | CO2, black-oil and seismic adapters explicitly unavailable |
| Reference comparison | Hashed CSV/NPZ evidence, strict alignment, tolerance metrics and replay verification | Synthetic harness tests; no genuine GMS runtime matches |
| REA reconstruction accounting | Exact main executable/resource observation and source-linked capability catalogue | Static structure is distinct from observed behavior |
| Static dialog templates | All 429 listed standard/extended templates decoded into 6,853 numeric control layouts | Dialog units and stored styles only; no original captions, dynamic UI or handler reproduction |
| Native MF6 / GPR data | General MF6 reference graph, opaque sidecars, bounded HDF5 metadata/array reads | Actual official tutorial import and native-input rerun; no GMS UI/translation witness |
| Saved GPR project relationships | Explicit tree inspection and literal UUID graph | One actual tutorial: 29 nodes, 21 relationships, 16 unresolved; no external component synchronization |
| Native GPR geometry | Physical nodes, hexahedra and cell elevations for one verified rectilinear representation | All 1,125 tutorial cell coordinates match native DIS; units/CRS/datum remain unknown, no GPR writing |
| GIS / CAD / boreholes | Not implemented | No shapefile/CAD/CRS transformation claims |
| Unstructured meshes / solids | Not implemented | No grid refinement or stratigraphic interpolation |
| Conservative solute transport | Standalone bounded1D GWF/GWT exporter/runner/result reader | Synthetic uniform/Gaussian/inlet checks and every-step mass balance; no general3D/GMS/field equivalence or shared UI adapter |
| Particles and other transport | Not implemented | No MODPATH, MT3D, reactions or density-dependent interface |
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
