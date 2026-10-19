# Development handoff

## Expanded 2026-10-19 reconstruction checkpoint

User objective: reconstruct the whole GMS workbench using REA and preserve
extension paths for CCS/oil exploration. **That objective remains unfinished.**
The smaller confined workflow below is the initial historical snapshot, not the
current scope or a replacement definition of completion. Public work is in
[PR #10](https://github.com/delimune04/basinlens-ccs/pull/10), branch
`feat/gms-groundwater-workbench`; main baseline remains `f17934e`.

The final integrated run passed **203 tests with zero skips** using actual
MF6 6.7.0, FloPy 3.11.0 and the optional UI/HDF5 dependencies. Required capacity
CLI/verifier, compilation, diff checks and actionlint also passed.

Current components:

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
  saved-data viewer. Unknown units/CRS/datum/time semantics stay unknown.
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
project says GMS 10.8.2 and shipped solver says MF6 6.4.1. Its 1,536 geometry
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
Normal Windows startup displayed both hash-identical registered GMS targets;
both stopped at unclassified blocking dialogs. No active edition, standard
menu state or original numerical run was established. No provider guard or
licensing mechanism was bypassed.

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
