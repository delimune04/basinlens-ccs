# Authored mesh generation and flat extrusion

This implements a bounded independent mesh subset. It does not establish original
GMS parity, decode original GMS Quadtree/UGRID objects, write GPR, or implement all
GMS grid/mesh tools. Original comparison stays `NOT_OBSERVED`.

## Supported operations

| Operation | Exact support | Limits |
|---|---|---|
| Planar model | Shared numbered vertices and convex counterclockwise polygon rings, material IDs, literal CRS and provenance | Meters only; no CRS transformation, inferred units, overlapping interiors, unused/duplicate vertices, concavity or self intersection |
| Structured generation | Explicit increasing nonuniform X/Y edges; quadrilaterals or a stated SW–NE/NW–SE triangle diagonal | No inferred feature meshing, Delaunay, smoothing or raster clipping |
| Rectangle refinement | Additional recursive four-way splits selected by literal bounding box, points, or the entire source | Axis-aligned rectangular leaves; no 2:1 balancing or GMS algorithm equivalence |
| Interfaces | Every new edge point appears in both neighboring cell rings and uses the same global vertex ID | Collinear interface vertices are allowed; unresolved hanging interfaces are rejected |
| Flat extrusion | Explicit descending flat elevations, outward closed prism faces, positive area-times-thickness volumes, layer-major cell materials and explicit adjacent-material sets per shared node | No horizon interpolation, faults, pinch-outs, curvilinear/variable-top geometry, or general polyhedron importer |
| DISV conversion | Zero-based FloPy `vertices`, clockwise `cell2d`, literal XY centroids, `top`/`botm`, meters | Geometry conversion only; boundaries, properties and physics remain the caller's explicit responsibility |
| Portable I/O | Strict JSON, fresh atomic output, exact semantic relocation/roundtrip, source hashes | Own schema only; no GPR write or inferred format compatibility |
| Rendering data | Closed literal XY rings, centroid, area and material ID per cell | No automatic rasterization or geological interpretation |

A mesh may contain disconnected components or holes represented by absent cells.
The validator does not invent an exterior boundary or claim full coverage of an
unspecified domain. Selection combines a supplied box and points by union; a
point on an interface selects every touching leaf. A box uses positive interior
intersection. `levels` counts additional splits, rather than absolute tree depth.
No balancing claim is made. The source remains unchanged when a budget fails.
Refinement provenance records the source canonical SHA-256 and exact additional
levels, box, points, cell budget and no-balancing declaration as numbered literal
JSON chunks. Large selectors or accumulated history can exceed the explicit
64-note provenance budget and are refused before refinement.
Cell material IDs are authoritative. Each extruded node lists the sorted set of
materials of all incident cells; interfaces can have multiple materials. No
physical node property is averaged or inferred from that adjacency list.

## Data contract and budgets

`basinlens-planar-mesh-v1` requires exactly `schema`, `length_unit="m"`, `crs`,
`vertices`, `cells`, and `provenance`. Vertex records require consecutive
zero-based `id`, `x_m`, `y_m`; cell records require consecutive zero-based `id`,
`vertices` (unclosed ring of distinct vertex IDs) and `material_id`. Provenance
notes and identifiers are literal strings. Unknown fields and units are rejected.
Coordinates must be finite numbers within ±1e9 m, never booleans or numeric text.
Known geographic angular declarations (`EPSG:4326/4269/4258/4979`,
`OGC:CRS84`, `CRS:84`) contradict meter XY and are refused. Other CRS strings
remain literal metadata, rather than a verified projection/unit lookup.

Bounds: 10,000 planar cells, 40,000 vertices, 100,000 ring edges, 256 vertices per
cell, two million sweep/candidate checks, 20 million polygon/overlap comparisons,
and 16 MiB per serialized artifact. Refinement accepts 1–8 additional levels and
at most 1,000 selector points. Flat extrusion accepts 1–64 layers, at most 100,000
prisms/300,000 nodes/two million node-and-face vertex uses. A supported geometry
can still exceed an operation or serialization budget; it is rejected explicitly.

Predicate tolerance is `max(1e-10 m, overall XY span * 1e-12)`. Edges shorter than
ten times this tolerance and areas below the documented local precision budget
are rejected. Near-touching geometry is handled conservatively; this is not an
exact-arithmetic geometry kernel or a geographic projection engine. Bounds prevent
large imports or pathological topology from initiating unbounded pair searches.

File reads use a nonblocking descriptor, reject symlinks/nonregular files, check
size before reading, and recheck descriptor identity/size/time afterward. FIFO
inputs are refused without blocking. Writers serialize before publishing and use
a temporary sibling plus an exclusive hard link, so existing files are preserved.
Paths must not traverse symbolic links. These operations assume the output parent
is controlled by the caller; they do not promise race-proof isolation against a
concurrent hostile filesystem administrator.

## Python API

```python
from basinlens_ccs.subsurface.mesh import (
    structured_mesh, refine_quadtree, extrude_mesh, to_disv,
    read_mesh, write_mesh, verify_mesh_roundtrip, topology, render_data,
)

mesh = structured_mesh([0, 2, 5], [0, 3, 7], crs="LOCAL:synthetic meters")
mesh = refine_quadtree(mesh, levels=2, points_m=[[1, 1]])
write_mesh(mesh, "fresh.mesh.json")
receipt = verify_mesh_roundtrip("fresh.mesh.json")
solid = extrude_mesh(mesh, [10, 6, -1], vertical_datum="LOCAL:synthetic zero")
disv_kwargs = to_disv(mesh, [10, 0])
```

MODFLOW 6 documents clockwise CELL2D vertex order and shared interface vertices.
The converter reverses the internal counterclockwise ring, without reflecting XY
or changing cell IDs. FloPy accepts zero-based Python records and writes native
one-based vertex/cell IDs. Native-input references:

- [USGS MODFLOW 6 DISV input description](https://modflow6.readthedocs.io/en/6.6.1/_mf6io/prt-disv.html)
- [USGS MODFLOW 6 input/output manual](https://water.usgs.gov/water-resources/software/MODFLOW-6/mf6io_6.6.0.pdf)

Before writing with FloPy, set both fields below and verify all reloaded vertices,
centroids, ring ownership and elevations against the declared geometry:

```python
simulation.simulation_data.float_precision = 17
simulation.simulation_data.float_characters = 26
```

This matters at large literal origins. The first authored example failed before
execution because FloPy's default eight-digit formatting moved
`4100000.375` to `4100000.38`, a 0.005 m error. The failure was diagnosed; the
example/compiler test now explicitly uses 17-digit formatting and retains the
strict 1e-9 m reload gate. This repair did not widen geometric tolerances. The
pure `to_disv` function returns full Python float data and does not configure an
external simulation or execute a solver.

## Reproduce

Choose new output paths for every invocation:

```bash
python -m basinlens_ccs.subsurface.mesh generate --x-edges 0 2 5 --y-edges 0 3 7 --crs LOCAL --output build/base.mesh.json
python -m basinlens_ccs.subsurface.mesh refine build/base.mesh.json --point 1 1 --levels 2 --output build/refined.mesh.json
python -m basinlens_ccs.subsurface.mesh extrude build/refined.mesh.json --surfaces 10 6 -1 --vertical-datum LOCAL --output build/prisms.json
python -m basinlens_ccs.subsurface.mesh verify build/refined.mesh.json
python -m basinlens_ccs.subsurface.mesh render-data build/refined.mesh.json --output build/render.json
python -m basinlens_ccs.subsurface.mesh disv-data build/refined.mesh.json --surfaces 10 0 --output build/disv.json
python examples/mesh/run_mesh_example.py --output build/mesh-example --exe /absolute/path/to/mf6
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -p test_mesh.py -v
```

The example creates a 9×7 m nonuniform frame at a large literal origin, refines
around a declared point, saves/relocates/reads it, exports render/DISV data, and
extrudes two layers spanning 11 m. The independent hand results are 63 m² and
693 m³. The optional explicit solver path enables a real confined steady single-
phase uniform-head DISV case with boundary head 3 m and initial head 2 m. The
existing isolated native runner verifies its captured input/output inventory.
No solver is downloaded or run when `--exe` is absent. A manifest records exact
example file hashes; failures retain their fresh output directory for diagnosis.

## Executed validation

The scoped suite checks nonuniform hand areas/centroids at large origins, both
triangle diagonals, an oblique trapezoid centroid, overlap/containment, invalid
winding/self crossing/concavity/degeneracy, duplicate/unused vertices, explicit
hanging-node repair, local/repeated refinement and material preservation, source
immutability on failure, closed prism edge/face ownership and independent signed
shell volumes, DISV orientation, FIFO/symlink/duplicate-key/NaN/byte bounds, CLI
roundtrip, actual FloPy reload and a real MF6 constant-head solution. These are
synthetic geometry/software/limited groundwater checks, not original-program or
field validation. Missing FloPy/MF6 marks the solver test skipped; a skipped solver
test must never be reported as passed.

### 2026-10-19 authored subset checkpoint

The final scoped run passed **21 tests, zero failures/errors/skips**, in 4.362s,
with actual USGS MF6 6.7.0, FloPy 3.11.0 and Python 3.12.14. A separate peer
independently ran all 21 tests and reviewed geometry, material propagation,
face closure, DISV orientation, input bounds and I/O; the review's huge-integer,
known-angular-CRS and SAT-work-budget findings were corrected. Compilation and
`git diff --check` passed. The repaired fresh example has 15 planar cells and
30 explicit flat prisms, area 63 m² and volume 693 m³; its actual native run
completed with unchanged captured sources and the uniform-head analytical gate.
The earlier eight-digit-formatting failure remains a failed diagnostic case,
rather than positive evidence. These results cover this exact synthetic subset
and do not close original-program comparison obligations.
