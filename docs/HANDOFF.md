# Development handoff

## Latest model loading and workflow checkpoint — 2026-10-19

The whole GMS objective remains unfinished. The new integrated model/file scope
is described in [MODEL_IO_CHECKPOINT.md](gms/MODEL_IO_CHECKPOINT.md); the older
265-test snapshot below is historical. New code adds bounded portable `.blproj`
save/relocate/open/re-save checks, a canonical spatial-water project bridge,
named flat strata and complete cell material assignments, explicit six-kind
period boundary tables, actual native FloPy rewrite/two-run checks, and an
integrated model editing/plotting/download workspace. Legacy shared-coordinate
metadata was corrected with an explicit version-2 Y reflection; the new spatial
compiler reverses native rows to preserve physical XY.

Official-feature accounting now validates every one of the unchanged 163
selected investigation rows against exact source/test identities and actual
executed test IDs. Current counts are **147 NONE / 16 PARTIAL / 0 SCOPED_COMPLETE**;
three saved-original-file observations and **zero VERIFIED**. The official six
pages' 223 observed items include 55 UNMAPPED_OPEN items. These are separate
partial inventories; no whole-product completion percentage exists. The genuine
REA ledger remains 577 open obligations and zero closures. See
[IMPLEMENTATION_STATUS.md](gms/IMPLEMENTATION_STATUS.md).

The combined authored synthetic example saved and relocated its project,
exported/reloaded/rewrote native input and ran both actual MF6 decks: zero head
and budget-column differences, all three water/boundary/confined-support gates
passed, 50 cell/time head CSV rows. Six independently authored analytical cases
on the exact final compiler also passed. General package operations never execute
a solver. `modflow6_spatial` uses the explicit workflow entry points; it is not
silently routed through the legacy layer-only shared registry adapter.

The first selected integration run failed one AppTest because the test assumed
alphabetical example order. Selecting the intended layered fixture fixed it;
the next selected run passed **336 tests, zero skips**, in 62.303s. Both failed
v3 and successful v4 receipts/logs are retained; only v4 is positive feature
evidence. The subsequent strict full suite passed **352 tests, zero skips,
failures or errors**, in 87.586s using actual MF6 6.7.0. All 107 recorded source
hashes were rechecked after execution. Exact counts/identities are in
[model_io_validation_record.json](gms/model_io_validation_record.json).
Installation, the required 2,000-sample seed-42 capacity example and its
artifact verifier, compilation, actionlint and diff checks were also run.
Public commit `cc7b13ad` / tree `d99ffbb1` then passed push run `39229412904`
and PR run `39229419781`, all three jobs in each. Each strict real-MF6 job ran
352 tests with zero skips/errors/failures and the saved/relocated two-run project
example passed. Both artifacts were downloaded and matched their GitHub SHA-256
digests; all 107 source hashes match. Exact feature/PR-merge commit and artifact
bindings are retained in
[model_io_ci_validation_record.json](gms/model_io_ci_validation_record.json).

Reproduce the prioritized model flow in a fresh output directory:

```bash
python examples/workflow/run_project_example.py --output build/project-flow --exe /absolute/path/to/mf6
python -m streamlit run groundwater_app.py
python -m basinlens_ccs.reconstruction.status validate
```

Next independent code priority: explicit borehole/log import and portable
roundtrip, then geological interpretation and grid support mapping. Native GPR
writing, arbitrary geology/mesh construction, most engines/packages, complete
object/UI behavior and CO2/oil multiphase physics remain absent. Original GMS
numerical comparison still needs an authorized applicable module and successful
observed model loading beyond the already witnessed owned error-classified
dialog, followed by fresh retained input/solver/output evidence. The native REA
timeout still needs a supported successful analysis path or useful analyzer
diagnostics. No licensing/access/provider guard was bypassed. These comparison
obstacles do not block independent implementation of the remaining features.

## Expanded 2026-10-19 reconstruction checkpoint

User objective: reconstruct the whole GMS workbench using REA and preserve
extension paths for CCS/oil exploration. **That objective remains unfinished.**
The smaller confined workflow below is the initial historical snapshot, not the
current scope or a replacement definition of completion. Public work is in
[PR #10](https://github.com/delimune04/basinlens-ccs/pull/10), branch
`feat/gms-groundwater-workbench`; main baseline remains `f17934e`.

The latest integrated run passed **265 tests with zero skips** using actual
MF6 6.7.0, FloPy 3.11.0 and the optional UI/HDF5 dependencies. Required capacity
CLI/verifier, compilation, diff checks and actionlint also passed. This exact
265-test implementation is published within `5c62acf9` / tree `5ef3ae2f`; both
remote CI runs `39215889617` and `39215883507` passed all three jobs. Later
Windows probe source/check bindings are separate. The required numerical/UI
CI job now pins the exact public MF6 archive/binary and direct dependencies,
rejects every skip or incomplete discovery, and retains JSON/log/source identity
evidence. Its new strict runner passed 265/265 locally in 47.560s. Public push `39220409626` and PR `39220417755` then each passed all 265
tests with zero skips/errors/failures and all three jobs; 85 source hashes matched.
The durable [CI record](gms/real_mf6_ci_validation_record.json) distinguishes
feature-head and equivalent PR-merge checkouts. See
[CI_VALIDATION.md](gms/CI_VALIDATION.md).

Current components:

- Standalone bounded 1D saturated GWF/GWT conservative-solute module with
  deterministic native export, exact captured case/input binding, every-step
  concentration/mass result reader and existing native executor/verifier reuse.
  Uniform/Gaussian/refinement/inlet checks passed; separate explicit-case UI
  provides actual runs, profile/mass plots, CSV and verified ZIP. No shared-project registry,
  GMS comparison, CO2, reactions or density-dependent physics are implied.
- Typed shared subsurface projects, explicit units/CRS/datum and asset identity,
  preserved geological/observation metadata, trusted engine registry and a
  working MODFLOW background-water adapter for groundwater/CCS/oil projects.
  CO2, black-oil and seismic descriptors explicitly report unavailable.
- Strict native MF6 input/sidecar discovery, bounded immutable SQLite snapshots,
  FloPy loading, isolated general-native execution preserving native units and
  packages, complete hashed run inventories and verification. GUI sidecars are
  archived; they are not synchronized into solver inputs.
- Bounded GPR/HDF5 inventory and explicit array reads; a narrow rectilinear
  geometry decoder with all-cell connectivity/elevation checks and a read-only
  saved-data viewer. The explicit saved project-tree UI reads hierarchy/literal
  UUID relationships and exports anonymous metadata. Actual tutorial: 29 nodes,
  21 relationships, 16 unresolved. Bounded raw-chunk decoding prevents HDF5
  decompression from exceeding the declared read budget. Unknown
  units/CRS/datum/time semantics stay unknown. A separate strict Quadtree reader
  validates 20,684 nodes/9,976 cells. XY agrees with native DISV but raw Z differs
  30/75; full 3D correspondence remains false. Its explicit saved-data UI
  rendered all 9,976 cells with no app errors and unchanged source bytes.
- A comparison/replay harness separates synthetic fixtures, shipped tutorial
  output and witnessed original GMS output. No witnessed original GMS numerical
  comparison has passed. No full GPR writer/round trip or complete UI exists.
- Actual REA 6.7.0 resource evidence for the exact GMS 10.9.7 main executable,
  independently checked against PE structure. Actual REA ledger generation has
  577 open obligations (576 numeric command IDs plus the unknown whole-product
  reconciliation barrier), zero verified closures. The new numeric dialog decoder
  covers all 429 listed templates/6,853 static controls without original text or
  dynamic UI claims. The 163-entry documented
  catalogue is not a product denominator.

The unchanged official tutorial's 15 native files reproduce its shipped head
and budget binaries byte for byte using public USGS MF6 6.7.0. The tutorial
project stores GMS-version metadata 10.8.2 and the shipped solver says MF6 6.4.1;
the project creator is not established. Its 1,536 geometry
nodes/1,125 hexahedra match every native DIS cell center/top/bottom literally;
GPR unit metadata conflicts with the native feet/seconds declarations. These
are file interoperability checks, not an original GMS session or full parity.
The saved-data viewer was also exercised on that private project: all 1,125
cells rendered, no application errors, source bytes unchanged, unknown units
retained. No original program, resources, inputs, GPR payloads or pseudocode
are distributed.

Validation records:
[VALIDATION.md](gms/VALIDATION.md),
[expanded_validation_record.json](gms/expanded_validation_record.json),
[geometry_validation_record.json](gms/geometry_validation_record.json), and
[TUTORIAL_INTEROPERABILITY.md](gms/TUTORIAL_INTEROPERABILITY.md) bind exact
source/input/engine identities and distinguish software checks from physics.
[REA_FINDINGS.md](gms/REA_FINDINGS.md) records default native-analysis timeout,
auxiliary partial Ghidra work and original-runtime investigation outcomes.
Native REA diagnostic run `39210146753` returned `provider_timeout` after
1,202.736s with no overview; exact logs yielded no analyzer timing or verified
delaying analyzer. The historical generic SCRIPT marker is not post-analysis
completion. The collector naming correction passed 13 targeted tests. See
[native_rea_diagnostic_run.json](gms/native_rea_diagnostic_run.json).
Normal Windows startup displayed both hash-identical registered GMS targets;
both stopped at unclassified blocking dialogs. A subsequent passive observation
verified one actual exact free Community button, without selecting it. The reviewed opt-in run `39211459223` then delivered one exact free Community
choice and observed an enabled main window with four identical complete
134-item standard-menu snapshots. Their 102 reported numeric IDs overlap
85 static REA IDs; other IDs are unclassified, including possible system/generated
entries. The second target remained at an unknown dialog with no action.
Edition entitlement and original numerical execution remain unverified;
[windows_free_choice_receipt.json](gms/windows_free_choice_receipt.json) preserves
the actual metadata and exact action counts. The subsequent original File/Open run `39213425352` observed an owned standard
Open dialog with 23 controls and no read errors/truncation, after exactly two UI
attempts. No filename/confirmation or original solver action occurred.
[windows_open_dialog_receipt.json](gms/windows_open_dialog_receipt.json) retains
that exact evidence. The later pinned-tutorial run `39216983932` verified one
filename-combo/Edit path write/readback and one Open confirmation, after four
counted UI attempts on target1 and zero on target2. An eight-control owned
standard dialog then appeared and was heuristically classified as an error.
Cause and project loading remain unverified; no unknown button was pressed.
Both GPR/executable identities stayed unchanged. The probe issued no solver
action and did not monitor automatic numerical execution.
[windows_tutorial_open_receipt.json](gms/windows_tutorial_open_receipt.json)
preserves the exact scope and historical wording qualifications. No provider
guard or licensing mechanism was bypassed. The official10.9 edition table
marks the MF6 interface in paid MODFLOW and higher columns, with Community
blank; this is separate documented scope, not the dialog cause or observed
entitlement. The passive diagnostic run `39218744781` then observed licensing,
file-operation and generic-error keyword flags in one complete eight-control
dialog. The diagnostic added zero UI actions; source identities stayed unchanged
and cause/module availability/project loading remain unverified.
[windows_tutorial_diagnostic_receipt.json](gms/windows_tutorial_diagnostic_receipt.json)
retains the exact artifact/source binding. See
[RUNTIME_DIAGNOSTICS.md](gms/RUNTIME_DIAGNOSTICS.md).

Reproduction:

```bash
python -m pip install -e ".[app,groundwater,gms]"
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -v
python -m streamlit run groundwater_app.py
python -m basinlens_ccs.subsurface engines
```

Next work must follow the whole-product evidence contract in
[RECONSTRUCTION_PLAN.md](gms/RECONSTRUCTION_PLAN.md): establish an original
runtime corpus, reconcile dynamic UI/package/format inventory, reconstruct
native project persistence/synchronization, and add capability-specific
implementations and independent comparisons. Keep code ownership isolated in
worktrees. Integrity hashes, static IDs, successful MF6 execution and a labelled
CCS project do not establish original GMS behavior or multiphase physics.

## Initial 2026-10-19 snapshot: confined groundwater workbench (historical)

Base: `f17934e` (main); branch `feat/gms-groundwater-workbench`.
User request: investigate GMS with REA and create a reusable CCS modeling module.
Implementation plan: inspect official targets and evidence, implement a bounded
original groundwater workflow with the public MODFLOW engine, validate physical
and operational behavior independently, and publish a reviewable branch/PR.

Changed files: new `src/basinlens_ccs/groundwater/` schema/adapter/CLI,
`groundwater_app.py`, two synthetic `examples/groundwater/` cases,
`tests/test_groundwater.py`, `tests/test_groundwater_ui.py`, optional dependency
and CLI registration, explicit solver installer, local REA inspection helper,
`docs/gms/` findings/feature matrix/reproduction/validation, and CI optional job.
Existing capacity engine and `app.py` calculations were not changed.

- Actual MODFLOW 6.7.0, FloPy 3.11.0, Python 3.12.14: **57 integrated tests
  passed with zero skips**, including five physical solver tests and a real
  Streamlit solver/export flow. Independent linear/recharge/Theis checks and
  the on/off/on near-zero-budget regression passed. Exact environment,
  fingerprints and demo residuals are in `docs/gms/validation_record.json`.
- Existing required capacity CLI and artifact verifier passed at 2,000 samples,
  seed 42. Groundwater CLI demo, input export, run/export verifiers, editable
  installation, compilation and diff checks passed. Output directories are
  intentionally immutable; no downloads occur in normal export/run.
- Independent review identified and fixed malformed/empty manifest acceptance
  and a near-zero-flow false budget failure. UI now reports absolute residual
  and explains the combined absolute/relative gate. Raw outputs remain in runs.
- REA 6.7.0 inspected only an exact prefix of the official GMS 10.9.7 installer
  bootstrap (48 resources). The main installed GMS executable was not extracted
  and checksum-verified. Native providers and Windows runtime were unavailable.
  This is **not recovered GMS modeling logic or proof of GMS equivalence**.
- Published sources contain no proprietary GMS binary, icons or resource bytes.
  Model scope is confined single-phase constant-density water. CO2 multiphase,
  native GMS projects, transport/GIS/calibration, field validation and Windows
  execution are not implemented/verified. No CCS evidence-level promotion.

Next reproducible commands:

```bash
python -m pip install -e ".[app,groundwater]"
python -m streamlit run groundwater_app.py
# Explicit solver download only if needed:
python tools/install_mf6.py --accept-download --destination build/mf6-bin
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -v
```

For further GMS reconstruction, use an installed authorized target in a suitable
Windows environment and define capability-by-capability behavior fixtures before
claiming compatibility. For CCS multiphase flow, implement an appropriate engine
adapter and independent benchmark as specified in the existing project plan.

## 2026-10-05: T1 input validation and deterministic ties

Baseline: `7ab91398e064bcc2fd323150e869fb521be234be`, rebuilt directly from the
accessible GitHub source. Scope: [issue #1](https://github.com/delimune04/basinlens-ccs/issues/1).
Plan: unify literal CSV identity parsing, validate direct scenarios and detailed
errors, correct tied ranks, add boundary/bundle regressions, then verify the
unchanged synthetic calculations. No equation or attention threshold was changed.

Changed files: `models.py`, `io.py`, `analysis.py`, `capacity.py`, `cli.py`, `app.py`,
`tests/test_validation.py`, `README.md`, `docs/METHODOLOGY.md`,
`docs/VALIDATION_PLAN.md`, and this handoff.

- The loader, CLI, and dashboard share literal identity parsing. IDs/names are
  trimmed strings; empty/missing/NaN identities and duplicate canonical IDs fail.
  Direct analysis rejects duplicate IDs before simulation instead of overwriting
  dictionary entries. Record positions do not depend on DataFrame index labels.
- Physical fractions are always in `[0,1]`; all physical inputs stay non-negative.
  Type, missing, non-numeric, non-finite and range errors keep field context.
  Independent review added coverage for direct-Python oversized integers, which
  now raise the same field-specific validation error rather than `OverflowError`.
- Sensitivity uses average ranks for ties; a hand calculation and all paired
  permutations verify `r=0.5`. Constant arrays keep the documented zero sentinel.
  Exact summary ties resolve by site ID. Input-order seed assignment is unchanged.
- Python 3.12.14, NumPy 2.3.5, pandas 2.2.3:
  `PYTHONPATH=src python -m unittest discover -s tests -v` — 39 tests passed.
- Editable installation in an isolated virtual environment with existing
  dependencies (`pip install --no-build-isolation --no-deps -e .`) passed, as did
  all 39 installed-package tests and the `basinlens` / `basinlens-verify` entry
  points at 2,000 samples, seed 42. `compileall` and `git diff --check` passed.
- Synthetic CSV, engine `volumetric-independent-triangular`, 20,000 samples per
  site, seed 42: CLI and bundle verification passed. `summary.csv`,
  `sensitivity.csv`, and `report.md` were byte-identical to the baseline run;
  Q50 remains 7.56, 5.92, and 11.11 Mt rounded for the three example sites.
- The existing CI only installs/runs tests and the synthetic bundle on standard
  `ubuntu-latest` Python 3.10/3.12 runners. No deployment, secrets or paid services.

Scientific evidence remains L0/synthetic-only. Streamlit visual flows, GPU, OPM,
Sleipner and industry pilot checks were not run. This does not validate real-site
safety. Explicit units/provenance and broader simulation-budget validation remain
outside this input-contract patch.

Next bounded task: [T2 / issue #2](https://github.com/delimune04/basinlens-ccs/issues/2),
the versioned case/evidence schema. Start with `python -m unittest discover -s tests -v`
after installation, then use a fresh directory for the documented CLI check.

## Earlier foundation handoff (retained for history)

Updated: 2026-10-03. Baseline upstream before this change:
`0f0022888d6464865be6c21fc7690f0b34af3f6c`.

## What exists

- Python volumetric capacity, independent triangular Monte Carlo, rank sensitivity,
  illustrative attention scores, CSV CLI and existing Streamlit demonstration.
- v0.2 CLI captures exact input bytes and exports a manifest, summary, sensitivity
  and deterministic report. Manifest includes per-site seeds, versions, source
  fingerprint and checksums. `basinlens-verify` checks all four artifacts.
- Existing paths are refused; manifests are written last. Partial I/O failure
  may leave an incomplete directory; there is no job scheduler or recovery engine.
- Design documents cover scientific scope, module boundaries, NVIDIA, validation,
  development tasks and a professor review note.

## Checks performed

- Python 3.12: `PYTHONPATH=src python -m unittest discover -s tests -v` — 17 passed.
- Synthetic CLI: 20,000 samples, seed 42 — completed; unchanged v0.1 rounded
  Q50 capacities: Aurora 7.56, Borealis 5.92, Caldera 11.11 Mt.
- Bundle integrity verifier — passed. Repeat-run equivalence, altered/missing
  artifacts, existing-run refusal, incomplete manifest and invalid input tested.
- `git diff --check` — passed at the implementation check.
- Editable package installation and installed `basinlens` / `basinlens-verify`
  entry points — passed.
- [Remote CI](https://github.com/delimune04/basinlens-ccs/actions/runs/37098100648)
  for foundation commit `9544983f8ff47866daafd36a99c7869d1ece57df` — Python 3.10
  and 3.12 install, unit tests, example run and bundle verification all passed.
- GPU models, OPM, real Sleipner data, Streamlit UI and industry pilot — not run.

## Next task

[T1 / issue #1](https://github.com/delimune04/basinlens-ccs/issues/1) in
`DEVELOPMENT_PLAN.md`: input identity/bounds/errors. Existing gaps include
blank CSV identities becoming string `nan`, numeric-looking IDs losing leading
zeros, direct construction bypassing fraction bounds, and broad exception handlers
obscuring field-specific errors. Improve these without changing valid calculations.
Follow with T2 (case/evidence schema) and T3 (small licensed Sleipner asset).

## Start commands

```bash
git clone https://github.com/delimune04/basinlens-ccs.git
cd basinlens-ccs
python -m pip install -e .
python -m unittest discover -s tests -v
python -m basinlens_ccs.cli examples/synthetic_sites.csv --output build/handoff-run --samples 2000 --seed 42
python -m basinlens_ccs.artifacts build/handoff-run
```

Read `AGENTS.md` before editing; use a fresh output directory and one small branch.
No NVIDIA credentials or GPU are required for the current stage. Review physics
against independent evidence, not agreement between two AI coding tools.
