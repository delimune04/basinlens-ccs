# Explicit classic confined-water adapters

`basinlens_ccs.subsurface.classic` compiles the existing validated `WorkflowCase`
to **MODFLOW-2005 LPF/PCG** or **MODFLOW-NWT UPW/NWT with XMD**. This is an authored,
bounded adapter, not a general legacy importer, native GMS writer, full NWT
interface, or original-GMS comparison. CCS/oil metadata describes background
water only; CO2, oil, heat, reactions and multiphase physics are absent.

## Contract

- Metres, days and m3/day; all-active confined layers, uniform planar cells and
  explicitly flat descending layer surfaces. Internal rows increase northward;
  compilation reverses rows into the engines' north-to-south convention and
  result loading reverses them back. CRS/datum remain literal metadata.
- Named materials map cellwise Kx/Ky/Kz, specific storage and porosity. LPF/UPW
  use `laytyp=0`, horizontal harmonic connections and no drying/rewetting. The
  confined equation is storage volume rate plus the sum of conductance times
  head differences equals the specified external sources.
- CHD, RCH, WEL, GHB, DRN and RIV have explicit period support. An absent list
  package in a later period is written as zero, never an accidental carryover.
  CHD membership must stay unchanged across periods: this subset refuses a
  changing set because classic CHD can retain changed IBOUND state. Head values
  may change by period; each period has equal start/end values, without ramps.
- At least two connected cells are required. Actual one-cell tests showed PCG
  removing an isolated cell and NWT resetting it inactive. The subset rejects
  these inputs before execution; MF6's separately tested one-cell support remains
  distinct. An engine's zero CONSTANT HEAD budget without any CHD is accepted;
  nonzero flow without authored CHD support is refused.
- NWT defaults to the documented LINMETH=2 XMD, IACL=2 Bi-CGSTAB, NORTH=2,
  HCLOSEXMD=1e-10 and MXITERXMD=1000. The pinned engine's GMRES option crashed
  with a floating divide by zero when a closed transient storage case switched
  its well off. Keeping the physical inputs unchanged, XMD completed all steps.
  XMD in turn failed convergence on a three-cell fractional-CHD case with one
  active unknown; GMRES completed that unchanged case. Other documented XMD
  acceleration/ordering trials did not resolve both cases. Consequently the
  API/CLI/UI expose explicit `linear_solver`: pcg (MF2005), xmd or gmres (NWT).
  The choice is bound in settings, native tokens, rewrite and result summary.
  There is no hidden retry, solver fallback, perturbed forcing or claim that a
  single configuration handles all supported-looking decks. Nonconvergence is
  refused and retained. Select GMRES explicitly for the fractional-CHD fixture.
- Fixed-step periods preserve explicit duration/steady/transient state. Native
  saved time/period/step indices, grid dimensions and compact-budget method are
  checked against the compiled schedule. No extrapolated saved steps.
- Opening/exporting never runs or downloads an executable. Running requires an
  explicitly selected exact binary. Workspaces and rewritten outputs must be
  new. A failed/timeout run retains diagnostics; artifact collection cannot mask
  the original execution error.

## Precision, identity and roundtrip

The public MODFLOW-ORG executables release `29.0` archive is pinned by SHA256
`ab17192a3531dec61d4f4eab3da10f618e85d1f792d5edc71306a3e06e0e22c3`.
`mf2005dbl` is pinned to `08e49f5abae8dcb33370444b5e6f6c922887254301312bc6cd3192604a0c0e85`;
`mfnwtdbl` to `7c9a54732f0dc936daaf6a8cf6749c51cb38480049db650250e7464d64bef8f4`.
Observed normal-run banners identify MF2005 1.12.00 (2017-02-03) and NWT 1.3.0
(2022-07-01); these are pinned study binaries, not a claim about current releases.
The archive is prepared only by an explicitly invoked CI command. Program bytes
are not committed. Release prose and member banners are distinct evidence.

FloPy's legacy arrays are float32 even with double-precision executables.
Pre-write and actual written/reloaded layers must stay ordered and preserve
thickness within 1e-6 relative error; thin layers at large elevations can be
refused. FREE arrays use a parsed E32.17 descriptor to preserve stored values
and separators. Float64 list records retain fractional boundary values; the
native load/rewrite reader restores list values from the actual native text,
not from sidecar values. Unsupported parameter/reuse grammars are refused.

`verify_classic_roundtrip` actually loads the native model, writes another native
deck, checks the complete ordered numeric/keyword token semantics, and optionally
executes both decks. It checks exact metadata/source preservation, head differences
<=1e-7 m, budget-column differences <=1e-7 in their stated units, water balance
<=1e-8+1e-7 times the in/out scale, boundary rate/head gates and confined heads
above layer tops. Checksums bind compiler sources, FloPy, native inputs and run
artifacts; result loading revalidates these identities before exposing arrays.

The bounded binary readers check finite values and sums, saved ordering, exact
record sizes, node/layer support, expected budget terms and actual dt/pertim/totim.
They support only this compiler's double head and compact-budget methods 1/2/3/5
(method5 has no auxiliary fields), not arbitrary classic model output.

## Reproduce

```bash
python examples/classic/run_classic_example.py --output build/classic-example \
  --mf2005-exe /absolute/path/mf2005dbl --mfnwt-exe /absolute/path/mfnwtdbl
python -m basinlens_ccs.subsurface.classic export examples/workflow/layered_background_water.json \
  --engine mf2005 --output build/classic-input
python -m basinlens_ccs.subsurface.classic roundtrip build/classic-input \
  --output build/classic-roundtrip --exe /absolute/path/mf2005dbl
```

For NWT, `--linear-solver xmd` or `--linear-solver gmres` is an explicit authored
choice (`export_classic`/`run_classic` accept the same `linear_solver` keyword).
Result and run CLI commands return a nonzero exit when any physical gate fails;
diagnostic arrays remain available through the Python API with their false gates.

The example performs eight actual native runs, covering two cases and both
engines, emits coordinate-explicit head CSVs and source-bound receipts. Independent
tests additionally check harmonic series resistance, mixed GHB/recharge/well
balance, closed transient storage with a later well shutoff, asymmetric physical
rows, fractional CHD values and altered artifacts. These are synthetic checks;
field validation and original GMS equivalence remain unestablished.

Primary format/physics references: [USGS MF2005 documentation](https://water.usgs.gov/ogw/modflow/MODFLOW-2005-Guide/),
[USGS NWT](https://www.usgs.gov/software/modflow-nwt-a-newton-formulation-modflow-2005)
and [versioned executable distribution](https://github.com/MODFLOW-ORG/executables/releases/tag/29.0).
NWT controls are documented in the [USGS NWT package guide](https://water.usgs.gov/nrp/gwsoftware/modflow2000/MFDOC/nwt_newton_solver.html).
