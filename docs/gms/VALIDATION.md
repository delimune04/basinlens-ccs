# Groundwater module: completed checks

The 265-test snapshot below is historical and applies to its own recorded source.
See [GEOSCIENCE_CHECKPOINT.md](GEOSCIENCE_CHECKPOINT.md) for later code and strict
integrated regression, and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)
for current feature scope. No snapshot establishes whole-GMS equivalence.

## Expanded implementation check

The integrated groundwater/transport/GPR workbench snapshot passed **265 tests with zero skips** using real
MODFLOW 6, FloPy, Streamlit and h5py. Total discovery/run wall time was 47.999s.
Exact source hashes, versions, commands and additional checks are in
[expanded_validation_record.json](expanded_validation_record.json). The earlier
published 173-test, 190-test, 203-test, 237-test and 249-test snapshots and their successful remote CI are
retained there as history. The lightweight matrix can skip optional tests; the
required [real-engine job](CI_VALIDATION.md) now pins MF6 and rejects any skip.
Earlier ordinary-CI outcomes are separate from the local zero-skip result. The matching published snapshot `5c62acf9` / tree
`5ef3ae2f` passed all three jobs in each remote CI run `39215889617` and
`39215883507`; later Windows probe changes have separate source/check bindings.

Checks cover strict shared-project/engine contracts, actual CCS background-water
execution, native unconfined feet/seconds execution, native file boundaries and
byte preservation, complete run-inventory verification, SQLite snapshots,
GPR link/filter/read limits, geometry topology and coordinate mapping,
comparison provenance/tolerance failures, PE evidence binding, genuine REA
open-obligation generation and 34 workbench UI/viewer tests.
The added project/storage checks cover strict tree grammar, literal identity
joins, missing payloads, anonymous projection, raw deflate expansion, canonical
file datatypes and explicit tree UI source binding. Normal termination
of an arbitrary native model does not validate its physical assumptions.
The added [transport slice](TRANSPORT.md) passed 12 focused tests and seven
additional independently reviewed solver cases. Uniform concentration, Gaussian
variance/profile refinement and inlet mass checks apply only to its stated
1D single-phase conservative-solute contract.

Thirteen additional dialog tests cover standard/extended format differences,
UTF-16, IDs, alignment, creation data, alias budgets, skipped-menu verification,
metadata redaction and fresh outputs. All 429 actual templates decode into
6,853 static controls. Their captions and names remain omitted; neither stored
layouts nor a passing synthetic guard test establish dynamic UI behavior.

Independent geometry review found that equal cell centers can hide different
cell edges, and equal face means can hide different corner elevations. Both
false positives are fixed and have regression tests. The actual tutorial now
matches all 1,536 XY nodes and all 9,000 face-corner elevations against native
DIS coordinates and flat-cell face elevations. This comparison does not invent
a unique native shared-node Z surface or establish GPR units. The read-only
viewer also rendered its 1,125 saved-head cells with no app errors and unchanged
input bytes; unknown units/CRS/datum stayed unknown.

An unchanged official tutorial was independently rerun through the public
USGS engine and the new native runner. Its 1,125 heads and budget binary were
byte-identical to shipped results. Its stored GMS-version metadata, shipped solver identity, native
feet/seconds units, independent controls and unresolved GPR unit metadata are
recorded in [TUTORIAL_INTEROPERABILITY.md](TUTORIAL_INTEROPERABILITY.md). This is
shipped-input interoperability, not a witnessed original GMS numerical execution
or full product equivalence. The saved-tree reader independently found 29 nodes, 21 relationships and 16
unresolved items in the unchanged tutorial, without reading numeric payloads;
see [GPR_PROJECT.md](GPR_PROJECT.md). Earlier Windows probes stopped at blocking
dialogs. The reviewed sixth probe delivered one exact free Community choice,
then observed an enabled main window and 134 materialized menu items; the
second target remained at an unknown dialog. No original model run or edition
entitlement was established. See
[windows_free_choice_receipt.json](windows_free_choice_receipt.json).

The remaining text retains the initial 57-test confined-module snapshot and
its independent physical checks. Its source fingerprints describe that earlier
snapshot, not the expanded implementation.

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

## Scientific limits of the initial confined-model snapshot

These checks support only the declared rectangular confined, constant-density,
single-phase water model. The transient Theis comparison is one bounded
resolution case, not a completed spatial/time convergence study. Near-well head
is cell-scale and has no wellbore correction. No pressure limit or containment
decision is inferred.

No witnessed original GMS runtime output comparison, GMS project-format round trip, CO2–brine
multiphase benchmark, Sleipner field comparison, Windows run, GPU acceleration,
geomechanics or industry pilot was completed. The existing CCS evidence levels
are unchanged by these groundwater tests.

## Later transport UI and measured Quadtree geometry

The 265-test integrated source includes four new transport UI tests, four
explicit Quadtree UI tests and eight strict mesh-reader tests. Transport UI import, native export, real-MF6 run,
captured-case-only concentration/mass plots, gate failures, CSVs and verified
ZIP downloads passed without changing the shared groundwater/CCS project.

The separate [Quadtree reader](GPR_UNSTRUCTURED.md) recovered 20,684 nodes and
9,976 cells from another official project. All same-index XY footprints and
10,342 unique XY vertices match saved native DISV exactly; upper/lower corner
coordinate differences remain 30/75 and full 3D match is false. Units, datum and
synchronization remain unresolved; no repair or solver execution was applied.

The reviewed original File/Open probe then observed a complete owned standard
Open dialog (23 controls, no read errors/truncation), after two counted UI
attempts. No filename was entered or confirmed;
[windows_open_dialog_receipt.json](windows_open_dialog_receipt.json) preserves
the exact scope. These observations do not establish original numerical parity.

The measured Quadtree representation is now explicitly selectable in the GPR
viewer; its saved 9,976 cells rendered without app errors or source changes.
Unknown coordinate/field/time units, CRS and datum were retained, no wrapper
transform was applied, and no model synchronization or solver action occurred.
[unstructured_ui_validation_record.json](unstructured_ui_validation_record.json)
binds this read-only actual-file UI check to exact source/application identities.


## Actual pinned tutorial filename/confirmation outcome

Windows run `39216983932` passed pre-action compilation/pure policy gates and
completed one verified pinned filename write/readback and Open confirmation.
Target1 had four counted UI attempts; target2 had zero. A later complete owned
eight-control dialog was heuristically classified as an error. Its cause and
project-load outcome remain unknown; no unknown button was pressed. Both GPR
and executable identities were unchanged, no probe solver action was issued,
and numerical execution was not monitored. See
[windows_tutorial_open_receipt.json](windows_tutorial_open_receipt.json) and
[RUNTIME_DIAGNOSTICS.md](RUNTIME_DIAGNOSTICS.md) for exact counts and retained
historical wording qualifications. No genuine original numerical comparison or
obligation closure is established.


The subsequent passive diagnostic run `39218744781` passed Windows gates and
observed licensing/file-operation/generic-error keyword flags in one complete
owned eight-control dialog. It added no UI action; counts remained4/0 per target,
with unchanged executable/GPR identities. Cause, entitlement and project loading
remain unknown. See
[windows_tutorial_diagnostic_receipt.json](windows_tutorial_diagnostic_receipt.json).


## Required real-MF6 CI result

Push `39220409626` and PR `39220417755` each passed all 265 tests with zero skips,
failures, errors or discovery issues under the fixed actual MF6 binary. All 85
selected source hashes agree with the implementation; both runs passed their
three jobs. [real_mf6_ci_validation_record.json](real_mf6_ci_validation_record.json)
binds artifacts, environments, exact checkouts and the equivalent tested tree.
This does not execute original GMS or close its reconstruction obligations.
