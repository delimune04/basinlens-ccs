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

The separate original [dialog-template decoder](DIALOG_LAYOUTS.md) subsequently
decoded all 429 listed dialog resources: 113 standard and 316 extended,
containing 6,853 static controls, with zero failures. Its numeric projection
preserves dialog-unit rectangles, style bits, ordinal classes, IDs and numeric
font metadata while discarding captions, registered names and creation bytes.
The [derived receipt](dialog_layout_validation_record.json) binds the exact
target and REA inventory. These templates do not establish displayed dialogs,
dynamic controls, pixel layouts or event-handler behavior.

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

The completed default remote probe is recorded in
[native_rea_receipt.json](native_rea_receipt.json): provider doctor passed, but
the native overview reached its 1,200-second deadline and returned no overview.
The separate [auxiliary receipt](auxiliary_ghidra_receipt.json) reports command
completion after 1,378.71 seconds with automatic analysis explicitly timed out
and partial. Its 318,972 reported function entries are database observations,
not verified production functions or reconstructed features. Selected small
functions mostly concerned embedded test helpers; raw byte candidates included
code-byte false positives. Neither establishes production file grammars.

Measured costs were 753.416 seconds for entry-point disassembly, 297.989 seconds
for call-fixup installation and 123.520 seconds for discovered non-return flow.
The optional bounded-inventory REA profile retains entry disassembly while
disabling the latter two analyzers through REA's supported environment setting.
This weakens call/pcode semantics and is not full semantic analysis. The exact
requested profile is recorded in the versioned workflow; its result is separate
from the default timeout. No owned-process guard was changed.

The bounded-profile retry also reached its deadline: doctor passed in 2.906s,
analysis timed out after 1,200.857s, and no native overview was returned.
The unmodified [bounded-profile receipt](native_rea_bounded_receipt.json) came
from [run 39204176129](https://github.com/delimune04/basinlens-ccs/actions/runs/39204176129)
at source `26b330a384247a8ffed787808c9927f9d319a475`. Its workflow explicitly
set the two disabled analyzers above. Both actual remote attempts failed to
complete native REA analysis; the separate partial auxiliary Ghidra project is
not substituted for either result.

The normal Windows installation/startup probe subsequently completed in
[run 39205004553](https://github.com/delimune04/basinlens-ccs/actions/runs/39205004553).
Normal registration identified two byte-identical launch targets; both passed
the pinned size/SHA gate and were observed independently, without choosing one
as canonical. Both started and displayed original windows. Both observations
stopped at an unclassified blocking dialog. One exposed possible Community
option text, which does not confirm an active edition or permission state.
No UI actions, activation requests or numerical runs were initiated. No standard
HMENU state was available; custom menus or an unready UI remain unknown.
The exact sanitized [Windows receipt](windows_runtime_receipt.json) preserves
those distinctions. The workflow's successful collection status does not imply
a usable model session, a license/graphics diagnosis or product equivalence.

The subsequent [passive control observation](windows_control_receipt.json),
run 39208615776, compiled its helper and passed synthetic rejection/privacy
checks on Windows before installation. The first target exposed exactly one
enabled, visible standard `Community Edition` push button in an owned dialog,
with same-process and parent/root relationships verified. The fixed no-license
phrase was not observed, so the stricter passive context guard did not pass.
The second target exposed no matching button. No control was selected and no
active edition or new model run was established by this observation.

The native probe now separates the 1,200-second provider startup budget from
a 90-second outer cleanup grace. Earlier equal deadlines could suppress the
provider's own failure result. Bounded retained JSON and invocation-owned logs
can now contribute only allowlisted diagnostic stages/timings and numeric facts;
an outer timeout remains failed even if a retained result parses successfully.
This change improves measurement and does not establish analysis completion.

No original GMS numerical run has yet been normalized and compared. An activated
Premium edition, its dependencies and all UI behavior have not been observed.
The public implementation therefore makes **zero genuine GMS output-match
claims**. It is an original implementation under reconstruction, not a completed
replacement or compatibility-certified product.

There is a separate positive interoperability check: the official 10.9 tutorial
index ships a project whose stored GMS-version metadata is 10.8.2 and whose shipped
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

## Original free Community choice and materialized menus

Windows run [39211459223](https://github.com/delimune04/basinlens-ccs/actions/runs/39211459223)
passed source parsing, C# compilation and synthetic policy cases before normal
installation/execution. One verified exact free Community click was delivered
to the first target. Subsequent passive observation saw an enabled main window
and four identical complete standard-menu snapshots of 134 items. Their 102
reported nonseparator numeric IDs overlap 85 static REA menu IDs. The remaining
17 IDs are unclassified and may include Windows system or generated entries;
they are not automatically new GMS capabilities. The second target had no
eligible exact choice and received no UI action. Total target/licence UI actions
were one; probe activation requests and solver actions were zero. Numerical
execution was not monitored and no original numerical output was verified.

[windows_free_choice_receipt.json](windows_free_choice_receipt.json) binds the
artifact digest, raw public metadata and derived numeric intersection. A title,
click delivery and enabled window do not establish edition entitlement or
handler behavior. The original 577 reconstruction obligations remain open.

## Corrected-deadline native REA diagnostic result

Run [39210146753](https://github.com/delimune04/basinlens-ccs/actions/runs/39210146753)
returned REA’s actual `provider_timeout` error after 1,202.736 seconds, within
the 1,290-second outer watchdog. Doctor passed; no native overview returned.
Two owned logs supplied 27,600 bytes showing import and auto-analysis start.
The reported heap was 4G, no out-of-memory marker was observed, and no analyzer
timing report was available. The provider reported incomplete/truncated
diagnostics; cleanup and the delaying analyzer remain unknown.

The historical receipt’s `post_analysis_script_observed` label was too specific:
HeadlessAnalyzer also prints `SCRIPT:` for pre-analysis configuration. It is
now named `headless_script_observed`, with a targeted regression pass; the raw
historical receipt remains unchanged. Neither that marker nor the last
collected stage establishes completed analysis or an execution timeline.
[native_rea_diagnostic_run.json](native_rea_diagnostic_run.json) binds the run,
artifact digest and unchanged [receipt](native_rea_diagnostic_receipt.json).
No provider ownership guard was bypassed and no function recovery is claimed.
A separate local REA objdump attempt returned `capability_unavailable` /
`unsupported_provider` because its configured command could not be run; this
is not a successful metadata extraction or a demonstrated target limitation.

## Original File/Open dialog observation

Run [39213425352](https://github.com/delimune04/basinlens-ccs/actions/runs/39213425352)
passed Windows parsing, C# compilation and pure policy checks before execution.
After one normal free Community choice, the first target exposed a sole enabled
File/Open command 37447 at observed position1/2, with an enabled ancestor chain,
leaf-only semantics, verified WM_COMMAND menu style and matching fresh snapshots.
One reserved WM_COMMAND attempt timed out and was never retried. The next
passive snapshot observed an owned visible enabled standard dialog with the
exact fixed Open title:23 controls, zero read errors, no truncation, including
one Edit and five Buttons. The second target received no action.

[windows_open_dialog_receipt.json](windows_open_dialog_receipt.json) preserves
the actual public metadata and exact counters:two target UI actions (Community
plus File/Open), zero filename writes, confirmations, activation requests or
probe solver actions. The dialog class/counts alone do not establish filename
control semantics, successful model loading, entitlement or numerical parity.
Cross-process WM_USER-range CDM messages with local pointers are not used.


## Actual pinned tutorial filename/confirmation outcome

Windows run `39216983932` passed pre-action compilation/pure policy gates and
completed one verified pinned filename write/readback and Open confirmation.
Target1 had four counted UI attempts; target2 had zero. A later complete owned
eight-control dialog was heuristically classified as an error. Its cause and
project-load outcome remain unknown; no unknown button was pressed. Both GPR
and executable identities were unchanged, no probe solver action was issued,
and numerical execution was not monitored. See
[windows_tutorial_open_receipt.json](windows_tutorial_open_receipt.json) and
[RUNTIME_DIAGNOSTICS.md](RUNTIME_DIAGNOSTICS.md) for exact counts and retained
historical wording qualifications. No genuine original numerical comparison or
obligation closure is established.


The subsequent passive diagnostic run `39218744781` passed Windows gates and
observed licensing/file-operation/generic-error keyword flags in one complete
owned eight-control dialog. It added no UI action; counts remained4/0 per target,
with unchanged executable/GPR identities. Cause, entitlement and project loading
remain unknown. See
[windows_tutorial_diagnostic_receipt.json](windows_tutorial_diagnostic_receipt.json).
