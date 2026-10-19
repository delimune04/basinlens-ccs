# Native MF6 folder interoperability

`basinlens_ccs.groundwater.gms_native` independently reads the native MODFLOW 6
file graph produced by a GMS export. It discovers simulations directly or through
the observed `<project>_models/MODFLOW 6/<simulation>/mfsim.nam` and
`<project>_data/Components/<uuid>/mfsim.nam` layouts. A `.gpr` path is used only to
locate those adjacent directories; `.gpr` contents are not parsed. If both editor
components and exported simulations are present, select one `mfsim.nam` explicitly.

```bash
python -m basinlens_ccs.groundwater.gms_native /path/to/mfsim.nam
```

The report records models, packages, referenced inputs, output declarations,
file hashes, unresolved paths, and sidecars. Quoted paths and native input files
in subdirectories use the simulation working directory. Files outside the import
boundary are reported; an explicit `--allowed-root` can widen it to the supplied
project directory. A supplied project directory or `.gpr` path uses that project
directory as its import boundary. Structural text must be completely scanned;
only explicitly declared binary `OPEN/CLOSE` array leaves skip text parsing.
Aggregate inputs and sidecars are limited to 512 MiB. Nothing executes or modifies
the source model.

The Python `load_with_flopy(path)` function returns the public FloPy simulation
and the import report. This preserves numerical arrays and stress-period data
without forcing them into BasinLens's smaller confined-aquifer case schema.
The function does not run the numerical solver.

## Execute an existing native model

The separate native runner copies exact input bytes into a new isolated folder,
executes a caller-selected USGS MODFLOW 6 binary, checks that source and copied
inputs remain unchanged, and records native units, logs, outputs and hashes:

```bash
python -m basinlens_ccs.groundwater.native_run /data/project/model/mfsim.nam --allowed-root /data/project --output /data/runs/native-001 --exe /absolute/path/to/mf6
python -c 'from basinlens_ccs.groundwater.native_run import verify_native_run; print(verify_native_run("/data/runs/native-001")["status"])'
```

The output must be fresh and outside the original allowed-root tree. Absolute,
escaping and input-overwriting output references are refused. Default execution
limits are 300 seconds and 1 GiB; no solver is downloaded. The Streamlit native
section exposes inspection, execution and verified ZIP export separately from
confined-case plots. Its in-memory ZIP download is capped at 128 MiB; larger
results remain in the displayed server workspace.

Opaque GUI sidecars are archived separately and **never synchronized into solver
inputs**. A stale editor component and a saved-model export may calculate
different results even inside the same GMS project. Select the intended
`mfsim.nam` explicitly and establish export freshness. Normal solver termination
is operational success; arbitrary model physics, units correctness, conservation,
CO2 properties and GMS behavior are not independently validated by this runner.
`verify_native_run` checks inventory and byte integrity, not operator truth or
scientific validity. Failed runs retain diagnostics with an explicit failed state.

## Observed sidecar contract

| File | Independent import behavior |
| --- | --- |
| `gms_options.json` | Preserve the full JSON object, including unknown properties. Observed option names include `USE_OPEN_CLOSE`, `USE_INPUT_DIR`, `USE_OUTPUT_DIR`, and `AUTO_FILE_NAMING`. |
| `settings.json` | Preserve the full per-directory JSON object. UUID references are metadata; no native DMI compatibility is claimed. |
| `periods.db` | Inspect a private immutable snapshot of an ordinary `data` table, dynamic columns, period counts, and a bounded row sample; reject live WAL/journal state and virtual tables. |

Observed SQLite bookkeeping fields are `PERIOD` (one-based), `PERIOD_ROW`
(zero-based), and `id`. Native cell IDs are one-based. `CELLIDX`, or the two
`CELLIDX1`/`CELLIDX2` columns used for paired cells, are zero-based caches.
The importer retains these conventions rather than silently converting them.
It does not merge database edits into solver text files because synchronization
between a particular database and exported inputs has not been established.

## Provenance and limits

The format observations came from private static inspection of the official
GMS 10.9.7 distribution, installer SHA-256
`69fef79023d065d4664e74950e10669c784a7e18fabfaa8ada48b2760f624335`.
Relevant source boundaries were `xms.mf6.misc.settings`,
`xms.mf6.file_io.database`, `xms.mf6.file_io.mfsim_reader`,
`xms.mf6.file_io.mfsim_writer`, and `xms.mf6.components.sim_component`.
REA recorded their surrounding source inventory as historical reference:
manifest `hsm_3bf46c4b00c8fadc72b0f8d6d27390e09da7ea65fbc16a21040a200eaddd26b4`.
The importer is original code. No proprietary implementation or sample project
is distributed here.

Tests use independently authored native folders, JSON, SQLite records, and a
fresh model generated by FloPy. They verify path resolution, read-only period
import, and numerical-array loading. No GMS runtime comparison has occurred;
full `.gpr`, GUI, DMI, and numerical parity remain unverified.

Public numerical format references:

- [USGS MODFLOW 6](https://www.usgs.gov/software/modflow-6-usgs-modular-hydrologic-model)
- [FloPy](https://github.com/modflowpy/flopy)
