# GMS reconstruction evidence

Investigation date: **2026-10-19**. Baseline: official GMS **10.9.7 x64** full
installer, build 13 October 2026. REA: **6.7.0**. This freezes an artifact, not an
activated edition or every optional licensed module. The machine-readable
receipt is [rea_inspection_summary.json](rea_inspection_summary.json).

## Exact shipped target

The official installer is 1,992,547,136 bytes, SHA-256
`69fef79023d065d4664e74950e10669c784a7e18fabfaa8ada48b2760f624335`.
Its multipart S3 ETag also reproduced exactly. Initial attempts to decompress
embedded ZIP streams directly failed. Those attempts did not recover the main
application; the earlier bootstrap-only result is superseded by the following
successful extraction.

`tools/extract_gms_target.py` parses the Advanced Installer footer/table, restores
the observed outer archive framing, extracts the selected member, and checks the
fixed installer, archive and target identities. A complete integration check
against the original download passed. The unchanged main `gms10_9.exe` is
**145,479,264 bytes**, CRC32 **42447c5d**, SHA-256
`d69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2`.
Extraction does not install, execute, activate or modify GMS.

## Actual REA observations

The following operation ran against that main executable:

```bash
rea inspect-pe-resources /private/path/gms10_9.exe --format json
```

Evidence ID:
`ev_9eb14006478ec9134d3e2f86ea0ec19d033a9d9ae72c155639fed87365417306`.
REA reported **1,208 resources / 2,431 directory entries**. The independent
Windows menu-template decoder then used the exact REA ranges and payload hashes:
**131 menus**, **576 distinct static command IDs**, **429 dialog resources
inventoried**, zero menu-decoder failures. Dialog layout and command handlers
were not established by this operation. Static resources can be unused,
edition-dependent, disabled or dynamically replaced.

The installer also contains Python interface files. REA imported a private source
inventory as **historical reference**, with partial inventory authority and zero
semantic relationships. This establishes neither semantic Python analysis nor
native modeling algorithms. Separately reading those interfaces established
specific MF6 folder, sidecar and launch boundaries; original source stays private.

## Native analysis and original runtime

The local REA Ghidra provider failed its owned-process readiness guard because
the process namespace/procfs identities disagree. The guard was not disabled or
patched. A normal GitHub Actions runner is used for a separate, explicitly
opted-in native REA probe. Its workflow verifies the official installer and
Ghidra release, runs the actual doctor/analyze commands, and publishes only a
sanitized health/count receipt. A launched job or a successful download is not
reported as a completed native analysis.

A separate conventional Ghidra analysis uses a private project and an owned,
bounded process group. Findings from that route are labeled **auxiliary Ghidra,
not REA**. Tool health, import, analysis completion and timeout are separate facts.
See the separately recorded provider receipts for final status.

No original GMS numerical run has yet been normalized and compared. An activated
Premium edition, its dependencies and all UI behavior have not been observed.
The public implementation therefore makes **zero genuine GMS output-match
claims**. It is an original implementation under reconstruction, not a completed
replacement or compatibility-certified product.

There is a separate positive interoperability check: the official 10.9 tutorial
index ships a project whose stored creator metadata is 10.8.2 and whose shipped
solver listing says MF6 6.4.1. Re-executing its 15 unchanged native input files
with public USGS MF6 6.7.0 reproduced all 1,125 heads and the full shipped binary
budget file byte for byte. This was not an original GMS GUI run or translation.
[TUTORIAL_INTEROPERABILITY.md](TUTORIAL_INTEROPERABILITY.md) preserves the exact
scope, hashes, independent drain/recharge/well checks and metadata conflicts.

## Product inventory and completion

[capabilities.json](capabilities.json) records **163 research entries** drawn
from official product, model, edition and tutorial sources. The tutorial index
provided 132 PDF links. Neither number is a full-product denominator. The
current 10.9 manual index was identified, but direct retrieval returned 403;
a complete current manual PDF was not verified. Historical manuals do not prove
10.9 coverage. Unsupported historical engines and geometry-only integrations
are explicitly distinguished in the catalogue.

Completion requires reconciling every observed menu, dialog, toolbox tool,
package and format with a behavior contract; capturing original successful and
failure workflows; implementing them; and passing numerical, file round-trip,
UI and operational comparisons. Required physics, geometry, units, datum,
solver versions and tolerances must agree. Unknown and unlisted features remain
open. [PARITY.md](PARITY.md) describes the evidence checks.

## Publication boundary

The repository contains original code, synthetic fixtures, public source links,
hashes and original prose specifications. It contains no GMS installer,
executable, extracted artwork/resource payloads, native pseudocode or copied
proprietary source. Raw vendor tutorials, projects and detailed analysis remain
private pending their redistribution terms. No license bypass is implemented.
