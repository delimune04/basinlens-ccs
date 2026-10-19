"""Synthetic workflow checks; no original GMS comparisons are claimed."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from basinlens_ccs.subsurface.model_workflow import (
    WorkflowCase, WorkflowError, UNITS, export_workflow, load_workflow_case,
    preview_grid, read_workflow_results, run_workflow, verify_workflow_export,
    verify_workflow_roundtrip,
)
from basinlens_ccs.groundwater.native_run import NativeRunError

FLOPY = importlib.util.find_spec("flopy") is not None
SOLVER = os.environ.get("MF6_EXE") or shutil.which("mf6")
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/workflow/layered_background_water.json"


def boundary(kind, cell, **values):
    return {"kind": kind, "period": 0, "cell": list(cell), "values": values, "label": "synthetic_" + kind}


def case(ncol=2, nrow=1, **changes):
    data = {"schema": "basinlens-model-workflow-v1", "project": {
        "id": "synthetic", "name": "Original synthetic water case", "domain": "groundwater",
        "flow_role": "background_water", "units": dict(UNITS), "crs": "unknown",
        "vertical_datum": "local synthetic z=0 m", "provenance": ["Synthetic analytical fixture; no field or GMS validation."]},
        "grid": {"nrow": nrow, "ncol": ncol, "dx_m": 1.0, "dy_m": 1.0,
                 "x_origin_m": 100.0, "y_origin_m": 200.0, "rotation_degrees": 0.0,
                 "row_axis": "south_to_north", "layer_surfaces_m": [0.0, -10.0]},
        "strata": [{"id": "aquifer", "name": "Synthetic aquifer", "layer_indices": [0]}],
        "materials": [{"id": "sand", "name": "Synthetic sand", "kx_m_day": 1.0,
                      "ky_m_day": 1.0, "kz_m_day": 1.0, "ss_per_m": 1e-5, "porosity": .25}],
        "assignments": [{"material_id": "sand", "stratum_id": "aquifer",
                         "cells": [[0, r, c] for r in range(nrow) for c in range(ncol)]}],
        "initial_head_m": [10.0] * (nrow * ncol),
        "periods": [{"duration_day": 1.0, "nsteps": 1, "steady": True}],
        "boundaries": [boundary("CHD", (0, r, 0), head_m=10.0) for r in range(nrow)]}
    data.update(changes)
    return WorkflowCase.from_dict(data)


class WorkflowContractTests(unittest.TestCase):
    def test_case_json_roundtrip_and_explicit_metadata(self):
        c = load_workflow_case(EXAMPLE)
        self.assertEqual(WorkflowCase.from_dict(c.to_dict()), c)
        self.assertEqual(c.shape, (2, 1, 5))
        value = c.to_dict()
        value["project"]["name"] = "changed independent copy"
        self.assertNotEqual(c.to_dict()["project"]["name"], value["project"]["name"])
        for change in ({"extra": True}, {"schema": "gms-project"}):
            with self.assertRaises(WorkflowError):
                WorkflowCase.from_dict({**c.to_dict(), **change})

    def test_invalid_units_roles_nonfinite_and_unknown_fields_rejected(self):
        mutations = [lambda d: d["project"]["units"].update(length="feet"),
            lambda d: d["project"].update(flow_role="co2"),
            lambda d: d["grid"].update(row_axis="north_to_south"),
            lambda d: d["grid"].update(rotation_degrees=5),
            lambda d: d["grid"].update(nrow=True),
            lambda d: d["grid"].update(dx_m=float("nan")),
            lambda d: d["materials"][0].update(kx_m_day=float("inf")),
            lambda d: d["materials"][0].update(ss_per_m=0),
            lambda d: d["periods"][0].update(nsteps=True),
            lambda d: d["project"].update(crs=""),
            lambda d: d["project"].update(provenance=[])]
        for mutate in mutations:
            data = case().to_dict()
            mutate(data)
            with self.subTest(data=str(data)[:100]), self.assertRaises(WorkflowError):
                WorkflowCase.from_dict(data)

    def test_complete_coverage_stratigraphy_material_and_boundary_conflicts(self):
        mutations = [lambda d: d["assignments"][0]["cells"].pop(),
            lambda d: d["assignments"][0]["cells"].append([0, 0, 0]),
            lambda d: d["assignments"][0].update(stratum_id="missing"),
            lambda d: d["assignments"][0].update(material_id="missing"),
            lambda d: d["strata"][0].update(layer_indices=[]),
            lambda d: d["boundaries"].append(boundary("WEL", (0, 0, 0), rate_m3_day=1)),
            lambda d: d["boundaries"].append(boundary("CHD", (0, 0, 0), head_m=10)),
            lambda d: d["boundaries"].append(boundary("RIV", (0, 0, 1), stage_m=10, bottom_m=11, conductance_m2_day=1)),
            lambda d: d.update(boundaries=[boundary("DRN", (0, 0, 1), elevation_m=5, conductance_m2_day=1)]),
            lambda d: d.update(boundaries=[boundary("RIV", (0, 0, 1), stage_m=10, bottom_m=5, conductance_m2_day=1)])]
        for mutate in mutations:
            data = case().to_dict()
            mutate(data)
            with self.subTest(data=str(data)[:100]), self.assertRaises(WorkflowError):
                WorkflowCase.from_dict(data)

    def test_preview_geometry_y_direction_properties_and_unknown_crs(self):
        c = case(nrow=2)
        preview = preview_grid(c)
        self.assertEqual(preview["shape"], [1, 2, 2])
        self.assertEqual([x["x_m"] for x in preview["cells"]], [100.5, 101.5, 100.5, 101.5])
        self.assertEqual([x["y_m"] for x in preview["cells"]], [200.5, 200.5, 201.5, 201.5])
        self.assertEqual(preview["crs"], "unknown")
        self.assertEqual(preview["cells"][0]["stratum_id"], "aquifer")
        self.assertEqual(preview["cells"][0]["kx_m_day"], 1.0)
        self.assertIn("native MF6 row nrow-1-r", preview["row_mapping"])

    def test_cli_numerical_roundtrip_failure_has_nonzero_exit(self):
        from basinlens_ccs.subsurface.model_workflow import main
        with patch("basinlens_ccs.subsurface.model_workflow.verify_workflow_roundtrip",
                   return_value={"numerical_roundtrip_passed": False}), patch("builtins.print"):
            with self.assertRaises(SystemExit) as error:
                main(["roundtrip", "captured-export", "--output", "fresh-output", "--exe", "mf6"])
            self.assertEqual(error.exception.code, 2)

    def test_duplicate_json_large_read_and_bad_cell_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "case.json"
            for raw in (b'{"schema":1,"schema":1}', b'{"x":1e9999}', b'x' * (8 * 1024 * 1024 + 1)):
                path.write_bytes(raw)
                with self.assertRaises(WorkflowError):
                    load_workflow_case(path)
        data = case().to_dict()
        data["assignments"][0]["cells"][0] = [0, 0, True]
        with self.assertRaises(WorkflowError):
            WorkflowCase.from_dict(data)


@unittest.skipUnless(FLOPY, "Install optional FloPy for workflow native export")
class WorkflowExportTests(unittest.TestCase):
    def test_deterministic_export_reloads_and_native_roundtrip_preserves_case(self):
        import flopy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            c = load_workflow_case(EXAMPLE)
            a, b = export_workflow(c, root / "a"), export_workflow(c, root / "b")
            self.assertEqual({p.name: p.read_bytes() for p in a.iterdir()}, {p.name: p.read_bytes() for p in b.iterdir()})
            self.assertEqual(verify_workflow_export(a), c)
            loaded = flopy.mf6.MFSimulation.load(sim_ws=str(a), verbosity_level=0)
            self.assertEqual(loaded.tdis.nper.get_data(), 2)
            self.assertEqual(loaded.get_model("flow").npf.k.array.shape, c.shape)
            receipt = verify_workflow_roundtrip(a, root / "roundtrip")
            self.assertTrue(receipt["case_metadata_preserved"])
            self.assertTrue(receipt["native_token_semantics_equal"])
            self.assertIsNone(receipt["numerical_roundtrip_passed"])
            self.assertFalse(receipt["gms_project_roundtrip"])
            self.assertEqual(verify_workflow_export(root / "roundtrip/rewritten"), c)
            with self.assertRaises(FileExistsError):
                export_workflow(c, a)

    def test_altered_settings_inputs_extra_symlinks_and_semantics_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for change in ("case", "native", "extra", "symlink", "semantics"):
                p = export_workflow(case(), root / change)
                if change in ("case", "semantics"):
                    record = json.loads((p / "settings.json").read_text())
                    if change == "case":
                        record["case"]["materials"][0]["kx_m_day"] = 2
                    else:
                        record["native_token_semantics_sha256"] = "0" * 64
                    (p / "settings.json").write_text(json.dumps(record))
                elif change == "native":
                    with (p / "flow.npf").open("a") as stream:
                        stream.write("# altered exact bytes\n")
                elif change == "extra":
                    (p / "extra.dat").write_text("extra")
                else:
                    outside = root / "outside.npf"
                    (p / "flow.npf").rename(outside)
                    (p / "flow.npf").symlink_to(outside)
                with self.subTest(change=change), self.assertRaises(WorkflowError):
                    verify_workflow_export(p)

    def test_roundtrip_metadata_mutation_is_detected_and_failed_receipt_retained(self):
        import flopy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = export_workflow(case(), root / "source")
            original_load = flopy.mf6.MFSimulation.load
            def load_then_mutate(*args, **kwargs):
                sim = original_load(*args, **kwargs)
                record = json.loads((source / "settings.json").read_text())
                record["case"]["project"]["name"] = "Changed during native reload"
                (source / "settings.json").write_text(json.dumps(record))
                return sim
            with patch.object(flopy.mf6.MFSimulation, "load", side_effect=load_then_mutate):
                with self.assertRaisesRegex(WorkflowError, "metadata changed"):
                    verify_workflow_roundtrip(source, root / "failure")
            receipt = json.loads((root / "failure/roundtrip.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["error_type"], "WorkflowError")
            self.assertNotIn("case_metadata_preserved", receipt)
            self.assertEqual(verify_workflow_export(root / "failure/rewritten"), case())

    def test_roundtrip_failure_retains_exact_rewritten_inputs_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = export_workflow(case(), root / "source")
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            with self.assertRaises(NativeRunError):
                verify_workflow_roundtrip(source, root / "failure", exe_name="no-such-workflow-mf6-executable")
            receipt = json.loads((root / "failure/roundtrip.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["error_type"], "NativeRunError")
            self.assertEqual(receipt["native_runs_completed"], 0)
            self.assertEqual(receipt["native_runs_requested"], 1)
            self.assertEqual(verify_workflow_export(root / "failure/rewritten"), case())
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)

    def test_native_rows_property_fields_boundaries_and_explicit_shutoff(self):
        import flopy
        data = case(nrow=2).to_dict()
        data["materials"].append({**data["materials"][0], "id": "silt", "ky_m_day": 3.0})
        data["assignments"] = [{"material_id": mid, "stratum_id": "aquifer", "cells": [[0, r, 0], [0, r, 1]]}
                               for r, mid in enumerate(("sand", "silt"))]
        data["initial_head_m"] = [10., 11., 12., 13.]
        data["periods"] *= 2
        data["boundaries"] = [boundary("GHB", (0, r, 0), head_m=10+r, conductance_m2_day=2.) for r in range(2)]
        data["boundaries"] += [{**b, "period": 1} for b in data["boundaries"]]
        data["boundaries"].append(boundary("WEL", (0, 0, 1), rate_m3_day=1.))
        with tempfile.TemporaryDirectory() as temporary:
            p = export_workflow(WorkflowCase.from_dict(data), Path(temporary) / "export")
            s = flopy.mf6.MFSimulation.load(sim_ws=str(p), verbosity_level=0)
            m = s.get_model("flow")
            np.testing.assert_array_equal(m.ic.strt.array[0], [[12,13],[10,11]])
            np.testing.assert_array_equal(m.npf.k22.array[0], [[3,3],[1,1]])
            self.assertEqual(tuple(m.wel.stress_period_data.get_data(0)[0]["cellid"]), (0,1,1))
            self.assertEqual(len(m.wel.stress_period_data.get_data(1)), 0)


@unittest.skipUnless(FLOPY and SOLVER, "Set MF6_EXE for actual workflow physics checks")
class WorkflowPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_case(self, c, name):
        run = run_workflow(c, self.root / name, exe_name=SOLVER)
        result = read_workflow_results(run.workspace)
        self.assertTrue(result.summary["water_balance_passed"], result.summary)
        self.assertTrue(result.summary["boundary_rates_passed"], result.summary)
        self.assertTrue(result.summary["confined_saturation_support_passed"], result.summary)
        self.assertFalse(result.summary["gms_parity_established"])
        return result

    def test_heterogeneous_harmonic_conductivity_series_solution(self):
        data = case(ncol=5).to_dict()
        data["materials"].append({**data["materials"][0], "id": "fast", "kx_m_day": 10.})
        data["assignments"] = [{"material_id": "sand", "stratum_id": "aquifer", "cells": [[0,0,i] for i in (0,1)]},
                               {"material_id": "fast", "stratum_id": "aquifer", "cells": [[0,0,i] for i in (2,3,4)]}]
        data["boundaries"].append(boundary("CHD", (0,0,4), head_m=8.))
        result = self.run_case(WorkflowCase.from_dict(data), "harmonic")
        k = np.array([1.,1.,10.,10.,10.])
        resistance = .5 / (k[:-1] * 10.) + .5 / (k[1:] * 10.)
        q = 2. / resistance.sum()
        expected = 10. - np.r_[0., np.cumsum(resistance)] * q
        np.testing.assert_allclose(result.heads_m[0,0,0], expected, rtol=0, atol=1e-8)
        self.assertAlmostEqual(result.budget["CHD(CHD)_IN"][0], q, places=7)
        self.assertAlmostEqual(result.budget["CHD(CHD)_OUT"][0], q, places=7)

    def test_ghb_recharge_well_signs_and_area_support(self):
        for rate in (-2., 2.):
            c = case(ncol=1, boundaries=[boundary("GHB", (0,0,0), head_m=10., conductance_m2_day=2.),
                boundary("WEL", (0,0,0), rate_m3_day=rate)])
            result = self.run_case(c, "well" + str(rate))
            self.assertAlmostEqual(result.heads_m[0,0,0,0], 10 + rate / 2, places=8)
        d = case(ncol=1, boundaries=[boundary("GHB", (0,0,0), head_m=10., conductance_m2_day=2.),
            boundary("RCH", (0,0,0), rate_m_day=.01)]).to_dict()
        d["grid"].update(dx_m=4.,dy_m=5.)
        result = self.run_case(WorkflowCase.from_dict(d), "recharge")
        self.assertAlmostEqual(result.heads_m[0,0,0,0], 10.1, places=8)
        self.assertAlmostEqual(result.budget["RCH(RCH)_IN"][0], .2, places=8)

    def test_drain_on_off_and_river_bottom_clipping(self):
        for name, elevation, expected in (("open",5., (10*10+2*5)/12), ("closed",11.,10.)):
            c = case(boundaries=[boundary("CHD", (0,0,0), head_m=10.),
                boundary("DRN", (0,0,1), elevation_m=elevation, conductance_m2_day=2.)])
            result = self.run_case(c, name)
            self.assertAlmostEqual(result.heads_m[0,0,0,1], expected, places=8)
            self.assertAlmostEqual(result.budget["DRN(DRN)_OUT"][0], 2*max(expected-elevation,0), places=7)
        for name, bottom, expected in (("river-linear",0.,(10*10+2*12)/12), ("river-capped",11.8,10.04)):
            c = case(boundaries=[boundary("CHD", (0,0,0), head_m=10.),
                boundary("RIV", (0,0,1), stage_m=12., bottom_m=bottom, conductance_m2_day=2.)])
            result = self.run_case(c, name)
            self.assertAlmostEqual(result.heads_m[0,0,0,1], expected, places=8)
            self.assertAlmostEqual(result.budget["RIV(RIV)_IN"][0], 2*(12-max(expected,bottom)), places=7)

    def test_stress_period_shutoff_and_implicit_storage_limit(self):
        d = case(ncol=1, boundaries=[boundary("GHB", (0,0,0), head_m=10., conductance_m2_day=2.),
            boundary("WEL", (0,0,0), rate_m3_day=-2.)]).to_dict()
        d["periods"] *= 2
        d["boundaries"].append({**d["boundaries"][0], "period": 1})
        result = self.run_case(WorkflowCase.from_dict(d), "shutoff")
        np.testing.assert_allclose(result.heads_m[:,0,0,0], [9.,10.], atol=1e-8)
        np.testing.assert_allclose(result.budget["WEL(WEL)_OUT"], [2.,0.], atol=1e-8)
        d = case(ncol=1, boundaries=[boundary("GHB", (0,0,0), head_m=10., conductance_m2_day=2.),
            boundary("WEL", (0,0,0), rate_m3_day=2.)]).to_dict()
        d["periods"] = [{"duration_day": .001, "nsteps": 2, "steady": False}]
        result = self.run_case(WorkflowCase.from_dict(d), "storage")
        h, expected = 10., []
        for _ in range(2):
            h = (.2*h + 2*10 + 2) / 2.2  # Ss*V/dt=.2 m2/day.
            expected.append(h)
        np.testing.assert_allclose(result.heads_m[:,0,0,0], expected, atol=1e-8)
        np.testing.assert_allclose(result.budget["STO-SS(STORAGE)_OUT"], .2*np.diff([10.]+expected), atol=1e-8)

    def test_physical_xy_row_mapping_and_result_binding(self):
        d = case(ncol=1,nrow=2).to_dict()
        d["boundaries"] = [boundary("CHD", (0,r,0), head_m=h) for r,h in enumerate((8.,12.))]
        result = self.run_case(WorkflowCase.from_dict(d), "rows")
        np.testing.assert_allclose(result.heads_m[0,0,:,0], [8.,12.], atol=1e-10)
        # Every returned row is in project coordinates; native files use reverse row IDs.
        import flopy
        native = flopy.utils.HeadFile(str(self.root / "rows/native/flow.hds"), precision="double")
        try:
            np.testing.assert_allclose(native.get_data()[0,:,0], [12.,8.], atol=1e-10)
        finally:
            native.close()
        with (self.root / "rows/native/flow.hds").open("ab") as stream:
            stream.write(b"altered")
        with self.assertRaises(NativeRunError):
            read_workflow_results(self.root / "rows")

    def test_equal_but_below_top_solution_does_not_pass_numerical_roundtrip(self):
        c = case(ncol=1, initial_head_m=[0.], boundaries=[
            boundary("GHB", (0,0,0), head_m=0., conductance_m2_day=1.),
            boundary("WEL", (0,0,0), rate_m3_day=-2.)])
        source = export_workflow(c, self.root / "unsupported-export")
        receipt = verify_workflow_roundtrip(source, self.root / "unsupported-roundtrip", exe_name=SOLVER)
        self.assertEqual(receipt["maximum_head_difference_m"], 0.)
        self.assertTrue(receipt["both_runs_water_balance_passed"])
        self.assertTrue(receipt["both_runs_boundary_rates_passed"])
        self.assertFalse(receipt["both_runs_confined_saturation_support_passed"])
        self.assertFalse(receipt["numerical_roundtrip_passed"])
        self.assertEqual(receipt["native_runs_completed"], 2)

    def test_full_layered_roundtrip_executes_two_identical_models(self):
        c = load_workflow_case(EXAMPLE)
        export = export_workflow(c, self.root / "export")
        receipt = verify_workflow_roundtrip(export, self.root / "roundtrip", exe_name=SOLVER)
        self.assertTrue(receipt["native_runs_performed"])
        self.assertTrue(receipt["numerical_roundtrip_passed"])
        self.assertEqual(receipt["maximum_head_difference_m"], 0.)
        self.assertEqual(receipt["maximum_budget_column_difference"], 0.)
        self.assertEqual(read_workflow_results(self.root / "roundtrip/rewritten-run").case, c)
