# Geoscience workspace

Run `python -m streamlit run geoscience_workspace.py`, or embed
`render_geoscience_workspace()` in the existing groundwater workbench. A fresh
session displays six idle tabs; no model is imported, downloaded or solved until
an explicit user action. The implemented algorithms and their limits are shown
beside each workflow. This interface does not establish complete GMS
implementation or original-program equivalence.

| Tab | Actual workflow | Scope and limitations |
|---|---|---|
| Borehole/geology | Registered-asset JSON load, strict draft editing, vertical interval plot, finite-polyline section, auditable material edit, portable CSV/assets export | Vertical depth below collar converted to Z-up elevation; exact declared horizon/material IDs; no inferred surfaces |
| Conceptual features | Strict coverage JSON load/edit/apply, nodes/points/arcs/polygon shells/holes display, attribute table and local grid extent | Literal local/metre or declared geographic coordinates; no implicit CRS conversion or automatic solver boundary mapping |
| Scatter | Versioned JSON/CSV load, strict draft and audited value/missing-value edit, IDW/nearest/explicit-TIN queries, masked output/CSV, compatible two-dataset arithmetic | 2D/3D scalar support; explicit search radius, neighbor bounds, IDW power and vertical distance scale; no kriging or uncertainty estimate |
| Mesh | Nonuniform rectangular/triangular generation, selected rectangular refinement, actual closed rings, flat-layer closed-prism extrusion/3D view and JSON | Explicit edges and layer elevations; no geological interpolation or general tetrahedral mesh; no implicit solver execution |
| Results | Load unchanged verified MF6 workflow, supported coordinate query, polyline section, cell-centre plane/scalar clip, source-bound analysis bundle, manual observation residual metrics | Captured case authority; unsupported points remain masked; visibility clipping creates no cut-cell geometry; no automated parameter fitting |
| MODFLOW-2005/NWT | Explicit known confined-water example or JSON, selected pinned executable, native input export, actual isolated run, saved layer/time head plots, CSV and complete run ZIP | Limited authored confined single-phase subset; no arbitrary legacy import, drying/rewetting, original GMS comparison or CO2/oil multiphase physics |

Known examples are addressed by exact filenames (`synthetic_boreholes.json`,
`local_coverage.json`, `synthetic_plane.json`,
`layered_background_water.json`) rather than directory order. JSON uploads and
editable drafts are bounded to 2 MiB; strict backend parsers enforce their own
structure, finite values, identity and source-asset contracts. A geology upload
with registered files requires an explicitly selected server asset root; missing
or changed source bytes are refused. Failed imports preserve the last valid
applied document. A changed/invalid draft clears dependent products and blocks
operations until a valid draft is explicitly applied.

CRS, datum, units and algorithm support remain literal. Borehole and prism plots
use Z-up elevations. Unknown CRS/datum labels remain unknown. Scatter IDW/nearest
mask outside the axis-aligned source bounds; this is not a convex hull. Explicit
TIN uses only supplied triangle connectivity. Missing scalar results remain
null with reasons. Arithmetic checks point IDs, coordinates, units and quantity;
no expression evaluation or guessed unit conversion is performed.

Mesh refinement/extrusion apply to the preserved generated mesh; its actual
bounds and CRS are displayed even when pending generation settings are edited.
The planar view displays at most the first 2,000 real closed cell rings, and the
prism view at most the first 2,000 cell shells; JSON retains full connectivity.
Shared internal prism faces may appear twice in the visualization. Generation
and extrusion use backend topology/closure checks rather than visual appearance
as evidence. No horizon surface is inferred from these flat layers.

Result loading checks the complete captured native run. Changing the source
path, a failed reload, changed file bytes or changed captured metadata deactivates
cached results, removes products/downloads and blocks analysis until a successful
explicit reload. While active, source metadata/inventory is reverified each
rerun. The preserved last-valid snapshot is clearly labelled inactive after a
failure. Manual observation JSON must match captured project/case identity,
literal CRS/datum and exact units; output JSON preserves source/time support,
residual convention and observation identity alongside the CSV. The bundle
verifier checks file integrity and CSV/JSON consistency; it does not recompute
analytical values or establish authorship, field validity or GMS equivalence.

Classic engine/timeout/case/executable/output changes clear old products. Before
cached classic numerical results are exposed, the backend rechecks native bytes,
compiler/case identity and captured output. A positive message requires all
water-balance, explicit boundary-rate and confined-saturation checks. The chosen
engine must match the backend's exact allowed public executable identity; missing
or unknown executables fail visibly with no fallback or download. The timeout
is bounded to 1–1,800 seconds. Outputs require fresh paths; missing parents are
created only after an explicit export/run action.

ZIP creation refuses symlinks and limits total uncompressed content to 128 MiB
and 5,000 files. Backend failures retain diagnostics and their output paths;
retries use a fresh directory. These bounded flows do not imply a native GPR
writer, full GMS reconstruction, original numerical parity or multiphase physics.

## Checks

`tests/test_geoscience_workspace_ui.py` includes seven AppTests:

- Idle startup, known borehole section distances/Z, immutable source plus audited
  material edit, malformed upload and missing registered asset recovery.
- Invalid conceptual drafts and an explicitly applied point coordinate edit.
- Hand-checked scatter support/null masking, affine TIN value 3.5, compatible
  arithmetic, auditable value edit and stale-draft blocking.
- Four nonuniform cells, selective refinement to seven cells, fourteen closed
  prisms totaling 450 m3 and preservation after invalid generation.
- Actual MF6 run loading, supported/exterior queries, section/clip, verified
  analysis bundle, known residual RMSE 0.5 m/chi-square 4, path change and head-file
  tamper invalidation.
- Real classic input export and unknown-executable refusal.
- Both actual pinned MODFLOW-2005/NWT runs, captured engine identity, all three
  physical-support checks, 12 m fixed head, complete ZIP and invalid-draft removal.

The optional numerical checks require explicitly provided executables; skips
are never counted as performed engine checks:

```bash
MF6_EXE=/absolute/path/to/mf6 \
MF2005_EXE=/absolute/path/to/mf2005dbl \
MFNWT_EXE=/absolute/path/to/mfnwtdbl \
PYTHONPATH=src python -m unittest tests.test_geoscience_workspace_ui -v
```

Local versions: Python 3.12.14, Streamlit 1.66.0, Plotly 7.1.0, FloPy 3.11.0,
MF6 6.7.0 and the classic backend's pinned double-precision public engines. The
source-bound seven-test run passed with zero skips in 7.095 seconds before final
caption-only changes; the independent final-source run is recorded in the
integration handoff. All fixtures are authored synthetic inputs. None of these
checks execute original GMS.

## Raster, encoded point clouds, interpreted surfaces and mixed projects

The workspace now has ten tabs. The additional tabs perform real operations:

- **Raster:** explicit metre geometry and north-to-south rows, NODATA-preserving
  nearest/bilinear samples, clipping, target-geometry resampling, explicit overlap
  policy for merging, pixel-centre CSV and actual ASCII/JSON reopen comparison.
  Plots use the literal north-row centre coordinates; they do not flip the values
  into the shared project's south-row order. No georeferencing is inferred.
- **Point cloud:** self-contained typed JSON or real uncompressed LAS 1.2 import
  with owner-supplied CRS, horizontal/vertical units, datum and provenance;
  classification/XY/height filtering, bounded point rendering, supported-cell
  mean/min/max/count aggregation and actual LAS/JSON round trip. View decimation
  keeps stored encoded points unchanged. Aggregation uses south-to-north rows and
  leaves empty cells unsupported. LAZ, other LAS versions and VLR-derived CRS
  interpretation are not implemented. LAS itself cannot retain the project-local
  per-point IDs; the accompanying JSON preserves them explicitly.
- **Interpreted surfaces:** supplied XY triangles and correlated horizon
  elevations, supported barycentric queries, real supported section-band plots,
  closed sloping prism generation/volume and 3D display, audited vertex elevation
  edits, optional fixed-boundary numerical smoothing, CSV export and typed reopen
  comparison. The 2,000-prism display limit does not alter full JSON connectivity.
  Surface correlation and geological correctness are supplied assumptions.
- **Mixed project:** explicit shared project JSON plus selected currently valid
  applied objects, registered source assets and common view state can be saved in
  an own `.blproj`, actually opened/re-saved/reopened for comparison, downloaded,
  relocated and restored into their typed tabs. No solver executes during this
  workflow and no object is silently mapped into flow physics. Spatial metadata
  must meet the backend's exact unit/CRS/datum contract; unknown labels remain
  unknown and their equality does not establish physical registration.

The mixed base project's asset verification uses its explicit selected/restored
asset root, including while validating an edited JSON draft. This avoids treating
an unrelated temporary draft folder as the asset root. Registered source bytes
are still fully checked. Opening a malformed package preserves prior valid
objects. Successful opening replaces the collection; prior solver caches are
removed or deactivated. Additional objects of the same kind and objects larger
than the 2 MiB editor budget remain explicitly retained under their original
collection IDs rather than being silently dropped. The first editable object of
a kind is shown in its tab. Exported analysis archives remain inert files, with
no automatic revival of a source path or engine state.

A selected object's invalid or unapplied draft blocks mixed saving rather than
omitting that selection. Package view and generic project metadata are preserved.
Temporary restored asset directories live for the session and are replaced only
after a different package has successfully opened. ZIP/archive bounds and strict
backend regular-file/format checks remain in force. JSON/LAS uploads in these UI
flows are bounded to 2 MiB, and mixed package uploads to 32 MiB; backend CLI APIs
can have separate documented limits.

The extended AppTests retain the earlier seven flows and add north-row affine
raster sampling (5/12 m plus unsupported exterior), actual ASCII round trip,
six-point encoded LAS known bin means and filtering to three points, byte/ID
round trip, the tilted surface's 13 m sample and independent 48 m3 volume,
source-preserving vertex edits and CSV round trip, relocated mixed-package
save/open/re-save with real assets and duplicate-kind ID preservation, selected
invalid-draft blocking and corrupted-package refusal.

A separate actual MODFLOW-2005 diagnostic starts above a 20 m top but imposes
10–12 m boundary heads. It must fail the confined-saturation support flag. The
UI retains plots/files as diagnostic evidence and labels its ZIP **execution
record**, never a validated supported model. Positive indicators still require
all three physical-support gates. Source/solver validation and archive integrity
are distinct from physical acceptance, field verification and original GMS parity.

Classic linear methods are explicit: PCG for MODFLOW-2005; XMD or GMRES for
MODFLOW-NWT. Export and execution retain that choice, and changing it invalidates
cached products. Convergence can differ by case; a failure retains diagnostics
and requires the user to select a method and fresh output explicitly. The UI
does not substitute a different method automatically. An additional actual NWT
GMRES test uses the independently authored three-cell fractional-head case:
12.3456789123 m and 9.8765432199 m endpoints and their arithmetic mean at the
middle cell agree within 2e-9 m. Selecting XMD afterward removes the previous
run from the active display while preserving its on-disk record.

The final extended local suite passed **13 tests, zero skips/failures/errors**
in **23.489 seconds**, with actual MF6, pinned MODFLOW-2005 and pinned
MODFLOW-NWT. The original seven workflows remain covered. Tests and source
identities are retained with the integration record; these are synthetic
software/mathematical checks and do not execute original GMS.

Independent UI review found two additional operational issues and both now have
regressions. Base-asset draft validation uses bounded regular-file reads:
32 MiB per asset and 128 MiB total unique bytes, checked both before and after
reading; a sparse oversized asset fails before unbounded hashing while preserving
the prior base project. Relocating/opening a mixed package resets controls for
adding a new analysis source and resets old retain-checkbox state. This prevents
an already archived inert analysis from being added twice under the same ID or
re-reading a deleted original source. The new test deletes that original bundle,
reopens the package and re-saves successfully from the retained archive bytes.

After those review fixes the local suite passed **14 tests, zero
skips/failures/errors, in 31.963 seconds** with all three actual public engines.
The earlier 13-test result describes the preceding source snapshot.
