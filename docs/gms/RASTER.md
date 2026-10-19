# Raster data operations

Implemented scope: a bounded, explicit-metadata pixel-centre raster, its own JSON
format, and square-pixel Esri ASCII exchange. This does not establish original
GMS equivalence, whole GIS coverage, or a groundwater/CCS/oil simulation result.
GeoTIFF, remote GIS services, arbitrary image formats, reprojection, rotations,
colour channels and categorical resampling are not implemented here.

## Metadata and coordinates

`basinlens-raster-v1` requires an asset identity, literal CRS, vertical datum,
coordinate unit `m`, a supported quantity/unit pair, source/assumption provenance,
finite numeric NODATA sentinel, exact dimensions, lower-left outer-corner XY,
and positive `dx_m` / `dy_m`. Supported quantities include head/elevation `m`,
recharge `m/day`, and the existing typed rock properties with their exact SI units.
Missing cells are JSON `null`; finite valid values cannot equal the chosen
sentinel. A file name or sidecar never implies a CRS or unit conversion.

Rows are explicitly **north to south**. For stored row `r`, column `c`,

- `x = xllcorner_m + (c + 0.5) * dx_m`
- `y = yllcorner_m + (nrow - r - 0.5) * dy_m`

These are point samples at pixel centres. The algorithms do not claim to
conserve areal averages or cell-integrated mass. The shared project uses the
opposite row direction; `sample_project_property` queries its physical cell
centres in their original south-to-north ordering and repeats a 2D field through
its declared layers. It requires exact CRS/datum/metre/quantity/unit agreement,
a registered SHA-256 binding the canonical raster JSON bytes, complete support
at every model cell centre, and valid typed property bounds. It returns an
`interpreted` `RockProperty`; it does not mutate the project, claim measurements,
choose geological support or run a solver.

Geometry bounds: 100,000 total cells; at most 10,000 per axis; origins and outer
extent within ±1e9 m; step 1e-6..1e6 m. Origin/extent ULP must be at most 1e-8 of
the corresponding step, and adjacent centres/boundaries must remain distinct.
This explicitly rejects poorly represented large-origin/tiny-pixel grids.
Exact represented grid centres/boundaries snap to their corresponding indices;
nearby `nextafter` points retain their own position. No fuzzy extrapolation is
introduced by this numerical rule.

## File contracts

[Esri ASCII specification](https://desktop.arcgis.com/en/arcmap/latest/manage-data/raster-and-images/esri-ascii-raster-format.htm),
checked 2026-10-19, defines NCOLS/NROWS, matching XLLCORNER/YLLCORNER or
XLLCENTER/YLLCENTER, CELLSIZE, optional NODATA_VALUE (default -9999), and a data
stream beginning with the northern row. The implementation normalizes centre
headers to outer corners, preserves data order, and rejects mixed centre/corner
headers, duplicates, unexpected tokens, nonfinite numbers and count mismatches.
CELLSIZE is square: a rectangular own-JSON grid must be explicitly resampled
before ASCII export. No nonstandard DX/DY extension is silently accepted.

`read_ascii(path, metadata=...)` requires exactly these caller-supplied metadata
fields: `asset_id`, `crs`, `vertical_datum`, `coordinate_unit`, `quantity`, `unit`,
`provenance`. ASCII geometry alone cannot supply them. The own JSON format
preserves all metadata and rectangular geometry directly.

`export_ascii_bundle(grid, fresh_directory)` creates `grid.asc` plus
`metadata.json`. The sidecar binds exact ASCII bytes to complete raster metadata
and geometry. `open_ascii_bundle` requires precisely those two regular files,
verifies hashes, parses the actual ASCII, and rejects disagreement with the
sidecar. This sidecar is our own interchange contract, not a GMS format.
`verify_roundtrip` actually writes, reopens and compares JSON and ASCII values
and metadata in temporary storage; it never invokes GMS or any solver.

Reads reject symlinks including ancestor paths, FIFOs/devices, empty files,
changes during reading, and files above 16 MiB. Writes require fresh paths and
existing parents. JSON duplicate keys, unknown fields, booleans as numbers and
nonfinite values are rejected. Metadata bundles are staged and checked before
publication. A publish interruption can leave an incomplete owned directory;
opening it fails without a success receipt. Keep it for diagnosis and retry at
a fresh path. Outputs never replace source files.

## Spatial operations

| Operation | Explicit contract |
|---|---|
| Nearest query | Half-open outer extent `[W,E) × [S,N)`; physical ties choose east/north; outside is null |
| Bilinear query | Closed centre rectangle; outside is null; any positive-weight missing neighbour makes the result null; zero-weight missing neighbours do not invalidate an exact centre |
| Resampling | Query target pixel centres with the requested nearest/bilinear method; rectangular target geometry and unsupported mask remain explicit |
| Clipping | Keep source cells with positive-area bbox overlap; touching cells are excluded; full cell samples/extents retained; no resampling |
| Merge | Identical step, exact represented integer-cell origin alignment, literal CRS/datum/quantity/unit match; conflicts explicitly `error`, `first`, or `last`; NODATA never replaces valid data; gaps stay null |
| Raster to scatter | One valid pixel-centre/value record per supported cell, original row/column, metadata and canonical source hash |
| Catalogue | At most 64 assets; exact ID/path/hash/byte count/extent/CRS/datum/quantity/unit; reopening rehashes and reparses all registered assets |

Catalogues permit only own raster JSON files under their parent directory,
reject duplicate IDs/paths, traversal and symlinks, and impose aggregate bounds
of 64 MiB and 1,000,000 decoded cells. A merger additionally caps total source
and output cells at 100,000. Every derived raster records its operation in
bounded provenance. Maximum provenance depth is 64; an over-budget history is
rejected rather than truncated.

## Actual synthetic checks and recovery

`tests/test_raster.py` currently executes **32 tests, zero skips**. Independent
checks include a constant field, a hand-derived linear field
`f(x,y)=2(x-100)+3(y-200)`, half-pixel offset sampling, northern/southern row
labels, all overlap policies, gap masks, full-cell clipping area, two-layer
model-field ordering, corruption and missing/extra assets, finite NODATA,
non-square export refusal, symlink/FIFO refusal, source-path replacement during
a read, huge numbers, and actual CLI
subprocesses.

Two independent peer reviews found precision bugs before integration:
large-origin/tiny-step centre loss, and a decimal exact clipping boundary that
included the merely touching prior cell. The ULP-relative geometry bound and
exact represented centre/boundary rules now have regressions, including adjacent
`nextafter` points. An injected sidecar-write failure leaves no accepted output;
retry to a fresh path succeeds. An attempted CLI receipt overwrite returns exit
2, preserves the old receipt, and succeeds with a new path.

The executable example actually saves/reopens JSON/ASCII, checks independent
linear and constant fields, clips/merges back to identical values/extent,
reopens three catalogue assets and emits six scatter centres. Its authored
reference receipt is in `examples/raster/expected_receipt.json`. Source bytes
remain unchanged. These are synthetic software/numerical checks; original GMS
comparison is `NOT_OBSERVED`.

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_raster.py -v
PYTHONPATH=src python examples/raster/run_example.py build/raster-example-1
PYTHONPATH=src python -m basinlens_ccs.subsurface.raster roundtrip examples/raster/linear_head.json build/raster-receipt-1.json
PYTHONPATH=src python -m basinlens_ccs.subsurface.raster resample examples/raster/linear_head.json examples/raster/target_geometry.json build/resampled-1.json --method bilinear
PYTHONPATH=src python -m basinlens_ccs.subsurface.raster query examples/raster/linear_head.json examples/raster/query_points.json build/queries-1.json --method bilinear
```

All output paths above must be absent. The module CLI also exposes
`import-ascii`, `export-ascii`, `open-ascii`, `clip`, `merge`, `scatter`, `catalog`
and `verify-catalog`; each subcommand has `--help`.
