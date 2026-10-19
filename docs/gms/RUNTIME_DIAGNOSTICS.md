# Passive Windows startup diagnostics

`tools/probe_gms_community.ps1` starts only a normally installed executable whose
size and SHA256 match the pinned original GMS 10.9.7 target. It observes the
process tree it started and stops that tree after a bounded interval or a
blocking dialog. It does not select controls, send keyboard input, request a
trial, activate a licence, or run a model.

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
unobserved GMS 10.9.7 control. A subsequent action would require its own reviewed
implementation and actual compatible control observations.

## Checks before an expensive run

The opt-in workflow first parses its PowerShell source, compiles the embedded
Windows helper, and checks synthetic observation guards. Cases cover exact-label
normalization, misleading labels, duplicate controls, visibility, enabled state,
process ownership, parent/root relationship, non-push and nonstandard controls,
missing context, incomplete snapshots and public metadata isolation. These tests
call no native selection API and do not start GMS. They are software guard checks,
not observations of original GMS behavior.
