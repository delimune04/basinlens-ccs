# Portable typed geoscience collections

`geoscience_project.py` adds a strict typed-object manifest to the existing own
`.blproj` package. It saves, relocates, opens and re-saves geological logs,
scatter data, conceptual features, planar meshes, rasters, encoded point clouds,
explicit geological surfaces and **inert exported analysis bundles**. It does
not change the old workflow project schema/behavior, write GPR, execute assets,
convert coordinates, register datasets, map objects into a solver, restore live
analysis engines or establish original GMS parity.

## Reproduce

```bash
python examples/geoscience_project/run_geoscience_project_example.py --output build/portable-geoscience
python -m basinlens_ccs.subsurface.geoscience_project roundtrip build/portable-geoscience/mixed.blproj
python -m basinlens_ccs.subsurface.geoscience_project open build/portable-geoscience/mixed.blproj --output build/another-restoration
python -m unittest discover -s tests -p test_geoscience_project.py -v
```

No solver, service, proprietary file or download is needed. The example really
removes the temporary original geology dependency root before restoring the
relocated archive. It then re-saves and compares archive bytes. Original input
and code SHA-256 values, restored canonical object identities and all generated
artifact hashes are retained in `example.json`.

The main authored collection uses literal `unknown` CRS/datum, as declared by
its own fixture. Equality of unknown labels is **not spatial alignment proof**.
Existing raster/point-cloud/surface fixtures declare different coordinate
contracts, so the example uses a separate explicitly matching reference project
for each. No loaded object is retagged or silently transformed. Its analysis
archive contains an explicitly authored array fixture, not a solver run.

## Public API

```python
from basinlens_ccs.subsurface.geoscience_project import (
    ProjectObject, save_geoscience_project, open_geoscience_project,
    verify_geoscience_project_roundtrip,
)

save_geoscience_project(
    typed_subsurface_project,
    [ProjectObject("geology", "boreholes", typed_geology),
     ProjectObject("features", "coverage", typed_features)],
    "fresh.blproj", asset_root="generic-original-assets",
    object_asset_roots={"boreholes": "geology-original-assets"},
    view_state={"selected_layer": 0, "selected_field": "porosity",
                "chart_mode": "3d", "show_wells": False},
)
loaded = open_geoscience_project("fresh.blproj", "fresh-restoration")
save_geoscience_project(loaded.project, loaded.objects, "another.blproj",
                       asset_root=loaded.asset_root, view_state=loaded.view_state)
verify_geoscience_project_roundtrip("another.blproj")
```

`LoadedGeoscienceProject` exposes the typed `project`, tuple of `ProjectObject`
records, `asset_root`, `view_state`, operation `receipt`, and restored `root`.
Its `object_asset_roots` property maps each geology object ID to that restored
asset root. Original geological relative paths remain unchanged.

| Kind | Exact trusted value type | Stored support |
|---|---|---|
| `geology` | `GeologyProject` | Complete own canonical JSON and every original registered source asset byte |
| `scatter` | `ScatterDataset` | Values, missing reasons, units, provenance, identities and explicit dimensional metadata |
| `features` | `FeatureCoverage` | Complete conceptual nodes/points/arcs/polygons/attributes; no automatic boundary conversion |
| `mesh` | `PlanarMesh` | Actual validated connectivity, cell material labels and geometry/provenance |
| `raster` | `RasterGrid` | Values/null masks, explicit pixel geometry/row direction and literal metadata |
| `pointcloud` | `PointCloud` | Original encoded LAS prefix/records, opaque payload bytes and source point identities inside own typed JSON |
| `surfaces` | `SurfaceModel` | Actual explicit TIN connectivity, horizons, material layers and edit history |
| `analysis_archive` | `AnalysisArchive` | Exact original `analysis.json`, `samples.csv`, `manifest.json` as registered inert files |

Collection IDs are project-local ASCII `[A-Za-z][A-Za-z0-9_-]{0,63}`. They never
replace IDs inside the original object. IDs are globally unique across kinds,
including case folding. Duck-typed dictionaries, arbitrary module/class names,
unknown kinds, extra fields and unsupported own schema versions are refused.

## Generic project preservation and spatial agreement

All generic `SubsurfaceProject` fields, observations, wells, strata, model
options, original registered assets and supported view state are preserved.
The layer only appends its registered managed assets. Model domains such as
CCS/oil remain metadata: no new multiphase engine or flow mapping is inferred.
Existing generic reference assets are copied byte for byte and not interpreted.

Every spatial object must explicitly declare metre coordinates and the same
literal CRS as the outer project. A declared vertical datum must also match.
Purely planar features/meshes have no vertical datum alignment claim. Point
cloud horizontal and vertical units must both explicitly equal `m`; `ft` and
`unknown` units are refused. There is no conversion, CRS lookup, guessed datum
or automatic georeferencing. Matching metadata do not prove field registration,
geological compatibility, common extent or model support. Objects may be
reference data outside the model geometry; no object-to-model assignment occurs.

## Manifest and original bytes

The reserved registered manifest is asset `bl_geoscience_manifest` at
`geoscience/objects.json`. It binds the preserved generic project canonical hash,
every kind/collection/document ID, canonical JSON hash/path, literal spatial
metadata, exact source dependency IDs, and the complete managed `DataAsset`
metadata. Managed object IDs use `bl_geo_*`; managed paths use `geoscience/`.
These names are refused for unrelated generic assets.

The existing bounded container still verifies all source/asset/view bytes. The
new layer then validates the actual trusted object types and semantic manifest
bindings before publishing the restored root. A valid generic package with
contradictory inner metadata therefore fails. Rehashing generic archive bytes
does not remove these independent type/metadata checks. Integrity hashes do not
prove authorship, legal entitlement or scientific truth.

Geology dependency paths, SHA-256, media type and license remain exactly as
declared by the original object. The wrapper uses project-local registration
IDs while preserving every original ID/reference inside the typed geology
document. Duplicate path bytes/media/license, case-folding, file/directory and
reserved namespace conflicts are refused. Shared exact original bytes at one
path may have separate consistent registration IDs.

Re-saving an existing typed collection first validates its original managed
graph, then explicitly replaces the supplied object collection while retaining
all generic metadata/assets. It can remove/replace objects without leaving
unreferenced managed payloads. It does not silently modify a loaded object's
coordinate labels to fit a new project.

## Inert analysis archive

`archive_analysis_bundle(existing_export_folder)` captures a valid own exported
analysis bundle. `AnalysisArchive.files` returns independent mappings of exact
immutable bytes. The original analysis metadata/source claims are preserved,
but stored workspace paths are never followed while opening the collection.
The archived result is not a live `AnalysisVolume`; solver state is not restored.

Analysis archive validation checks **file inventory, hashes and JSON/CSV
consistency**, supported explicit operation/unit/spatial metadata, and exact
original file bytes. It does not independently recompute query values/residuals,
authenticate user-edited derived dictionaries, reverify an unavailable original
solver run, establish field validation or compare with GMS. The receipt states
that analysis archives are inert and that no engine was executed.

## Bounds, failure recovery and checks

The container remains capped at 64 MiB compressed, 128 MiB decoded, 32 MiB per
asset, 1,003 members and 2 MB generic project metadata. This extension allows
1..64 objects and at most 2,000,000 finite JSON values per canonical object.
A cloud module's larger standalone JSON limits do not override the package's
32 MiB single-asset cap. No unbounded chunking/import or dynamic plugin loading
is implied. All source/destination parent directories must be trusted against
concurrent replacement, as required by the existing package layer.

Source files are rechecked before and after saving; mutation detected after
publication removes only the unchanged newly created output, including when an
original file disappears or becomes a special file. A replaced destination is
preserved and reported separately. Aggregate unique-path byte budgets and asset
counts are enforced incrementally before reading later source payloads; objects
are validated one at a time rather than retaining 64 maximum-size clones.
Consistent alias paths share one captured byte object. Existing outputs are
never overwritten. Opening validates in an owned staging directory and publishes
only after all checks; rejected opens remove that staging directory and leave
the requested final destination absent. Correct the exact diagnostic and retry
using a fresh output path.

Focused tests perform actual relocation/open/re-save and deterministic archive
comparison, preservation of generic metadata/options/observations/opaque bytes,
typed new modules under their actual coordinate contracts, inert archived
analysis recovery, explicit collection edits, and original-source immutability.
Adversarial cases build valid rehashed **generic** packages with contradictory
typed metadata/paths/media/licenses/identity/connectivity, unknown executable
class fields, duplicate dependencies, reordered/extra assets and changed outer
metadata. These must still fail the typed layer. Missing/changed/FIFO/symlink
sources, mutation during save/open, unsupported budgets and CLI recovery are
also checked. No original GMS or field-equivalence claim follows from these tests.
