# One supported Quadtree/XmUGrid mesh representation

`groundwater.gpr_unstructured.read_gpr_quadtree(path, grid_group)` reads an
explicitly selected `Geometry.xmsgrid` byte vector through the shared bounded
HDF5 storage reader. It returns physical XYZ points, every cell's face-node
indices, upper/lower faces, and explicit cell elevation/layer arrays. Input
SHA256 is checked before and after inspection. `receipt()` publishes counts,
hashes, validation results, and limitations without raw coordinates, UUIDs,
project names, or HDF5 paths.

This original reader supports only the representation measured in one private
official MODFLOW 6 conceptual tutorial: `Binary QuadtreeGrid3d Version 1`,
three dimensions, zero angle, `KIJ` numbering, the observed decreasing-Y /
increasing-X / decreasing-Z orientation, `NUM_LEVELS 0`, one vertical interval,
and an embedded `Binary XmUGrid Version 2` body. Other refinement levels,
wrappers, layers, or cell types are explicitly unsupported.

## Protocol and topology

The public primary protocol reference is Aquaveo's BSD-licensed
[XmUGridUtils.cpp](https://github.com/Aquaveo/xmsgrid/blob/7045701d1736f87f61572c1ea6a4178864214bd0/xmsgrid/ugrid/XmUGridUtils.cpp),
with cell identifiers in
[XmUGrid.h](https://github.com/Aquaveo/xmsgrid/blob/7045701d1736f87f61572c1ea6a4178864214bd0/xmsgrid/ugrid/XmUGrid.h).
The type-42 polyhedron stream consists of a cell type, face count, and each
face's point count followed by its node indices. The current reader accepts
exactly six quadrilateral faces: 32 little-endian int32 values per cell.
No upstream implementation or proprietary implementation was copied.

The existing original bounded block reader decodes base64/zlib numeric vectors.
Limits include a 32 MiB packet, 64 MiB total decoded vectors, 1 MiB decoded
blocks, 100,000 cells, 500,000 points, and two million items per opaque wrapper
array. Counts, finite values, block boundaries, node-index ranges, and exact
record completion are checked before returning a mesh.

Every supported cell must have eight distinct nodes, twelve edges used twice
with opposite directions, one horizontal upper face and one horizontal lower
face matching its explicit elevations, a convex quadrilateral footprint, and
the four corresponding vertical side faces. Repeated cells are rejected.
Globally, a face can have at most two owners and shared face winding must be
opposite. These checks verify the supported connectivity; they do not attest
to general mesh quality, an arbitrary overlapping-cell analysis, or numerical
model correctness.

The wrapper origin, parametric axes, and two `QUAD_GRID_*` arrays remain private
metadata. Their array counts are checked, but values are opaque and never used
as pointer indices. No wrapper-origin, axis, vertical, unit, or coordinate-system
transformation is applied. Physical coordinates are the embedded XmUGrid
locations, unchanged. Coordinate units, CRS, and vertical datum remain unknown.

## Literal native DISV comparison

`compare_with_disv(mesh, model)` compares a separately loaded single-layer
native MODFLOW 6 DISV model. It uses declared native cell IDs against stored GPR
cell-stream indices; no spatial remapping is chosen. All quadrilateral cell
footprints are compared allowing cyclic starting points and reversed winding.
The complete unique physical XY vertex set is also checked. Single-layer
connectivity requires one upper/lower physical node pair per XY vertex and no
unused nodes; equal coordinates cannot hide disconnected duplicated nodes.
Native declared
offset/rotation options are handled by public FloPy's native grid transform;
the GPR wrapper origin is not applied.

Every upper/lower physical corner Z is compared with its native cell's
top/bottom scalar. Native reference centers are compared with GPR corner means
as a separately labelled diagnostic; the GPR packet supplies no independent
declared center field. No interpolated shared-node native Z surface is invented.
`full_3d_mesh_coordinate_match` requires matching polygons, all XY vertices,
node-pair topology, and all corner elevations. It does not establish physical or runtime equivalence
when GPR units, datum, and other model-state semantics are unknown.

## Independent official case and observed mismatch

The input came from the official
[mf6_conceptual.zip](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/mf6_conceptual.zip).
Its stored `GMS Version` attribute is 10.7.0, without proving an original creator
or observed runtime. Source ZIP/GPR/packet and native input identities are in
[unstructured_validation_record.json](unstructured_validation_record.json).
No tutorial payloads, raw coordinates, or vendor source are distributed.

The reader recovered 20,684 physical nodes and 9,976 closed polyhedron cells.
All 9,976 same-index horizontal footprints and all 10,342 unique XY vertices
match the independently loaded saved native DISV input exactly. It verified
20,682 boundary faces and 19,587 shared faces, at most two owners per face,
and no unused nodes. The native reference-center/corner-mean diagnostic differs
by at most approximately `1.1642e-10` in literal coordinates.

The GPR and saved native model have different vertical states: maximum upper
corner difference is 30 and lower corner difference is 75. Therefore the full
3D mesh match is **false**. The native input declares meters; GPR geometry units
remain unknown, so those discrepancies are raw coordinate differences without
unit conversion. This reader preserves the mismatch and applies no repair,
shift, or synchronization. Exact horizontal agreement does not establish an
equivalent geological model.

Eight synthetic tests use independently constructed two-cell prism packets and
public FloPy DISV inputs. They cover all faces/vertices and shared topology,
opaque wrapper values and unapplied origins, changed native edges/offsets,
same-XY/different-Z rejection of a full match, invalid faces/indices/winding/
types/nonfinite values, truncated/unsupported records, independent size limits,
disconnected duplicated-node detection, and unchanged input identity. No solver
or GMS executable was run.

This is narrow file interoperability evidence. Adaptive refinement, arbitrary
polyhedra, multilayer meshes, QUAD pointer/layer semantics, GPR writing,
project synchronization, numerical equivalence, and whole-product reconstruction
remain outside the verified scope.

## Saved-data workbench view

The GPR section now offers an explicit representation choice: the existing
rectilinear format or this measured level-zero/single-layer Quadtree format.
The app calls only the chosen decoder; unsupported representations fail without
heuristic fallback. Display points are physical upper/lower vertex means,
computed from the selected face corners without building a large face tensor.
Raw scalar fields use the existing size/count/finite/precision limits; their
physical meaning and units remain unknown. No row/column indices are invented
for the unstructured view, and no wrapper transform is applied.

Four synthetic UI tests cover representation selection, wrong-format refusal,
raw-field validation and source identity. The actual private project rendered
all9,976 cells with no app errors, unchanged input bytes and preserved unknown
units/CRS/datum. No native DISV comparison or vertical repair runs in the viewer.
[unstructured_ui_validation_record.json](unstructured_ui_validation_record.json)
preserves that separate read-only UI check.
