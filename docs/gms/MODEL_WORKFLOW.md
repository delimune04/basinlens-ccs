# Named geology to an executable confined-water model

`subsurface/model_workflow.py` adds an independent, bounded model format with
named stratigraphy, explicit cell material assignments, stress periods, six
boundary types, deterministic native MF6 writing, reload/rewrite verification,
actual execution and captured-case result reading. This is an implemented
synthetic water workflow. Original GMS equivalence, GPR writing, general geology
construction, CO2–brine, black-oil and field validation remain unverified or
unimplemented.

## Contract and coordinates

The exact versioned schema is `basinlens-model-workflow-v1`. Runnable synthetic
examples live in `examples/workflow/`.

| Field | Required meaning |
|---|---|
| `project` | ID/name/domain, explicit `background_water` role, complete literal units, CRS, vertical datum and provenance statements |
| `grid` | nrow/ncol, uniform dx/dy, XY origin, zero rotation, explicit `south_to_north` project row axis and descending flat layer surfaces |
| `strata` | Named IDs with an exact nonoverlapping partition of layer indices |
| `materials` | Named kx/ky/kz [m/day], Ss [1/m] and porosity [1] |
| `assignments` | Explicit material/stratum IDs and zero-based [layer,row,column] cells; every active cell covered once |
| `initial_head_m` | One head per project cell, C order [layer,row,column] |
| `periods` | Explicit duration [day], equal timestep count and steady/transient mode |
| `boundaries` | Kind, zero-based stress period, explicit cell support, exact typed values and label |

Missing/extra fields, nonfinite numbers, Boolean numbers, wrong units, unknown
references, stratigraphic overlap, incomplete assignments and unused materials
are rejected. Literal `unknown` CRS remains unknown. No unit conversion, datum
inference, missing-property filling or automatic geometry correction occurs.

The project coordinates use x increasing with column, y increasing with row,
layer increasing downward and elevation z increasing upward. The origin is the
southwest grid corner. Native MF6 row zero lies at the north side. Compilation
maps project row `r` to native row `nrow-1-r`, reverses all cell arrays and every
boundary row ID, and reverses saved head arrays back on reading. Physical XY
coordinates are preserved. An asymmetric two-row actual solver check verifies
both preview coordinates and the opposite raw native row order.

All cells are active. Layers have flat horizontal surfaces; horizontal spacing
is uniform. Bounds include 20 layers, 20,000 cells, 100 periods, 2,000 saved
steps, 2,000,000 saved head values, 8 MiB case JSON and 32 MiB native input.
Arbitrary surfaces, pinching layers, faults, inactive cells, rotated grids,
quadtree/DISV construction and GIS interpolation are outside this contract.

Porosity is preserved in the case and preview as a geological property. It is
not substituted for specific storage and does not enter confined GWF flow or
storage equations. The current flow model uses directional K and Ss, constant
density and viscosity, `icelltype=0` and `iconvert=0`.

## Boundary support and signs

Positive Q below means water entering the aquifer; C has units m2/day.

| Kind | Exact values | Independent rate checked against each saved native budget |
|---|---|---|
| CHD | `head_m` | Prescribed saved head; package flux participates in global balance |
| RCH | `rate_m_day` | Recharge × dx × dy; explicit top-layer list cell |
| WEL | `rate_m3_day` | Positive injection; negative extraction |
| GHB | `head_m`, `conductance_m2_day` | C × (boundary head − cell head) |
| DRN | `elevation_m`, `conductance_m2_day` | −C × max(cell head − drain elevation, 0) |
| RIV | `stage_m`, `conductance_m2_day`, `bottom_m` | C × (stage − max(cell head, river bottom)) |

Duplicate same-kind supports and any CHD overlap on one cell/period are rejected.
A cell can combine WEL/recharge with one head-dependent boundary. Multiple GHB,
DRN or RIV kinds on one cell/period are rejected. RIV stage must exceed its bottom;
conductance must be positive and recharge nonnegative. Every steady period needs
a CHD or GHB reference. A closed drain and a river below its bed are not guaranteed
head references.

Every native package receives an explicit record for every period, including an
empty block when absent. WEL shutoff is tested numerically; omitted later rows
cannot accidentally inherit an earlier pumping period. The exporter explicitly
writes TDIS `NPER`; this avoids a diagnosed first-run PERLEN-size mismatch when
FloPy's default single-period count was used with two period records.

The implementation uses public MF6 6.7.0 package semantics:
[GHB](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-ghb.html),
[DRN](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-drn.html),
[RIV](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-riv.html),
[list recharge](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwf-rch.html).
No unsaturated recharge, rerouting, time-series interpolation, movers, auxiliary
scaling or variable-density boundary interpretation is implemented here.

## Native export, preservation and round trip

`export_workflow(case, fresh_dir)` writes a portable native GWF deck and our own
`settings.json`. That sidecar preserves the full case, named geology, porosity,
provenance, units and coordinate convention. Those metadata are not inferred
from native K arrays when reloading. This is our format, not a GMS sidecar schema.

The record captures every native input's byte count/hash, the compiler source
hash, FloPy version and a fingerprint of all ordered native input token rows.
The comparison normalizes comments, case-insensitive keywords/labels and numeric
text. Native filenames retain case. It retains token order and array encoding,
so this conservative check can refuse an equivalent rewrite outside the
compiler's bounded subset; it is not a general MF6 semantic equivalence prover.

`verify_workflow_export` checks exact bytes, native graph completeness and that
the captured case regenerates the same complete solver token fingerprint.
`verify_workflow_roundtrip(source_export, fresh_dir)` uses the existing strict
native importer and actual FloPy loader, writes a fresh native deck, compares
both full token fingerprints and retains both exact inventories. Original case
metadata is explicitly copied into our sidecar. Original source bytes are checked
again, including exact settings.json bytes before rewrite and after both optional runs. A metadata-only source mutation is rejected with a retained failure receipt. Native comments/keyword spelling can differ while meaning matches.

Providing `exe_name` additionally runs both decks through the existing isolated
`native_run` executor and reads both with the captured-case reader. The receipt
reports maximum head and budget-column differences, each run's balance, boundary
rate and confined-support gates, and the exact solver identity. No solver is
downloaded automatically. The layered example had zero head and budget-column
differences across the two actual runs.

Content hashes detect alteration; they do not authenticate an operator against
replacement of an entire bundle. Strict verification requires the recorded
compiler source and FloPy version. A changed compiler must not silently relabel
an older result. Native graph and run manifests remain independently verified.

## Results and failure recovery

`read_workflow_results(run_workspace)` accepts the native bundle's captured case;
there is no external case argument that can relabel a result. It verifies every
artifact hash and exact captured input/sidecar identity, reconstructs solver token
semantics, checks all head binary headers/dimensions/times and exact budget column
membership, and returns project-order heads, times and budget vectors.

The result separates three gates: water balance, every supported prescribed or
head-dependent boundary rate, and heads supporting the fully saturated confined
assumption. A below-top head does not become a validated confined result merely
because the algebraic solver terminates. No absolute pressure is inferred.

The existing runner preserves failed-run diagnostics, source snapshots, stdout,
stderr and manifests. Round trips retain `roundtrip.json` checkpoints with
requested/completed run counts, status, error type and error text. Failed or
partial work does not overwrite the source or an earlier run. Choose a fresh
output path after correcting a case or executable path; retain the failure for
diagnosis. A missing executable test confirms rewritten input preservation and
an explicit failure receipt. A timeout uses the existing process termination and
failed-manifest logic rather than a second executor.

## Measured checks

The 18 focused workflow tests passed with real MF6 6.7.0 and FloPy 3.11.0, zero
skips, in 10.310 seconds before the documentation-only update. They check schema,
coverage, source identity, corruption, row mapping, reload/rewrite, failure
preservation and independent physical limits:

- Harmonic series resistance across heterogeneous K cells, with independent
  analytical cell heads and CHD inflow/outflow.
- GHB plus injection/extraction signs; recharge multiplied by actual cell area.
- Drain active/inactive thresholds; river linear and below-bottom capped flow.
- Explicit pumping shutoff; one-cell implicit Euler storage response using Ss×V.
- Asymmetric native/project row order and tampered result rejection.
- Two-layer, steady/transient example with two actual roundtrip executions.
- Equal below-top solutions fail the confined-support gate and numerical roundtrip; the CLI returns exit 2 when a requested numerical roundtrip fails.

A separate reviewer independently ran six differently parameterized actual MF6
cases on an earlier explicitly hashed compiler snapshot. All expected heads
matched exactly; maximum water-rate closure residual was 7.11e-15 m3/day. That
snapshot's identity remains separate from later source changes. None of these
synthetic checks establishes original GMS behavior or field applicability.

Exact focused source/example hashes and numerical example receipts are in
[model_workflow_validation_record.json](model_workflow_validation_record.json).
