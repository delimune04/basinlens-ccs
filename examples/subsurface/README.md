# Subsurface extension examples

These two version-1 projects reuse the same synthetic confined-water case in
CCS and oil-exploration project domains. Their model role is **background_water**.
The domain label does not change the fluid or numerical model. No CO2 plume,
petroleum discovery, black-oil flow or seismic interpretation is computed.

`synthetic_layer_properties.csv` is a CC0 synthetic fixture, registered by SHA-256
in each project. No field measurements are included. Hydraulic conductivity is
in m/day, specific storage in 1/m, geometry/head in m, and time in days. Origin
coordinates and upward-positive elevations share the declared local datum.

```bash
PYTHONPATH=src python -m basinlens_ccs.subsurface engines
PYTHONPATH=src python -m basinlens_ccs.subsurface validate examples/subsurface/ccs_background_water.json
PYTHONPATH=src python -m basinlens_ccs.subsurface export examples/subsurface/oil_background_water.json --output build/oil-background-inputs
PYTHONPATH=src python -m basinlens_ccs.subsurface run examples/subsurface/ccs_background_water.json --output build/ccs-background-run --exe /absolute/path/to/mf6
```

Install the existing `groundwater` extra explicitly to use FloPy. Running also
requires an installed MODFLOW 6 executable; these commands do not download it.
Every output directory must be new.

The outer bundle preserves `project.json`, exact conversion `mapping.json`,
`project_summary.json` and a checksummed `project_run_metadata.json`; the inner
`engine/` bundle is the unchanged existing groundwater workflow. Verify both
with `basinlens_ccs.subsurface.verify_project_bundle(path)`.

Source assets are checked before export/run and remain referenced by path/hash;
the raw asset files are not copied into run bundles. A snapshot inside a run can
be loaded with `load_project(path, check_assets=False)`; to recheck original
assets call `verify_assets(project, original_asset_root)`. Disabling the loader
check does not bypass the registry's mandatory asset checks before export/run.

`RockProperty` supports explicitly ordered global, layer and cell fields. The
implemented MODFLOW adapter accepts global or complete layer hydraulic fields;
it rejects cell fields instead of silently averaging them. Additional rock
properties, stratigraphic labels, registered mesh assets and observations are
preserved as metadata. Observations are not assimilated; mesh assets do not
replace the structured solver grid. Unused properties are listed in mapping.

The registry also advertises `opm_flow_co2`, `opm_flow_blackoil`, and
`seismic_interpretation` as **NOT_AVAILABLE**. Selecting them fails before output
creation. Their names describe extension boundaries, not installed integrations.
Trusted Python code may register an `EngineAdapter` with declared physics, roles,
domains and runtime availability. Project JSON never imports executable plugins.
