# Development handoff

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
