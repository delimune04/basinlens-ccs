# Supported GPR geometry interoperability

`groundwater.gpr_geometry.read_gpr_rectilinear(project, grid_group)` now reads
one explicitly selected `Geometry.xmsgrid` byte dataset from an HDF5 GPR file.
The result contains physical node coordinates, hexahedron connectivity,
structured cell elevations, and a verified mapping to `(layer, row, column)`.
It hashes the entire input before and after inspection and rejects a changed
file. HDF5 reads retain the existing hard-link, numeric-type, built-in-filter,
and byte-budget boundaries.

The reader supports a deliberately narrow representation observed in the
official MODFLOW 6 grid tutorial. It rejects unsupported origins, rotations,
orientations, cell types, or inconsistent mappings. It does not write GPR files
or reconstruct a complete GMS project. Coordinate units, CRS, and vertical
datum remain unknown.

## Independent format implementation

The implementation is original Python. Protocol facts for the embedded grid
and compressed array framing were checked against public Aquaveo source:

| Component | Primary source and revision | Facts used |
| --- | --- | --- |
| XmUGrid v2 | [xmsgrid/XmUGridUtils.cpp](https://github.com/Aquaveo/xmsgrid/blob/7045701d1736f87f61572c1ea6a4178864214bd0/xmsgrid/ugrid/XmUGridUtils.cpp) | `LOCATIONS`, `CELL_STREAM`, optional cell-order record |
| Array blocks | [xmscore/daStreamIo.cpp](https://github.com/Aquaveo/xmscore/blob/503a9692186422fb0574fc1f0e75d32a3d435aef/xmscore/dataio/daStreamIo.cpp) | `BINARY_BLOCK encoded_length decoded_length`, base64, zlib |
| Cell identifiers | [xmsgrid/XmUGrid.h](https://github.com/Aquaveo/xmsgrid/blob/7045701d1736f87f61572c1ea6a4178864214bd0/xmsgrid/ugrid/XmUGrid.h) | Hexahedron identifier 12 and eight node indices |

Both public projects use BSD licenses. No upstream implementation was copied
into this reader. The outer rectilinear wrapper was derived from private,
read-only inspection of one official tutorial project; no vendor project or
program bytes are included in this repository.

| Supported record | Interpretation and validation |
| --- | --- |
| `Binary RectilinearGrid3d Version 1` | Three dimensions, zero origin, zero rotation only |
| `NUMBERING KIJ` | Layer, decreasing-Y row, increasing-X column |
| `ORIENTATION Y_DECREASE X_INCREASE Z_DECREASE` | Exact supported orientation |
| `LOCATIONS_X/Y/Z` | Increasing little-endian float64 parametric arrays |
| `Binary XmUGrid Version 2` / `LOCATIONS` | Actual little-endian float64 XYZ node coordinates |
| `CELL_STREAM` | Little-endian int32 records: 12, 8, eight node indices |
| `POINT_ELEVATIONS` | Must equal embedded node Z coordinates |
| `CELL_TOPS`, `CELL_BOTTOMS` | Must equal the means of their respective four physical face-node elevations |
| `CELL_LAYERS` | One-based layers; verified for every cell |

For node dimensions `(nz, ny, nx)`, the supported node index is
`k*ny*nx + row*nx + column`. Every cell's eight indices must match the
corresponding two adjacent node planes. Only after checking all cells does the
reader expose C-order arrays with shape `(nz-1, ny-1, nx-1)`. Optional embedded
`CELL_ORDER` must be `INCREASING_DOWN`.

The Z parametric axis does **not** supply physical elevations. In the examined
project it ranges from 0 to 10 while embedded physical Z ranges from -450 to
200. The decoder uses actual node coordinates and explicit elevations, with
no conversion or guessed unit assignment.

Input packets are limited to 32 MiB, total decoded arrays to 64 MiB, individual
decoded blocks to 1 MiB, and cells to one million. Base64 syntax, bounded
decompression, exact zlib stream boundaries, counts, finite numbers, topology,
and physical-coordinate consistency are checked before returning geometry.

## Actual tutorial comparison

The private input was downloaded from Aquaveo's official
[mf6_grid.zip](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/mf6_grid.zip).
Its GPR identifies its creator as GMS 10.8.2. The ZIP, project, and geometry
packet hashes are recorded in [geometry_validation_record.json](geometry_validation_record.json).

The original decoder recovered 1,536 nodes and 1,125 hexahedra in a 5×15×15
grid. A separate public FloPy load of the tutorial's saved native MODFLOW 6
DIS export supplied the comparison arrays. All 1,125 cell centers in X/Y/Z,
all cell tops and bottoms, and all 1,536 node XY coordinates matched exactly.
Native offsets and rotation are included in the XY vertex comparison. Every
physical GPR upper/lower face corner also matched its native cell's top/bottom
elevation, for 9,000 corner-elevation comparisons. All maximum absolute errors
were zero. This establishes the literal array correspondence for this case.
The native export declares feet; that does not establish the GPR geometry's
own unit metadata, CRS, or datum.

DIS stores cell top/bottom scalars rather than a unique shared-node Z surface.
The corner-Z comparison explicitly uses each cell's declared scalar elevation
as a flat-face interpretation; it creates no interpolated native vertices.
Nonflat GPR faces can decode, but cannot receive an exact match merely because
their average elevations agree with native cells. Center coordinates alone
also cannot establish matching footprints: every XY vertex must agree.

Nine focused tests use independently constructed synthetic packets and
HDF5 containers. They cover unequal-width cells, physical Z distinct from
parametric Z, all-cell connectivity validation, malformed and oversized blocks,
bounded decompression, unsupported records, immutable input identity, and an
independently constructed public DIS model. Regression cases distinguish grids
with identical centers but different edges, and nonflat faces with matching
means but different corner elevations. No tutorial bytes are test fixtures.

This is file interoperability evidence. It does not attest to a witnessed GMS
runtime session, complete GPR compatibility, or full GMS equivalence.
