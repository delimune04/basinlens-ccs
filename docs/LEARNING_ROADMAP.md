# Learning and development roadmap

This repository is intentionally split into a functioning prototype and a
post-exam reimplementation track. The goal is to finish the project with code
the owner can explain, test, and extend independently.

## Before the exam: design together

- Define the user and the decision the tool supports.
- Review every physical quantity, unit conversion, and assumption.
- Replace synthetic examples with a carefully licensed public dataset.
- Decide which features belong in v0.1 and which should remain research ideas.
- Collect references for capacity and containment-screening methods.
- Turn each major design choice into a short GitHub issue.

## After the exam: reimplement by hand

1. Recreate `TriangularEstimate` and its validation tests.
2. Recreate the volumetric equation and verify the 0.028 Mt hand calculation.
3. Add random sampling and prove that a fixed seed is reproducible.
4. Compute Q10/Q50/Q90 without copying the existing function.
5. Implement rank-correlation sensitivity and interpret one example.
6. Read a CSV and produce clear errors for invalid inputs.
7. Build the CLI, then the Streamlit interface.
8. Replace one demonstration threshold with a referenced method.
9. Open a pull request containing the independently written implementation.
10. Compare outputs against this prototype and explain every difference.

## Candidate milestones

- `v0.1`: synthetic data, volumetric uncertainty, transparent attention flags
- `v0.2`: real public well data and automated LAS quality control
- `v0.3`: spatial layers and an interactive GIS view
- `v0.4`: literature-backed screening criteria and correlated uncertainty
- `v0.5`: pressure-limited case study using OPM Flow or MRST
- `v1.0`: documented validation against a published CCS benchmark

