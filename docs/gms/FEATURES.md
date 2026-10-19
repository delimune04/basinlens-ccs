# Conceptual feature coverage — bounded implementation

This independent implementation adds literal conceptual points, nodes, noded
arcs, polygon shells and holes. It is a subset of the GIS-style feature concept
on [Aquaveo's official GMS introduction](https://aquaveo.com/software/gms/introduction).
It does not establish original GMS behavior, native GPR writing, whole-feature
completion or the behavior of any numeric modeling engine.

## Contract and coordinates

`basinlens-feature-coverage-v1` JSON has `id`, `name`, `coordinate_system`,
`provenance`, `nodes`, `points`, `arcs` and `polygons`. Every object has a globally
unique literal `id` and finite JSON-object `attributes`. Nodes/points have `x,y`;
arcs have `node_ids`; polygons have a closed node-ID `shell` and a list of closed
node-ID `holes`. Nodes can be shared by arcs and polygons; independent points
are separate. Polygon rings do not refer to arc IDs. Unreferenced nodes remain
present during saving and editing.

| Coordinate contract | Meaning | Allowed operations |
|---|---|---|
| `units: m`, literal CRS or `unknown`, `axis_order: x,y` | local/projected metre XY; caller owns CRS truth | planar containment, metre length/area, centroid, grid frame, own JSON |
| `units: degrees`, literal `EPSG:4326`, `axis_order: x,y` | WGS 84 longitude, latitude | own JSON and RFC 7946 GeoJSON; planar containment only |

No projection, axis reinterpretation, geodetic area or datum conversion occurs.
Metre coordinates cannot carry `EPSG:4326`. The module refuses metric calculations
on degree data. Floating-point planar predicates use **no hidden snap tolerance**;
near-degenerate data may need deliberate caller preprocessing. Near-zero numeric
area is not a claim about survey precision. Antimeridian-crossing edges and Z
positions are explicitly refused.

[RFC 7946](https://www.rfc-editor.org/rfc/rfc7946.html), sections 3, 4 and 11.2,
requires WGS 84 geographic coordinates in decimal degrees. Consequently projected
or local eastings/northings are never emitted as RFC 7946 GeoJSON. General imports
support only `FeatureCollection` with `Point`, `LineString` and `Polygon`, optional
literal string feature IDs, and explicit import identity/name/provenance.
Unsupported members, null properties, legacy CRS objects, 3D positions and multi
geometries fail explicitly. This is a strict documented subset of GeoJSON.

Own GeoJSON exports include standard geometry/properties plus a foreign
`basinlens_coverage` member containing the complete noded source contract and its
SHA-256. The reader checks both this hash and every visible geometry/attribute
against the embedded contract before restoring it. This retains unused nodes,
IDs, provenance, attributes and ring order exactly. Exported visible polygon
rings follow the RFC outer-counterclockwise/hole-clockwise rule. General imports
do not infer shared topology from coincident coordinates; each imported geometry
gets explicit fresh nodes.

## Geometry, edits and sampling

Individual arc paths and polygon rings must be simple. Zero-length edges,
nonadjacent self-touches, crossings and overlapping folded adjacent edges are
refused. Holes must lie strictly inside the shell, cannot touch it, and cannot
overlap, touch or nest one another. Multiple independent polygons may overlap;
this module does not choose property precedence, perform polygon booleans, or
prove complete nonoverlapping coverage. It does not automatically polygonize arcs.

`contains_point(..., edge_policy='include'|'exclude')` applies the same explicit
policy to both shell and hole boundaries. Hole interiors are excluded.
`prepare_polygon` / `prepare_polygon_xy` capture validated immutable rings once
for repeated mesh queries; their `.contains(...)` uses the same policy.

Edits return a newly validated immutable `FeatureCoverage` and append an explicit
authored-change provenance record bound to the complete prior canonical SHA-256.
The prior file remains unchanged; retain it for historical reconstruction. These
records are not signatures or proof of observations. `move_point` moves independent
points while retaining attributes. `move_node` updates
all incident geometry by reference; invalid topology rejects the edit atomically.
Deleting a referenced node fails unless `cascade=True` explicitly removes its
dependent arcs/polygons. Other node attributes and independent points remain.
Selection filters exact IDs/kinds/attribute values; no expression evaluation runs.

`to_scatter_points` requires an explicit sampling rule: independent points,
nodes, arc vertices, arc endpoints, or planar area centroids. Arc sampling uses
the arc's selected numeric attribute at every sampled vertex; this is not linear
attribute interpolation. Duplicated vertices remain distinct samples. Polygon
centroids subtract hole areas and **can lie outside a concave or holed region**.
No weighting, interpolation or automatic property assignment occurs. Value units
remain `unknown` and must be declared by the caller before scientific use.
`grid_extent` reports an unrotated positive-area frame from all nodes/points,
with explicit nonnegative metre padding and south-to-north row coordinates.

## Bounds and failure behavior

Core code uses the standard library only. Inputs/serialized outputs are bounded
to 8 MiB, 5,000 nodes, 1,000 combined non-node objects, 256 vertices per line/ring,
16 holes per polygon, and two million topology segment comparisons per coverage.
Attributes have explicit depth, string, key and array bounds. Unknown fields,
versions, missing references, duplicate JSON keys/IDs, nonfinite values and
Boolean/string numeric coordinates fail with `FeatureError`. Reading refuses
links/devices/FIFOs and checks open-file identity/change. Writes stage and fsync bytes before same-directory exclusive atomic linking;
existing input or output files are never overwritten. A staging write/publication
failure removes the owned temporary file and leaves the final output absent.
Source and destination directories must be trusted against concurrent filesystem
mutation. Symbolic-link ancestors are also refused.

Shapefile, arbitrary GIS formats, topological arc groups, interactive geometric
snapping, automatic reprojection, polygon booleans, grid property mapping,
original GMS feature replay and GPR writing are still absent. They remain open
features; these tests do not promote them or original equivalence.

## Reproduce

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_features.py -v
PYTHONPATH=src python examples/features/run_feature_example.py --output build/features-demo
PYTHONPATH=src python -m basinlens_ccs.subsurface.features check examples/features/local_coverage.json
PYTHONPATH=src python -m basinlens_ccs.subsurface.features move-node examples/features/local_coverage.json b 12 0 build/features-edited.json
PYTHONPATH=src python -m basinlens_ccs.subsurface.features select examples/features/local_coverage.json --kind polygons
```

The example checks exact local and WGS 84 metadata/noding roundtrips, an atomic
node move, explicit arc sampling, a grid frame, independent square-minus-hole
arithmetic (96 m² area, 48 m perimeter), and a 20 m arc. All geometry/attributes
are authored synthetic fixtures. `invalid_self_intersection.json` is deliberately
rejected. The original GMS comparison status remains `NOT_OBSERVED`.
