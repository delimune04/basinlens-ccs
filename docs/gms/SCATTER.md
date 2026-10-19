# Scalar scatter data and deterministic interpolation

This independent implementation supports versioned 2D/3D scalar point datasets,
point value edits, bounded dataset arithmetic, nearest and inverse-distance
weighting (IDW), and linear interpolation inside explicit user-supplied 2D
triangle connectivity. It is a **partial scatter/interpolation workflow**. It is
not a full GMS scatter/geostatistics implementation, native GMS file format,
kriging, fitted variogram, uncertainty estimate or original-program comparison.
No field validation or CO2/oil fluid physics is implied.

## Data and file contract

`basinlens-scatter-v1` JSON requires exact keys: `schema`, `id`, `dimension`,
`coordinate_unit`, `crs`, `vertical_datum`, `vertical_axis`, `quantity`,
`value_unit`, `basis`, `provenance`, `duplicate_coordinate_policy`, `points`.
All coordinate units are literal `m`; XYZ uses `positive_up`, XY uses
`not_applicable`. Literal CRS/datum strings are preserved, including an explicit
unknown label. No transformation or inference follows from such labels. Scalar
quantity and unit are explicit text; no guessed conversion occurs.

Each point has `id`, `coordinates_m`, `value`, `missing_reason`. A missing value
is JSON null plus an explicit reason. A finite value requires null missing
reason. Duplicate IDs or exact coordinate tuples are rejected, including missing
observations. Input coordinate magnitudes are bounded by 1e9 m; scalar magnitudes
by 1e100. Explicit basis is synthetic/measured/interpreted/assumed. All supplied
provenance is preserved; an edit that would exceed 32 provenance records fails
instead of discarding history. Value edits set basis to interpreted and bind the
parent semantic SHA-256. Original data remain immutable.

The CSV is self-contained: its first line is `# basinlens-scatter-v1 ` followed
by compact JSON metadata without `points`. The exact header is
`id,x_m,y_m[,z_m],value,missing_reason`. Empty value means missing, with a required
reason. Python's roundtrippable numeric text preserves IEEE double values, and
normal CSV quoting preserves literal IDs. This is our own format; arbitrary
column mappings and native GMS scatter formats remain unsupported.

Both JSON and CSV are bounded to 16 MiB and 20,000 points. Reads reject symlinks,
FIFO/device/directory inputs and changed files. Writes stage and atomically
publish fresh files, refuse existing destinations and require an existing parent.
The roundtrip verifier loads both written formats and compares the entire typed
semantic dataset, including metadata, support, values and missing reasons. It
does not execute a solver or establish a native GMS roundtrip.

## Numerical methods and explicit support

IDW uses `sum(value_i * d_i^-p) / sum(d_i^-p)` for a positive explicit power
(up to 16), retaining only nonmissing source values within the selected radius
and at most `max_neighbors`. Internally weights are divided by the nearest
weight, preserving the formula while avoiding overflow. An exact coordinate hit
returns its exact source value. An exact missing source remains unsupported;
nearby values do not overwrite it. Minimum-neighbor failures remain unsupported.
Nearest is the one-neighbor case. Equal distances break by literal point ID.

3D distance is `sqrt(dx²+dy²+(vertical_scale*dz)²)`; the positive scale is an
explicit dimensionless modeling choice. The radius is measured in this scaled
metric. No geological anisotropy is inferred. A nonexact distance that underflows
floating point is rejected. There is no angular anisotropy or barrier model.

Default `bounds_policy="mask"` masks queries outside the axis-aligned bounds of
all source coordinates. This box is **not** a convex hull or physical boundary.
`"allow"` explicitly permits distance-weighted values beyond that box, with the
outside flag retained. The selected neighborhood and truncation flags are
reported for every query. Null radius explicitly selects unlimited search.
The result contains a dataset identity, settings, source counts, support mask and
reasons; IDW/nearest provide no prediction uncertainty.

Linear TIN evaluates barycentric weights only within user-provided triangles.
No Delaunay construction is claimed. Triangles must reference distinct existing
point IDs. Duplicate connectivity, degenerate/ill-conditioned triangles,
non-manifold edges and overlapping interiors are rejected. Intersection-area
checks use relative tolerance 1e-10; barycentric inclusion tolerance is 1e-12.
Disconnected components are permitted, with gaps unsupported. Barycentric weights of magnitude at most 1e-12 snap to zero. Missing vertices
with remaining nonzero support mask the result; a zero-weight missing vertex does not mask
an exact observed point or supported edge. Outside triangles remain unsupported.
TIN supports at most 1,024 triangles and has bounded pairwise topology checking.
All interpolation methods reject more than 20,000 queries or 2,000,000
query/source (TIN: query/triangle) comparisons. Submit explicit smaller batches;
no silent truncation of query requests occurs.

## Dataset arithmetic

Only literal `+`, `-`, `*`, `/` are accepted; no expression evaluation occurs.
Operands require equal coordinate contracts and exactly equal point-ID/coordinate
support (record order may differ). Addition/subtraction require identical
quantity and unit. Multiplication requires a dimensionless operand; division
requires a dimensionless divisor or matching quantities/units, yielding `ratio`
with unit `1`. Other compound-unit operations are refused. Result metadata must
match the derived quantity/unit. Missing operands propagate missing results;
evaluated division by zero and nonfinite/over-budget results fail. Computed
provenance binds both parent identities.

## API and examples

```python
from basinlens_ccs.subsurface.scatter import (
    load_scatter, save_scatter, verify_scatter_roundtrip,
    interpolate_idw, interpolate_nearest, interpolate_tin,
    edit_values, dataset_math,
)
points = load_scatter("examples/scatter/synthetic_plane.json")
result = interpolate_idw(points, [[0.25, 0.25]], power=2,
                         max_neighbors=4, min_neighbors=1,
                         radius_m=None, vertical_scale=1, bounds_policy="mask")
assert result["rows"][0]["supported"]
```

Run each command with a fresh output path:

```bash
python examples/scatter/run_scatter_example.py --output build/scatter-example
python -m basinlens_ccs.subsurface.scatter load examples/scatter/synthetic_plane.json --output build/scatter-points.csv
python -m basinlens_ccs.subsurface.scatter roundtrip build/scatter-points.csv --output build/scatter-roundtrip.json
python -m basinlens_ccs.subsurface.scatter query examples/scatter/synthetic_plane.json examples/scatter/queries_2d.json --method tin --triangles examples/scatter/triangles.json --output build/scatter-tin.json
python -m basinlens_ccs.subsurface.scatter math examples/scatter/synthetic_plane.json + examples/scatter/synthetic_plane.json --id doubled --quantity hydraulic_head --unit m --output build/scatter-double.json
python -m unittest discover -s tests -p test_scatter.py -v
```

The synthetic affine fixture has `f(x,y)=1+2x+3y`. Tests independently check
linear TIN against this expression, IDW against hand-calculated distances
0.25/0.75 and weights 16/(16/9), and 3D vertical scaling against values 2 and 5.
Other checks cover constants/exact hits, missing/outside/radius masks, duplicate
support, units, zero division, topology/degeneracy, large-data budgets, portable
roundtrips, immutable edits, fresh publication, actual CLI failure and recovery.

Primary algorithm references checked 2026-10-19:

- [Esri, How inverse distance weighted interpolation works](https://pro.arcgis.com/en/pro-app/3.5/help/analysis/geostatistical-analyst/how-inverse-distance-weighted-interpolation-works.htm):
  distance-power weighted local interpolation, exactness, neighborhood sensitivity
  and absence of prediction standard errors. This implementation is independently
  authored and does not claim the Esri neighborhood/GUI behavior.
- [QGIS 3.44, GDAL raster analysis: Linear](https://documentation.qgis.org/3.44/en/docs/user_manual/processing_algs/gdal/rasteranalysis.html):
  linear interpolation using barycentric coordinates inside triangles. Our
  implementation requires user connectivity instead of building Delaunay.
