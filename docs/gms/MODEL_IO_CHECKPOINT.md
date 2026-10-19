# Model loading and workflow checkpoint — 2026-10-19

The whole GMS reconstruction remains unfinished. This checkpoint implements
the requested model/file and geology-to-results priorities within explicit
confined single-phase water contracts. It does not close the 577 genuine REA
obligations or establish original GMS equivalence.

## Implemented together

- Portable `.blproj` version 1: typed project, geological/observation metadata,
  exact registered assets and four bounded view settings. Actual save, relocate,
  open, re-save and reopen compare semantics, every asset byte and view state.
  Full member inventory, path, version, checksum and decompression budgets apply.
- Spatial water workflow: named flat strata, complete cell material assignments,
  directional K, Ss, porosity metadata, initial heads, explicit steady/transient
  periods and cell-supported CHD/RCH/WEL/GHB/DRN/RIV. No period carry-forward is
  silently substituted for an absent condition.
- Geology/grid preview, material and per-period boundary tables, validated JSON
  drafts, 2D/3D fields, wells, saved layer/time head plots, full-grid CSV and
  verified native bundles. Invalid or unapplied changes block execution and
  clear stale products; a failed import preserves the last valid model.
- The spatial project bridge preserves all forcing in one registered canonical
  case asset and derives the shared typed geometry/strata/properties. A
  coherently rehashed but contradictory outer project is refused. CCS/oil domain
  metadata is retained with the explicit background-water role.
- Native export -> actual FloPy load -> fresh rewrite -> complete ordered-token
  comparison -> two optional real MF6 runs -> captured-case result reads.
  Numerical roundtrip success requires head/budget agreement and both runs'
  water-balance, prescribed/head-dependent boundary-rate and confined-support
  checks. Native inputs and the authoritative metadata are checked unchanged
  again after rewriting and after optional runs.
- Legacy shared-adapter coordinate metadata now explicitly reflects Y; the
  spatial compiler instead reverses every native row array and condition to
  preserve physical XY. Both contracts are documented and tested separately in
  [PROJECT_COORDINATES.md](PROJECT_COORDINATES.md).

See [PROJECT_PACKAGE.md](PROJECT_PACKAGE.md),
[WORKFLOW_PROJECT.md](WORKFLOW_PROJECT.md),
[MODEL_WORKFLOW.md](MODEL_WORKFLOW.md) and
[MODEL_WORKSPACE_UI.md](MODEL_WORKSPACE_UI.md) for exact limits and APIs.

## Retained execution evidence

- [project_workflow_example_record.json](project_workflow_example_record.json):
  original synthetic two-layer/five-step model saved, relocated, reloaded,
  exported, rewritten and actually run twice. Maximum head and budget-column
  differences are both zero. All three result gates passed; the executable
  example emitted 50 cell/time CSV rows.
- [workflow_independent_validation_record.json](workflow_independent_validation_record.json):
  six separately authored synthetic analytical cases on the exact final
  compiler and actual MF6 6.7.0. Maximum head error is zero, maximum water-rate
  closure residual 7.105427357601002e-15 m3/day. Cases and exact identities are
  retained; no original GMS comparison occurred.
- [model_workflow_validation_record.json](model_workflow_validation_record.json):
  focused compiler tests and actual native examples, with source/solver hashes.
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md): independent implementation
  and original-comparison states, current official-page reconciliation, source
  hashes and specifically executed tests. The 163 selected entries are a partial
  investigation inventory, not an official total or completion denominator.

The first integrated selected-module run executed 336 tests with one failure:
an AppTest expected the layered fixture's 12 m head but implicitly selected the
new alphabetically first fixture with a 10 m head. The test now explicitly
selects `layered_background_water.json`; no physical equation or expected head
was changed. The failed v3 receipt is retained separately; it is never positive
status evidence. The selected rerun passed 336 tests with zero skips. The
subsequent strict full suite passed 352/352 with zero skips, errors or failures,
in 87.586 seconds using actual MF6 6.7.0. See
[model_io_validation_record.json](model_io_validation_record.json) for exact
source, environment, solver and full test-ID bindings. The integrated workbench
also loaded the spatial model with valid feature accounting and two plots,
preserving the independent legacy editor state without an application error.
Public feature commit `cc7b13ad` and its equivalent PR merge tree passed both
push/PR CI runs `39229412904` / `39229419781`, all three jobs in each. Both strict
jobs ran 352 tests with zero skips and completed the actual portable project
example. Downloaded artifact digests and all 107 source hashes were checked;
[model_io_ci_validation_record.json](model_io_ci_validation_record.json) retains
the durable parsed receipts and full member identities.

## Reproduce

```bash
python -m pip install -e ".[app,groundwater,gms]"
python -m streamlit run model_workspace.py
# Or use the integrated workbench:
python -m streamlit run groundwater_app.py
python examples/workflow/run_project_example.py --output build/project-flow --exe /absolute/path/to/mf6
python -m basinlens_ccs.reconstruction.status validate
MF6_EXE=/absolute/path/to/the/pinned/mf6 python tools/ci_real_mf6.py test
```

Choose a new output path for each operation. The example and UI do not download
a solver or execute anything merely by opening a project. The CI runner requires
the exact pinned Linux executable identity; direct explicit model execution can
use another installed MF6 but records its actual identity.

## Remaining implementation and comparison conditions

1. Native GMS GPR writing/roundtrip, synchronized project editing, complete
   object selection and full original UI are absent. Unknown saved semantics
   remain unknown; the inert `.blproj` is a separate format.
2. Borehole/horizon/TIN/solid interpretation, variable surfaces, faults,
   conceptual GIS meshing, general structured/unstructured construction,
   calibration and the remaining documented engine/package families need actual
   implementation and their own tests. They are not blocked from independent
   development by the current original-runtime obstacle.
3. Original numerical comparison is blocked by the already witnessed owned
   error-classified dialog after the pinned tutorial Open operation. Licensing,
   file-operation and generic-error diagnostic flags were observed, but the
   cause, successful model loading and applicable module entitlement remain
   unverified. Resume only with an authorized applicable edition/module and a
   successful observed model load, followed by retained fresh native input,
   solver and output evidence. Do not retry unknown buttons or substitute a
   different engine's command ID. See [RUNTIME_DIAGNOSTICS.md](RUNTIME_DIAGNOSTICS.md).
4. Native REA returned `provider_timeout` after 1,202.736 seconds without an
   overview or verified delaying analyzer. Further original-logic comparison
   needs a supported successful analysis path or useful analyzer diagnostics.
   No provider guard or licence control was disabled.
5. CO2–brine/oil multiphase physics, reactions, seismic interpretation and field
   validation remain absent. A domain label, preserved porosity or a successful
   confined-water run does not implement these capabilities.

The next independent implementation priority is an explicit borehole/log data
contract and import/roundtrip checks, followed by geological interpretation and
grid mapping with independently checked support. Original comparison stays
separate from that software work.
