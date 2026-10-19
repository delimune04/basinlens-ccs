# Groundwater module: completed checks

Performed **2026-10-19** on Linux, Python **3.12.14**, NumPy **2.3.5**, pandas
**2.2.3**, FloPy **3.11.0**, Streamlit **1.66.0**, Plotly **7.1.0**, actual
MODFLOW **6.7.0** (`mf6: 6.7.0 02/05/2026`). Solver and source fingerprints,
plus the numerical demo summary, are in [`validation_record.json`](validation_record.json).

## Software and numerical checks

The integrated suite passed **57 tests, zero skips** in **12.689 s**:

```bash
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -v
```

| Check | Independent basis / acceptance | Result |
|---|---|---|
| Existing capacity/input/bundle regression | Existing 39 tests | Passed |
| Linear steady head | h linearly spans fixed head cell centres, error ≤ 1e-7 m | Passed |
| Uniform recharge | Confined discrete parabola, error ≤ 1e-7 m | Passed |
| Recharge water balance | R × interior top area, flow tolerance 1e-4 m3/day | Passed |
| Transient injection | Independent Theis E1 series at r=40 m, t=0.04 day, relative head-rise error <5% | Passed |
| Three-layer transient demo | Finite fields, 13 saved times, correct 100 m3/day injection | Passed |
| On/off/on wells | Off field returns to 10 m within 1e-7 m; identical on fields | Passed |
| Case contract and failure handling | Units, finite values, geometry, schedules, missing solver, immutable outputs | Passed |
| Manifest failures | Empty/malformed, missing required files, tampered bytes, unsafe paths | Passed |
| UI workflow | Initial view, valid/invalid edits, input ZIP, missing solver, actual solver results, complete ZIP and CSV | Passed |

The three-layer demo has **2,583 cells**, **13 saved times**, and **31 days**.
Its maximum double-precision binary-budget residual was
**7.596862587888609e-7 m3/day**, maximum relative discrepancy
**2.429975438121622e-7%**. Head range: **10–12 m**. These are synthetic model
outputs, not observed field performance.

The budget gate uses
`abs(in-out) <= max(1e-6 m3/day, 0.001 * mean(total_in,total_out))`.
Relative percentages can be ill-conditioned when both totals approach zero;
the absolute check handles that case. Budgets aggregate external and storage
terms from double-precision CBC records; internal face transfers are excluded.
Rounded listing values are retained separately and do not control acceptance.

Independent review caught and resolved two material issues before publication:
empty manifests could pass verification, and near-zero flow could falsely fail a
pure percentage gate. Regression cases cover both. A separate reviewer also
ran the one-layer, one-row, one-time UI case successfully with actual MODFLOW.

## Operational reproduction

- Editable package install and CLI entry points passed.
- Existing capacity CLI: 2,000 samples, seed 42, bundle verifier passed.
- Groundwater CLI demo, run-bundle verifier, input export and export verifier
  passed with fresh output directories.
- Python compilation and `git diff --check` passed.
- CI includes optional dependency/UI/export coverage. CI does **not** silently
  download MODFLOW; its numerical tests are skips unless `MF6_EXE` is provided.

## Scientific limits

These checks support only the declared rectangular confined, constant-density,
single-phase water model. The transient Theis comparison is one bounded
resolution case, not a completed spatial/time convergence study. Near-well head
is cell-scale and has no wellbore correction. No pressure limit or containment
decision is inferred.

No native GMS output comparison, GMS project-format round trip, CO2–brine
multiphase benchmark, Sleipner field comparison, Windows run, GPU acceleration,
geomechanics or industry pilot was completed. The existing CCS evidence levels
are unchanged by these groundwater tests.
