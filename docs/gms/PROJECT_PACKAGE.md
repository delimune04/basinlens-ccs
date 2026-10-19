# Portable BasinLens project persistence

The new `.blproj` version 1 format saves the existing typed `SubsurfaceProject`,
its declared asset bytes and a small validated view state in one portable ZIP.
A project can be moved to a different directory, reopened and repacked without
losing its registered evidence or declared model configuration. This is an
original BasinLens format. Native GMS GPR writing, GPR round-trip equivalence and
original GMS project-loading behavior remain unverified and unimplemented here.

## Run the synthetic example

From the repository root, using a new output path:

```bash
PYTHONPATH=src python examples/project_package/run_example.py --output build/project-package-demo
PYTHONPATH=src python -m unittest discover -s tests -p test_project_package.py -v
```

The example creates `synthetic.blproj`, a relocated project directory and
`receipt.json`. The receipt records actual open/repack/reopen comparisons of
canonical project metadata, view state and every registered asset's exact bytes.
The example contains two authored synthetic CSV assets, three stratigraphic
units, a water well, a synthetic head observation, local CRS/datum declarations,
nonzero XY origin and a confined background-water engine configuration. The
observation is retained as metadata; it is not assimilated or field validated.
No solver, network request or original GMS process is invoked by this example.

## API

```python
from basinlens_ccs.subsurface.project_package import (
    save_project_package, open_project_package, verify_project_roundtrip,
)

saved = save_project_package(project, "study.blproj",
    asset_root="source-assets", view_state={"selected_layer": 0})
loaded = open_project_package(saved, "new-relocated-directory")
# loaded.project is typed; its relative asset paths resolve below this root:
asset_root = loaded.asset_root
receipt = verify_project_roundtrip(saved)
```

`save_project_package` returns the absolute saved `Path`.
`open_project_package` returns `LoadedProjectPackage` with `project`, `asset_root`,
`view_state`, `receipt` and `root`. The extraction root contains `project.json`,
`view_state.json`, `manifest.json` and an `assets` directory. Its project asset
paths are relative to `loaded.asset_root`, so direct `load_project` calls on the
extracted JSON must use `check_assets=False` and supply that asset root for
subsequent asset verification or engine export. A loaded package already checks
all of those asset bytes. No asset path, CRS, datum, units, property support,
observation time, stratigraphic relation or well metadata is guessed or converted.

All four view-state keys are saved explicitly after defaults and validation:

| Key | Supported values | Default |
|---|---|---|
| `selected_layer` | Integer in the project's layer range; booleans refused | `0` |
| `selected_field` | `head`, `hydraulic_conductivity_x`, `hydraulic_conductivity_y`, `hydraulic_conductivity_z`, `specific_storage`, `porosity` | `head` |
| `chart_mode` | `2d`, `3d` | `2d` |
| `show_wells` | Boolean | `true` |

A saved view selection does not assert that a computed result exists or that a
viewer supports every field. Unknown view keys and values fail explicitly.

## Format and integrity contract

Every package contains canonical UTF-8 JSON for its typed project, view state
and manifest. Canonical JSON sorts keys, uses compact separators, permits only
finite JSON values and ends with one newline. The manifest binds format and
integer version identifiers, the exact inventory of all other ZIP members,
their SHA-256/size pairs, every registered asset ID and relative path, and a
semantic digest over project metadata, view state and asset records. JSON
nesting/value-count budgets and duplicate-key refusal apply before typed use.

Only explicitly registered assets are included. Their original relative paths
are stored below `assets/`; their complete license/source/media-type/identity
metadata stays in the project. Reusing a single exact path for multiple declared
asset IDs is allowed only when all declare the same checksum. Each unique path
is read once per check, so aliases do not amplify file reads. Unregistered extra
ZIP entries and missing entries are refused, including a forged manifest that
attempts to introduce an undeclared asset. Typed project validation rechecks all
property, stratigraphic, mesh and observation asset references.

SHA-256 provides integrity binding, not authenticity or a digital signature.
Someone who replaces the whole project, asset bytes and all corresponding hashes
can create a different internally consistent package. Assets remain opaque inert
bytes; the package API does not parse their formats or establish their scientific
truth, license provenance or original GMS equivalence.

## Bounds, failures and recovery

| Bound | Version 1 limit |
|---|---:|
| Compressed archive | 64 MiB |
| Total declared and decoded member bytes | 128 MiB |
| Single registered asset | 32 MiB |
| Canonical project JSON | 2,000,000 bytes |
| Manifest JSON | 2,000,000 bytes |
| View-state JSON | 4,096 bytes |
| ZIP member count | 1,003 |
| JSON depth / values | 32 / 200,000 |

The reader accepts regular stored/deflated ZIP members, and refuses encryption,
unsupported compression, symbolic links, directory entries, comments/extra
fields, archive prefixes/trailing data, duplicate/case-fold-colliding paths,
file/directory collisions, traversal, drive/absolute paths, Windows device names,
trailing spaces/dots, non-NFC path spellings and other nonportable names. It reads
members within decoded limits without using `ZipFile.extract`. It checks regular
files before opening them, uses nonblocking/no-follow flags where available and
checks stable file identities, avoiding a FIFO wait. Source and destination
ancestors must not be symbolic links.

Saving checks each asset before construction and again before publication.
Opening hashes its source before and after, verifies all incoming members, then
verifies every restored file and its exact inventory before publishing the
relocated directory. Round-trip verification actually opens, repacks from the
relocated assets and opens again. It compares canonical project/view metadata
and all asset bytes, hashes the original source again, and reports ZIP byte
identity separately. A semantically identical accepted ZIP may have different
compression metadata and therefore a different archive hash.

Destination files/directories must be new and their parent directories must
already exist. Package files are staged on the same filesystem and published
using an atomic no-replace hard link; relocated directories use a same-filesystem
rename after a final fresh-path check. Parent directories must be trusted against
concurrent external replacement. This API does not coordinate arbitrary external
writers to a destination directory. Expected write/verification errors clean up
their staging files/directories and leave the final destination absent, allowing
the same command to be retried. A process kill or power loss can leave an unused
hidden `.partial-*` staging path; it is never treated as a valid package or
loaded project, and a retry uses a fresh staging path. Cleanup of a leftover
staging path is appropriate only after confirming no writer still owns it.

Existing destinations are always refused. No pickle, executable deserialization,
dynamic imports from package contents, automatic solver execution, native GPR
writing or unknown-format conversion is supported.

## Validation scope

The 30 package regressions cover metadata/byte relocation, actual deterministic
open/repack/reopen, empty packages, shared-path aliases, tamper and forged
inventories, versions, duplicate JSON/ZIP members, view-state bounds, direct
mutable option revalidation, malformed/nonportable paths, symlinks/encryption/
compression/budget refusals, controlled corrupted-DEFLATE errors, bounded FIFO rejection, existing-output protection,
source changes during operations, simulated full-disk and rename failures and
successful retry. These are software persistence checks on synthetic data.
They establish neither original GMS compatibility nor new numerical/field
validation. The whole GMS reconstruction objective remains open.
