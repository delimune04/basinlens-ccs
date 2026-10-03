# Development handoff

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
- GPU models, OPM, real Sleipner data, Streamlit UI and industry pilot — not run.
  Python 3.10 is covered by configured remote CI, not by this local execution.

## Next task

T1 in `DEVELOPMENT_PLAN.md`: input identity/bounds/errors. Existing gaps include
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
