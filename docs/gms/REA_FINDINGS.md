# REA investigation: observed, inferred, unknown

Investigation date: **2026-10-19**. Tool: official `rea-agents` **6.7.0**,
Node **24.19.0**, Linux. The compact machine-readable record is
[`rea_inspection_summary.json`](rea_inspection_summary.json).

## Observed

1. The official Aquaveo download selected was GMS **10.9.7 x64**, build
   **13 October 2026**. The full installer was downloaded privately: **1,992,547,136
   bytes**, SHA-256 `69fef79023d065d4664e74950e10669c784a7e18fabfaa8ada48b2760f624335`.
   The S3 multipart ETag reproduced from 10 MiB MD5 parts exactly matched
   `3b6bb1dd69e6828fdea909ccc1fe3918-191`. Extraction errors are therefore not
   evidence of a damaged transfer.
2. The installer begins with a PE32 x86 Advanced Installer bootstrap. An exact
   **2,103,808-byte prefix**, ending at the last PE section's raw extent and
   excluding the installer overlay, was inspected with REA:

   ```bash
   rea inspect-pe-resources /private/path/gms-installer-bootstrap.exe --json
   ```

   REA successfully returned a complete resource-table inventory for **that
   bootstrap**: **106 entries, 48 resources**. Evidence ID:
   `ev_c0073ae26271fa5c4bb7b9f5a229219947d3438ce12b618fc0b25ef38d20ef6c`.
   The exact derived subject hash is in the JSON record.
3. Standard ZIP/DEFLATE and Deflate64 attempts did **not** produce a
   checksum-verified installed `gms10_9.exe`. Candidate archive headers are not
   treated as recovered files or proof of executing dependencies.
4. Native analysis providers were unavailable: no configured Hopper/Ghidra/IDA,
   and the host's `ps` failed REA's Linux owned-process readiness check. The check
   was not bypassed. Windows GMS was not executed.

## Inference boundary

The successful REA operation establishes **installer resource structure only**.
It does not recover GMS modeling algorithms, project formats, native functions,
rendering behavior, or numerical answers. No pseudocode or proprietary resource
was used as the implementation of this module.

The workbench implements an independent bounded workflow based on publicly
documented model-building concepts and the public FloPy/MODFLOW APIs. Its
scientific tests compare against independent groundwater solutions, **not GMS**.
Calling this a complete REA-derived GMS clone would be inaccurate.

## Remaining work for GMS equivalence

- Supply an installed, authorized GMS target to a suitable Windows environment
  and a configured native REA analysis provider.
- Select explicit capabilities and representative native projects; observe
  inputs, UI actions, file changes, solver invocation and exported results.
- Write testable behavior specifications and compare the same physical model,
  boundary placement, discretization, solver tolerances and version.
- Add project-format import only after actual format evidence and round-trip
  fixtures exist. Record incompatible/unknown fields explicitly.

The repository deliberately contains no GMS installer, executable, extracted
icons, resource payloads or decompiled source. Raw inspection outputs remain
private because a PE-resource report can carry original resource bytes. The
published summary is metadata, hashes, status and limitations only.
