# Authored raster example

`linear_head.json` is a six-pixel synthetic head field in metres, not solver
output or observations. At physical pixel centres it equals
`h=2(x-100)+3(y-200)`; stored rows run north to south. CRS/datum are deliberately
local synthetic labels.

Run `PYTHONPATH=src python examples/raster/run_example.py build/raster-example-1`
from the repository root with a fresh output directory. It writes and verifies
real JSON/ASCII files, independently checks linear/constant field resampling,
clips and merges the source cells, reopens a three-asset catalogue and emits
scatter coordinates. `expected_receipt.json` is the actual reference execution
receipt. No original GMS or solver is executed. See `docs/gms/RASTER.md` for
assumptions, limits, recovery and individual CLI operations.
