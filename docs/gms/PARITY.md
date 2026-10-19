# Captured-output comparison

The `basinlens_ccs.parity` package compares captured numerical datasets and
accounts for evidence within a supplied feature catalogue. It does not launch
GMS, infer that two models have identical physics, or certify the full product.

## Reproduce the synthetic example

```bash
python examples/parity/generate_synthetic.py build/parity-demo
python -m basinlens_ccs.parity compare build/parity-demo/reference.json build/parity-demo/candidate.json --output build/parity-demo/comparison.json
python -m basinlens_ccs.parity verify build/parity-demo/comparison.json
python -m basinlens_ccs.parity coverage docs/gms/capabilities.json --output build/documented-coverage.json
```

All output paths must be new. The example uses independently written arithmetic
for a linear hydraulic-head vector. It tests data interchange and verification;
its `gms_match` is always false because its reference is synthetic.

## Capture an original result

Use `python tools/capture_gms_reference.py --help` in the environment where an
authorized GMS run actually completed. Capture the exact native input files,
raw exported results, original frontend identity, distinct numerical solver
identity/version/hash, run log, operator run record and normalization script
commit. Windows PE version metadata is read without activating or executing GMS.
The helper records explicit operator attestations; it cannot authenticate their
truth. No activation or license bypass is implemented.

The normalized JSON manifest binds the data file by SHA-256 and size. CSV and
NPZ are supported. It declares ordered grid geometry, active support, times,
CRS, vertical datum, units, quantity identity and sign convention. A common
`comparison_input` artifact describes the physical case; each side separately
captures its exact native run inputs. A matching shared case does not replace
review of the translation between those native inputs and the common case.

Observed GMS and candidate datasets require structured capture and operator
records consistent with their file snapshots. For an original GMS dataset,
`implementation.git_commit` identifies the capture/normalization implementation,
not unavailable proprietary GMS source. The candidate commit identifies the
tested reconstruction. Arbitrary text receipts are rejected.

## Interpret and verify

Comparison rejects incompatible geometry, time, units, datum, quantity support,
sign conventions and metadata such as absolute versus gauge pressure. No
automatic regridding, unit conversion or datum correction is performed. Reports
contain maximum absolute error, RMSE, declared absolute/relative tolerances,
input/output provenance and a content fingerprint. `verify` rehashes artifacts
and replays the calculation, comparing canonical JSON types and values exactly.

A feature catalogue may bind implementation files and test receipts to a real
commit. A matched stage additionally requires original observed GMS comparisons
for every required reference case and output, at or below the feature's explicit
tolerance cap. Paths must remain inside the catalogue directory; use a repository
root catalogue or a bounded evidence directory when binding source files.

Stage counts refer only to the supplied catalogue. Matching selected hydraulic
heads does not establish UI, native-file round trips, transport, calibration,
failure handling, performance or complete feature equivalence. The documentation
catalogue currently contains no original GMS runtime matches.
