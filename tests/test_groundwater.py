"""Input/optional-dependency checks; numerical tests require an explicit MF6 path."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

import numpy as np

from basinlens_ccs.groundwater import (GroundwaterCase, GroundwaterDependencyError, GroundwaterValidationError,
    demo_case, export_case, load_case, run_case, verify_bundle)

MF6_EXE = os.environ.get("MF6_EXE") or os.environ.get("BASINLENS_MF6_EXE")


def simple_case():
    d = demo_case().to_dict()
    d.update(case_id="benchmark", name="Synthetic independent benchmark", wells=[], recharge_m_per_day=0)
    d["grid"].update(nlay=1, nrow=3, ncol=21, delr_m=10.0, delc_m=10.0, layer_bottoms_m=[-10.0])
    d["properties"] = {"kx_m_per_day": 10.0, "ky_m_per_day": 10.0, "kz_m_per_day": 10.0,
                       "specific_storage_per_m": 1e-4}
    d["periods"] = [{"length_days": 1.0, "steps": 1, "transient": False}]
    return d


class GroundwaterContractTests(unittest.TestCase):
    def test_canonical_roundtrip_and_layer_expansion(self):
        case = GroundwaterCase.from_dict(simple_case())
        self.assertEqual(case.properties["kx_m_per_day"], [10.0])
        self.assertEqual(case.to_dict(), GroundwaterCase.from_dict(case.to_dict()).to_dict())
        self.assertEqual(demo_case().grid["nlay"], 3)

    def test_invalid_cases_and_bounds(self):
        invalid = []
        for field, value in [("nlay", True), ("ncol", 2), ("nrow", 501), ("delr_m", 0),
                             ("top_m", float("nan")), ("layer_bottoms_m", [0])]:
            d = simple_case(); d["grid"][field] = value; invalid.append(d)
        for field, value in [("kx_m_per_day", -1), ("kz_m_per_day", [1, 2]), ("specific_storage_per_m", -1)]:
            d = simple_case(); d["properties"][field] = value; invalid.append(d)
        d = simple_case(); d["units"] = {"time": "SECONDS"}; invalid.append(d)
        d = simple_case(); d["boundaries"]["left_head_m"] = -1; invalid.append(d)
        d = simple_case(); d["initial_head_m"] = -1; invalid.append(d)
        d = simple_case(); d["periods"][0]["transient"] = 1; invalid.append(d)
        d = simple_case(); d["periods"][0]["steps"] = 1001; invalid.append(d)
        d = simple_case(); d["provenance"]["assumptions"] = "not a list"; invalid.append(d)
        d = simple_case(); d["properties"]["specific_storage_per_m"] = 0; d["periods"][0]["transient"] = True; invalid.append(d)
        d = simple_case(); d["unexpected"] = 1; invalid.append(d)
        for d in invalid:
            with self.subTest(case=d), self.assertRaises(GroundwaterValidationError):
                GroundwaterCase.from_dict(d)

    def test_wells_boundary_duplicate_and_schedules(self):
        d = simple_case()
        w = {"name": "p", "layer": 0, "row": 1, "column": 10, "rate_m3_per_day": -5}
        d["wells"] = [w]
        d["periods"].append({"length_days": 3, "steps": 3, "transient": True, "wells": []})
        case = GroundwaterCase.from_dict(d)
        self.assertEqual(case.periods[-1]["wells"], [])
        for bad in [dict(w, column=0), dict(w, column=21), dict(w, layer=-1), dict(w, rate_m3_per_day=float("inf"))]:
            d["wells"] = [bad]
            with self.assertRaises(GroundwaterValidationError): GroundwaterCase.from_dict(d)
        d["wells"] = [w, copy.deepcopy(w)]
        with self.assertRaises(GroundwaterValidationError): GroundwaterCase.from_dict(d)

    def test_json_duplicate_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "duplicate.json"
            p.write_text('{"case_id":"a","case_id":"b"}')
            with self.assertRaisesRegex(GroundwaterValidationError, "duplicate"):
                load_case(p)

    def test_empty_malformed_manifests_and_cli_fail_cleanly(self):
        from basinlens_ccs.groundwater.__main__ import main
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run_metadata.json"
            for manifest in [{"status": "completed", "files": {}}, {}, [],
                             {"manifest_schema_version": 1, "status": [], "files": {}},
                             {"manifest_schema_version": True, "status": "completed", "files": {}}]:
                path.write_text(json.dumps(manifest))
                with self.assertRaises(GroundwaterValidationError): verify_bundle(td)
                with redirect_stderr(StringIO()) as stderr:
                    self.assertEqual(main(["verify", td]), 2)
                self.assertNotIn("Traceback", stderr.getvalue())
            path.write_text("{broken")
            with self.assertRaises(GroundwaterValidationError): verify_bundle(td)

    def test_missing_solver_does_not_create_output(self):
        if importlib.util.find_spec("flopy") is None: self.skipTest("FloPy not installed")
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "missing"
            with self.assertRaises(GroundwaterDependencyError):
                run_case(simple_case(), output, exe_name=Path(td) / "does-not-exist")
            self.assertFalse(output.exists())

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "Optional FloPy not installed")
    def test_export_portable_inputs_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as td:
            output = export_case(simple_case(), Path(td) / "export")
            self.assertTrue((output / "model" / "mfsim.nam").is_file())
            self.assertEqual(verify_bundle(output)["status"], "exported")
            self.assertFalse((output / "heads.npz").exists())
            with self.assertRaises(FileExistsError): export_case(simple_case(), output)
            manifest_path = output / "run_metadata.json"
            manifest = json.loads(manifest_path.read_text())
            variants = []
            altered = copy.deepcopy(manifest); del altered["files"]["case.json"]; variants.append(altered)
            altered = copy.deepcopy(manifest); altered["files"]["case.json"] = {}; variants.append(altered)
            altered = copy.deepcopy(manifest); altered["case_sha256"] = "0" * 64; variants.append(altered)
            for unsafe in ("../outside", "/outside", "model/../../outside", "model\\outside"):
                altered = copy.deepcopy(manifest); altered["files"][unsafe] = {"size_bytes": 0, "sha256": "0" * 64}; variants.append(altered)
            for altered in variants:
                manifest_path.write_text(json.dumps(altered))
                with self.assertRaises(GroundwaterValidationError): verify_bundle(output)
            manifest_path.write_text(json.dumps(manifest))
            (output / "case.json").write_text("{}")
            with self.assertRaises(GroundwaterValidationError): verify_bundle(output)


@unittest.skipUnless(MF6_EXE and importlib.util.find_spec("flopy"),
    "Set MF6_EXE to an installed MF6 executable for numerical checks")
class GroundwaterSolverTests(unittest.TestCase):
    def run_model(self, d):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return run_case(d, Path(temporary.name) / "run", exe_name=MF6_EXE)

    def test_linear_head_independent_solution(self):
        result = self.run_model(simple_case())
        exact = np.linspace(12, 10, 21)
        np.testing.assert_allclose(result.heads[-1, 0], np.tile(exact, (3, 1)), rtol=0, atol=1e-7)
        self.assertLess(result.summary["water_budget"]["max_abs_percent_discrepancy"], 0.1)
        self.assertEqual(verify_bundle(result.workspace)["status"], "completed")
        self.assertEqual(result.heads.shape, (1, 1, 3, 21))
        with self.assertRaises(FileExistsError):
            run_case(simple_case(), result.workspace, exe_name=MF6_EXE)

    def test_uniform_recharge_independent_discrete_parabola_and_balance(self):
        d = simple_case(); d["recharge_m_per_day"] = 0.001
        d["boundaries"] = {"left_head_m": 10, "right_head_m": 10}
        result = self.run_model(d)
        # Confined T = K*b = 100 m2/day. For constant R, the centred finite
        # difference of h=H + R*x*(L-x)/(2*T) is exact at these cell centres.
        x = np.arange(21) * 10.0
        exact = 10 + 0.001 * x * (200 - x) / (2 * 100)
        np.testing.assert_allclose(result.heads[-1, 0, 1], exact, atol=1e-7, rtol=0)
        record = result.summary["water_budget"]["final_record"]
        recharge = 0.001 * 10 * 10 * 3 * 19
        self.assertAlmostEqual(record["RCHA_IN"], recharge, places=4)
        self.assertAlmostEqual(record["CHD_OUT"] - record["CHD_IN"], recharge, places=4)

    def test_transient_theis_far_from_boundaries(self):
        d = simple_case()
        d["grid"].update(nrow=101, ncol=101)
        d["boundaries"] = {"left_head_m": 10, "right_head_m": 10}
        d["initial_head_m"] = 10
        d["wells"] = [{"name": "injection", "layer": 0, "row": 50, "column": 50, "rate_m3_per_day": 100}]
        d["periods"] = [{"length_days": 0.04, "steps": 40, "transient": True}]
        result = self.run_model(d)
        # Independent Theis line-source solution for an effectively infinite,
        # confined aquifer. At r=40 m, u=.1. E1 from its convergent series,
        # not a second numerical groundwater solver. Finite grid/time expected
        # error <5%; boundaries at 500 m are far beyond diffusion scale 126 m.
        import math
        u = 0.1
        e1 = -0.5772156649015329 - math.log(u) - sum((-u)**k / (k * math.factorial(k)) for k in range(1, 30))
        exact = 100 / (4 * math.pi * 100) * e1
        numerical = result.heads[-1, 0, 50, 54] - 10
        self.assertLess(abs(numerical / exact - 1), 0.05)
        self.assertGreater(result.heads[-1, 0, 50, 54], result.heads[0, 0, 50, 54])

    def test_multilayer_demo_well_schedule_and_finite_fields(self):
        result = self.run_model(demo_case())
        self.assertEqual(result.heads.shape, (13, 3, 21, 41))
        self.assertTrue(np.isfinite(result.heads).all())
        self.assertGreater(result.heads[-1, 2, 10, 20], result.heads[0, 2, 10, 20])
        self.assertAlmostEqual(result.summary["water_budget"]["final_record"]["WEL_IN"], 100)

    def test_on_off_on_well_schedule_zero_flow_budget(self):
        d = simple_case()
        d["grid"]["delc_m"] = 20
        d["properties"].update(ky_m_per_day=30, kz_m_per_day=2)
        d["boundaries"] = {"left_head_m": 10, "right_head_m": 10}
        d["initial_head_m"] = 10
        d["wells"] = [{"name": "injection", "layer": 0, "row": 1, "column": 10, "rate_m3_per_day": 100}]
        d["periods"] = [{"length_days": 1, "steps": 1, "transient": False},
                        {"length_days": 1, "steps": 1, "transient": False, "wells": []},
                        {"length_days": 1, "steps": 1, "transient": False}]
        result = self.run_model(d)
        np.testing.assert_allclose(result.heads[1], 10, atol=1e-7, rtol=0)
        self.assertGreater(result.heads[0, 0, 1, 10], 10)
        np.testing.assert_allclose(result.heads[0], result.heads[2], atol=1e-7, rtol=0)
        self.assertTrue(result.summary["water_budget"]["gate_passed"])
        self.assertAlmostEqual(result.summary["water_budget"]["final_record"]["WEL_IN"], 100)


if __name__ == "__main__":
    unittest.main()
