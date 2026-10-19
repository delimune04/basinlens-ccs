# Static Win32 dialog layouts

The original `reconstruction.dialogs` decoder now reads standard Win32
`DLGTEMPLATE`/`DLGITEMTEMPLATE` and version-1 extended templates. Applied to the
unchanged, hash-verified GMS 10.9.7 main executable, it decoded **429 listed
dialog resources: 113 standard and 316 extended, containing 6,853 controls**.
There were zero decoding failures or resources excluded by the decoder limits.
The maximum observed control count in one dialog was 129.

These are static template observations. They do not establish which dialogs
were displayed, dynamic controls, enabled states, event handlers, or runtime
layout. Dialog units depend on font metrics; they are not pixel coordinates.
The original GMS runtime behavior and complete product coverage remain open.

## Public format and numeric projection

The implementation follows Microsoft's primary format descriptions:

- [DLGTEMPLATE](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-dlgtemplate)
- [DLGITEMTEMPLATE](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-dlgitemtemplate)
- [DLGTEMPLATEEX](https://learn.microsoft.com/en-us/windows/win32/dlgbox/dlgtemplateex)
- [DLGITEMTEMPLATEEX](https://learn.microsoft.com/en-us/windows/win32/dlgbox/dlgitemtemplateex)

The returned API data preserves signed dialog-unit rectangles, style and
extended-style bits, help IDs, numeric control IDs, ordinal references, and
numeric font fields. Standard control IDs retain their unsigned WORD values,
including 65535; extended control IDs retain the full DWORD, including
4294967295. Neither is silently converted to a signed identifier.

Title, registered-class, resource and typeface names are omitted. UTF-16 strings
are bounded and validated before their content is discarded. Named classes
are marked as text omitted; they are not guessed to be predefined classes.
Among the observed controls, 589 have named classes, whose names remain private.
The six predefined class ordinals have these occurrence counts:

| Class ordinal | Observed controls |
|---|---:|
| 128 | 3,428 |
| 129 | 851 |
| 130 | 1,739 |
| 131 | 32 |
| 132 | 2 |
| 133 | 212 |

Creation data remains opaque. A nonzero standard control creation-size WORD
includes its own two bytes; extended `extraCount` counts following bytes.
The decoder consumes these different lengths without exporting their content.
All creation-size values in this particular GMS artifact were zero. Independent
synthetic tests cover nonzero lengths, including odd lengths and the following
DWORD alignment. Stored font metadata is not proof of the runtime-selected font.

## Evidence binding and bounds

The shared resource inventory verifies the target SHA-256, actual PE directory
identities and every listed resource payload digest. The new strict boolean
`decode_menus=False` inventory mode skips unrelated menu decoding while retaining
all those checks. Only this nondefault mode adds an explicit skipped-menu marker;
the default menu observation output remains unchanged.

The dialog phase rechecks target identity, reads each exact verified range,
checks its payload SHA-256 and rechecks target and Evidence identities after
decoding. Identity hashes and Evidence reads have fixed byte bounds and reject
growth or truncation. Receipt authorship is not authenticated by these structural
checks. The original REA resource Evidence identifier and exact receipt hash
are retained in [dialog_layout_validation_record.json](dialog_layout_validation_record.json).

Each template is limited to 2 MB, 8,192 controls and 16,384 UTF-16 code units per
string. The catalogue charges every dialog payload occurrence, including aliases,
against a 32 MiB budget and every declared control count against a 50,000-control
budget before decoding. Global budget exhaustion stops the operation. Invalid
individual templates remain explicit failures. Unsupported extended versions,
invalid UTF-16, truncated fields/data, and trailing non-padding bytes are rejected.
Internal alignment padding is consumed without requiring its bytes to be zero.

## Reproduce

Supply a caller-owned original target and the exact private REA
`inspect-pe-resources` Evidence. This command does not execute the target:

```bash
PYTHONPATH=src python -m basinlens_ccs.reconstruction.dialogs \
  /absolute/private/gms10_9.exe \
  --evidence /absolute/private/rea-resources.json \
  --output /absolute/private/new-dialog-layouts.json
```

The output path must be new. The numeric-only catalogue includes per-dialog
layout observations; this repository publishes only the aggregate receipt,
source hashes, original decoder and independent synthetic fixtures. No original
captions, class/font/resource names, resource bytes or private paths are published.
The Python APIs are `decode_dialog(payload_bytes)` and
`dialog_catalogue(target_path, evidence_path)`.

On 2026-10-19, Python 3.12.14 passed 13 focused dialog tests, 11 existing resource
tests and 5 ledger boundary tests, all with zero skips. Checks include every
non-padding truncation of both synthetic templates, surrogate pairs and invalid
surrogates, signed coordinates, extended IDs, font fields, both creation-data
contracts, global limits, source changes, metadata text exclusion, skipped-menu
verification, and fresh output refusal. The actual target CLI exited zero.
The previous actual menu observation remained identical as canonical JSON, and
the actual REA obligation ledger replay remained byte-identical. No obligation
was promoted to verified and no GMS parity comparison was added.

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_dialogs.py -v
```
