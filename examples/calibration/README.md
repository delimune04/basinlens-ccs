# Authored actual-MF6 calibration examples

Steady: analytically authored Kx=4 m/day, internal-head training and a withheld
internal cell. Transient: backward-Euler authored Ss=0.05 1/m, an early training
head and a withheld later head. Flat: fixed-head-only observations with a strong
prior, expected to fail the data-identifiability gate.

All values are synthetic; they are not measurements, GMS output or PEST cases.
The case hash in each observation file identifies the **initial reference case**.
A trial may change only the material fields named in its settings.

Run the explicit example from repository root with a fresh output directory:

```bash
mkdir -p build
PYTHONPATH=src python examples/calibration/run_example.py build/calibration-example-1 --exe /path/to/mf6
```

This starts bounded actual MF6 runs and retains every attempted run, original
source byte, search decision and native log. `expected_receipt.json` is the
actual pinned-MF6 reference receipt. Read `docs/CALIBRATION.md` for the independent
calculations, parameter bounds, objective units, failure recovery and scope.
