# Geoscience implementation checkpoint — 2026-10-19

The whole GMS objective remains unfinished. This checkpoint records independent
code additions and their declared limits. It is not a replacement definition of
the product or proof of original-GMS equivalence. The complete selected/unmapped
backlog remains in [FULL_IMPLEMENTATION_BACKLOG.md](FULL_IMPLEMENTATION_BACKLOG.md).
The pinned 163-entry catalogue and separate 223 observed official-page items are
partial inventories, not a whole-product denominator.

## Runnable feature groups

| Module | Implemented operations | Remaining scope includes |
|---|---|---|
| [portable collections](GEOSCIENCE_PROJECT.md) | Canonical typed object manifest, exact original assets, generic project/view preservation, save/relocate/reopen/resave with explicit reference compatibility | Native GPR writer, implicit alignment or engine mapping, live-result reconstruction from an analysis archive |
| [geology](GEOLOGY.md) | Vertical boreholes, explicit logged/gap intervals, materials, typed JSON and portable CSV bundle, traceable edits, finite-polyline sections and explicit horizon contacts | Deviated holes, inferred correlations, native GPR |
| [scatter](SCATTER.md) | Scalar 2D/3D points, IDW/nearest, authored-triangle barycentric interpolation, value edits and dimensional dataset arithmetic, exact JSON/CSV | Automatic triangulation, natural neighbour and broader interpolation |
| [geostatistics](GEOSTATISTICS.md) | Explicit ordinary/simple kriging, rotated covariance, experimental variogram, seeded conditional/unconditional Gaussian fields, unitful scalar LHS, typed scatter output and JSON/CSV | Variogram fitting, noisy observations, universal/trend kriging, geological posterior or flow-ensemble risk interpretation |
| [parameter search](../CALIBRATION.md) | Bounded actual-MF6 K/Ss search, data-only finite-difference identifiability, separate priors, withheld heads, immutable attempts and recomputed verification | PEST/PEST++, global uniqueness, confidence intervals, general inverse or field calibration |
| [conceptual features](FEATURES.md) | Stable nodes/arcs/points, polygon shells/holes, topology edits/query, local JSON and explicit geographic GeoJSON, tables/scatter conversion | General GIS/CAD, reprojection, polygon booleans |
| [mesh](MESH.md) | Nonuniform structured quads/triangles, conforming bounded quadtree refinement, topology, flat extrusion, DISV geometry and an actual MF6 geometry example | General FEM/3D meshing, arbitrary horizons, complete DISV model compiler |
| [surfaces](SURFACES.md) | Explicit TIN horizons, ordered noncrossing contacts, barycentric supported queries, traceable edits/smoothing, closed prisms, arbitrary vertical sections, JSON/CSV | Automatic interpretation, pinches, arbitrary volumes, model mapping of sloping layers |
| [raster](RASTER.md) | Typed north-row-first pixels, ESRI ASCII, NODATA-aware nearest/bilinear sampling, resample/clip/aligned merge, catalogues and explicit property sampling | GeoTIFF, remote imagery, reprojection |
| [point clouds](POINTCLOUD.md) | Bounded uncompressed LAS1.2 formats0–3, original point/VLR attributes, typed JSON identity, filters, compatible merge, explicit bin aggregates, rendering decimation | LAZ, other LAS versions/formats, inferred CRS or units |
| [result analysis](ANALYSIS.md) | Source-bound captured heads, cell/trilinear queries, vertical sections, scalar/plane/visibility clipping, section frame data, manual observation residuals and diagnostic bundles | Arbitrary object queries, isosurfaces, encoded animation, automatic inversion |
| [classic engines](CLASSIC.md) | Authored confined LPF/PCG MF2005 and UPW/NWT decks, six boundary kinds, native load/rewrite/two-run comparison, bounded binary results and explicit PCG/XMD/GMRES choices | General legacy import, unconfined/drying, arbitrary packages, universal solver configuration |

Run `python -m basinlens_ccs.subsurface.<module> --help` for each documented
module; `analysis` and `classic` use those names. Portable collection Python APIs
and the executable example are documented separately. The GUI is
`python -m streamlit run groundwater_app.py`; its geoscience panel can also run
alone with `python -m streamlit run geoscience_workspace.py`. The
[inference panel](../INFERENCE_WORKSPACE_UI.md) is also integrated, or runs as
`python -m streamlit run inference_workspace.py`. Loading or saving
data never implicitly executes a solver or downloads an engine.

## Execution evidence and error recovery

[geoscience_examples_record_v4.json](geoscience_examples_record_v4.json) retains
eight root integration invocations with exact source/test/runner hashes, complete
output inventories and actual parsed receipts. All eight commands exited zero.
Independent expected values include 48 m3 for a sloping prism, 63 m2 planar mesh
area/693 m3 extrusion, exact affine TIN interpolation and NODATA masks. The mesh
example actually executed MF6; the analysis example generated captured heads,
18 section rows, three clipped cells, five frames and a known 0.5 m residual.
These are authored synthetic examples, not original GMS or field observations.

[classic_validation_record_v4.json](classic_validation_record_v4.json) binds the
final compiler to 26 dedicated tests with zero skips/failures/errors, eight
independent analytic engine cases and an eight-native-run executable example.
[classic_solver_recovery_record_v4.json](classic_solver_recovery_record_v4.json)
retains the failed one-cell/GMRES/XMD experiments and separate diagnostic settings.
The successful final cases do not erase those limits. Single cells are refused
before export; the NWT linear solver is an explicit captured user choice. A
known GMRES zero-forcing crash and a known XMD fractional-CHD nonconvergence have
different successful configurations; no hidden retry changes the forcing.

Meaningful independent reviews also found and fixed narrow triangle-boundary
tolerance, raster decimal cell-boundary clipping, large-coordinate resolution,
source replacement while reading, typed GeoJSON tampering and stale result
cache paths. The initial strict integrated suite executed **647 tests with zero
skips/errors/failures**, in 382.444s. All 185 recorded program/test/config/example
hashes were identical before/after and matched the actual 631-test selected bootstrap.
The [full receipt](geoscience_full_tests_v4.json), [dedicated log](geoscience_full_tests_v4.log)
and [integrated validation record](geoscience_validation_record_v4.json) preserve
the exact evidence, environment and fresh 2,000-sample/seed-42 capacity run/verifier.
The first public source CI passed those 647 tests, then failed at the first
new example because the shared output parent was absent.
[Failure/recovery details](geoscience_ci_parent_recovery_v4.json) remain retained.
Only the CI workflow gained explicit parent creation; 184 other fingerprinted
files are unchanged. Fresh corrected-source local strict regression passed
**647 tests, zero skips/errors/failures**, in 431.696s. All 185 current before/after
hashes match; see [the corrected full receipt](geoscience_full_tests_v5.json)
and [log](geoscience_full_tests_v5.log). Corrected source push CI `39242500749` and PR CI `39242506897` passed all three
jobs each, including the strict 647-test zero-skip job and all 13 authored examples.
Exact source/merge-tree, downloaded ZIP and 185-file identity checks are preserved
in [the public CI validation record](geoscience_ci_validation_record_v4.json).
Later evidence-only publication preserves those corrected program bytes. The older 352-test model-I/O
checkpoint remains historical evidence for its own source tree.

## Original comparison and remaining work

The genuine REA ledger still has 577 open obligations and zero verified closures.
No new original-GMS comparison is asserted by these independent implementations.
The retained authorized original run reached an owned error-classified dialog;
its cause, entitlement and successful full model loading remain unknown. Resume
comparison with authorized applicable modules, a successfully witnessed load
and fresh retained input/solver/output evidence. The native REA provider timeout
still lacks useful analyzer-phase diagnostics; its guard was not disabled.

Native GPR writing/synchronization, most remaining solver families/packages,
complete UI/display behavior and CO2/oil multiphase simulation remain open. CCS
and oil domain metadata and portable objects support future adapters; the water
solvers currently represent background water only. Unknown reference metadata
stays unknown, and geometries are not silently retagged or flattened into a
different physical model.
