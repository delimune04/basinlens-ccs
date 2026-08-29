# Methodology

## Purpose

BasinLens CCS v0.1 is a transparent educational and research prototype for
**concept screening**. It is designed to make assumptions visible and results
reproducible. It is not a substitute for site characterization, reservoir
simulation, geomechanical assessment, regulation, or professional judgment.

## Volumetric capacity

The prototype calculates effective pore-volume capacity as:

\[
M_{CO_2} = A h \phi \rho_{CO_2} E
\]

where:

- `A` is storage area in square metres;
- `h` is net reservoir thickness in metres;
- `phi` is effective porosity as a fraction;
- `rho_CO2` is in-situ CO2 density in kilograms per cubic metre; and
- `E` is a dimensionless storage-efficiency factor.

The result is converted from kilograms to million metric tonnes (Mt).

Each input is represented by a triangular distribution with low, most-likely,
and high values. Monte Carlo sampling propagates input uncertainty into the
capacity distribution. The reported Q10, Q50, and Q90 are ordinary statistical
quantiles. They are named `Q`, not petroleum reserve `P`, to avoid ambiguity
between cumulative and exceedance-probability conventions.

## Sensitivity

Sensitivity is reported as rank correlation between each sampled input and the
simulated capacity. This indicates association within the assumed input ranges;
it does not establish causal importance outside the scenario.

## Illustrative containment-attention indicators

The prototype deliberately calls these values **attention indicators**, not
risk scores. The default demonstration thresholds are:

| Indicator | 0 attention | 100 attention | Weight |
|---|---:|---:|---:|
| Caprock thickness | at least 100 m | at most 20 m | 45% |
| Distance to mapped fault | at least 10 km | at most 1 km | 35% |
| Legacy wells per 100 km2 | 0 | at least 20 | 20% |

Linear interpolation is used between the endpoints. These values have **not**
been calibrated for a particular basin, jurisdiction, lithology, fault system,
well inventory, or regulatory framework. Future versions must replace them
with literature-supported, project-specific criteria and uncertainty.

## Important omissions

The prototype does not currently model:

- pressure-limited capacity or basin-scale pressure interference;
- injectivity, relative permeability, or capillary pressure;
- multiphase plume migration and trapping mechanisms;
- fault transmissibility or reactivation;
- wellbore integrity;
- coupled geomechanics, induced seismicity, or geochemistry;
- seal entry pressure and mineralogical compatibility;
- monitoring, remediation, economics, permitting, or social constraints; or
- correlations among uncertain input parameters.

These omissions mean that a high capacity or low attention score cannot be
interpreted as evidence that a site is suitable or safe.

## Starting references

- U.S. Geological Survey, *National Assessment of Geologic Carbon Dioxide
  Storage Resources—Methodology Implementation* (Open-File Report 2013-1055):
  https://pubs.usgs.gov/of/2013/1055/
- U.S. DOE/NETL, *CO2 Storage prospeCtive Resource Estimation Excel aNalysis
  (CO2-SCREEN) User's Manual* (2020):
  https://www.osti.gov/biblio/1617640
- Goodman, Sanguinito, and Levine, *Prospective CO2 saline resource estimation
  methodology: Refinement of existing US-DOE-NETL methods based on data
  availability* (2016), DOI: 10.1016/j.ijggc.2016.09.009.
- Society of Petroleum Engineers, *11th Comparative Solution Project*:
  https://www.spe.org/csp/spe11/

These sources motivate the volumetric prototype and its uncertainty-aware
direction. They do not validate the demonstration attention thresholds.
