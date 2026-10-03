# Claude Code entry point

Follow `AGENTS.md`. Start with `docs/HANDOFF.md`, then the project brief,
architecture and validation plan. This repository is the shared source of truth
for alternating Claude Code and Codex sessions.

The first next task is **T1: input identity, physical bounds and clear errors**
in `docs/DEVELOPMENT_PLAN.md`; do not start a GPU model or replace the UI first.

Suggested first session prompt:

> Read AGENTS.md and docs/HANDOFF.md. Audit the current CSV and direct-Python
> input validation. Implement T1 on a new branch: reject blank/NaN IDs, preserve
> string IDs including leading zeros, enforce physical fraction bounds on direct
> SiteScenario construction, and retain the offending field in error messages.
> Keep valid v0.2 outputs numerically unchanged. Add meaningful invalid-input and
> end-to-end bundle tests, run the documented checks, update HANDOFF.md, and
> prepare one small PR. State scientific and software limitations separately.

The owner should be able to explain the method and their own contributions.
Keep AI-generated scaffolding and genuinely validated research results distinct.
