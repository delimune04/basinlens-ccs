# BasinLens development instructions

Read `docs/PROJECT_BRIEF.md`, `docs/VALIDATION_PLAN.md`, and `docs/HANDOFF.md`
before changing this research software. Claude Code also reads `CLAUDE.md`.

## Scope and scientific integrity

- Keep conceptual capacity, reference flow simulation, observation interpretation,
  and surrogate output separate. Label the engine and validation level in artifacts.
- Current v0.2.0 implements volumetric screening and CLI bundles only. NVIDIA,
  OPM, seismic, and enterprise features are planned; never claim they ran.
- Quantities must have explicit units and datum/support where relevant. Missing
  evidence stays unknown; illustrative attention scores are not risk probabilities.
- Preserve original data and reference cases. Geological changes, retry settings,
  and observations must be traceable. Do not invent field measurements or benchmarks.
- Do not change a scientific equation or calibration without documenting the
  assumptions, independent numerical check, effect, and applicability.
- Keep CPU core usable without optional GPU/LLM services. Do not enable paid calls,
  large downloads, unbounded sweeps, or private-data uploads by default.
- Respect upstream code, model and dataset licences; commit only permitted public
  or synthetic data. Never commit credentials or private research material.

## Work cycle

1. Inspect current branch, remote changes, and applicable instructions; preserve
   uncommitted user work. One implementer edits a branch at a time.
2. Select one bounded issue. Use `feat/<topic>` or `fix/<topic>` and record a brief
   implementation plan. Routine reversible work within the task is authorized.
3. Make a working slice. Test scientific/operational behaviour, not just structure.
4. Run checks below; update documentation and handoff; open a reviewable PR.
5. The other coding tool reviews units, model limits, failure cases, reproducibility,
   and evidence. Project owner makes scientific interpretation decisions.

## Checks

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m basinlens_ccs.cli examples/synthetic_sites.csv --output build/review-run --samples 2000 --seed 42
python -m basinlens_ccs.artifacts build/review-run
git diff --check
```

Choose a new output directory for each run; an existing path is intentionally refused.
If package installation is unavailable, use `PYTHONPATH=src` and say which route ran.
Do not count skipped GPU/solver/Streamlit checks as passed.

End a session by recording changed files, exact checks/results, data/engine versions,
known limitations, issue/commit references and the next actionable command in
`docs/HANDOFF.md`. Report software checks separately from scientific validation.
