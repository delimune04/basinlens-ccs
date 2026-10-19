# Explicit TIN surfaces, horizons and prism solids

This independent geometry subset uses **user-supplied connectivity and horizon
correlation**. It does not infer geology, triangulate a point cloud, write GPR,
claim original GMS equivalence, or map a sloping prism to a flat MF6 cell.
There has been no original GMS comparison (`NOT_OBSERVED`).

## Data and scientific contract

`SurfaceModel.from_dict()` accepts `basinlens-surfaces-v1` JSON. Literal `id`,
`name`, `crs`, `vertical_datum`, and nonempty `provenance` are required. Units are
exactly `{"length":"m","elevation":"m","volume":"m3"}`. CRS and datum strings
are carried literally; no coordinate, datum or unit conversion is performed.
The fixtures declare local synthetic coordinates and are not field measurements.

| Element | Required content |
| --- | --- |
| `vertices` | Unique literal `id`, finite `x_m`, `y_m`; no duplicate XY |
| `triangles` | Unique `id`, three known `vertex_ids`, counterclockwise XY |
| `horizons` | Ordered top to bottom; `id`, `name`, `elevations_m` aligned with vertex order |
| `layers` | One `id`, `name`, `material_id` per consecutive horizon pair |
| `history` | Initially `[]`; edits append source SHA-256, operation, parameters and reason |

Each triangle has strictly positive projected area. Shared edges must have
opposite directions and at most two incident faces. Vertex links must form one
connected path or cycle, excluding disconnected fans touching at one vertex.
Crossing edges, overlapping interiors, partial coincident edges, T-junctions,
duplicate triangles and unused vertices are rejected. Disconnected components
and holes are allowed; their gaps are retained.

The numerical orientation threshold is
`max(total_XY_span**2 * 1e-12, 1e-18)` in m² (twice-area/cross-product units).
Query support separately uses dimensionless barycentric bounds
`[-1e-12, 1+1e-12]`; section clipping uses each triangle's twice-area times
`1e-12` as its cross-product tolerance. A distant large component never expands
a small triangle's query support. Inputs near these thresholds require explicit
rescaling/review; this is floating-point geometry, not exact arithmetic.
All consecutive horizon vertex thicknesses must be at least
`1e-6 m`. With shared planar triangles, positive vertex thickness implies
positive thickness throughout each triangle by barycentric linearity.

## Implemented operations

- `query_surface(model, horizon_id, points_xy)` evaluates barycentric linear
  elevation, source triangle/vertex IDs and weights. Outside/hole points have
  `supported=false`, `elevation_m=null`. Boundary ownership uses the first
  supplied triangle. No extrapolation occurs beyond the stated tolerance.
- `edit_vertices(model, *, horizon_id=None, elevations=None, xy=None, reason)`
  performs explicit ID-addressed edits, validates the complete result and
  preserves the original immutable model. It records the exact source identity
  and edits. A history identity is traceability metadata, not authentication of
  an independently supplied history or proof of geological correctness.
- `smooth_horizon(model, horizon_id, *, iterations, weight=0.5, reason)` applies
  simultaneous uniform-neighbour Jacobi Laplacian updates to **elevation only**.
  Every boundary vertex remains fixed. Iterations and weight are explicit;
  transient crossing/touching horizons are refused. This is an optional numerical
  edit, not a geological interpretation or uncertainty estimate.
- `extrude_solids(model)` emits six XYZ vertices and five outward-oriented faces
  for each closed triangular prism, with source triangle/horizon/layer/material
  IDs. Volume is `projected_triangle_area * mean(three_vertex_thicknesses)`.
  Because thickness is linear, this integral is exact for the stated geometry.
  Neighbouring prisms share interfaces; each output prism is individually closed.
- `section_surfaces(model, polyline)` clips arbitrary explicit vertical-section
  polyline segments against each XY triangle. It emits supported distance/elevation
  pieces, horizon endpoints and layer/material band polygons. Distance is measured
  along the entire supplied polyline, including gaps outside support. Shared-edge
  intervals are assigned once; holes and outside intervals remain gaps. This is
  section clipping only: **mesh extent clipping remains unimplemented**.

Shared literal CRS/datum, vertex IDs and explicit source hashes permit future
links to borehole interpretation, raster/point data and mesh generation. These
APIs do not automatically correlate those data, transform support, infer material
properties, or silently change sloping geometry into a solver discretisation.

## Persistence and bounds

`save_surfaces`/`load_surfaces` use strict JSON with duplicate-key, unknown-field,
NaN/infinity, regular-file and byte-budget validation. Each output file is
published by an atomic no-replace hard link from an owned temporary file.
Existing paths and final-component symlinks are refused; no source is modified.

`export_surface_tables` writes `vertices.csv`, `triangles.csv`, `elevations.csv`
and a final manifest with every byte count/hash plus literal metadata. The output
directory is exclusively reserved and the manifest is installed last. The entire
directory is not an atomic filesystem transaction; interrupted output lacking
the complete exact inventory/manifest is rejected on import. Import rejects
missing, changed, unregistered, duplicate, contradictory or symlink table files.
Export CSV is a scientific interchange format; values are not spreadsheet
formulas and literal IDs are not altered to match spreadsheet conventions.

`verify_surface_roundtrip(source, output_dir)` writes a fresh JSON copy, exact
hashed CSV bundle, imports it, writes/reloads a restored JSON file, checks full
typed semantics and source bytes, then saves a receipt. A receipt establishes
the tested own-format roundtrip, never GPR interoperability or original parity.
Failure leaves an explicitly incomplete fresh output for diagnosis; use a new
output path after correcting the cause.

Bounds: 8 MiB JSON input; 2,000 vertices; 1,000 triangles; 20 horizons; 64 history
records (128 KiB parameters each, subject to the whole JSON limit); 500,000
triangle-pair/query/section/smoothing work units per operation; 100 smoothing
iterations; 20,000 output prisms; 8 MiB total CSV table bytes; 64 MiB per output
artifact. A valid JSON model with unusually long IDs can exceed the separate
CSV budget; export refuses it before creating its destination. No truncation,
implicit resampling, network access or optional dependencies occur.

## Reproduce

Use a fresh output path for every command:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_surfaces.py -v
PYTHONPATH=src python examples/surfaces/run_surface_example.py --output build/surface-example
python -m basinlens_ccs.subsurface.surfaces check examples/surfaces/tilted_planes.json
python -m basinlens_ccs.subsurface.surfaces query examples/surfaces/tilted_planes.json --horizon top --values examples/surfaces/query_points.json --output build/surface-query.json
python -m basinlens_ccs.subsurface.surfaces section examples/surfaces/tilted_planes.json --values examples/surfaces/section_polyline.json --output build/surface-section.json
python -m basinlens_ccs.subsurface.surfaces extrude examples/surfaces/tilted_planes.json --output build/surface-prisms.json
python -m basinlens_ccs.subsurface.surfaces edit examples/surfaces/tilted_planes.json --horizon top --values examples/surfaces/vertex_edits.json --reason 'Authored synthetic alternative' --output build/surface-edited.json
python -m basinlens_ccs.subsurface.surfaces roundtrip examples/surfaces/tilted_planes.json --output build/surface-roundtrip
```

The authored fixture has upper `z=10+x+2y`, lower `z=5+x+y`, rectangle
`0<=x<=4`, `0<=y<=2`. Independent integration gives `8*(5+1)=48 m³`.
Tests also independently integrate oriented closed-shell tetrahedra, check
planar interpolation, true section distances, unsupported gaps, fixed-boundary
Jacobi arithmetic, manifold/topology failures, duplicate JSON, FIFO refusal,
altered/extra/symlink tables, source preservation and actual CLI operations.
These are mathematical/software checks on authored synthetic geometry. The
whole GMS workbench, field geology and CCS/oil physical validation remain open.
