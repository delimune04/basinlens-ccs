# Bounded stationary geostatistics

This independently authored module implements small scalar statistical problems.
It has **no witnessed original GMS comparison**, no field validation and no claim
of general kriging or geological uncertainty equivalence. It adds actual numerical
operations to the existing typed `ScatterDataset`; it does not fit a model merely
because a dataset was loaded.

## Input and units

`CovarianceModel.from_dict` requires exactly:

```json
{
  "schema": "basinlens-covariance-v1",
  "dimension": 2,
  "kind": "exponential",
  "partial_sill": 1.0,
  "nugget": 0.0,
  "value_unit": "m",
  "ranges_m": [1.0, 1.0],
  "rotation": [[1.0, 0.0], [0.0, 1.0]]
}
```

Coordinates are metres, in an explicitly declared literal CRS and vertical datum.
Two and three dimensions are supported; 3D Z is positive upward. The dataset and covariance dimensions
and value unit must agree exactly. Both `partial_sill` and `nugget` are variances
in **`(value_unit)^2`**, which is retained in result metadata. No unit conversion,
CRS transform, trend fitting, normal-score transform or parameter estimation occurs.
Missing scatter observations are retained in the input snapshot and excluded from
the statistical calculation. Duplicate coordinates are rejected by the scatter
contract; no hidden averaging is performed.

## Covariance and nugget

For coordinate difference $d=x-y$, principal-axis rotation matrix $R$ and ranges
$a_j$, the normalized distance is $h=\|(dR)_j/a_j\|_2$. Rotation columns are
right-handed orthonormal principal axes expressed in world coordinates.

The stationary process covariance is $C(x,y)=s\rho(h)+n\,1[x=y]$, where $s$ is
partial sill and $n$ is nugget. Supported correlations are exponential
$\exp(-h)$, Gaussian $\exp(-h^2)$, and spherical
$1-1.5h+0.5h^3$ for $h<1$ (zero thereafter). Exponential/Gaussian ranges are
scale parameters, **not** a 95% practical range; no factor 3 is inserted.

The nugget is independent microscale **process** variance at distinct locations.
An identical coordinate refers to the same process value, so its cross-covariance
includes the nugget and exact conditioning reproduces the supplied value.
Measurement noise, repeated noisy observations and a separate latent/noisy
prediction target are outside this version. These meanings must not be exchanged.

## Kriging and support

`krige(dataset, queries_m, model, *, method, mean, radius_m, min_neighbors,
max_neighbors, domain_bounds_m, allow_extrapolation)` returns a
`GeostatisticsResult`. `.records` provides readable per-query records;
`.to_dict()` retains typed columns/units, complete input snapshot, model,
settings, selected original point IDs, weights and matrix condition numbers.

Simple kriging requires a declared known scalar mean. Ordinary kriging requires
`mean=null` and solves the constant-unknown-mean constrained system
$[C,1;1^T,0][w,\lambda]^T=[c,1]^T$. Both covariance and cross-covariance are
normalized by total point variance before solving; the constraint is unchanged.
Prediction-error variance is evaluated directly as
$C(0)-2w^Tc+w^TCw$. Small negative roundoff within $10^{-9}C(0)$ is clipped to
zero; larger negative values fail. Ordinary kriging reproduces constants under
its constraint. General affine/trend reproduction is not claimed.

Support is explicit and every unsupported query has null prediction/variance,
false support and a reason. A query must be in the owner-declared closed domain,
have the requested number of valued observations in the Euclidean search radius,
and use no more than the declared maximum neighbours. Distances select nearest
points; ties use original point IDs. Anisotropic covariance and Euclidean
neighbour search have distinct meanings.

When `allow_extrapolation=false`, the query must also lie in the **global valued
observation affine/convex hull**, including lower-dimensional point/line/plane
cases. A bounding box does not stand in for a hull. Local selected neighbours can
still have negative weights; the hull gate concerns the complete valued dataset.
When true, extrapolation is explicitly permitted inside the owner domain and
radius rules. No values are silently filled beyond these rules.

Hull computation normalizes by the largest coordinate span. Signed face/edge
distances and affine residuals use normalized tolerance `1e-10`, also recorded
as metres (`span × 1e-10`). For a 1 km span this is 0.1 micrometres; for the
maximum supported 2e9 m span it is 0.2 m. This is a numerical tolerance, not
survey accuracy or an exact zero-tolerance boundary claim. Affine rank uses
`max(n,dimension) × float64_epsilon × max(largest_singular_value,1) × 100`;
near-degenerate geometry can be treated as a lower-dimensional affine support.
Thin faces and short edges use normalized distances to keep the stated tolerance.

`kriging_to_scatter(result, dataset_id=..., field="prediction"|"variance")`
exports a typed interpreted scatter field for existing spatial workflows. Null
support/reasons remain null. Variance uses squared value units and a distinct
quantity; it is not a measured property. Full result identity and assumptions
are retained in provenance. Duplicate query coordinates are explicitly rejected
when exporting to the existing duplicate-reject scatter contract.

## Experimental variogram

`experimental_variogram(dataset, bin_edges_m)` computes unordered pairs once,
with Euclidean metre lag and semivariance $0.5(z_i-z_j)^2$. Bins are lower-inclusive
and upper-exclusive, except the last upper edge is included. Pair counts,
mean lags, source point IDs and excluded-pair counts are retained. Empty bins
remain null with count zero. This is a raw omnidirectional experimental estimate:
no automatic variogram fitting, declustering, direction filter or nugget inference
is performed.

## Gaussian fields and Latin hypercube sampling

`gaussian_field(coordinates_m, model, *, mean, seed, realizations, metadata,
conditioning=None)` draws the specified finite multivariate Gaussian using
Cholesky decomposition. Simulation sites are explicitly chosen by the owner;
conditioning may extrapolate and does not infer a hull. A known scalar mean,
stationary covariance and Gaussian point-process interpretation are assumptions.
Conditional mean and covariance are $m+K_{qo}K_{oo}^{-1}(y-m)$ and
$K_{qq}-K_{qo}K_{oo}^{-1}K_{oq}$. Matching observed coordinates are retained
exactly in every draw. Conditioning requires exact CRS/datum agreement and no
measurement-error term. No hidden jitter or covariance fitting is added.

`latin_hypercube(marginals, *, samples, seed)` assigns one randomized probability
stratum to each sample in every scalar marginal, then applies its inverse CDF.
Uniform, normal and triangular marginals have explicit names, units and
parameters. Marginals use independent permutations; correlation/copulas, conditional
LHS, optimum design and coverage of a particular geological posterior are absent.
The triangular transform avoids squaring tiny physical ranges. Unresolved
floating-point ranges/spreads are refused. Gaussian draws additionally require
mean ULP ≤ standard deviation × 1e-8 at every nonfixed site; otherwise adding
noise could collapse the represented distribution. Rescaling is explicit.

Both operations use an explicit NumPy `Generator(PCG64(seed))`, retaining seed
and NumPy version. Exact same-environment repetition is checked. Serialized
results retain the actual draws; identical floating-point decompositions across
all NumPy/BLAS/platform versions are not promised.

## Bounds and failure handling

Limits are 64 valued observations, 256 query/simulation sites, 32 local neighbours,
256 combined conditioning/target sites, 1,024 realizations, 4,096 LHS samples,
32 marginals and 65,536 sampled values. A 3D hull inspects at most
`C(64,3)=41,664` candidate planes. There are no unbounded sweeps. Dense systems
with condition number above `1e10`, singular/indefinite covariance, duplicate
simulation sites, incompatible units/metadata and unresolved arithmetic fail
explicitly. No smoothing or pseudoinverse is silently substituted.

Own JSON/CSV reads and writes have an 8 MiB limit. Reads reject symlinks, FIFO,
nonregular inputs, changing files, duplicate JSON keys and nonfinite numbers.
Writes publish to a fresh path using the existing atomic scatter writer.
The own result CSV has a versioned metadata line with column kinds/units and
JSON-encoded scalar cells (including distinct null, boolean and text values).
`save_result/load_result` and `verify_result_roundtrip` preserve complete metadata,
all draws, variance, masks and reasons across actual JSON/CSV writes/reopens.
This is semantic file consistency, not a trusted signature or original GMS match.

## Run and evidence

```bash
python examples/geostatistics/run_geostatistics_example.py --output build/geostatistics-example
python -m basinlens_ccs.subsurface.geostatistics krige examples/geostatistics/synthetic_observations.json examples/geostatistics/covariance.json examples/geostatistics/queries.json examples/geostatistics/settings.json build/kriged.json
python -m basinlens_ccs.subsurface.geostatistics roundtrip build/kriged.json build/kriged-roundtrip.json
```

The module CLI also exposes `variogram`, `simulate` and `lhs`. Inputs/settings
are strict own JSON; `--help` lists positional files. Existing outputs are refused;
a corrected retry needs a fresh path. Loading or checking files never runs MF6,
contacts a service, or fits a covariance model.

The 23 tests in `tests/test_geostatistics.py` passed with zero skips. They use
independent one/two-point hand matrices, known covariance kernels and rotated
anisotropy, constants and process-nugget exactness, actual triangular/tetrahedral
and coplanar/thin hulls, support masks, singular/condition refusal, sill scaling,
known pair semivariances, conditional Gaussian hand formulas, seed repetition,
1,024-draw covariance moments, marginal probability stratification, tiny-range
triangular sampling and real CLI/JSON/CSV corruption/failure/recovery checks.
The actual example reproduced a 3 m midpoint and variance
`0.8319087592754217 m²`, retained both conditioned values in every draw, rejected
the outside-hull query and passed four result JSON/CSV roundtrips.

A separate implementer reviewed ordinary/simple systems, conditional covariance
normalization, process nugget and LHS formulas. No remaining mathematical blocker
was identified within this stated subset. These authored tests do not establish
site-specific Gaussianity/stationarity or a complete geostatistical product.

## Primary sources checked 2026-10-19

- [SAS Institute, ordinary kriging derivation](https://support.sas.com/documentation/cdl/en/statug/66859/HTML/default/statug_krige2d_details21.htm)
  (publisher endpoint timed out; the same authored documentation was read in its
  [SFU-hosted manual copy](https://www.sfu.ca/sasdoc/sashtml/stat/chap34/sect15.htm)).
- [SAS Institute spatial covariance forms](https://www.sfu.ca/sasdoc/sashtml/stat/chap41/sect20.htm),
  Table 41.4; formulas use explicit scale parameters.
- [Rasmussen and Williams, *Gaussian Processes for Machine Learning*, chapter 2](https://gaussianprocess.org/gpml/chapters/RW2.pdf),
  author-hosted MIT Press text, conditional Gaussian calculation.
- [SciPy LatinHypercube documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.LatinHypercube.html),
  definition of probability stratification; SciPy is not a dependency or invoked.
- [NumPy PCG64 documentation](https://numpy.org/doc/stable/reference/random/bit_generators/pcg64.html),
  explicit bit-generator identity. No upstream implementation code was copied.
