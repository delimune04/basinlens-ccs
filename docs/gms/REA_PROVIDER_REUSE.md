# Supported REA 6.7.0 analysis reuse

Read-only investigation, 2026-10-19. The installed `rea-agents` package reports
version 6.7.0. Its launcher symlink resolves from
`research/rea/node_modules/.bin/rea` to
`research/rea/node_modules/rea-agents/scripts/rea.mjs`. This note records
supported interfaces; no provider or ownership guard was changed, no target was
executed, and no additional deep analysis was started for this investigation.

| Route | Supported behavior | Limit |
|---|---|---|
| One live MCP connection | Open the exact binary with `open_binary`, then issue focused `analyze_function`, `procedure_pseudo_code` or instruction queries | Initial full-image import/default analysis still must finish |
| CLI `--snapshot` / MCP snapshot paths | Reuse successful exact-result observations when binary, provider, profile, operation and parameters match | JSON cache, not a saved Ghidra database; new queries may start/import the provider |
| Existing private Ghidra project | Not exposed by this REA version | Launcher always creates an ephemeral import and deletes it on close |
| Function selector / seed file | Select a function query or provide pre-analysis seeds | Neither provides function-only import or skips whole-image default analysis |

The installed source provides the version-specific evidence:

- `dist/application/DirectAnalysis.js` intentionally creates and releases an
  isolated session for every CLI invocation.
- `dist/ghidra/GhidraLauncher.js` supplies a fresh runtime project, `rea-project`,
  `-import`, `-readOnly` and `-deleteProject`. It does not expose `-process` or
  `-noanalysis` options.
- `dist/ghidra/GhidraClient.js` creates owner-private temporary roots and removes
  them during close. Cancellation can terminate the ephemeral database.
- `dist/ghidra/GhidraProviderCapabilities.js` states that incomplete auto-analysis
  does not expose partial session results.
- `dist/application/binary/AnalysisSnapshotCache.js` binds exact queries and
  marks replayed provenance. Windows Ghidra source admission can require provider
  startup even for cached results.

The official [installation guide](https://github.com/morluto/rea/blob/main/docs/installation.md)
explicitly states that REA never opens an existing user project. The
[native investigation guide](https://github.com/morluto/rea/blob/main/docs/native-investigation.md)
and [CLI guide](https://github.com/morluto/rea/blob/main/docs/cli.md) describe live
session reuse and exact-result snapshots. These main-branch documents can advance;
the installed 6.7.0 source above is the inspected version boundary.

Supported startup/profile settings include `REA_GHIDRA_STARTUP_TIMEOUT_MS`,
`REA_GHIDRA_DISABLED_ANALYZERS` and `REA_GHIDRA_SEED_FILE`. Analyzer names are exact,
profile-bound and validated before analysis; `WindowsResourceReference` is the
documented PE resource analyzer name. Seeds use
`address<TAB>function|code|label[<TAB>name]` and run before default analysis. These
options change declared analysis assumptions; they are not project-reuse or
partial-analysis bypasses. Native function decompilation has no fixed internal
per-function deadline; caller cancellation remains a lifecycle event.

For static metadata that does not need Ghidra, REA also offers:

- `inspect-with-objdump PATH file_headers` and `section_headers` through an
  already installed GNU objdump. The wrapper's fixed operation set does not
  expose arbitrary extra objdump flags for full PE import/export tables.
- `inspect_pe_resources` / `inspect-pe-resources`, a bounded portable parser for
  PE format/machine and resource identities/ranges/hashes. Its 64 MiB default
  input bound is smaller than the pinned GMS image; the caller must explicitly
  choose a suitable bound within the 512 MiB ceiling. It does not decode general
  import/export tables or replace loaded-image analysis.
- `execute-rizin-command PATH iij`, `iEj` or `iIj` for import, export and binary
  information with a separately installed Rizin. REA supports the one-shot
  `-N -q -c` path and `REA_RIZIN_COMMAND`; it does not install the provider or
  normalize every command's JSON. These commands were researched, not run here.

See the [official REA reverse-tools guide](https://github.com/morluto/rea/blob/main/docs/reverse-engineering-tools.md)
and [Rizin command definitions](https://github.com/rizinorg/rizin/blob/dev/librz/core/cmd_descs/cmd_info.yaml).
In a shared REA MCP server, an unrestricted Rizin command retires the active
binary-analysis session. Use a separate one-shot CLI process before or apart
from a long-lived Ghidra session if that session must remain available.
