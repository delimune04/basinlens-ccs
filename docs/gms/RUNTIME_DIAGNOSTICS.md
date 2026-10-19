# Passive Windows startup diagnostics

`tools/probe_gms_community.ps1` starts only a normally installed executable whose
size and SHA256 match the pinned original GMS 10.9.7 target. It observes the
process tree it started and stops that tree after a bounded interval or a
blocking dialog. By default it does not select controls. An explicit option
allows the single verified free Community choice described below. It never sends
keyboard input, requests a trial, activates a licence, or runs a model.

The optional Windows workflow keeps screenshots, dialog text, native class
names, control IDs, process IDs and window handles in its private temporary
capture tree. Those private files are not uploaded. Public JSON includes only
sanitized classifications, numeric standard-menu state, counts, booleans and
fingerprints. A fingerprint alone does not reveal or authenticate a dialog's
contents. Seeing an original window does not establish Community mode or a new
numerical reference run.

## Community button observation guard

The native control snapshot is capped at 128 controls and 1.5 seconds per visible
top-level window, with at most 100 milliseconds per text read. Missing or truncated
reads leave the guard incomplete. Only visible controls have their text read.
Raw control labels and metadata stay private.

The public guard recognizes the fixed label `Community Edition`, ignoring case, trimming/collapsing
whitespace and removing single mnemonic ampersands only. Escaped `&&` retains its
literal ampersand, and missing or inserted word boundaries do not match. It does not accept substrings,
translations, punctuation variants, or synonyms. For each exact label it reports
whether the observed control has the standard Windows `Button` class, is a push
button, is visible and enabled, belongs to this probe's process tree, shares the
top-level window's process, and has a verified child/parent/root relationship.
Duplicate labels, nonstandard controls, incomplete snapshots and unverified
relationships prevent the fully qualified observation status.

The phrase `no license found` (or `no licence found`) is recognized as a fixed,
case-insensitive text pattern. Its category explicitly says that the dialog
context remains unverified. An owned, visible, enabled dialog, complete snapshot,
recognized phrase and one verified standard push button yield
`passive_candidate_observed_review_required_no_action`. Every guard reports
`ActionsEnabled: false` and `RequiresReviewBeforeAnyAction: true`. The guard has
no control-selection API. This result is evidence for a later review, not
permission to act and not proof of Community entitlement.

Aquaveo's [current Community page](https://aquaveo.com/software/gms/community)
states that the full installation runs in Community mode until purchase.
Aquaveo's [registration guidance](https://aquaveo.com/blog/post/changes-aquaveo-registration)
describes selecting Community Edition when a no-licence dialog appears; that
article was written for the GMS 10.5 generation. These documents explain the
fixed observation label. They do not establish the actual labels or state of an
unobserved GMS 10.9.7 control. The optional action below has a separate policy and is based on the later
actual compatible control observation; the old phrase guard remains unchanged.

## Checks before an expensive run

The opt-in workflow first parses its PowerShell source, compiles the embedded
Windows helper, and checks synthetic observation guards. Cases cover exact-label
normalization, misleading labels, duplicate controls, visibility, enabled state,
process ownership, parent/root relationship, non-push and nonstandard controls,
missing context, incomplete snapshots and public metadata isolation. These tests
call no native selection API and do not start GMS. They are software guard checks,
not observations of original GMS behavior.

## Optional single free Community choice

The default remains passive. `-SelectFreeCommunityEdition`, the explicit workflow
boolean `select_free_community`, or the commit marker
`[gms-free-community-choice-probe]` opts into one documented free Community choice
per normally started target (at most four normally registered targets per
workflow; it is not a single global click budget). This option refuses document launches. It is not
an activation, trial request, purchase, terms acceptance or licence modification.

The fifth original Windows probe (`39208615776`, 2026-10-19) observed one actual
GMS 10.9.7 standard `Community Edition` push button in an owned, visible, enabled
dialog. Its complete four-control snapshot had one exact label, verified process
ownership and parent/root relations, and no read errors. It did **not** observe
the older documented `no license found` phrase. The passive guard preserves that
unknown result. The separate opt-in selection policy uses the actually observed
unique free-choice button plus normal startup and the vendor's documented free
Community path; it does not manufacture missing wording or treat the old guard
as having passed.

Before any selection, the helper verifies the pinned executable bytes again,
reads all visible owned windows and their bounded native controls, checks global
button and dialog uniqueness, verifies the candidate process's exact executable
path and fresh image hash, and takes a second complete live snapshot. Changed
handles/processes, incomplete reads, multiple dialogs/buttons, unverified button
relations, document launches and terms-acceptance text observed in the candidate
dialog stop the action. A normal chooser may mention paid keys or trials as alternatives; those
mentions are recorded separately and cannot make any button except the exact
free Community choice eligible. No key entry, payment, registration or trial
API is invoked. No unknown label becomes a selection candidate.

Only the exact verified button can receive one `BM_CLICK`, with a one-second
message timeout. The sole attempt is reserved before delivery; timeout or failure
is counted as one action and never retried. There is no keyboard, coordinate,
foreground-window, alternate button or legacy-licensing fallback. Microsoft
[documents](https://learn.microsoft.com/en-us/windows/win32/controls/bm-click) that
an inactive dialog may ignore `BM_CLICK`; this probe records that uncertainty
without activating the window or trying another action. The receipt
reports one target UI action and one licence UI action whenever delivery was
attempted, with zero probe-initiated activation requests. Target application
network activity is not monitored or inferred.

After the attempt, the helper observes passively and stops at any later observed
dialog, including an unchanged startup dialog. A sent click, a title or an enabled
window does not prove Community entitlement or successful workspace operation;
`community_mode_confirmed` remains false. The probe issues no solver action. Raw UI evidence
remains private, and public policy decisions contain only fixed categories,
counts and booleans. Workflow self-tests exercise this separate policy without
calling its native selection method.

## Optional File/Open dialog observation

`-ObserveFileOpenDialog` is a separate default-off phase and requires
`-SelectFreeCommunityEdition` with normal startup and no project argument. The
workflow boolean `observe_file_open_dialog` or marker `[gms-open-dialog-probe]`
explicitly opts into both phases. Passive startup, the free-choice-only marker,
and document observation retain their existing behavior.

The sixth original Windows probe (`39211459223`, 2026-10-19) sent one exact free
Community button message and subsequently observed an enabled main window with
standard HMENU state. Four complete snapshots contained 134 records and 102
unique numeric IDs. Of those IDs, 85 matched the 576-ID static catalogue and 17
remained unclassified; some IDs are Windows/system commands rather than GMS
application commands. These counts do not measure product completeness. The
original REA-backed private resource catalogue identified File/Open as command
37447, and the actual enabled menu record appeared at position `1/2`.

Before one File/Open delivery, the probe requires a completed normal free-choice
message, a freshly observed enabled main window, and no visible owned dialog.
It rechecks the pinned executable size and SHA256, exact candidate process image
path and bytes, and two complete live owned-window/menu snapshots. The snapshots
must retain the same main-window handle, menu handle, process and complete
numeric menu-state fingerprint. Exactly one enabled, nonseparator leaf command 37447
must occupy position `1/2` beneath a unique enabled nonseparator submenu at `1`.
The top-level and containing menu styles must be readable and must not request
`MNS_NOTIFYBYPOS`; no alternate notification is sent. Menu styles and submenu
flags participate in both complete fingerprints. Delivery also requires one
enabled visible menu-bearing main window and zero visible owned dialogs. Unknown/incomplete state, multiple candidates,
changed menus and any document argument prevent delivery.

The sole File/Open attempt is reserved before sending `WM_COMMAND`, with the
menu ID in the low word, zero high word and zero `lParam`, as specified by
[Microsoft](https://learn.microsoft.com/en-us/windows/win32/menurc/wm-command).
Its one-second timeout does not prove failure or successful dialog creation;
a modal handler may still be waiting. The probe never retries or sends an
alternate message. It does not type a path, pick a file, press Open/OK/Cancel,
change focus, invoke a solver, or save. It passively records the first later
observed dialog and stops, or ends after a separate 15-second post-command
observation budget. That extra phase is reported explicitly and is only enabled
for this opt-in probe.

Public dialog observations include only owned/visible/enabled flags, a standard
native-dialog-class flag, an exact fixed `Open` title flag, bounded snapshot
completeness and counts in known native control-class categories. Every other
class is counted as `OtherControls`; raw labels/classes/IDs/handles and screenshots
stay private. A different or localized title remains unknown. A matching fixed
title/class observation does not establish successful file loading or complete
Open-dialog behavior. No file is selected or confirmed.

`file_open_ui_actions` is independent of licence UI actions. Any File/Open
attempt, including a timeout, increments cumulative `target_ui_actions` by one
and does not reset the earlier Community count. No edition-entitlement or new
numerical-run claim is made. The opt-in workflow compiles the helper and tests
pure refusal/metadata-isolation policies before downloading or starting GMS;
those tests never call the native delivery methods.

## Optional pinned MF6 tutorial load through native controls

The default-off marker `[gms-open-mf6-project-probe]` or workflow boolean
`open_verified_mf6_project` enables a new phase after normal free Community and
File/Open actions. It fetches the existing pinned official `mf6_grid.zip`
(509,175 bytes, SHA256
`ad5d7684e9c6270a9a2a129430b04cc0c6bd39ba03a73f1c21825e3fa3e87dd4`)
and passes the one pinned GPR through `VerifiedTutorialPath`, never `ProjectPath`.
Ordinary document options or the ordinary document marker conflict and are
refused before download. The GPR is 3,071,450 bytes with SHA256
`afb9d3dd71f29d0cbb83dc5eee27c342b1ea75e86a9bd1bec06e860b2c6b4467`.
There is no alternate source, digest or filename override for this phase.

The seventh original probe observed a complete owned standard Open dialog with
23 native controls, including one Edit and five Buttons, but did not establish
the filename/confirmation identifiers. This phase must verify the actual native
layout afresh and refuse before writing unless it matches a documented pattern:

- One writable native Edit directly under the Open dialog with `edt1`, or the
  sole native Edit under a unique `cmb13` filename ComboBox/ComboBoxEx32 chain.
  A bounded chain may contain only verified native combo containers.
- One owned, visible, enabled standard push button directly under that same
  dialog with `IDOK`, push-button style 0 or 1, and exact normalized label `Open`.
- Complete snapshots, one visible owned Open dialog, unique documented roles,
  same target process and verified parent/root relationships. Read-only/password
  edits, custom classes, ambiguous fields or unknown labels do not qualify.

Microsoft documents [these roles](https://learn.microsoft.com/en-us/windows/win32/dlgbox/open-and-save-as-dialog-boxes#explorer-style-control-identifiers).
Its SDK defines `edt1=0x0480`, `cmb13=0x047c` in
[dlgs.h](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/dlgs.h),
and `IDOK=1` in
[WinUser.h](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/WinUser.h).
These are live eligibility checks, not assumptions inferred from an Open title.

The helper rechecks the pinned source, executable bytes and exact process image,
then two fresh consistent control snapshots. It reserves one `WM_SETTEXT`
attempt to the verified filename Edit, with a one-second timeout. Both message
completion and native TRUE are required. Bounded `WM_GETTEXT` must return the
exact entire canonical absolute path, including matching native length. The
source/main bytes and complete control relationships are checked again, and the
same text is read again immediately before reserving one `BM_CLICK` on that
exact Open button. Any failure stops without retries or an alternative action.
The earlier File/Open timeout does not prevent this phase when the actual
complete Open dialog is independently present; Community message completion
remains required.

These are system messages below `WM_USER`, documented by
[WM_SETTEXT](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-settext),
[WM_GETTEXT](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-gettext),
and [SendMessage](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagew).
The CDM messages use pointer arguments above `WM_USER` and cannot be sent from
this separate observer with local pointers. No CDM message, remote allocation,
injected hook/bridge, coordinate, keyboard, focus change or unknown-button
fallback is used. Unsupported Common Item Dialog/custom layouts are refused.

Every reserved write or confirmation attempt is counted even on timeout or an
exception. Cumulative actions are at most Community 1 + File/Open 1 + filename
text 1 + confirmation 1 per target. A confirmation attempt starts a passive
30-second observation window, ending sooner at any later dialog. No warning,
save or licence dialog is confirmed. An observed project basename in a window
title is reported separately from `project_load_verified`, which stays false.
Units, active entitlement and numerical results remain unverified.

After shutdown the source GPR's existence, size and SHA256 are recorded without
restoring it or saving the project. A replacement above the bounded 64 MiB
post-observation hash limit is reported changed with its hash unavailable. An
unreadable post-observation identity remains unknown rather than being asserted
as a change.
Public decisions contain only fixed categories, counts, booleans and hashes;
paths, control identifiers/handles, unknown text and screenshots remain private.
`probe_solver_actions` is zero and `numerical_execution_monitored` is false:
this probe issues no solver action and does not establish that the target could
not perform an automatic numerical action. Pure policy tests and Windows helper
compilation run before downloads or target execution.


## Actual pinned tutorial filename/confirmation outcome

Windows run [39216983932](https://github.com/delimune04/basinlens-ccs/actions/runs/39216983932)
passed parsing, C# compilation and pure policy tests before download/target
startup. The first target matched the documented filename-combo/Edit pattern.
One pinned path write was accepted, exact full-path readback and fresh
preconfirmation source/image/control checks passed, and one Open confirmation
completed. Counts were Community 1 + File/Open 1 + filename 1 + confirmation 1
= 4; the second target received zero UI actions.

A subsequent owned standard dialog had eight controls, no read errors or
truncation, and was not the fixed Open dialog. The probe heuristically classified
its text as an error; the exact cause and GPR parse/load outcome remain unknown.
No later button was pressed. No post-tutorial main window or project-basename
title was observed. Both executable identities and the pinned GPR stayed
unchanged. The probe issued zero solver actions; numerical execution was not
monitored and no original numerical output was verified.

[windows_tutorial_open_receipt.json](windows_tutorial_open_receipt.json) retains
the artifact identities, unchanged parsed public records, exact counters and
qualifications for historical summary/passive-observer wording. This is guarded
input/confirmation evidence, not verified model loading, active entitlement,
translation or a numerical comparison. All 577 reconstruction obligations remain
open. No raw UI text, screenshots or private paths are distributed.


## Separate documented edition context

The current official [GMS10.9 edition comparison](https://aquaveo.com/software/gms/pricing)
marks the MODFLOW6 Model & Interface in the paid MODFLOW and higher columns,
with no inclusion mark in Community. The [Community page](https://aquaveo.com/software/gms/community)
links that comparison and gives grid/stress-period limits. This is documented
edition scope, not evidence of the observed dialog's cause or the running
process's active entitlement. Reference MF6 behavior requires independently
established module availability; the passive diagnostic does not request a
trial, change licensing or override a module check.


## Passive post-confirmation keyword diagnostic

After a confirmation attempt and at most once per target, the helper can inspect
one later visible, enabled, owned standard root dialog. It rechecks the live process path,
start identity, executable size/hash and window owner/PID/title/class around a
bounded control read. Classification requires complete top-level/control text,
verified visible-control ownership, no read errors/truncation, and elapsed
acceptance within eight seconds. This elapsed check is not an interruptible
watchdog for every native/file read. Enabled state is required and its stability
is checked; the diagnostic performs no button, text, menu or other UI action.

The public projection contains fixed keyword-presence booleans for licensing,
modules/features, availability, file operations, parser/format, HDF, dependencies,
memory, access, paths, versions, graphics and generic errors. Each field is
classified separately so phrases cannot cross unrelated controls. Counts and a
SHA256 of invariant length-prefixed exact text fields provide an identity; raw
text/paths/control identities remain private. Categories can overlap, refer to
context, or all be absent. None identifies the cause or authorizes a repair,
licensing action, trial, dialog confirmation or solver run.

Pure category/refusal/hash/privacy tests run immediately after Windows Add-Type
and before downloads. Source review and local actionlint/diff checks passed;
actual Windows compilation/policy checks and observations are recorded separately
when available. The earlier four mutating action sites are unchanged.
