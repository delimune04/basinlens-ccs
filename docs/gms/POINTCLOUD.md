# Bounded LAS point-cloud tools

This is an independently implemented subset. It has **no original GMS runtime
comparison** and does not close the full LiDAR, LAS, GIS or GMS feature scope.
All distributed point data are original synthetic fixtures, not survey measurements.

## Implemented file contract

`basinlens_ccs.subsurface.pointcloud` reads uncompressed LAS 1.2 point formats
0, 1, 2 and 3. It validates the 227-byte header, point offset and exact file
length, 20/28/26/34-byte records, positive finite scale factors, finite offsets,
actual coordinate extrema, all five return counters, global encoding and record
flags. Returns are 1..5; scan angle rank is -90..90. GPS time must be finite.

The reader retains the complete original prefix (header, opaque VLRs and padding)
and complete encoded point records. Integer XYZ, quantization scales/offsets,
intensity, return flags, classification flags, scan angle, user data, source ID,
GPS time and RGB remain intact. It computes coordinates as integer × scale +
offset without requantizing. Unknown VLR payloads are retained but **not
interpreted or synchronized** to changed points. The reader makes no claim about
those VLRs' application semantics. Formats outside 0..3, LAZ, extra point bytes,
extended headers, waveform records, trailing payload and newer LAS versions
are explicitly refused. Exact header extrema must equal decoded point extrema;
files with inconsistent or rounded bounds need an explicit repair outside this
reader, with the original retained.

Limits are 32 MiB per LAS, 200,000 stored points, 256 VLRs, 96 MiB own JSON,
200,000 aggregation cells and at most 20,000 rendered points. Reads reject FIFO,
nonregular files, final-component symlinks, growing inputs and over-budget data.
Writes require fresh paths; source bytes are never overwritten. A failed multi-file
roundtrip may leave its own incomplete diagnostic directory and must be retried
at a fresh path. Invalid input remains invalid; there is no silent repair.

Owner metadata is mandatory and literal:

```json
{
  "crs": "LOCAL:authored-planar",
  "horizontal_unit": "m",
  "vertical_unit": "m",
  "vertical_datum": "authored elevation zero",
  "provenance": ["Synthetic example; not a measurement"]
}
```

Units may be `m`, `ft` or `unknown`. Unknown values stay unknown. No CRS, unit,
height datum, georeferencing, survey accuracy or date is inferred from the
filename or opaque VLRs. No reprojection, unit conversion, GPS-time conversion,
terrain classification or ground-height normalization is performed.

## Editing, aggregation and identity

The own `basinlens-pointcloud-v1` JSON preserves all prefix/point bytes, owner
metadata and a unique `source-LAS-SHA256:original-index` identity for each point.
`PointCloud.from_dict/to_dict` and `load_pointcloud/save_pointcloud` are the
portable integration API; they have no external file dependencies.

- `filter_points`: classification, inclusive XY bounding box, inclusive raw
  elevation interval, return number and optional withheld exclusion. It retains
  exact records and original identities, records filter criteria in provenance,
  and updates LAS header totals/extrema. Classification tests the lower five bits;
  synthetic/key-point/withheld flags are independent.
- `merge_pointclouds`: concatenate without rescaling or reprojecting; reject
  duplicate source identities or incompatible owner CRS/units/datum, scales,
  offsets, GPS encoding, opaque VLR bytes or other header contract. Headers must
  match except point totals/extrema; this is deliberately narrower than general
  LAS merging. Source histories are retained. Extraction/merge header labels
  identify the operation and BasinLens writer.
- `aggregate_grid`: bin elevation or intensity by count, minimum, maximum or
  mean. Grid row zero is south; domain is `[xmin,xmax) × [ymin,ymax)`. Internal
  edges go to the cell to the north/east, including exactly represented decimal
  grid boundaries. Empty cells have `null`, count zero and false support;
  they are never interpolated. Every retained and excluded source identity is
  recorded. CRS, horizontal units and datum must agree literally; unknown CRS
  and horizontal units block aggregation. Vertical units remain explicit.
- `render_points`: deterministic index-stride view decimation returns original
  indices/identities and never changes stored points. This is a bounded display
  sample, not statistical downsampling or a new point cloud.

Grid spacing must be positive and sufficiently resolved at the chosen origin
(maximum origin/extent ULP ≤ spacing × 1e-8). Inadequate floating-point precision
is rejected instead of assigning points to an unreliable grid.

A standalone LAS has no field for the retained per-point source identities or
this owner metadata contract. **Keep the own JSON alongside exported LAS.**
`verify_pointcloud_roundtrip` actually writes/reopens both: it checks exact LAS
prefix/point bytes and exact own JSON metadata/identity equality. This is a
file check, not GMS parity or survey validation.

## Run

```bash
python examples/pointcloud/run_pointcloud_example.py --output build/pointcloud-example
python -m basinlens_ccs.subsurface.pointcloud inspect examples/pointcloud/synthetic_points.json
python -m basinlens_ccs.subsurface.pointcloud filter examples/pointcloud/synthetic_points.json build/class2.json --classes 2
python -m basinlens_ccs.subsurface.pointcloud export build/class2.json build/class2.las
python -m basinlens_ccs.subsurface.pointcloud roundtrip build/class2.json build/class2-roundtrip
python -m basinlens_ccs.subsurface.pointcloud import-las build/pointcloud-example/authored.las build/imported.json --metadata build/pointcloud-example/metadata.json
```

The CLI additionally provides `merge` and `rasterize --grid grid.json` (grid JSON
contains the exact `aggregate_grid` keyword arguments). Parent directories must
exist; each output must be fresh. `--help` exposes all supported options.

## Evidence and review

The 16 tests in `tests/test_pointcloud.py` independently assemble LAS records
with literal ASPRS legacy offsets, known integer/scale/offset coordinates,
flags, RGB and GPS values. They check all four formats, unchanged LAS bytes,
exact JSON/identity roundtrips, selected attributes, empty selection, disjoint
merge, known bin means/min/max/counts, decimal and outer grid edges, unsupported
masks, render-only decimation, malformed headers/records, duplicate/deep JSON,
FIFO/symlink refusal, byte budgets and actual CLI failure/recovery. These tests
passed with zero skips. The example executed and retained six identities, exact
source bytes and the independently expected grid means 100/100/110.

A separate raster implementer reviewed encoded layouts and failure contracts.
Review found floating-point grid precision and contradictory JSON sidecars;
these were fixed and regression checked before integration. No original GMS
session or real survey/CRS transformation was tested.

## Primary specification basis (checked 2026-10-19)

The original ASPRS LAS 1.2 PDF URLs indexed by search returned HTTP 404 during
this implementation. The official ASPRS Working Group repository's maintained
LAS 1.4 source explicitly retains the legacy point record layouts and the LAS
1.2 global encoding distinction. Those primary sources were fetched at commit
`c5bdb7df3153b14dea7a90a89d929f6e8fef9f5e`:

- [ASPRS legacy point record definition](https://github.com/ASPRSorg/LAS/blob/c5bdb7df3153b14dea7a90a89d929f6e8fef9f5e/source/02.06_point.sub),
  SHA-256 `161fdfb3e3b0c11c366b5dfce01d60f060dcd3f60de8a64609ca95179515af07`.
- [ASPRS header definition and LAS 1.2 encoding note](https://github.com/ASPRSorg/LAS/blob/c5bdb7df3153b14dea7a90a89d929f6e8fef9f5e/source/02.04_header.sub),
  SHA-256 `2f795a8dffe2eae4267a5850ee3de4c17cfb24c3c8ff36afdd6cd4b339afee32`.

No upstream program code or proprietary point cloud is distributed. The module
supports LAS 1.2 files only; consulting a newer specification's legacy sections
does not imply newer LAS support or full conformance certification.
