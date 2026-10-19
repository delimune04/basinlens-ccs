# Portable spatial workflow projects

`workflow_project.py` connects the authored spatial model workflow to the
portable BasinLens `.blproj` package. Saving records the complete canonical
workflow case, its exact derived shared project and the supported view state.
Opening validates all three before publishing a relocated project directory.
This is a BasinLens format. Native GMS GPR writing, original GMS loading
equivalence and original GMS numerical parity remain unimplemented/unverified.

## Reproduce a save, relocation and actual round trip

From the repository root, with the optional groundwater dependencies installed:

```python
from pathlib import Path
from basinlens_ccs.subsurface.model_workflow import load_workflow_case
from basinlens_ccs.subsurface.workflow_project import (
    save_workflow_project, open_workflow_project,
    verify_workflow_project_roundtrip,
)

root = Path("build/workflow-project-example")
root.mkdir(parents=True, exist_ok=False)
case = load_workflow_case("examples/workflow/layered_background_water.json")
archive = save_workflow_project(case, root / "model.blproj",
    view_state={"selected_layer": 1, "selected_field": "porosity",
                "chart_mode": "3d", "show_wells": False})
loaded = open_workflow_project(archive, root / "relocated")
assert loaded.case.to_dict() == case.to_dict()
assert loaded.receipt["workflow_shared_project_consistent"]
receipt = verify_workflow_project_roundtrip(archive)
assert receipt["roundtrip_verified"]
```

Run the focused software regressions with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_workflow_project.py -v
```

The persistence operations execute no solver and access no network service.
The loaded case can be passed explicitly to `export_workflow` or `run_workflow`;
actual numerical execution and native input round trips have separate receipts.

## One authoritative model

The complete canonical workflow JSON is the registered asset
`workflow/model.json`, asset ID `workflow_model`. It preserves every period,
boundary kind/support/value, initial head, material name, material assignment,
stratum, unit, origin, row convention and provenance statement. No boundary
schedule is reconstructed from a geometry-only summary.

The outer `SubsurfaceProject` is derived deterministically from that asset:

| Shared field | Exact projection |
|---|---|
| Identity/domain | Workflow project ID, name and domain |
| Spatial reference | Declared m/day units, literal CRS and vertical datum; unknown stays unknown |
| Geometry | Uniform spacing, unrotated flat layer surfaces and XY origin |
| Local rows | Canonical project y increases with row; workflow row axis is south to north |
| Named geology | Every stratum ID, name and its exact layer indices |
| Rock fields | All-cell Kx/Ky/Kz, specific storage and porosity |
| Provenance | Every workflow provenance statement retained as a shared assumption |
| Model declaration | `modflow6_spatial`, confined single-phase water, explicit `background_water` role |
| Model options | Only the authoritative `workflow_asset_id` reference |
| Registered asset | Exact canonical case bytes and their SHA-256 identity |

Each property uses global support if all cell values are exactly equal, complete
layer support if each whole layer is exactly uniform, otherwise complete ordered
cell support. No numerical approximation or sparse coverage is introduced.
The shared properties are marked assumed and reference the canonical case;
this projection does not invent measured-property provenance. Porosity remains
declared geological metadata; confined GWF does not use it as a storage coefficient.

Outer static wells and observations are empty. Every period-specific WEL,
CHD/RCH/GHB/DRN/RIV condition remains in the authoritative case, including
explicit termination between periods. Saving this workflow does not import
unrelated shared-project observations or source assets. The workflow schema
does not contain such records; generic shared-project persistence is handled by
the separate project package API.

Opening recomputes the complete expected shared project from the asset and
requires exact agreement. A coherently rehashed generic package with a changed
outer origin, CRS, property, stratum, name, engine declaration or extra asset is
rejected. A case asset with invalid units/physics or noncanonical JSON is rejected
even if its generic package hashes are consistent. The shared engine declaration
does not register an engine dynamically: `default_registry` does not expose the
new spatial compiler. Use the explicit spatial workflow API for export/run.
Neither the CCS nor oil-exploration domain label provides multiphase physics.

## Bounds, failures and evidence

All generic package path, decoded-byte, inventory and canonical-JSON guards
apply. This bridge additionally requires the workflow case byte budget and the
shared schema's geometric limits, including at most 500 columns. The spatial
compiler accepts up to 1,000 columns; a wider case is refused by the bridge
without publishing a package. Highly heterogeneous property projections can
reach the generic package's 2,000,000-byte project or JSON-value budget before
the spatial compiler's cell limit. Such cases are refused explicitly; no fields
are dropped or downsampled.

The final output must be new. Opening first restores the generic package into a
private sibling staging directory, validates the canonical case and complete
outer projection, then hashes the original archive again immediately before
final publication. A source change or contradiction removes the staging output
and leaves the final destination absent. Failed final promotion likewise cleans
the staging directory; the same command can be retried after correcting its
cause. Package files use atomic no-replace publication; restored directories
use same-filesystem rename under the generic API's trusted-parent concurrent
writer boundary. A kill or power loss may leave an unused hidden staging path;
it is not a valid loaded project.

`LoadedWorkflowProject` returns `case`, `project`, `view_state`, `receipt`, `root`
and `asset_root`. The enriched workflow receipt is returned to the caller;
the generic on-disk receipt retains its own narrower package-validation scope.
The actual round-trip function opens, saves from the authoritative relocated
case, reopens and compares complete case/project/view semantics and exact asset
bytes. It separately reports archive byte identity and source preservation.
Integrity hashes do not authenticate the data owner or establish scientific
truth, licensing rights, field validation or original GMS equivalence.

The focused regressions exercise actual relocation, global/layer/cell property
support, every supported boundary across periods, canonical assets, coherently
rehashed contradictions, invalid physics, existing-output refusal, source
changes after generic opening, simulated final-promotion failure and successful
retry. They are software persistence checks on authored synthetic data.
