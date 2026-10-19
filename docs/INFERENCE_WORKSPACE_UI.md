# Inference workspace

`inference_workspace.py` exposes `render_inference_workspace()` for the main
Streamlit application and can run independently:

```bash
python -m streamlit run inference_workspace.py
```

It provides two explicit, bounded workflows. Opening the page, importing or
applying input does not execute a solver. All `ix_*` keys belong to this module.
The algorithms are authored implementations; original GMS comparison remains
`NOT_OBSERVED`. This workspace does not establish whole GMS equivalence, PEST,
CO2/oil multiphase physics, field validity or a globally optimal calibration.

## Covariance inference and stochastic samples

Load the named authored example or upload one JSON bundle containing
`observations`, `covariance`, `settings`, and `queries`. The typed scatter and
covariance contracts preserve literal CRS, datum and value units. Edit the whole
bundle and explicitly apply it before running ordinary/simple kriging. Simple
kriging requires a declared known mean. Search radius, neighborhood counts,
domain bounds and extrapolation policy are explicit.

The query table preserves unsupported rows as null predictions and variances,
with support reasons. Prediction and variance plots show supported rows against
x in metres; the complete XY/XYZ coordinates remain in the table and downloads.
The variance is model-based prediction error under the declared stationary
covariance and mean assumptions, not measured geological uncertainty. No
automatic variogram fitting or drift selection occurs.

Separate explicit actions calculate an experimental distance-bin variogram,
generate seeded Gaussian realizations with optional exact conditioning on the
applied observations, or generate independent Latin hypercube marginal samples.
Gaussian targets include all declared query coordinates, including outside the
observation hull; this differs from the kriging support mask and is stated in the
UI. LHS supports the backend's declared uniform/normal/triangular marginals; it
does not introduce cross-parameter dependence. Gaussian plots show at most 16
realizations while full tables and exports retain all requested realizations.

JSON and the backend's metadata-bearing CSV retain column units, settings,
source identities, seed where applicable and support. The explicit roundtrip
button actually writes and reloads both formats and compares their semantics.
Charts dispatch by the typed operation, so legitimate LHS parameter names such
as `prediction` or `r0000` cannot be confused with another result schema.

## Actual bounded MF6 calibration

Load the named `steady_case.json`, `steady_observations.json` and
`steady_settings.json` example, or upload a bundle with `case`, `observations`
and `settings`. The observation contract binds every value to the source case,
literal units/CRS/datum and spatial/time support. Original observations remain
unchanged; the output captures source documents and every attempted native run.

The applied settings declare 1–3 supported property parameters, bounds, scales,
optional priors, disjoint training/withheld observations, finite-difference
settings, evaluation cap, total deadline and per-run timeout. All real solver
calls, including finite-difference and failed evaluations, count toward budget.
Training residuals plus any declared prior term form the objective. Withheld
values are reported separately and do not enter the objective or data-sensitivity
rank. Priors do not establish missing observational identifiability.

Choose an explicit MF6 executable and a fresh output folder, then click start.
The UI creates only the output's parent if necessary; the backend refuses an
existing output directory and never downloads or selects a substitute engine.
Results show the captured engine, exact stop reason, best sampled parameters,
training/withheld residuals, local sensitivity/rank, objective and evaluation
history. Reaching the evaluation cap produces an explicit warning and preserves
the best actual evaluation; it does not claim convergence or statistical fit.
History parameter columns use `parameter:<original ID>` so a parameter named
`objective` or `status` cannot overwrite the diagnostic fields.
Three water/boundary/confined-support checks must pass for an evaluation to
contribute an accepted objective.

The result ZIP contains input copies, observations, attempts, evaluations,
checkpoints, native inputs/outputs, fitted case when accepted, result and manifest.
History/residual CSV downloads are accompanied by the source-bearing result JSON
and full ZIP. Failed attempts retain their diagnostics and explicit recovery
conditions. A verified failed bundle is labelled as a stopped execution record;
an incomplete/unverified failure path cannot expose a successful result download.
There is no automatic resume: correct the cause and use a fresh output path.

## State and resource limits

- JSON input is at most 2 MiB, UTF-8, finite, without duplicate keys, nesting over
  32 or arrays over 100,000 entries. Backend limits further bound observations,
  targets, matrix sizes, sample counts, cells, steps, parameters and solver budgets.
- The last applied valid problem survives a failed upload or invalid draft.
  Changed or invalid drafts disable execution and remove earlier result/download
  eligibility until explicitly applied. Source/settings/seed/executable/output
  changes clear products, preserving the diagnostic and original source files.
- Before each calibration plot or download, the full backend verifier checks
  retained sources, inventory, actual native arrays, residuals and sensitivity
  probes without executing a solver. Exact manifest and result hashes plus all
  three selected input documents must match the captured display snapshot. A
  changed file or replacement by another valid run invalidates cached artifacts.
- Download ZIP assembly is limited to 128 MiB, 5,000 files and 10,000 path entries,
  refuses symlinks/nonregular files, and reads through the mutation-detecting
  bounded regular-file reader with an aggregate actual-byte budget.
  If packaging fails, the saved execution folder remains available for diagnosis;
  no truncated ZIP is presented as a verified result.

## Reproducible UI checks

```bash
PYTHONPATH=src MF6_EXE=/absolute/path/to/mf6 \
  python -m unittest discover -s tests -p test_inference_workspace_ui.py -v
```

Six AppTests cover idle imports with a solver-execution trap, failed import
recovery, the independent two-point ordinary-kriging midpoint 3 m and variance
0.8319087592754217 m², hull masks, actual JSON/CSV roundtrip, simple-mean settings,
invalid-draft blocking, hand semivariance 2 m², exact conditional endpoints,
seed repeatability, LHS strata and collision-safe parameter names. Actual MF6
tests recover synthetic Kx=4 m/day with withheld predictions, verify evaluation
history and native ZIP contents, reject head-file tampering, retain an explicitly
expired deadline before any solve, run with a 12-evaluation cap, and reject a
different fully valid bundle substituted at the displayed path. Deadline expiry
uses a deterministic module-local test clock; it is not an actual slow solver
benchmark. Missing optional UI dependencies or MF6 are explicit skips, never
positive scientific evidence.
