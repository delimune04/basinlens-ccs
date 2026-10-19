# Partial serialized project relationships

`groundwater.gpr_project.read_gpr_project(path)` now reads a bounded subset of
the GPR project's saved tree and UUID reference vectors. It returns a private
in-memory `ProjectGraph`; `public_summary()` emits anonymous node/entity IDs,
fixed categories, relationships, counts, and an input identity receipt. Original
labels, raw type strings, module numbers, UUID strings, filenames, and HDF5
paths are omitted from that public projection. The command below emits that
projection only:

```bash
python -m basinlens_ccs.groundwater.gpr_project /absolute/path/project.gpr
```

This is an original implementation derived from read-only format observations
in one official Aquaveo MODFLOW 6 grid tutorial project. No vendor project,
program bytes, copied implementation, or reconstructed writer is included.

## Observed grammar

`/Tree/Tree` is a one-dimensional fixed-width string vector. The examined file
has 190 records of width 44 bytes. The parser recognizes these balanced frames:

| Record | Observed structural meaning |
| --- | --- |
| `BEGTREE` / `ENDTREE` | One tree envelope with one root of type `Project` |
| `BEGTRNODE` / `ENDTRNODE` | Nested nodes; the nearest enclosing node supplies the parent |
| `BEGTRMOD number` / `ENDTRMOD number` | Matching numbered module envelopes inside a node |
| `TRTYPE token` | One bounded ASCII type token per node |
| `TRNAME "text"` | Optional private label; no evaluation or escape interpretation |
| `TRGUID uuid` | Optional UUID string with canonical hexadecimal/hyphen syntax |
| `TRID`, `TREXPANDED`, `TRSTATE`, `TRACTIVE` | Optional signed 32-bit fields; expansion is restricted to the observed 0/1 values |

Fields cannot repeat within a node. Missing/mismatched frames, unsupported
records, control characters, malformed UUIDs or labels, and excessive depth or
record counts fail closed. Fixed strings must decode as UTF-8; the actual
tutorial records are ASCII. Legacy encodings and quoted-label escaping have
not been established. State/active integers are retained privately without
assigning undocumented UI behavior to their values.

Known observed node tokens map to fixed public categories such as project,
grid, dataset, component, solution folder, and dataset pointer. An unknown but
syntactically valid type stays `unknown`; its raw token remains private. Module
numbers are structural observations, without inferred module capabilities.

## Relationships that can be supported by the data

| Serialized data | Supported observation |
| --- | --- |
| Root `GUID` | Literal UUID match to a project tree node |
| Grid `PROPERTIES/GUID` and `Datasets/Guid` | Grid-container UUID agreement and matches to grid tree nodes |
| Three `PROPERTIES/* Z Dataset Uuid` values | Declared point/top/bottom geometry-field references matching dataset tree nodes |
| A saved dataset's `GUID` | Matches to dataset/dataset-pointer tree nodes; `Values`, `Times`, and `Active` storage metadata only |
| `SimSolutions/<family>/<solution>/GUID` | Matches to solution-folder tree nodes |
| `SolutionDatasets` | Explicit UUID-vector entries matched against tree nodes and saved dataset identities |
| `SolutionComponents` | Explicit UUID-vector entries matched against component tree nodes |

Matches use **literal, case-preserving string equality**. No trimming, case
folding, label matching, UUID rewriting between contexts, or chosen target among
duplicates is inferred. Each equality edge records the number of matching
targets. Duplicate or nil UUID equality is a string coincidence, rather than
proof that serialized objects are equivalent. A tree-only match does not prove
that numeric storage or an external component payload exists. A GUID-only saved
dataset group remains an identity record; absent `Values` storage is explicitly
unresolved and does not count as numeric storage backing a tree node.

The grid-pointer node's target encoding remains unknown. Component files are
not followed or synchronized, the simulation-to-editor-component mapping is
not established, and an unmatched solution-folder identity remains unresolved.
Geometry-field property references are declarations; the tree reader does not
decode their geometry packet or load numeric field values. Coordinate units,
CRS, vertical datum, physical time interpretation, and numerical behavior remain
outside this graph's scope.

## Read boundaries and compressed-storage hardening

The input is limited to 512 MiB and hashed before and after inspection. Only
complete HDF5 hard-link paths are traversed. String payloads must be fixed-width,
one-dimensional vectors; VLEN/object, virtual, external-storage, plugin-filter,
and indirect-link reads are rejected. Limits include 20,000 records, 4,096
nodes, depth 128, 8 MiB logical string bytes, 16 MiB stored string bytes,
16 MiB decoded full-chunk bytes, and 4,096 chunks across the graph inspection.
Generated entities, relationships, unresolved records, and candidate-join work
also have independent hard limits (8,192 / 32,768 / 16,384 / 1,000,000).

The shared `gpr_storage` helper also hardens existing explicit numeric reads.
Checking a dataset's logical shape and advertised chunk size is insufficient:
an independently constructed raw deflate chunk can expand beyond its declared
size before HDF5 returns only the expected prefix. The helper therefore reads
bounded raw chunk bytes and performs its own output-limited zlib decoding. It
does not invoke HDF5's decompressor afterward. Stored chunk count/size/mask,
coordinate coverage, full edge-chunk expansion, aggregate decoded bytes, exact
stream completion, and trailing data are checked before returning arrays.

Only unfiltered storage or a single deflate filter is supported for payload
reads. Shuffle, Fletcher32, mixed/unknown filters, sparse/unallocated chunks,
and noncanonical numeric file datatypes are rejected. Numeric file types must
equal the canonical HDF5 type reconstructed from the NumPy dtype, preventing
silent loss of file precision/bit-offset rules. Fixed strings support ASCII or
UTF-8 NULLTERM/NULLPAD layouts. NULLTERM values end at their first NUL as defined
by HDF5; later padding bytes are excluded. SPACEPAD and interior NUL in NULLPAD
records are rejected. Metadata inventory remains available
without decoding unsupported payloads. Inputs must remain quiescent during
inspection; the whole-file before/after hash verifies the observed byte identity.

The primary HDF5 API contract for raw chunks and filter masks is documented in
[h5py's low-level dataset API](https://api.h5py.org/h5d.html) and file datatype
rules in [its datatype API](https://api.h5py.org/h5t.html). Format inspection and
checks were run with h5py 3.16.0 and HDF5 2.0.0.

## Actual tutorial observation and tests

The input came from Aquaveo's official
[mf6_grid.zip](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/mf6_grid.zip).
[project_validation_record.json](project_validation_record.json) contains the
source and ZIP hashes, anonymous graph, boundaries, and validation counts.
The GPR stores a `GMS Version` attribute of 10.8.2; this does not establish the
original creator or an observed runtime session. The reader found 29 tree nodes,
two module envelopes, 10 entities, 21 literal relationships, and 16 unresolved
items. It read 11 string vectors (8,767 logical bytes), with zero numeric dataset
payload reads and no external file traversal. Source bytes were unchanged.

Twelve original project tests cover hierarchy, grammar failures, privacy,
literal UUID and duplicate-reference behavior, missing saved storage, global
budgets, source identity, and forbidden HDF5 representations. Ten storage
tests cover the streamed 32 MiB excess-inflation regression for both tree and
numeric reads, multidimensional/endian/edge chunks, filter masks, stream
boundaries, sparse/filter rejection, expansion/count limits, custom numeric
file precision, string padding, and empty arrays. No tutorial bytes are fixtures.

The explicit tree UI was also exercised on that unchanged private tutorial:
29 nodes, 21 relationships and 16 unresolved items appeared without app errors.
The anonymous summary excludes original label values, UUID strings and HDF5
paths; the saved-geometry view still renders 1,125 cells with unknown units.
[project_ui_validation_record.json](project_ui_validation_record.json) records
the source/application hashes and checks.

This graph is evidence of partial file interoperability. It does not establish
a complete persistence model, project round trip, runtime synchronization,
recovered GMS execution logic, or full product equivalence.

## Additional bounded official corpus

Three other official tutorial archives supplied five distinct additional GPR
files (15,016,429 downloaded bytes; 42,476,404 extracted bytes; 216 members).
All five passed HDF5 inventory and the current balanced tree grammar. Their
semantic coverage remains partial: unknown node counts are 33, 33, 21, 28 and 2.
One file contains a quadtree packet outside the current rectilinear decoder;
four have no geometry at the supported HDF5 path. No parser meaning, geometry
transformation or native synchronization was invented to make them pass.

[gpr_corpus_validation_record.json](gpr_corpus_validation_record.json) binds
source URLs, archive/project hashes, numeric counts and explicit unsupported
results to the published implementation. All input hashes stayed unchanged;
no original GPR, external component or numerical runtime was executed or
distributed. Stored version attributes describe file metadata, without proving
a creator identity or observed original session.

That corpus record describes the earlier source snapshot. The later separate
[GPR_UNSTRUCTURED.md](GPR_UNSTRUCTURED.md) reader now supports the measured
level-zero/single-layer quadtree packet. It verifies all horizontal topology
and coordinates while preserving the native elevation mismatch. Other unknown
node semantics and geometry representations remain unresolved.
