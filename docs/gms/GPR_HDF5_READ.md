# Read-only GPR/HDF5 interoperability

`groundwater.gpr_hdf5.inventory_gpr(path)` inventories a GMS project as HDF5.
It reads group names, dataset shapes/types, attribute names, filter IDs, and link
metadata. It does not load dataset payloads or follow soft/external links.
Hard-link aliases are recorded without repeated traversal.

```bash
pip install h5py
python -m basinlens_ccs.groundwater.gpr_hdf5 /path/project.gpr
```

`read_gpr_numeric_array(path, "/explicit/dataset/path")` returns one selected
numeric array and its storage descriptor. Reads are bounded to 32 MiB and reject
indirect links, virtual datasets, external raw storage, variable-width objects,
and plugin filters. Payload reads support unfiltered storage or a single deflate
filter. Shuffle, Fletcher32, mixed filters, sparse/unallocated storage, and
noncanonical numeric file datatypes are explicitly unsupported. No unit or
coordinate transformation is inferred.

Chunked payloads are assembled from bounded raw chunks and decoded with an
output-limited zlib stream, rather than HDF5's decompressor. The reader checks
stored chunk bytes/count/masks, full edge-chunk and aggregate decoded bytes,
coordinate coverage, and exact stream completion. This rejects chunks that
inflate beyond their advertised size. The descriptor includes a storage-read
receipt. See [GPR_PROJECT.md](GPR_PROJECT.md) for the shared storage limits and
independent malformed-chunk regressions.

## Original format observations

The official [MODFLOW 6 Grid tutorial ZIP](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/mf6_grid.zip)
has SHA-256 `ad5d7684e9c6270a9a2a129430b04cc0c6bd39ba03a73f1c21825e3fa3e87dd4`.
Its `mf6-solution.gpr` is an HDF5 file with SHA-256
`afb9d3dd71f29d0cbb83dc5eee27c342b1ea75e86a9bd1bec06e860b2c6b4467`.
The source sample remains private and is not distributed with this repository.

The inspected sample contains 1,827 HDF5 objects: 272 groups and 1,555 datasets.
The fixed root attribute `GMS Version` says `10.8.2`; the tutorial index is 10.9,
so the index version must not be treated as the creator/runtime version.
The `File Type` dataset identifies XMDF. The observed top-level groups include
`Project`, `Coordinates`, `Tree`, `SimSolutions`, and `UnstructuredGridModule`.

| Observed structure | Storage contract |
| --- | --- |
| `UnstructuredGridModule/<grid>/Geometry.xmsgrid` | Compressed signed-byte geometry packet. It remains opaque to this storage helper; the separate [geometry decoder](GPR_GEOMETRY.md) supports one verified rectilinear v1/XmUGrid v2 representation. |
| `<grid>/GridCellProps/Material` | Integer material data by cell. |
| `<grid>/Datasets/<field>/Values` | Numeric time-by-location array. |
| `<grid>/Datasets/<field>/Active` | Active-state time-by-location array. |
| `<grid>/Datasets/<field>/Times` | Numeric time coordinates. |
| `Tree/Tree` | String records; the separate [partial project reader](GPR_PROJECT.md) supports balanced observed hierarchy and anonymous node categories. |
| `SimSolutions/<model-family>/<simulation>` | UUID references; the partial reader reports literal equality edges and explicit unresolved relationships. |

The sample head data is `float32` with shape `(1, 1125)` and exactly equals the
shipped native `float64` head output converted to `float32`. The maximum
difference before conversion is approximately `3.804156e-6` in the native head
units. This establishes one concrete storage mapping, not full GPR equivalence.

Metadata must be preserved literally: the sample head group has an empty
`DatasetUnits` attribute, `TimeUnits=Days`, and a stored time value of `86400`.
The native solver export separately declares feet and seconds. The reader does
not choose a conversion or infer that every metadata context is synchronized.

The new importer has been exercised on this actual container and on independent
synthetic HDF5 files. Tests cover link cycles, external storage, virtual datasets,
unavailable filters, explicit numeric reads, and bounds. No GMS executable ran,
and project writing, complete geometry-format coverage, GUI state reproduction,
and GMS runtime parity remain unverified. The separate geometry decoder has
synthetic checks and a literal native-DIS comparison for the supported tutorial.
