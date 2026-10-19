# Structured result analysis and manual head comparisons

This independently authored module samples the existing bounded spatial-water
workflow. It implements volume queries, polyline sections, cell visibility and
manual head residual diagnostics. It does not implement full GMS visualization,
isosurfaces, parameter optimization, PEST, native GMS animation, general meshes,
CO2/oil multiphase physics or original-product equivalence.

## Reproduce

Use a fresh directory and an explicitly installed real MODFLOW 6 executable:

```bash
python examples/analysis/run_analysis_example.py --output build/analysis-example --exe /absolute/path/to/mf6
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -p test_results_analysis.py -v
python -m basinlens_ccs.subsurface.analysis section build/analysis-example/water-run --polyline '[[105,210],[145,210]]' --z '[-5,-20]' --spacing 5 --time 1 --output build/another-section
python -m basinlens_ccs.subsurface.analysis compare build/analysis-example/water-run build/analysis-example/synthetic-observations.json --output build/another-comparison
```

No solver is downloaded. The example creates a real MF6 run from the existing
authored layered example, loads its captured input and output, exports verified
CSV/JSON sections/clipping/comparison, and generates sampled section frames.
The comparison is deliberately **synthetic**: a prescribed 12 m model head is
compared with an authored 11.5 m value and 0.25 m sigma. The independently known
residual is +0.5 m and objective 4. It is not a field observation or calibration.

## API and support

```python
from basinlens_ccs.subsurface.analysis import (
    load_analysis_run, write_analysis_bundle, verify_analysis_bundle,
)
volume = load_analysis_run("captured-workflow-run")
result = volume.section([[105, 210], [145, 210]], [-5, -20], 5,
                        time_day=1, spatial_method="cell")
folder = write_analysis_bundle(result, "fresh-analysis-folder")
verify_analysis_bundle(folder)
```

| Operation | Implemented support |
|---|---|
| `query(points_xyz_m, field="head_m", time_day=None, spatial_method="cell", temporal_method="exact")` | Explicit XYZ samples; field values, support mask and containing-cell indices |
| `section(polyline_xy_m, z_m, spacing_m, **query_options)` | Regular chainage plus every vertex/end point, explicit fixed Z selections, segment indices and unchanged unsupported samples |
| `clip(field="head_m", time_day=None, scalar_min=None, scalar_max=None, plane=None, visibility=None)` | AND scalar inclusive bounds, plane half-space and explicit boolean cell mask |
| `section_frames(frames, **query_options)` | Up to 100 explicitly positioned/timed sampled sections; data only, no video renderer |
| `compare_observations(document, temporal_method="exact")` | Explicit indexed-cell manual head comparisons; no fitted parameters |

The volume is unrotated, uniform in X/Y, flat layered, all-active and indexed
`[layer,row,column]`; rows increase south to north, Z increases upward. Supported
fields are `head_m`, `kx_m_day`, `ky_m_day`, `kz_m_day`, `ss_per_m`, `porosity`.
Material fields are static metadata and require `time_day=None`; porosity is not
a confined GWF flow/storage coefficient. Sampling is not physical validation.

### Spatial support

- `cell`: piecewise constant value in the containing cell. Ownership is
  `[xmin,xmax)`, `[ymin,ymax)`, `(bottom,top]`. An internal horizontal layer
  interface belongs to the layer below. The final lower/outside edges remain
  unsupported; coordinates are never clamped into the grid.
- `linear_centres`: trilinear interpolation within the Cartesian box spanned by
  cell centres. Unequal vertical layer-centre distances are respected. A
  singleton axis supports only its centre within an explicit absolute 1e-9 m
  tolerance. No extrapolation toward grid edges or beyond the box occurs.
- Unsupported values are JSON `null` with `supported=false`. Returned cell IDs
  identify the containing cell; they do not list every interpolation vertex.
- Sections keep unsupported sample rows. Sampling along a line is not a cut-cell
  mesh or a continuous geological interpretation.
- Clipping uses **whole-cell centre visibility**. Plane coefficients mean
  `nx*x_m + ny*y_m + nz*z_m + offset_m >= 0`; all masks combine by logical AND.
  No cell/plane intersections, clipped polyhedra or isosurfaces are generated.

### Temporal support

Head query/section/clip `time_day=None` explicitly defaults to the last captured
saved time, which is recorded in the result. `exact` requires exact equality
with a captured time. `linear` must be requested and interpolates only between
adjacent saved times; indices, times and weight are recorded. No extrapolation
before/after the saved interval occurs. A manual observation must provide its
own finite time; `null`/boolean/missing times are rejected, never defaulted.

## Observation document and equations

Own schema `basinlens-head-observations-v1` requires exactly `project_id`,
`case_sha256`, literal `crs`, literal `vertical_datum`, `units={"head":"m",
"time":"day"}` and an `observations` list. Each observation requires unique
`id`, `time_day`, `cell=[layer,row,column]`, `head_m`, positive `sigma_m`,
`basis=synthetic|measured|interpreted`, and explicit `provenance`. No automatic
unit/CRS/datum conversion or nearest-time association occurs. The case hash
prevents relabelling another case as this run. An `unknown` label remains
unknown; exact literal equality with indexed-cell support does not establish
georeferencing or observation representativeness.

Residual `r_i = h_simulated,i - h_observed,i`. The reported metrics are:

- bias `mean(r_i)`;
- RMSE `sqrt(mean(r_i²))` and MAE `mean(abs(r_i))`;
- weighted RMSE in metres `sqrt(sum(w_i*r_i²)/sum(w_i))`, `w_i=1/sigma_i²`;
- objective `sum((r_i/sigma_i)²)` and normalized RMSE `sqrt(objective/N)`.

Sigma weights are user declarations. These equations do not infer independence,
distribution, parameter uncertainty, statistical acceptance or calibration
success. There is no optimizer, Jacobian, PEST linkage or parameter fit.

## Identity, budgets and verification limits

`load_analysis_run` uses the existing full native run verifier and captured-case
reader, rechecks the inventory, then captures immutable byte-backed head/time
arrays and canonical case/preview metadata. Source identities include canonical
case/array hashes, captured settings hash, native head binary hash, complete
native input identities, solver identity and run metadata hash. A caller cannot
pass another case to this loader. `AnalysisVolume.from_arrays` is available for
analytical fixtures, explicitly labelled `AUTHORED_ARRAYS`, never a verified
solver execution.

All output directories must be fresh and outside the source run. Before writing
a solver-derived bundle, the source inventory is reverified. Files and source
bytes remain unchanged. Failure can leave an incomplete newly created output
directory; `manifest.json` is written last and incomplete/extra/changed bundles
fail verification. Retry with a fresh directory after correcting the diagnostic.

The bundle verifier checks exact inventory, byte hashes and CSV/JSON/source
consistency. It **does not independently recompute the sampled values**, prove
authorship, verify an original GMS comparison or authenticate caller-edited
result dictionaries. Numerical acceptance comes from independent checks and
the actual source-bound execution path, separately from integrity hashes.

Limits: 20,000 source cells through the existing workflow, 2,000,000 head values,
1,000 saved times, 100,000 sample points per result/combined frames, 1,000
polyline vertices/Z selections, 5,000 observations, 32 MiB file/JSON budgets,
finite values with magnitude at most 1e12 in analysis arrays, and sigma at least
1e-12 m. During frame budget rejection at most one additional individually
bounded frame is computed. Symlinks/FIFOs/devices, duplicate JSON keys,
nonfinite values and unsupported contracts are refused. These are explicit
engineering limits, not an automatic large-model chunking implementation.

## Independent checks

`tests/test_results_analysis.py` independently constructs an affine field
`2x+3y-4z+7t` on 2 layers with unequal thickness and nonzero XY origin. Trilinear
space/linear time sampling reproduces the independently calculated values;
cell/interface ownership, no extrapolation, singleton support, chainage corners,
AND visibility, explicit time, unit/datum/case mismatch and invalid budgets are
checked. The hand residual pair `[1,-3] m` with sigma `[1,2] m` gives bias -1 m,
RMSE sqrt(5) m, weighted RMSE sqrt(2.6) m and objective 3.25.

Actual MF6 tests load the synthetic captured run, check its prescribed 12 m
boundary and known comparison, exercise all four CLI operations and verify
unchanged inputs. Tampered head output/source evidence, malformed bundles and
attempted source-run output are rejected. These checks establish this bounded
software/numerical scope only; original GMS comparison and field validation
remain unperformed.
