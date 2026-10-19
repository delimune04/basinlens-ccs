# Synthetic geology-to-water examples

Both JSON cases are original synthetic inputs, with explicit unknown CRS and a
local elevation datum. `layered_background_water.json` has two named layers and
materials, steady/transient periods and an injection well.
`head_dependent_water.json` exercises CHD/RCH/WEL/GHB/DRN/RIV in one small grid.
Neither represents field data, CO2 flow or a verified GMS reconstruction.

Run from the repository with optional groundwater dependencies installed and an
explicit trusted MF6 executable. Use fresh output paths for every execution.

```bash
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow preview examples/workflow/layered_background_water.json
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow export examples/workflow/layered_background_water.json --output build/workflow-export
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow verify-export build/workflow-export
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow run examples/workflow/layered_background_water.json --output build/workflow-run --exe "$MF6_EXE"
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow results build/workflow-run
PYTHONPATH=src python -m basinlens_ccs.subsurface.model_workflow roundtrip build/workflow-export --output build/workflow-roundtrip --exe "$MF6_EXE"
```

Omit `--exe` on `roundtrip` for the file-only load/write comparison. A numerical
round trip is only reported when both actual native runs and result gates pass.
See `docs/gms/MODEL_WORKFLOW.md` for the exact support, coordinates and limits.
# Portable project through to two actual native runs

From the repository root, with an explicitly installed solver:

```bash
python examples/workflow/run_project_example.py --output build/project-flow --exe /absolute/path/to/mf6
```

This saves the full synthetic case as `.blproj`, restores it in a new location,
checks project/view/asset preservation, exports native inputs, reloads and
rewrites them with FloPy, and runs both native decks. It refuses a failed
numerical roundtrip or physical support gate. `receipt.json` and `heads.csv`
retain explicit times, project cell indices and metre coordinates. Omit `--exe`
for file operations only. Choose a fresh output directory for each run.

The equivalent project file operations are also available through
`python -m basinlens_ccs.subsurface workflow-save|workflow-open|workflow-roundtrip`.
For a generic restored typed project, `validate|export|run` accept
`--asset-root /path/to/restored/assets`; its relative asset paths are rooted
there. The spatial workflow is executed explicitly through
`python -m basinlens_ccs.subsurface.model_workflow`, not the legacy layer-only
shared registry adapter.

These examples are single-phase background water for a CCS project. They do not
calculate CO2 or oil multiphase flow and are not original GMS comparisons.

