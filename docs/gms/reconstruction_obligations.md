# Evidence-bound reconstruction obligations

`reconstruction_obligations.json` is the actual Evidence emitted by REA 6.7.0
`build-reconstruction-obligation-ledger`. It authenticates a finite list of work
still to perform; it does not establish a replicated application.

The target is the extracted official GMS 10.9.7 x64 executable, 145,479,264 bytes,
SHA-256 `d69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2`.
REA's original `inspect_pe_resources` Evidence has identifier
`ev_9eb14006478ec9134d3e2f86ea0ec19d033a9d9ae72c155639fed87365417306`.
The local decoder verified its target and menu payload hashes, decoded 131 menu
resources and observed 576 distinct nonzero, non-popup command IDs. A static ID
can be unused, reused across contexts, dynamically replaced, disabled, or limited
to a particular edition. It does not identify a recovered command handler or a
numerical algorithm.

The tool supplies 576 analyst-reviewed command-characterization obligations to
REA and one explicit whole-product scope-reconciliation barrier. REA reports
576 **unowned**, one **unknown**, zero verified, and an overall **unknown**
ledger status. No owner bindings, original runtime cases, fixtures or verifier
results were invented. Each command still requires original runtime observations
and independently defined behavioral comparisons. The wider barrier requires
reconciling engines, file formats, dynamic UI, editions and installed modules.

REA's `coverage.status: complete` means its supplied finite candidate set was
projected into the ledger. It is **not complete GMS feature coverage**. REA's
`source_state: reviewed` records analyst-provided definitions, not observed
runtime behavior. The public summary preserves those distinctions explicitly.
The generic REA ledger workflow uses its internally named JavaScript application
workflow provider; no JavaScript application graph or native semantic graph was
inferred from these PE resources.

Original PE resource labels, names, payload bytes, icons, artwork and native
source are absent from the public artifact. The original Evidence, canonical
source bundle, exact private decoder observation, and child diagnostics remain
outside the repository. Numeric IDs, byte offsets, hashes and original analytical
prose are sufficient to bind this work list to the original static observation.

## Reproduce with a caller-owned original target

Install the project and an isolated `rea-agents@6.7.0` package. This is an
explicit research operation; normal tests do not download or execute GMS.
Extract and verify the official target with `tools/extract_gms_target.py`, run
REA `inspect-pe-resources`, and create a private decoder observation using
`python -m basinlens_ccs.reconstruction`. Then run:

```bash
PYTHONPATH=src python tools/build_gms_ledger.py \
  --target /absolute/private/gms10_9.exe \
  --evidence /absolute/private/gms-main-rea-resources.json \
  --observations /absolute/private/gms-command-observations.json \
  --rea-package /absolute/rea/node_modules/rea-agents \
  --private-workspace /absolute/private/new-ledger-workspace \
  --output /absolute/new-public-ledger
```

The two output directories must be new and separate. The Python wrapper freshly
decodes verified target bytes and checks the supplied observation's numeric
commands, offsets and exact source Evidence hash. The pinned Node adapter uses
REA's `parseEvidence` to authenticate the semantic Evidence ID, creates and
authenticates its canonical bundle, invokes the real public REA CLI, and checks
the returned Evidence ID, ledger schema and closure digest. It never runs GMS.
All provider diagnostics stay in the private workspace; publishing the canonical
source bundle would expose the original resource inventory and is unnecessary.

## Recorded checks

On 2026-10-19, Python 3.12.14, Node v24.19.0 and REA 6.7.0 produced the committed
ledger from the actual verified target. The REA CLI exited zero. The ledger
closure digest is
`8320e8788370b0e66a9b5e6abf77073fa7685a2b9851de55eafd58d2c9f46200`.
`reconstruction_obligations_summary.json` records the exact public file hash,
source Evidence file hash, source observation file hash and REA Evidence ID.
A second run in fresh directories produced byte-identical public ledger and
summary files.

Five deterministic boundary tests passed with zero skips. They cover nested
command deduplication, exclusion of popup IDs and separators, tampered commands
and runtime claims, private text exclusion, malformed numeric identities, and
ambiguous/non-finite JSON rejection. An actual negative integration check altered
the original Evidence limitations while retaining its old ID; REA rejected it
with `Evidence semantic identifier does not match its record`, and the wrapper
created no public output. These are software/provenance checks; zero original
runtime equivalence cases were performed.

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_rea_ledger.py -v
```
