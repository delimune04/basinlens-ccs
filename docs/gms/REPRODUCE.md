# Groundwater workbench: run and reproduce

## Install

Use Python 3.10 or newer, preferably in a virtual environment:

```bash
python -m pip install -e ".[app,groundwater]"
```

MODFLOW 6 is an optional external executable. Its source is available from
[MODFLOW-ORG/modflow6](https://github.com/MODFLOW-ORG/modflow6); use its documented
release appropriate to your OS. The application never silently downloads a solver.
The repository also supplies an explicit `tools/install_mf6.py` helper. Run
`python tools/install_mf6.py --help` to select the destination and release.

## Use

```bash
python -m streamlit run groundwater_app.py
```

Load the synthetic demo or a saved JSON project, apply input edits, and provide
the path to `mf6` (`mf6.exe` on Windows). Exporting input files requires FloPy
but does not require the solver executable. Running requires both.

Command-line use:

```bash
python -m basinlens_ccs.groundwater demo --output build/groundwater-demo --exe /absolute/path/to/mf6
python -m basinlens_ccs.groundwater export examples/groundwater/demo.json --output build/groundwater-input
python -m basinlens_ccs.groundwater run examples/groundwater/demo.json --output build/groundwater-run --exe /absolute/path/to/mf6
```

Every output path must be new. Keep the whole output directory: the input,
MODFLOW files, stdout/listing, heads, budgets and summary form one run record.
The UI can download an input ZIP or complete run ZIP and head-table CSV.

## Interpret

- Length: metres. Time: days. K: m/day. Wells: m3/day, positive into aquifer.
  Recharge: m/day. Specific storage: 1/m. Layer/row/column: zero-based in JSON.
- Head is hydraulic head relative to the stated vertical datum. Head change can
  be converted to an equivalent single-phase pressure change with an explicitly
  chosen fluid density and gravity; it is not absolute reservoir pressure.
- The model assumes a saturated, confined, constant-density, single-phase fluid.
  All cells are active. Flat layers and uniform horizontal cell spacing are
  deliberate scope limits. No safe-injection-pressure decision is produced.
- Injection is a volumetric groundwater source. Do not enter CO2 mass rates as
  volumetric water rates or interpret water heads as CO2 saturation/plume.
- Existing capacity estimates and this flow result remain distinct engines.
  OPM Flow / DuMux integration is future work, not a solver run performed here.

## Shared CCS and oil projects

```bash
python -m basinlens_ccs.subsurface engines --exe /absolute/path/to/mf6
python -m basinlens_ccs.subsurface validate examples/subsurface/ccs_background_water.json
python -m basinlens_ccs.subsurface export examples/subsurface/oil_background_water.json --output build/oil-water-input
python -m basinlens_ccs.subsurface run examples/subsurface/ccs_background_water.json --output build/ccs-water-run --exe /absolute/path/to/mf6
python -c 'from basinlens_ccs.subsurface import verify_project_bundle; verify_project_bundle("build/ccs-water-run"); print("verified")'
```

See [the example contract](../../examples/subsurface/README.md) for units,
coordinate axes, asset-root rules, supported property fields and trusted Python
engine registration. Source asset bytes stay at their registered path; the run
preserves their hashes and exact project/mapping. Selecting an unavailable
physics adapter fails before producing output. Domain labels do not change the
fluid formulation. [PARITY.md](PARITY.md) covers original-result comparisons.

## Existing native model data

```bash
python -m pip install -e ".[gms]"
python -m basinlens_ccs.groundwater.gms_native /absolute/path/mfsim.nam --allowed-root /absolute/project/root
python -m basinlens_ccs.groundwater.gpr_hdf5 /absolute/path/project.gpr
```

The first command inventories native references and GUI sidecars without running
the engine. The second inventories HDF5 metadata without reading datasets or
following indirect links. Use the documented Python API for a specifically
selected bounded numeric array. See [MF6_NATIVE_IMPORT.md](MF6_NATIVE_IMPORT.md)
and [GPR_HDF5_READ.md](GPR_HDF5_READ.md). Native units stay literal; conflicting
GPR metadata is not resolved by guessing a conversion.

The [geometry API](GPR_GEOMETRY.md),
`read_gpr_rectilinear(project_path, grid_group)`, supports the explicitly
documented rectilinear representation. In the app, open the separate read-only
GPR section, inventory an explicit server path, choose an observed geometry
dataset and explicitly select its supported representation. The default is
rectilinear; the separate measured level-zero/single-layer Quadtree reader is
documented in [GPR_UNSTRUCTURED.md](GPR_UNSTRUCTURED.md). No automatic decoder
fallback or coordinate repair occurs. Select a raw numeric cell field and first-axis index only when needed.
The view shows saved data with unknown units/CRS/datum and no inferred time
conversion. It renders at most 20,000 cell centers and reads at most 8 MiB for
the selected field; it does not run a solver or save a GPR project.

When `/Tree/Tree` is present, select **저장 프로젝트 트리 읽기** to inspect the
saved parent/child hierarchy. This explicit action is independent of geometry
decoding. Original labels appear only in the local view; the download contains
an anonymous graph without labels, UUID strings or HDF5 paths. Unresolved
references are counted rather than guessed. The CLI equivalent is:

```bash
python -m basinlens_ccs.groundwater.gpr_project /absolute/path/project.gpr
```

See [GPR_PROJECT.md](GPR_PROJECT.md) for supported grammar and raw-chunk read
limits. Unsupported filter/storage representations are refused.

The app's separate native-model section can execute an existing resolved MF6
model and download its verified bundle. The CLI equivalent and its disjoint
source/output rule are in [MF6_NATIVE_IMPORT.md](MF6_NATIVE_IMPORT.md).

## Inspect an installed GMS with REA

Install the official [REA package](https://github.com/morluto/rea) separately, then:

```bash
python tools/inspect_gms.py /local/path/gms10_9.exe --output build/private-gms-evidence
```

This records real REA output, input hashes and per-command exit codes without
executing GMS. Keep the output private: PE evidence may include original resource
payloads. Do not add it to the repository. `--native-provider ghidra` optionally
requests actual native static analysis when that engine is already configured.
Failure records remain failures; installing REA alone does not reconstruct GMS.

The [dialog decoder](DIALOG_LAYOUTS.md) reads numeric layouts using the same
exact REA evidence and independently checked PE ranges:

```bash
python -m basinlens_ccs.reconstruction.dialogs /private/path/gms10_9.exe --evidence /private/path/rea-resources.json --output /private/path/new-dialog-layouts.json
```

The optional normal Windows startup workflow and its passive control guards
are described in [RUNTIME_DIAGNOSTICS.md](RUNTIME_DIAGNOSTICS.md). Its default
mode is passive. Separate default-off options permit one verified free Community
selection, one verified File/Open command, and the pinned tutorial filename/open
sequence through documented native controls. Each action requires fresh
identity/ownership/control checks. No activation request or solver action is
issued. The Windows helper compiles and runs pure policy checks before any
installer download or target startup. See the separate actual receipts for
which phases were attempted and observed.

For the pinned official installer, `python tools/extract_gms_target.py --help`
shows the explicit download/extraction interface. This is a roughly 2 GB opt-in
research operation; it is not part of normal installation or tests. Keep its
output private. The generic menu observation tool is:

```bash
python -m basinlens_ccs.reconstruction /private/path/gms10_9.exe --evidence /private/path/rea-resources.json --output /private/path/menu-observations.json
```

Text labels are excluded by default. Use `--include-labels` only for private
functional observations. Neither command executes GMS. The native probe in
`.github/workflows/gms-native-analysis.yml` is explicitly opted in; ordinary CI
does not download GMS or silently run a native investigation.

## Verify

```bash
python -m unittest discover -s tests -v
```

Solver tests are opt-in through `MF6_EXE=/absolute/path/to/mf6`; missing optional
dependencies or executable are reported as skips. Read `VALIDATION.md` for the
exact checks actually completed and their scientific limits.

## Conservative-solute workbench

The separate 1D transport section loads one synthetic example or a bounded JSON
upload only after an explicit action. Choose a fresh output directory to export
native input or run the configured MF6 executable. Result plots and downloads
use the verified run’s captured case. Both mass-conservation and concentration
bounds must pass for a successful scientific indicator. CLI commands, strict
units, benchmark equations and limits are in [TRANSPORT.md](TRANSPORT.md).
