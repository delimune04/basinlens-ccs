# Vertical boreholes, material logs and explicit sections

This independent implementation supports a bounded geological data workflow:
strict JSON loading, portable CSV export/import, complete semantic roundtrip,
material interpretation edits with retained history, finite-polyline sections,
and grouping of sample contacts by **explicitly supplied horizon identifiers**.
It is not a GMS/GPR writer, a recovered proprietary algorithm, a geological
solid builder, or an original GMS behavior comparison. All examples are authored
synthetic data. No field measurement or CCS/oil multiphase validation is implied.

## Contract

`basinlens-geology-v1` retains the project identifier/name, explicit metre units,
CRS and vertical datum, asset identities, provenance records, materials, horizon
identifiers, borehole collars, intervals and edit history. `unknown` CRS/datum
remain literal `unknown`; loading performs no projection, conversion or inference.
Coordinates are XY and elevation Z positive upward. Known `EPSG:4326` longitude/
latitude degree coordinates are refused under the metre contract; opaque other CRS
text is retained, without certifying its units or suitability. Boreholes are vertical.
Depth is positive downward from each collar, so `elevation = collar_z - depth`.
Measured-depth/deviated surveys, feet and other depth conventions are refused.

Each borehole contains sorted, contiguous intervals covering exactly zero through
`total_depth_m`. An unknown/unlogged span must be an explicit `kind="gap"`
interval with null material and null contact identifiers. Logged spans require
a registered material; no missing interval is filled automatically. Adjacent
non-null contact identifiers must agree. A horizon identifier cannot occur at
two different depths in one vertical borehole in this schema. Fault repetitions
or complex stratigraphic interpretations therefore require another explicit
contract; they are not flattened into this one.

Each material, horizon, borehole and interval has a valid `provenance_id`.
Provenance distinguishes `synthetic`, `observed`, `interpreted` and `unknown`.
Observed/interpreted records require registered source assets. This is traceable
input metadata, not independent proof that a declared observation is correct.
Assets declare an identifier, safe `assets/...` path, SHA-256, media type and
license/use condition. Every registered file is read and checked. Source files
are never modified. No URI is fetched and no asset content is executed.

`GeologyProject.from_dict()` returns an immutable canonical document. All public
operations revalidate its content, including directly constructed instances.
`edit_interval_material()` returns a new document; it records the interval,
old/new material IDs, explanation, provenance, source project SHA-256 and before/
after geological state hashes. Validation replays every retained edit backwards
against the full current document. Hashes detect accidental corruption; they
are not signatures, permission grants or scientific validation. Human explanations
are retained literal text. Existing gap evidence cannot be changed to a logged
span through this limited material-edit operation.

## Files and portability

The JSON reader rejects duplicate keys, unknown fields/versions, nonfinite
numbers, Boolean coordinates, malformed references and nonregular/symlink paths.
`save_geology()` atomically creates a fresh canonical UTF-8 JSON file and refuses
existing destinations. JSON declares asset paths relative to an explicitly supplied
`asset_root`; saving a JSON file does not copy its assets. When moving a JSON alone,
keep its registered assets and pass `asset_root` to API operations or `--asset-root`
to the CLI. Use the CSV directory for a self-contained portable representation.

`export_geology_csv()` atomically creates a fresh directory containing:

| File | Content |
|---|---|
| `metadata.json` | Schema, project metadata, provenance, asset declarations and edit history |
| `materials.csv` | Material identifiers, names, descriptions and provenance |
| `horizons.csv` | Explicit horizon identifiers, names and provenance |
| `boreholes.csv` | Collar XYZ, total vertical depth and provenance |
| `intervals.csv` | Hole/interval IDs, top/bottom depths, explicit gap/log kind, material and horizon IDs |
| `assets/...` | Exact registered source bytes |
| `manifest.json` | Every member's byte length/hash and the complete semantic project hash |

CSV columns and order are exact, IDs remain strings, null references are empty
fields, and numbers preserve Python's roundtrippable finite float representation.
The importer is this explicit CSV contract, not an arbitrary vendor CSV guesser.
It rejects extra/missing/unregistered files, changed bytes, inconsistent metadata,
invalid table geometry and semantic hash disagreement. No table is silently dropped.
Both JSON and CSV fail before publishing a final output on a validation/I/O failure;
their owned staging paths are cleaned. Retry with a fresh destination after correcting
the source. Filesystem parents must be trusted against concurrent mutation; this is
not an adversarial concurrent directory service.

Bounds: 200 boreholes, 20,000 total intervals, 1,000 materials/horizons/provenance
records, 100 registered assets, 32 material edit events, 8 MiB JSON/table, 16 MiB
per asset, 64 MiB portable payload, 1,000 section vertices, finite coordinate
magnitude at most 1e9 m, total depth at most 1e6 m. Asset path depth and filesystem
inventory are also bounded. Source regular-file checks precede opening (including
pipes); read size and identity are checked again after reading. Output conflicts
and faults preserve the source and never overwrite an existing result.

## Sections and contact grouping

`project_section(project, polyline_xy, max_distance_m=...)` evaluates every collar
against every **finite, clamped** polyline segment. The nearest segment is selected;
the earliest segment wins an exact-distance tie. Chainage is the preceding segment
length plus the along-segment distance. Only collars at or within the explicit
cutoff are included. Both the included and excluded distances are returned.

`signed_offset_m` is the perpendicular component, positive to the left of the
selected oriented segment. `distance_m` is the full Euclidean distance to the
finite segment, including endpoint displacement. A collinear collar beyond an
endpoint can have offset zero and a nonzero distance. Returned intervals retain
their source IDs/provenance and add top/bottom elevations. There is no vertical
exaggeration, nearest-hole substitution or geological interpolation.

`correlate_horizons()` groups only identical declared horizon IDs. Adjacent
interval references to the same contact are de-duplicated as one sample point
while preserving both provenance references. Unused horizons retain an empty
contact list. The result contains the source semantic hash, CRS/datum and
`surfaces_inferred=false`. Equal material names, similar depths or nearby holes
do not produce a correlation, horizon surface or volumetric layer.

Independent hand arithmetic in the regression fixture: polyline `(0,0)→(10,0)→(10,10)`
projects A `(3,4)` to chainage 3 m, distance/offset +4 m; B `(12,8)` to chainage
18 m, distance 2 m and offset −2 m. C `(−3,0)` has chainage zero, distance 3 m
and zero perpendicular offset. D at the corner chooses segment zero. A's explicit
H1 contact is elevation `100−2.5=97.5 m`; B's is `110−4=106 m`.

## Run the implementation

From the repository root, with an installed package or `PYTHONPATH=src`, choose
fresh output paths whose parent exists:

```bash
python -m basinlens_ccs.subsurface.geology check examples/geology/synthetic_boreholes.json
python -m basinlens_ccs.subsurface.geology roundtrip examples/geology/synthetic_boreholes.json --output build/geology-roundtrip
python -m basinlens_ccs.subsurface.geology section examples/geology/synthetic_boreholes.json --polyline-json examples/geology/section.json --max-distance-m 4 --output build/geology-section.json
python -m basinlens_ccs.subsurface.geology contacts examples/geology/synthetic_boreholes.json --output build/geology-contacts.json
python examples/geology/run_geology_example.py --output build/geology-example
python -m unittest discover -s tests -p test_geology.py -v
```

`export-csv`, `import-csv` and `edit-material` are also actual CLI commands; run
`--help` for their arguments. `invalid_overlap.json` deliberately fails validation.
The tests cover nonuniform logs/gaps, exact source/asset and relocated roundtrips,
hand-calculated oblique and bent sections, contact provenance, edit replay,
unknown units/references, duplicate keys, malformed CSV/manifest, symlink/pipes,
budgets, output conflicts and injected failure followed by successful retry.
These are software and synthetic geometry checks. Original GMS comparison remains
not performed, and whole-product reconstruction remains incomplete.

## Implementation check, 2026-10-19

The focused suite passed **26 tests, zero skips**, in 6.616 s on Python 3.12.
The authored execution example completed with four projected boreholes, two
explicit H1 contacts, one traceable material edit, equal JSON→CSV→JSON meaning,
exact registered asset bytes and unchanged source. The invalid overlap example
returned CLI exit 2 with the specific depth-coverage error. An independent peer
review verified the hand geometry and ran the 26-test suite (zero skips); its
known geographic-CRS/metre contradiction finding was corrected and covered by
regressions. Final portability checks also reject non-NFC and DEL asset names.
These results do not establish compatibility with original GMS behavior.
