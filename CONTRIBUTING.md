# Contributing

Thanks for considering a contribution. BasinLens CCS is an early research and
educational prototype, so clarity and scientific traceability matter as much as
code.

Before opening a pull request:

1. Explain the geoscience or software problem in an issue.
2. Cite the source for new equations, thresholds, or datasets.
3. State units explicitly and add validation for new inputs.
4. Add or update tests for behavior changes.
5. Keep real-site claims separate from synthetic demonstrations.
6. Update the methodology and limitations when scope changes.

Run the checks locally with:

```bash
python -m unittest discover -s tests -v
python -m basinlens_ccs.cli examples/synthetic_sites.csv --samples 2000
```

