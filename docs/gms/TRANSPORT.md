# Bounded conservative-solute transport

This original implementation adds a small, runnable MODFLOW 6 GWF/GWT slice to
the reconstruction project. It is independent of GMS and does not close a GMS
parity obligation. CO2–brine, oil, density-dependent flow, reactions, sorption,
heterogeneous geology and general 3D transport are outside this contract. The
shared registry and UI are not extended by this slice.

## Model and units

`groundwater.transport.TransportCase` describes a uniform, saturated, confined
`1 × 1 × ncol` Cartesian grid with a single mobile-domain porosity. Every case
contains the exact `units` object; unsupported units are refused rather than
converted. Concentration is **kg of solute per m³ of pore water**, Darcy flux is
m/day, hydraulic conductivity is m/day, and effective diffusion is m²/day.
Inputs are synthetic assumptions, including the local elevation datum.

For cross-sectional area `A = width × thickness`, positive prescribed Darcy
flux `q` gives water rate `Q = q A` in m³/day and pore velocity `v = q/porosity`
in m/day. A WEL source injects water into the first cell at the specified inlet
concentration. A CHD sink at the last cell fixes hydraulic head to
`thickness + 1 m`; withdrawn solute uses that cell's simulated concentration.
The CHD auxiliary value is zero, but it does not impose zero concentration on
the outgoing water. The remaining water boundaries are closed. No GWF storage
package is used: flow is steady, transport evolves in time.

The boundary packages act on cells. They do not prescribe a continuous-domain
Dirichlet concentration at the external face. There is no external diffusive
or dispersive solute flux. In the uniform interior, nominal hydrodynamic
dispersion is `D = diffusion + longitudinal_dispersivity × v`. With constant
porosity, the interior conservative equation is

\[
\frac{\partial C}{\partial t}
=D\frac{\partial^2 C}{\partial x^2}
-v\frac{\partial C}{\partial x}.
\]

The exporter writes coupled GWF/GWT, MST porosity, TVD advection, DSP effective
diffusion/dispersivity, SSM source mixing, and every-step concentration/budget
output. FloPy's timestamp headers are disabled and numeric arrays/list entries
use 18 significant digits. This avoids changing a small non-round initial
inventory through FloPy's default eight-decimal formatting.

Bounds: 3–2,000 cells, 1–2,000 equal time steps and at most 2,000,000 saved
concentrations; porosity 0.01–1; concentration 0–1 kg/m³; nonnegative Darcy flux;
positive dimensions, conductivity and duration. All numbers must be finite and
booleans are refused as numbers. Advective Courant number must be at most one.
These bounds define this implementation and its resource/accuracy envelope;
they do not establish physical validity of every accepted parameter combination.
Diffusion number is reported, not treated as proof of temporal convergence.

## Export, execution and result identity

```bash
python -m basinlens_ccs.groundwater.transport export examples/transport/uniform.json --output build/transport-export
python -m basinlens_ccs.groundwater.transport verify-export build/transport-export
python -m basinlens_ccs.groundwater.transport run examples/transport/closed_gaussian.json --output build/transport-run --exe /absolute/path/to/mf6
python -m basinlens_ccs.groundwater.transport results build/transport-run
```

Every output directory must be fresh. No normal operation downloads a solver.
`run_transport` delegates all process execution, timeout/output limits, source
copying, failure retention, exact inventory hashing and bundle verification to
the existing `run_native_simulation` / `verify_native_run`. It introduces no
second execution framework. A `settings.json` with **our own versioned schema**
records the case and native input inventory; the existing importer archives it
as an opaque sidecar. This is not a claimed GMS settings format or a sidecar
synchronization mechanism.

`read_transport_results` accepts a completed native bundle, never an external
case. It verifies the native manifest and captured sidecar, regenerates the
native inputs from the captured case, and requires byte-identical native input
inventories. Reader and exporter must use the recorded exporter source revision
and FloPy version; revision/version mismatch is refused. Editing only the case
and rehashing both manifests cannot relabel a different simulation.

The reader supports this exporter’s little-endian double-precision concentration
records only. It checks exact size, every record's quantity/dimensions/layer and
complete time schedule before loading at most 2,000,000 values. Budget columns
have fixed meanings; unknown layouts, missing/nonfinite values, truncated data
and materially negative concentrations are refused. Inventories are bounded to
64 files, 2 MiB per native input and 8 MiB total. Exact hashes detect accidental
or partial alteration; they do not authenticate an operator who replaces an
entire bundle and its provenance.

The returned `TransportResult` has the captured case, cell-center x coordinates,
times, concentrations, total dissolved mass and an explicit summary. It keeps
operational native execution distinct from the synthetic physical checks below.
`conservation_passed` and `concentration_bounds_passed` are separate checks; no
pressure, containment, field safety or GMS equivalence is inferred.

## Independent synthetic checks

The tests use public USGS MF6 6.7.0 and independent equations, not original GMS
outputs. Exact source/fixture/solver identities and measured numbers are in
[transport_validation_record.json](transport_validation_record.json).

| Check | Independent reference | Engineering test gate |
|---|---|---|
| Uniform advective inlet | Initial and incoming `C=0.2 kg/m³` remain uniform for every step | Maximum concentration error <1e-8 kg/m³, mass error <1e-7 kg |
| Closed Gaussian diffusion | `C₀=0.2 exp[-(x−50)²/(2·3²)]`; `D=0.2 m²/day`, `t=20 day`; centroid 50 m, variance `9+2Dt=17 m²`, constant mass | Every-step centroid error <1e-7 m, variance error <1e-5 m², mass error <1e-8 kg |
| Gaussian profile/refinement | Infinite-domain Gaussian with variance `9+2Dt` and amplitude `0.2·3/sqrt(9+2Dt)` | Relative final L1 error <1%; halving dx and dividing dt by four reduces error below 40% of coarse error |
| Transient inlet | `M(t_n)−M(0)=Q Δt Σₖ(Cin−Cout,k)` with end-step outlet concentration | Every-step residual <1e-7 kg; independent 40-day expected mass 2.4 kg within 1e-5 kg, outlet remains distant |
| Non-round initial inventory | Closed uniform `C=0.00123456789 kg/m³` must retain its stated value | Maximum concentration error <1e-14 kg/m³, inventory residual <1e-12 kg |

For the Gaussian, domain length is 100 m and boundaries are more than 12 final
standard deviations from the center; the infinite-domain approximation is
therefore appropriate at this duration. The 100-cell/100-step and
200-cell/400-step checks compare concentration at cell centers with the
continuum profile. They do not establish convergence for arbitrary fields,
large diffusion numbers or other boundaries.

On the recorded MF6 6.7.0 run, final Gaussian relative L1 error decreased from
0.00401874474 to 0.00100258664 (a ratio of 0.24948). Fine-grid maximum every-step
variance error was 6.40e-14 m² and mass residual was 1.05e-14 kg. The uniform
advective case retained concentration and 12 kg inventory exactly; the inlet
case reached 2.400000000000001 kg with maximum inventory residual 7.11e-15 kg.
These are measured synthetic results for the recorded inputs and engine.

The result reader additionally compares the inventory integral with the
specified boundary flux at **every saved step**, and independently checks native
water source/sink rates, GWT source/sink rates and GWT storage rates. The balance
gate is `1e-8 kg + 1e-7 × mass scale`, where mass scale is the maximum of initial
mass, absolute integrated net boundary mass and total incoming mass. Boundary
mass-rate tolerance is `1e-8 kg/day + 1e-7 × Q × max(Cinitial,Cin)`; water-rate
tolerance is `1e-8 m³/day + 1e-7 × Q`. The tolerances are project engineering
targets, not regulatory or site acceptance limits. Absolute tolerances are
reported so a near-zero denominator cannot imply a meaningful relative pass.

```bash
MF6_EXE=/absolute/path/to/mf6 python -m unittest discover -s tests -p test_transport.py -v
```

The focused suite contains 12 tests. Export tests require FloPy; six
solver-dependent test methods require seven real runs because the Gaussian
refines twice. Four physics methods use five runs; two software integrity
methods use two runs. Missing optional dependencies cause explicit skips and must not be
reported as passed physical validation. Tamper checks, altered-case rebinding,
unknown units/fields, overflow, booleans, range/dimension limits, deterministic
exports and immutable output behavior are software checks.

The integrated isolated-worktree suite passed **249 tests with zero skips** in
35.511 seconds. Compilation and diff checks passed. This count includes the
existing 237 tests and the 12 new transport tests; it is a software check count,
not a product-coverage measure.

Independent review also exercised a different Gaussian (`L=120 m`, `sigma=5 m`,
`D=0.4 m²/day`, `t=12 day`), a porosity pair, an advective uniform concentration,
an inlet front with outlet breakthrough and non-round geometry/parameters. It
identified the initial formatting defect described above; the fix and its
regression were rerun. These checks add numerical evidence within this narrow
domain, without validating general transport or original GMS behavior.

## Primary references consulted

- USGS, Langevin et al. (2022),
  [Documentation for the MODFLOW 6 Groundwater Transport Model, TM 6-A61](https://doi.org/10.3133/tm6A61): control-volume conservative transport formulation and source/sink concepts.
- USGS MODFLOW 6.7.0 [MST](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwt-mst.html),
  [SSM](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwt-ssm.html),
  [DSP](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwt-dsp.html),
  [ADV](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwt-adv.html) and
  [OC](https://modflow6.readthedocs.io/en/6.7.0/_mf6io/gwt-oc.html): exact package meanings and output schedule.
- FloPy official [DSP API documentation](https://flopy.readthedocs.io/en/master/source/flopy.mf6.modflow.mfgwtdsp.html)
  and installed FloPy 3.11.0 public MF6 classes/simulation formatting properties.

Next bounded work: independently validate a specified advective-dispersive
breakthrough boundary problem before adding richer sources, heterogeneity,
multidimensional grids, shared engine registration or UI controls. Whole GMS
reconstruction and a native GPR writer remain separate open objectives.
