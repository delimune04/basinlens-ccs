# Bounded authored groundwater parameter calibration

This implements a small deterministic parameter search using **actual verified
MODFLOW 6** confined-water simulations. It is our own coordinate/bracket
optimizer. PEST, PEST++, automatic model structure selection, field calibration,
parameter confidence intervals, global uniqueness and original GMS equivalence
are not implemented or established by this module.

No run happens on import, problem validation or project opening. Solver
execution requires an explicit `fit` command or `run_calibration(...)` call with
an available trusted executable; no executable is downloaded automatically.

## Problem and source contracts

`CalibrationProblem` stores immutable original bytes of three documents: the
existing typed `WorkflowCase`, the exact `analysis.py` head observation document,
and versioned `basinlens-calibration-v1` settings. Loaded JSON views are copies.
Original bytes are captured under `source/` and hashed before evaluation.

Observations require their canonical **base case** SHA-256, project ID, literal
CRS and vertical datum, head `m`, time `day`, explicit indexed cells, exact saved
times, positive `sigma_m`, basis and provenance. The existing analysis contract
validates them; no second approximate observation schema is substituted. Every
observation ID must appear exactly once in either training or withheld groups.
At least as many training records as fitted parameters are required.

Trials copy the source case and modify only explicitly declared material fields.
Reverting those fields must restore the complete source case. Geometry,
stratigraphy, boundaries, periods, initial heads, domain/role, provenance and
undeclared properties remain equal. The original observation document is never
edited. A separate per-trial comparison copy changes its case hash to the
verified trial hash; both base/trial hashes and the original observation hash
are retained in `observation_binding`. This explicitly connects observations at
unchanged support to varying physical parameters.

One to three distinct material/field parameters are supported:

| Field | Unit | Physical bound inherited from workflow |
|---|---|---|
| `kx_m_day`, `ky_m_day`, `kz_m_day` | `m/day` | 1e-6..1e6 |
| `ss_per_m` | `1/m` | 1e-12..0.1 |

Each parameter declares its ID, material ID, field/unit, lower/upper bounds,
source-case initial value, `linear` or `log` coordinate scale and either no prior
or an explicit `{value,sigma,unit}` prior. Bounds must be numerically resolved;
very narrow intervals relative to floating-point ULP are rejected. The prior is
an optional **physical-parameter quadratic penalty**, not a Bayesian posterior
or a source of observation identifiability. Its mean must lie within the stated
bounds and its standard deviation must be positive with the same physical unit.

Limits: 2,000 cells, 100 saved steps, 100,000 saved head values and 200
observations per calibration problem. Other `WorkflowCase` limitations still
apply. This component uses the explicit spatial water compiler; it does not add
CO₂, oil, multiphase or reactive transport physics.

## Objective and method

For training observations only,

`data_SSE = sum(((simulated_head_m - observed_head_m) / sigma_m)^2)`.

Weights are `1/m²`; the normalized SSE is dimensionless. A supplied prior adds
`sum(((physical_parameter - prior_value)/prior_sigma)^2)`, reported separately as
`prior_sse`. Withheld residuals/RMSE are reported from the same trial solve and
never enter the objective, sensitivity rank or candidate selection. Sigma is an
explicit owner-supplied scale; an SSE value does not by itself establish a
statistical goodness-of-fit threshold.

Parameters map to normalized coordinates `[0,1]` using their declared linear or
logarithmic scale. Initial and final finite differences perturb one normalized
coordinate at a time, clipped at bounds. The Jacobian is
`d(simulated_head_m/sigma_m) / d(normalized_parameter_coordinate)`. Local
identifiability requires every data-Jacobian column to exceed the declared norm
threshold and all singular values to exceed
`max(minimum_sensitivity_norm, largest_singular_value * rank_rtol)`.
**Priors are excluded.** Fixed-head-only data or a flat/collinear response is
rejected rather than presented as an identified parameter.

The optimizer applies deterministic golden-section searches over each bounded
coordinate, retaining the smallest objective among all successful actual runs
and explicitly checking bounds when budget permits. Other coordinates stay
fixed during each bracket. It has a finite sweep count and declared coordinate
tolerance; coupled/nonconvex objectives can retain local or budget-limited
solutions. The result does not claim global optimization or statistical
acceptance. Diagnostic probes are genuine candidate runs too; if a final probe
improves the result, its value is retained and the offset from the final local
sensitivity anchor is explicit and restricted to the probe neighbourhood.

Every accepted value requires a completed source-bound native run, unchanged
compiled controls, the selected executable's SHA-256, and passing water balance,
boundary-rate and confined-saturation support gates. A normally terminated run
whose heads violate confined support is retained as a failed calibration
attempt. The equations and scope of the underlying physical model are unchanged.

## Budgets and failure recovery

Defaults are **40 actual model evaluations**, two sweeps, 300 seconds total
budget, 20 seconds per solver run, 0.01 finite-difference normalized step and
0.001 coordinate tolerance. Explicit settings may request at most 100 model
runs, four sweeps, 3,600 seconds total and 120 seconds per solver run.
Initial/final sensitivity, candidate search and every failed attempt all consume
the same evaluation budget. Withheld metrics use existing solves. Exact cached
parameter vectors are reused without new engine calls. The search reserves
slots for final sensitivity before spending its remaining evaluation budget.

The total deadline is checked before evaluations, after capture and before
accepting a result. An evaluation exceeding it is rejected and diagnostics are
retained. The underlying native runner additionally bounds each solver run;
compilation and its separately bounded executable version probe can finish
after the total deadline, so this is not a hard real-time process deadline.
No subsequent model evaluation starts after exhaustion. Workspaces are bounded
at 512 MiB and 20,000 files; the native runner retains its separate per-run bound.

A fresh output directory with an existing parent is mandatory. Output files
publish through flushed temporary files with atomic no-replace hard links.
`attempts/` records each request before execution, `evaluations/` records its
completed/failed outcome, `runs/` retains native inputs/outputs/logs, and numbered
`checkpoints/` retain search/sensitivity decisions. `result.json` records the
success/failure and recovery condition. `manifest.json` binds all files and
directories. Source documents, executable identity and module source hash are
retained on partial failure. Existing paths, symlinks, nonregular files,
nonfinite/duplicate-key JSON and altered artifacts are rejected.

Automatic resume is deliberately refused: inspect the saved error and native
logs, correct an invalid source/model/starting range or availability problem,
then explicitly start a fresh output path. Old failed directories remain
reviewable. Validation and bundle verification execute no solver.

`verify_calibration_bundle` checks the complete inventory and original source
hashes, accounts for every started attempt, reopens each completed native run,
recomputes training/withheld residuals and prior/total objectives, checks the
selected minimum, reconstructs the fitted case, and recomputes both local
Jacobian/rank reports from the actual retained finite-difference probes. Merely
altering a rank boolean or matrix and refreshing file hashes cannot substitute
for the numerical checks.

## Independent authored checks

The executable fixture is synthetic. Original GMS comparison remains
`NOT_OBSERVED`; these checks do not validate a field inverse problem.

**Steady conductivity.** One layer, five 1 m × 1 m cells, 10 m thickness,
constant head 10 m at both end cells and central extraction 10 m³/day. With
`Kx=4 m/day`, each face conductance is 40 m²/day. Each two-face path to a boundary
has conductance 20 m²/day, giving centre drawdown `10/(20+20)=0.25 m` and adjacent
drawdown 0.125 m. Training heads are 9.875 and 9.75 m; the other adjacent head
9.875 m is withheld. The initial conductivity is 1 m/day.

**Transient storage.** Three cells, the same thickness and end heads, known
`Kx=1 m/day`, central extraction 10 m³/day, two 0.05 day backward-Euler steps,
initial head 10 m and authored `Ss=0.05 1/m`. Storage conductance is
`Ss*volume/dt = 0.05*10/0.05 = 10 m²/day`; both face conductances are 10 m²/day.
Thus `h1=(10*10+20*10-10)/30=29/3 m`, and
`h2=(10*(29/3)+20*10-10)/30=86/9 m`. The first time is training and the second
is withheld. Initial storage is 0.02 1/m.

The actual reference execution used pinned MF6 `6.7.0 02/05/2026`, executable
SHA-256 `479185be33167701696604f7bb55acb4f96476f396e9bb015cbe7da52e278ec4`:

| Synthetic case | Authored parameter | Recovered | Training RMSE (m) | Withheld RMSE (m) | Actual evaluations |
|---|---:|---:|---:|---:|---:|
| Steady Kx | 4 | 4.0004798815 | 2.37084e-5 | 1.49945e-5 | 24 |
| Transient Ss | 0.05 | 0.0500136966 | 3.04341e-5 | 2.02912e-5 | 24 |
| Fixed-head-only + strong K prior | Unidentifiable | Rejected | — | — | 3 |

The complete reference receipt is `examples/calibration/expected_receipt.json`.
The tests additionally add a 3 m error solely to withheld data and recover the
same conductivity, reject a failed confined-support trial while retaining its
actual native outputs, count an injected launch failure, recover at a new path,
refuse an expired deadline before execution, and reject a rehashed fake
sensitivity report, modified native output or extra directory.

During development, the first fixture used spaces in boundary IDs, which the
existing strict workflow rejected before any solver run; the fixture IDs were
corrected. A subsequent transient setting exposed a copied upper storage bound
0.5 exceeding the workflow's actual 0.1 limit. The calibrator now enforces 0.1
and the independently derived storage test uses interior truth 0.05. Independent
review then required Jacobian/rank recomputation in the bundle verifier and
nonregular-file rejection; these have regression tests.

## Run

```bash
mkdir -p build
PYTHONPATH=src python -m basinlens_ccs.subsurface.calibration check examples/calibration/steady_case.json examples/calibration/steady_observations.json examples/calibration/steady_settings.json
PYTHONPATH=src python -m basinlens_ccs.subsurface.calibration fit examples/calibration/steady_case.json examples/calibration/steady_observations.json examples/calibration/steady_settings.json --output build/calibration-steady-1 --exe /path/to/mf6
PYTHONPATH=src python -m basinlens_ccs.subsurface.calibration verify build/calibration-steady-1
PYTHONPATH=src python examples/calibration/run_example.py build/calibration-example-1 --exe /path/to/mf6
MF6_EXE=/path/to/mf6 PYTHONPATH=src python -m unittest discover -s tests -p test_calibration.py -v
```

The ordinary CPU suite skips actual numerical solver tests when MF6/FloPy are
absent. The strict real-MF6 CI must execute them with zero skips. Source contracts,
I/O and pure sensitivity checks remain available without the solver.

## Primary physical references

Official MODFLOW 6 input documentation, checked 2026-10-19:

- [GWF NPF](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-npf.html): conductivity and principal directions.
- [GWF STO](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-sto.html): specific storage, transient/steady controls.
- [GWF WEL](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-wel.html): prescribed volumetric well rates.

These document the physical engine inputs. They do not endorse this authored
optimizer or establish equality with GMS/PEST workflows.
