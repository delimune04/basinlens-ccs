# Coherent model workspace

`streamlit run model_workspace.py` opens the bounded workflow directly.
`groundwater_app.py` may embed `render_model_workspace()` alongside its existing
specialized tools. Opening the page performs no model import, file writing,
engine download or numerical run.

The sequence is explicit:

1. Load an original synthetic example, strict workflow JSON (maximum 2 MiB), or
   BasinLens `.blproj` package (maximum 32 MiB). Backend parsers enforce their
   stricter format/member/expanded-data limits as well. Package opening verifies
   project metadata, registered workflow bytes and geometry/material consistency.
2. Review/edit the JSON draft. A changed or invalid draft clears displayed run,
   export, package and round-trip products immediately. Save/export/run buttons
   require a validated, applied draft. Failed imports preserve the last valid
   applied model. Applying an edited package draft drops the previous package's
   receipt/restored assets and labels the case as an edited draft; its view is
   preserved. The recovery button restores the last applied model.
3. Inspect declared strata, material properties, full cell assignments and each
   period's explicit CHD/WEL/RCH/GHB/RIV/DRN conditions. The UI does not infer geology
   or add missing boundary conditions. Omitted external boundaries carry the
   compiler's stated no-flow condition. Porosity remains metadata for this
   confined groundwater-flow compiler.
4. Select layer/property, 2D/3D and well-cell overlays. The preview uses literal
   project XY and vertical coordinates in metres; project rows increase north.
   CRS and datum are displayed as declared, including `unknown`. At most 20,000
   points are drawn; complete cell values are available in CSV. Well markers are
   cell positions, with explicit period/rate labels, rather than wellbore geometry.
5. Save/reopen a `.blproj` project with the view state; export verified native MF6
   inputs; perform a fresh FloPy native load/write and ordered-token comparison;
   or explicitly execute the configured MF6 binary with a timeout. Every operation
   requires a new output path. Saving creates a missing parent directory; the new
   package itself is never overwritten. The solver timeout is 1–1,800 seconds.
   Native round-trip creates `source/` and
   `roundtrip/` under that path and performs no numerical runs from this button.
6. Inspect captured-case-bound heads at saved times, native budget columns and
   independent water-balance/boundary-rate/confined-saturation flags. A success message requires
   all three flags. Whole-run ZIP is generated only after native bundle verification;
   selected-time CSV retains explicit cell, coordinates and `head_m`. Downloads
   have a 128 MiB budget; run ZIPs have a 5,000-file cap and refuse symlinks.

JSON/package load failures and solver errors retain a structured downloadable
last-error record containing stage, exception, output path and recovery steps.
Existing output paths are preserved, and retry requires a fresh directory.
No automatic alternate engine, unit conversion or parameter change occurs.

These are BasinLens software and synthetic single-phase confined-water checks.
The `.blproj` package is a separate format: no original GMS `.gpr` writing,
GMS format synchronization, complete GMS feature implementation, original
numerical equivalence, CO2/brine or oil multiphase physics is established.

## Regression checks

`tests/test_model_workspace_ui.py` exercises explicit loading, malformed upload
recovery, invalid/unapplied draft execution blocking, stale-output removal,
package save/reopen and view state, tampered package refusal, verified native
export/load-write comparison, visible missing-engine diagnostics and a real MF6
run. The real run uses asymmetric north/south fixed heads, nonzero origin and
multiple layers so row reversal or stale result relabelling is observable. It
checks literal project XY, known edge heads, captured-case identity, CSV values,
complete verified run download and invalidation after an edit.

The actual command/result is recorded with the implementation handoff; optional
engine skips do not count as executed numerical checks.

Local check on 2026-10-19 used Python 3.12.14, Streamlit 1.66.0, Plotly 7.1.0,
FloPy 3.11.0 and actual MF6 6.7.0: all five UI tests passed with zero skips in
6.564 seconds against the final backend after independent review. Failed package imports explicitly remove their temporary staging
files while preserving the previous valid model/package. The exact command is:

```bash
MF6_EXE=/absolute/path/to/mf6 PYTHONPATH=src python -m unittest tests.test_model_workspace_ui -v
```

Backend sources and the project bridge are independently implemented/tested in
their respective changes; the integration suite is authoritative for the merged
snapshot. No original GMS operation is performed by these five UI tests.

The first full-example integration exposed a test-fixture selection error: the
added `head_dependent_water.json` sorted before the layered example, while the
UI test assumed 12 m layered boundary heads. The helper now selects
`layered_background_water.json` by filename before loading. Model physics and
expected heads were not changed. With both production examples present, all
five UI tests passed with zero skips in 8.532 seconds, using the real MF6 engine.
