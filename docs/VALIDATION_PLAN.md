# Validation and acceptance plan

Draft · 2026-10-03. Proposed numerical gates below require domain review; they are
project engineering targets, not regulatory thresholds or achieved performance.

## Evidence levels

| Level | Permitted claim | Evidence required | Current status |
|---|---|---|---|
| L0 Concept screening | computational prototype with explicit assumptions | units, known calculation, reproducibility, failure handling | implemented; synthetic tests only |
| L1 Reference simulation | physical benchmark reproduced in a documented domain | solver version/deck, conservation, convergence, independent comparison | not implemented |
| L2 Observation comparison | monitored case compared under explicit interpretation assumptions | asset provenance, seismic QC, observation/model mismatch and uncertainty | not implemented |
| L3 Limited industry pilot | useful within an agreed company workflow | representative case, owner-defined tolerances, review, deployment/support checks | not performed |

Only a verified result can be promoted. A passing software test does not promote a
conceptual capacity estimate to a containment assessment.

## A. Existing volumetric engine

Equation: `M [Mt] = A [km²] × 10^6 × h [m] × phi × rho [kg/m³] × E / 10^9`.
Hand-check fixture: `A=1, h=10, phi=0.2, rho=700, E=0.02` gives `0.028 Mt`.
That independent arithmetic case, fixed distributions, same-seed replication and
range/duplicate checks are covered by the existing suite.

Additional validation work:

- Compare Monte Carlo moments against analytical products for independent inputs.
- Check sample convergence over multiple seeds and budgets; quantify Monte Carlo
  numerical error separately from geological uncertainty.
- Completed in the 2026-10-05 T1 software regression pass: mandatory direct-Python
  fractional/non-negative bounds, literal string IDs, blank/NaN rejection,
  uniqueness, and field-specific errors. The legacy reader still does not capture
  units/provenance as a versioned data contract.
- Ties now use average ranks, checked against a hand-calculated `0.5` fixture and
  every paired permutation. Constant arrays retain the documented legacy zero
  sentinel. Do not label this general Sobol analysis or use its values causally.
- Specify whether thickness is gross/net and how efficiency is defined, to prevent
  double counting when another estimation method is introduced.

## B. Physical reference engine

Start with one CO₂–brine case, not a large field history match. Record solver/PVT/
relperm versions, boundaries, active cells, datum, grid/time schedule and injection
controls. Reproduce no-injection and simple-flow limits before a heterogeneous case.

| Check | Initial engineering target | Qualification |
|---|---|---|
| Component balance | relative residual ≤ 0.1% in a closed test | define inventory, injected/produced/outflow mass and near-zero denominator; confirm with supervisor |
| Numerical convergence | refine space and time; key metric changes ≤ 5% | test maximum pressure and plume extent; choose tolerances from the use case |
| Cross-check | independent result/benchmark comparison | establish boundary, property and formulation equivalence first |
| Invalid state | no unhandled NaN, negative component mass or material saturation violation | tolerances and inactive-cell masks explicit; raw outputs retained |
| Pressure constraints | documented allowable pressure and its evidence | absent constraint produces `not evaluated`, never `pass` |

Containment requires seal entry pressure, stress/fault and well integrity evidence.
Distance-to-fault and caprock thickness alone do not provide that evidence. A
hydrodynamic simulation does not by itself establish long-term leakage probability.

## C. Observation and Sleipner validation

Register each dataset asset, licence, hash, CRS, depth/time datum, vintage and processing
history. The [Sleipner reference model](https://co2datashare.org/dataset/sleipner-2019-benchmark-model)
provides a starting geometry/property/observation resource; verify that all required
fluid properties and a runnable injection deck actually exist before claiming a
reproduced simulation.

For [4D seismic](https://co2datashare.org/dataset/sleipner-4d-seismic-dataset), document
registration, sampling, amplitude treatment and repeatability. Assess noise and
threshold sensitivity. Separate observed anomalies, interpreted plume outlines and
simulated CO₂ mass. Comparisons must share spatial/temporal support; a raw seismic
anomaly is not a saturation truth label.

First study: a small, licensed asset subset with a reproducible QC notebook and one
comparison plot. Later inversions require explicit rock-physics assumptions and
non-uniqueness assessment.

## D. Surrogate evaluation

Split by entire geological realization and preferably hold out an additional case
family. Fit normalization only on training data. Report independent sample counts,
uncertainty intervals, worst cases, extrapolation tests and failed inferences.

| Metric | Use |
|---|---|
| Field error and pressure MAE | broad spatial behaviour; insufficient alone |
| Maximum-pressure error, near-well error, dangerous underprediction | link to the decision's pressure margin |
| Plume boundary overlap and distance | common threshold, active mask and time support |
| CO₂ component balance and saturation bounds | independent physical consistency |
| Domain checks and failure/fallback frequency | define where the model can be used |
| End-to-end time, training cost, GPU peak memory | include I/O, preprocessing, training and verification |

Proposed early screening gate: pressure error ≤ 10% of the **independently established
available pressure margin**, component residual ≤ 1% in a closed test, and plume
overlap ≥ 0.8 under agreed threshold/support. These are unapproved research targets.
No known pressure margin means no pressure decision. Failing or out-of-domain
predictions fall back to the reference solver and are logged.

## E. Software and pilot acceptance

Run supported Python environments, packaged CLI commands, invalid/missing inputs,
immutable input capture, checksum verification and interrupted-run handling. The
v0.2.0 tests cover altered/missing outputs and refusal to overwrite an existing run.
The Streamlit workflow, GPU adapters, physical solver and private deployment need
their own end-to-end checks when implemented.

Before L3, an identified workflow owner must define one concrete use case, review
allowed inputs/tolerances, reproduce an independent case and accept deployment,
data access, backups, runtime budgets and recovery procedures. Record findings and
unresolved limitations. Enterprise or safety approval is not implied by a release tag.
