# Official tutorial native-input interoperability

On 2026-10-19, a fresh execution of the official **MODFLOW 6 Grid Approach**
tutorial's unchanged native inputs completed normally with public USGS MODFLOW 6
6.7.0. Its head and cell-budget binaries were byte-identical to the pre-existing
outputs distributed with the tutorial. This establishes interoperability for
this shipped native model. No original GMS GUI execution was observed.

The machine-readable observations, source checksums, input receipts, exact solver
identity and comparison methods are in
[tutorial_validation_record.json](tutorial_validation_record.json). Raw vendor
projects, inputs and outputs are not included in this repository.

## Sources and separate version identities

The source downloads are the official
[tutorial archive](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/mf6_grid.zip)
and [tutorial PDF](https://s3.amazonaws.com/gmstutorials-10.9.aquaveo.com/MODFLOW6-GridApproach.pdf).
The archive SHA-256 is
`ad5d7684e9c6270a9a2a129430b04cc0c6bd39ba03a73f1c21825e3fa3e87dd4`.

| Evidence | Identity | Meaning |
|---|---|---|
| Tutorial distribution | 10.9 URL namespace | Source distribution, not an observed application version |
| Saved GPR root `GMS Version` attribute | `10.8.2` | Stored metadata, not observed GMS execution |
| Shipped simulation listing banner | MODFLOW 6 `6.4.1`, release literal `12/09/2022` | Historical artifact; execution not witnessed |
| Observed rerun solver banner | `mf6: 6.7.0 02/05/2026` | Executable used for this study |

The observed executable SHA-256 is
`479185be33167701696604f7bb55acb4f96476f396e9bb015cbe7da52e278ec4`.
The GPR SHA-256 and PDF SHA-256 are recorded separately in the JSON.

## Execution and units

Fifteen native input files, totaling 3,778 bytes, were copied to a new private
directory. No shipped outputs were copied; the output directory started empty.
The solver exited with code zero and normal termination. Source and copied input
bytes were unchanged after execution. The canonical input-set SHA-256 is
`1d866906bce28e4a16a4af919b793b0703703ee296082a16a0667a05120de5f9`;
its encoding and all fifteen file receipts are in the JSON.

The native model has five layers, fifteen rows and fifteen columns: 1,125 cells.
Its DIS and TDIS files explicitly declare **FEET** and **SECONDS**. A single
86,400-second period has one step and no storage package, so the calculation is
steady state. The top layer is convertible; the four lower layers are confined.
These native units and formulations were preserved without conversion.

The GPR's stored Head group has blank `DatasetUnits`, `TimeUnits=["Days"]` and
`Times=[86400.0]`. These literal values conflict with a direct reading of the
native export's time units. The conflict remains unresolved. This study uses the
native export's units for the native engine calculation and does not infer GMS
display behavior, convert the GPR time values, or repair its metadata.

## Numerical observations

| Quantity | Observation |
|---|---:|
| Saved native output time | 86,400 s |
| Head range | −15.8554949641 to 129.0414115556 ft |
| Maximum head difference from shipped outputs, all 1,125 cells | 0 ft |
| Head RMSE from shipped outputs | 0 ft |
| Maximum head error in 75 constant-head cells | 0 ft |
| External inflow | 157.5000000000 ft³/s |
| External outflow | 157.4993424018 ft³/s |
| Inflow minus outflow | 0.0006575982 ft³/s |
| Residual divided by mean inflow/outflow | 0.0004175235% |

Independent summation gives well extraction of 75 ft³/s, drain outflow of
31.8529498697 ft³/s and constant-head outflow of 50.6463925321 ft³/s. The drain
law evaluated from native conductances, elevations and computed heads agrees
with the binary drain budget within 3.6 × 10⁻¹⁵ ft³/s. Recharge applied to the
210 non-constant-head top cells is 157.5 ft³/s, agreeing within
2.9 × 10⁻¹⁴ ft³/s. Applying recharge to all 225 top cells would instead give
168.75 ft³/s; that is not the applied binary-budget total. Internal face flows
were excluded from the external water balance.

Both head and cell-budget files have matching shipped/rerun SHA-256 values,
recorded in the JSON. Their agreement is evidence within the same solver family.
It is not an independent physical-solver benchmark or a witnessed GMS parity
capture. No parity capture was created by this study.

The geodetic CRS and vertical datum were not established. Negative hydraulic
head relative to the native elevation convention is not negative absolute
pressure; no pressure conversion was performed. This one steady-state tutorial
does not validate grid convergence, the confined groundwater adapter, CO₂–brine
or oil physics, field behavior, or storage safety.
