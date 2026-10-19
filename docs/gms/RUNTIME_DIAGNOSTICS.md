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
`community_mode_confirmed` remains false. No solver is invoked. Raw UI evidence
remains private, and public policy decisions contain only fixed categories,
counts and booleans. Workflow self-tests exercise this separate policy without
calling its native selection method.
