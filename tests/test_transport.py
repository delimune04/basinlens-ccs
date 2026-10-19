"""Original synthetic cases; operational checks and independent physics distinct."""
from dataclasses import replace
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from basinlens_ccs.groundwater.native_run import NativeRunError, verify_native_run
from basinlens_ccs.groundwater.transport import (
    TransportCase, TransportError, UNITS, export_transport, load_transport_case,
    read_transport_results, run_transport, verify_transport_export,
)

FLOPY = importlib.util.find_spec("flopy") is not None
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")


def case(**changes):
    values = dict(length_m=40.0, width_m=2.0, thickness_m=3.0, ncol=40,
        porosity=0.25, conductivity_m_per_day=1.0, darcy_flux_m_per_day=0.05,
        longitudinal_dispersivity_m=0.5, diffusion_m2_per_day=0.05,
        initial_concentration_kg_m3=(0.2,) * 40, inlet_concentration_kg_m3=0.2,
        duration_day=20.0, nsteps=40)
    values.update(changes)
    return TransportCase(**values)


def gaussian(ncol, nsteps):
    x = (np.arange(ncol) + 0.5) * 100.0 / ncol
    initial = 0.2 * np.exp(-((x - 50.0) ** 2) / (2 * 3.0**2))
    return case(length_m=100.0, width_m=1.0, thickness_m=1.0, ncol=ncol,
        initial_concentration_kg_m3=tuple(initial), inlet_concentration_kg_m3=0.0,
        darcy_flux_m_per_day=0.0, longitudinal_dispersivity_m=0.0,
        diffusion_m2_per_day=0.2, duration_day=20.0, nsteps=nsteps)


class TransportContractTests(unittest.TestCase):
    def test_explicit_units_and_exact_fields_round_trip(self):
        original = case()
        self.assertEqual(TransportCase.from_dict(original.to_dict()), original)
        for units in ({}, {**UNITS, "concentration": "mg/L"}, {**UNITS, "time": "second"}):
            with self.assertRaises(TransportError):
                replace(original, units=units)
        for data in ({k: v for k, v in original.to_dict().items() if k != "units"},
                     {**original.to_dict(), "decay": 1.0},
                     {**original.to_dict(), "schema": 1}):
            with self.assertRaises(TransportError):
                TransportCase.from_dict(data)

    def test_nonfinite_boolean_negative_and_dimension_bounds(self):
        for field in ("length_m", "porosity", "conductivity_m_per_day", "darcy_flux_m_per_day",
                      "diffusion_m2_per_day", "duration_day", "inlet_concentration_kg_m3"):
            for value in (True, float("nan"), float("inf"), -1, "1", 10**1000):
                with self.subTest(field=field, value=str(value)[:16]), self.assertRaises(TransportError):
                    case(**{field: value})
        for changes in ({"porosity": 0}, {"ncol": True}, {"nsteps": 0}, {"ncol": 2001},
                        {"initial_concentration_kg_m3": (0.2,)},
                        {"initial_concentration_kg_m3": (float("nan"),) * 40},
                        {"initial_concentration_kg_m3": (-1,) * 40},
                        {"initial_concentration_kg_m3": (1.1,) * 40},
                        {"nsteps": 1, "darcy_flux_m_per_day": 1},
                        {"conductivity_m_per_day": 1e-6}):
            with self.subTest(changes=str(changes)[:100]), self.assertRaises(TransportError):
                case(**changes)

    def test_pore_velocity_dispersion_and_mass_units_hand_calculation(self):
        c = case()
        self.assertAlmostEqual(c.water_rate_m3_day, 0.3)  # .05 m/day * 2 m * 3 m
        self.assertEqual(c.pore_velocity_m_day, 0.2)
        self.assertAlmostEqual(c.dispersion_m2_day, 0.15)
        self.assertEqual(c.dx_m, 1.0)
        self.assertEqual(c.dt_day, 0.5)
        self.assertEqual(c.courant_number, 0.1)
        self.assertAlmostEqual(sum(c.initial_concentration_kg_m3) * c.porosity * c.width_m * c.thickness_m * c.dx_m, 12.0)

    def test_duplicate_json_overflow_and_large_input_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary) / "case.json"
            for raw in (b'{"schema":1,"schema":1}', b'{"porosity":1e9999}', b'x' * (256 * 1024 + 1)):
                p.write_bytes(raw)
                with self.assertRaises(TransportError):
                    load_transport_case(p)


@unittest.skipUnless(FLOPY, "Install optional FloPy for transport export checks")
class TransportExportTests(unittest.TestCase):
    def test_export_is_deterministic_and_case_bound_without_solver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = export_transport(case(), root / "a")
            b = export_transport(case(), root / "b")
            self.assertEqual({p.name: p.read_bytes() for p in a.iterdir()},
                             {p.name: p.read_bytes() for p in b.iterdir()})
            self.assertEqual(verify_transport_export(a), case())
            self.assertIn("GWT6", (a / "mfsim.nam").read_text())
            self.assertIn("GWF6-GWT6", (a / "mfsim.nam").read_text())
            self.assertFalse((a / "solute.ucn").exists())
            with self.assertRaises(FileExistsError):
                export_transport(case(), a)

    def test_altered_case_inputs_extra_files_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for change in ("case", "input", "extra", "symlink"):
                p = export_transport(case(), root / change)
                if change == "case":
                    record = json.loads((p / "settings.json").read_text())
                    record["case"]["porosity"] = 0.5
                    (p / "settings.json").write_text(json.dumps(record))
                elif change == "input":
                    (p / "solute.mst").write_text("changed input")
                elif change == "extra":
                    (p / "unlisted").write_text("unlisted")
                else:
                    source = p / "solute.mst"
                    outside = root / "external.mst"
                    source.rename(outside)
                    source.symlink_to(outside)
                with self.subTest(change=change), self.assertRaises(TransportError):
                    verify_transport_export(p)


@unittest.skipUnless(FLOPY and SOLVER, "Set MF6_EXE for real conservative-solute checks")
class TransportPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_case(self, c, name):
        run = run_transport(c, self.root / name, exe_name=SOLVER)
        result = read_transport_results(run.workspace)
        self.assertTrue(result.summary["conservation_passed"], result.summary)
        self.assertIs(result.summary["gms_parity_established"], False)
        return result

    def test_uniform_advective_inlet_preserves_concentration_at_every_step(self):
        result = self.run_case(case(), "uniform")
        self.assertLess(float(np.max(np.abs(result.concentrations_kg_m3 - 0.2))), 1e-8)
        self.assertLess(float(np.max(np.abs(result.mass_kg - 12.0))), 1e-7)
        self.assertLess(result.summary["max_inventory_balance_error_kg"], 1e-7)
        self.assertLess(result.summary["max_water_boundary_error_m3_day"], 1e-8)

    def test_non_round_uniform_initial_inventory_preserves_double_precision(self):
        c = case(ncol=80, porosity=0.3, conductivity_m_per_day=5.0,
                 initial_concentration_kg_m3=(0.00123456789,) * 80,
                 inlet_concentration_kg_m3=0.0, darcy_flux_m_per_day=0.0,
                 longitudinal_dispersivity_m=0.0, diffusion_m2_per_day=0.02,
                 duration_day=6.0, nsteps=24)
        result = self.run_case(c, "precision")
        self.assertLess(float(np.max(np.abs(result.concentrations_kg_m3 - 0.00123456789))), 1e-14)
        self.assertLess(result.summary["max_inventory_balance_error_kg"], 1e-12)

    def test_closed_diffusion_gaussian_moments_profile_and_refinement(self):
        errors = []
        for ncol, nsteps in ((100, 100), (200, 400)):
            result = self.run_case(gaussian(ncol, nsteps), f"gaussian-{ncol}")
            x, values = result.x_m, result.concentrations_kg_m3
            mean = (values * x).sum(axis=1) / values.sum(axis=1)
            variance = (values * (x[None, :] - mean[:, None])**2).sum(axis=1) / values.sum(axis=1)
            expected_variance = 9.0 + 2 * 0.2 * result.times_day
            self.assertLess(float(np.max(np.abs(mean - 50.0))), 1e-7)
            self.assertLess(float(np.max(np.abs(variance - expected_variance))), 1e-5)
            self.assertLess(float(np.max(np.abs(result.mass_kg - result.summary["initial_mass_kg"]))), 1e-8)
            # Infinite-domain Gaussian, boundaries >12 final standard deviations away.
            final_variance = 17.0
            exact = 0.2 * 3.0 / math.sqrt(final_variance) * np.exp(-(x - 50.0)**2 / (2 * final_variance))
            relative_l1 = float(np.sum(np.abs(values[-1] - exact)) / np.sum(exact))
            self.assertLess(relative_l1, 0.01)
            errors.append(relative_l1)
        self.assertLess(errors[1], errors[0] * 0.4)  # dx/2 and dt/4 should improve continuum profile.

    def test_inlet_front_inventory_matches_independent_boundary_mass_integral(self):
        c = case(ncol=80, initial_concentration_kg_m3=(0.0,) * 80,
                 duration_day=40.0, nsteps=160, diffusion_m2_per_day=0.01)
        result = self.run_case(c, "inlet")
        # kg = m3/day * kg/m3 * day. Backward-Euler sink uses end-step C.
        expected = np.cumsum(c.water_rate_m3_day * (0.2 - result.concentrations_kg_m3[:, -1])) * c.dt_day
        self.assertLess(float(np.max(np.abs(result.mass_kg - expected))), 1e-7)
        self.assertLess(abs(result.mass_kg[-1] - 2.4), 1e-5)
        self.assertGreater(float(result.concentrations_kg_m3[-1, 0]), 0.19)

    def test_native_run_manifest_and_result_reader_detect_tampering(self):
        run = run_transport(case(), self.root / "tampered", exe_name=SOLVER)
        self.assertEqual(verify_native_run(run.workspace)["status"], "completed")
        path = run.simulation_workspace / "solute.ucn"
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(NativeRunError):
            read_transport_results(run.workspace)

    def test_wrong_captured_case_cannot_relabel_native_results_even_if_rehashed(self):
        run = run_transport(case(), self.root / "wrong-case", exe_name=SOLVER)
        path = run.workspace / "source_sidecars/settings.json"
        record = json.loads(path.read_text())
        record["case"]["inlet_concentration_kg_m3"] = 0.1
        path.write_text(json.dumps(record))
        # Simulate an operator updating both manifests, not a signed provenance claim.
        metadata_path = run.workspace / "native_run_metadata.json"
        metadata = json.loads(metadata_path.read_text())
        entry = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        metadata["files"]["source_sidecars/settings.json"] = entry
        metadata["source_snapshot"]["sidecars"]["settings.json"] = entry
        metadata_path.write_text(json.dumps(metadata))
        self.assertEqual(verify_native_run(run.workspace)["status"], "completed")
        with self.assertRaisesRegex(TransportError, "does not reconstruct"):
            read_transport_results(run.workspace)


if __name__ == "__main__":
    unittest.main()
