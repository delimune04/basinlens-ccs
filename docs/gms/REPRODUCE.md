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

## Verify

```bash
python -m unittest discover -s tests -v
```

Solver tests are opt-in through `MF6_EXE=/absolute/path/to/mf6`; missing optional
dependencies or executable are reported as skips. Read `VALIDATION.md` for the
exact checks actually completed and their scientific limits.
