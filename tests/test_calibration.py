"""Explicit contracts, independently derived fields, actual MF6 recovery/failures."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from basinlens_ccs.subsurface.calibration import (
    CalibrationError, CalibrationProblem, default_settings, load_calibration_problem,
    main, parameter_case, run_calibration, sensitivity_diagnostics, verify_calibration_bundle,
)
from basinlens_ccs.subsurface.model_workflow import UNITS, WorkflowCase

SOLVER=os.environ.get("MF6_EXE") or shutil.which("mf6")
FLOPY=importlib.util.find_spec("flopy") is not None


def canonical(data):
    return (json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+"\n").encode()


def water_case(*, transient=False):
    ncol=3 if transient else 5
    data={"schema":"basinlens-model-workflow-v1","project":{"id":"calibration-synthetic","name":"Authored analytic calibration fixture",
        "domain":"groundwater","flow_role":"background_water","units":dict(UNITS),"crs":"LOCAL:synthetic-metre",
        "vertical_datum":"synthetic-z=0","provenance":["Authored confined-water analytic calibration fixture; no observations or GMS source"]},
        "grid":{"nrow":1,"ncol":ncol,"dx_m":1.,"dy_m":1.,"x_origin_m":100.,"y_origin_m":200.,
                "rotation_degrees":0.,"row_axis":"south_to_north","layer_surfaces_m":[0.,-10.]},
        "strata":[{"id":"aquifer","name":"Synthetic aquifer","layer_indices":[0]}],
        "materials":[{"id":"sand","name":"Synthetic sand","kx_m_day":1.,"ky_m_day":1.,"kz_m_day":1.,
                      "ss_per_m":.02 if transient else 1e-5,"porosity":.25}],
        "assignments":[{"material_id":"sand","stratum_id":"aquifer","cells":[[0,0,c] for c in range(ncol)]}],
        "initial_head_m":[10.]*ncol,"periods":[{"duration_day":.1 if transient else 1.,"nsteps":2 if transient else 1,"steady":not transient}],
        "boundaries":[{"kind":"CHD","period":0,"cell":[0,0,c],"values":{"head_m":10.},"label":"fixed_head"} for c in (0,ncol-1)]}
    data["boundaries"].append({"kind":"WEL","period":0,"cell":[0,0,ncol//2],"values":{"rate_m3_day":-10.},"label":"known_extraction"})
    return WorkflowCase.from_dict(data)


def observations(case, *, transient=False, flat=False, withheld_offset=0):
    # Independent finite-volume steady result: K=4, thickness10 => each faceC40.
    # Q=-10, twoequal2facepaths => centraldrawdown.25; adjacentdrawdown.125.
    rows=[("train-left",1.,[0,0,1],9.875),("train-middle",1.,[0,0,2],9.75),("withheld-right",1.,[0,0,3],9.875+withheld_offset)]
    if transient:
        # Ss=.05, volume10, dt.05 => storageconductance10. EachendC10.
        # ImplicitEuler: h1=10-10/30=29/3; h2=(10*h1+200-10)/30=86/9.
        rows=[("train-early",.05,[0,0,1],29/3),("withheld-late",.1,[0,0,1],86/9+withheld_offset)]
    if flat:rows=[("fixed",1.,[0,0,0],10.)]
    return {"schema":"basinlens-head-observations-v1","project_id":case.to_dict()["project"]["id"],
            "case_sha256":hashlib.sha256(canonical(case.to_dict())).hexdigest(),"crs":case.to_dict()["project"]["crs"],
            "vertical_datum":case.to_dict()["project"]["vertical_datum"],"units":{"head":"m","time":"day"},
            "observations":[{"id":oid,"time_day":t,"cell":cell,"head_m":head,"sigma_m":.01,
                "basis":"synthetic","provenance":"Authored independent finite-volume/backward-Euler calculation; not field data"} for oid,t,cell,head in rows]}


def problem(*,transient=False,flat=False,withheld_offset=0):
    case=water_case(transient=transient)
    obs=observations(case,transient=transient,flat=flat,withheld_offset=withheld_offset)
    p={"id":"ss" if transient else "Kx","material_id":"sand","field":"ss_per_m" if transient else "kx_m_day",
       "unit":"1/m" if transient else "m/day","lower":.005 if transient else .5,"upper":.09 if transient else 8.,
       "initial":.02 if transient else 1.,"scale":"log","prior":None}
    train=[row["id"] for row in obs["observations"] if not row["id"].startswith("withheld")]
    held=[row["id"] for row in obs["observations"] if row["id"].startswith("withheld")]
    settings=default_settings([p],train,withheld_ids=held)
    if flat:p["prior"]={"value":4.,"sigma":.01,"unit":"m/day"}
    return CalibrationProblem.from_documents(case,obs,settings)


class CalibrationContractTests(unittest.TestCase):
    def test_immutable_documents_exact_source_copy_and_parameter_only_edit(self):
        p=problem();case,obs,settings=p.documents()
        original=case.to_dict();old_obs=copy.deepcopy(obs)
        trial=parameter_case(case,settings["parameters"],[4.])
        self.assertEqual(case.to_dict(),original)
        self.assertEqual(obs,old_obs)
        changed=trial.to_dict();changed["materials"][0]["kx_m_day"]=1.
        self.assertEqual(changed,original)
        settings["parameters"][0]["initial"]=2
        self.assertEqual(p.documents()[2]["parameters"][0]["initial"],1.)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name,raw in (("case",p.case_document),("obs",p.observations_document),("settings",p.settings_document)):(root/name).write_bytes(raw)
            loaded=load_calibration_problem(root/"case",root/"obs",root/"settings")
            self.assertEqual(loaded,p)

    def test_source_hash_crs_datum_time_units_support_and_duplicate_observations_rejected(self):
        p=problem();c,o,s=p.documents()
        for mutate in (lambda d:d.update(case_sha256="0"*64),lambda d:d.update(crs="other"),lambda d:d.update(vertical_datum="other"),
                       lambda d:d["units"].update(head="ft"),lambda d:d["observations"][0].update(time_day=.5),
                       lambda d:d["observations"][0].update(cell=[0,0,999]),lambda d:d["observations"][0].update(sigma_m=0),
                       lambda d:d["observations"].append(copy.deepcopy(d["observations"][0]))):
            oo=copy.deepcopy(o);mutate(oo)
            with self.subTest(obs=oo),self.assertRaises(CalibrationError):CalibrationProblem.from_documents(c,oo,s)

    def test_parameter_bounds_initial_units_prior_unknown_fields_and_budgets_rejected(self):
        p=problem();c,o,s=p.documents()
        for mutate in (lambda d:d.update(extra=1),lambda d:d.update(max_evaluations=True),lambda d:d.update(max_evaluations=101),
                       lambda d:d.update(max_evaluations=2),lambda d:d.update(fd_step_fraction=0),lambda d:d.update(max_total_seconds=0),
                       lambda d:d["parameters"][0].update(lower=0),lambda d:d["parameters"][0].update(upper=.4),
                       lambda d:d["parameters"][0].update(initial=2),lambda d:d["parameters"][0].update(unit="m2"),
                       lambda d:d["parameters"][0].update(scale="automatic"),lambda d:d["parameters"][0].update(prior={"value":4,"sigma":0,"unit":"m/day"}),
                       lambda d:d["parameters"].append(copy.deepcopy(d["parameters"][0])),lambda d:d["parameters"][0].update(field="porosity")):
            ss=copy.deepcopy(s);mutate(ss)
            with self.subTest(settings=ss),self.assertRaises(CalibrationError):CalibrationProblem.from_documents(c,o,ss)

    def test_every_observation_assigned_once_withheld_disjoint_and_training_nonempty(self):
        c,o,s=problem().documents()
        for update in ({"training_ids":[]},{"withheld_ids":[]},{"withheld_ids":["train-left","withheld-right"]},
                       {"training_ids":["missing"]},{"training_ids":["train-left","train-left"]}):
            ss={**s,**update}
            with self.assertRaises(CalibrationError):CalibrationProblem.from_documents(c,o,ss)

    def test_pure_sensitivity_rank_flat_collinear_and_identifiable(self):
        self.assertTrue(sensitivity_diagnostics([[1,0],[0,2]])["locally_identifiable"])
        self.assertFalse(sensitivity_diagnostics([[0],[0]])["locally_identifiable"])
        self.assertFalse(sensitivity_diagnostics([[1,2],[2,4]])["locally_identifiable"])
        self.assertFalse(sensitivity_diagnostics([[1,0],[0,0]])["locally_identifiable"])
        self.assertFalse(sensitivity_diagnostics([[1e-9]])["locally_identifiable"])
        self.assertFalse(sensitivity_diagnostics([[1]])["priors_used_in_rank"])
        for bad in ([[True]],[[1,True],[2,3]],[[1e308]],[[float("nan")]],[[1,2]],[[[1]]]):
            with self.assertRaises(CalibrationError):sensitivity_diagnostics(bad)

    def test_duplicate_nonfinite_direct_document_and_symlink_fifo_refused(self):
        p=problem()
        for raw in (b'{"schema":1,"schema":2}',b'{"x":NaN}',b'{"x":1e9999}',b'['*2000):
            with self.assertRaises(CalibrationError):CalibrationProblem(raw,p.observations_document,p.settings_document)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/"case";path.write_bytes(p.case_document)
            (root/"link").symlink_to(path)
            with self.assertRaises(CalibrationError):load_calibration_problem(root/"link",path,path)
            if hasattr(os,"mkfifo"):
                os.mkfifo(root/"fifo")
                with self.assertRaises(CalibrationError):load_calibration_problem(root/"fifo",path,path)

    def test_nonregular_inventory_artifact_and_unresolved_bounds_refused(self):
        from basinlens_ccs.subsurface.calibration import _inventory
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            if hasattr(os,"mkfifo"):
                os.mkfifo(root/"extra-fifo")
                with self.assertRaisesRegex(CalibrationError,"nonregular"):_inventory(root)
        c,o,s=problem().documents();s["parameters"][0].update(lower=1.,upper=1.+2e-16)
        with self.assertRaises(CalibrationError):CalibrationProblem.from_documents(c,o,s)

    def test_missing_executable_never_downloads_or_creates_output(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"run"
            with self.assertRaisesRegex(CalibrationError,"unavailable"):run_calibration(problem(),out,exe_name="definitely-no-mf6-basinlens")
            self.assertFalse(out.exists())

    def test_expired_total_deadline_retains_failure_sources_without_starting_model(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"expired"
            with patch("basinlens_ccs.subsurface.calibration.time.monotonic",side_effect=[0.,301.]),patch("basinlens_ccs.subsurface.calibration.run_workflow",side_effect=AssertionError("unexpected solve")):
                with self.assertRaisesRegex(CalibrationError,"time budget exhausted"):
                    run_calibration(problem(),out,exe_name=sys.executable)
            result=json.loads((out/"result.json").read_text())
            self.assertEqual(result["evaluations_consumed"],0)
            self.assertEqual(verify_calibration_bundle(out)["status"],"failed")
            self.assertTrue((out/"source/observations.json").is_file())

    def test_interruption_records_attempt_and_preserves_reviewable_failure(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"interrupted"
            with patch("basinlens_ccs.subsurface.calibration.run_workflow",side_effect=KeyboardInterrupt("explicit test interruption")):
                with self.assertRaises(KeyboardInterrupt):run_calibration(problem(),out,exe_name=sys.executable)
            result=json.loads((out/"result.json").read_text())
            self.assertEqual(result["evaluations_consumed"],1)
            self.assertEqual(result["failed_evaluations"],1)
            self.assertEqual(json.loads((out/"evaluations/0001.json").read_text())["error"]["type"],"KeyboardInterrupt")
            verified=verify_calibration_bundle(out)
            self.assertFalse(verified["native_residuals_recomputed"])
            self.assertEqual(verified["completed_native_evaluations_recomputed"],0)

    def test_fit_never_starts_on_check_or_existing_output(self):
        p=problem()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=[]
            for name,raw in (("case.json",p.case_document),("obs.json",p.observations_document),("settings.json",p.settings_document)):
                path=root/name;path.write_bytes(raw);paths.append(str(path))
            with patch("basinlens_ccs.subsurface.calibration.run_workflow",side_effect=AssertionError("unexpected solver")):
                self.assertEqual(main(["check",*paths]),0)
            command=[sys.executable,"-m","basinlens_ccs.subsurface.calibration","check",*paths]
            actual=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertFalse(json.loads(actual.stdout)["solver_executed"])


@unittest.skipUnless(SOLVER and FLOPY,"Actual MF6 + FloPy required for calibration numerical checks")
class CalibrationActualMF6Tests(unittest.TestCase):
    def test_actual_analytic_known_conductivity_recovery_and_withheld_prediction(self):
        p=problem();before=(p.case_document,p.observations_document,p.settings_document)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"fit"
            result=run_calibration(p,out,exe_name=SOLVER)
            self.assertAlmostEqual(result["best_parameters"]["Kx"],4.,delta=.01)
            self.assertLess(result["training"]["rmse_m"],.0002)
            self.assertLess(result["withheld"]["rmse_m"],.0002)
            self.assertEqual(result["withheld"]["count"],1)
            self.assertEqual(result["failed_evaluations"],0)
            self.assertLessEqual(result["evaluations_consumed"],40)
            self.assertTrue(result["initial_sensitivity"]["locally_identifiable"])
            self.assertTrue(result["final_sensitivity"]["locally_identifiable"])
            self.assertEqual(verify_calibration_bundle(out)["evaluations_verified"],result["evaluations_consumed"])
            self.assertEqual((p.case_document,p.observations_document,p.settings_document),before)
            with self.assertRaises(CalibrationError):run_calibration(p,out,exe_name=SOLVER)
            # Rehashing an altered sensitivity report cannot bypass the
            # independent native-probe Jacobian/rank recomputation.
            from basinlens_ccs.subsurface.calibration import _inventory
            original_result=(out/"result.json").read_bytes()
            original_manifest=(out/"manifest.json").read_bytes()
            changed=json.loads(original_result);changed["final_sensitivity"]["jacobian"]=[[0.],[0.]]
            (out/"result.json").write_bytes(canonical(changed))
            changed_manifest=json.loads(original_manifest);changed_manifest["files"]=_inventory(out)
            (out/"manifest.json").write_bytes(canonical(changed_manifest))
            with self.assertRaisesRegex(CalibrationError,"sensitivity/rank"):verify_calibration_bundle(out)
            for mutate in (lambda d:d["initial_sensitivity"].update(reference_coordinates=[True]),
                           lambda d:d["final_sensitivity"]["probes"][0].update(lower_evaluation=True),
                           lambda d:d["initial_sensitivity"].update(reference_coordinates=[.9])):
                changed=json.loads(original_result);mutate(changed)
                (out/"result.json").write_bytes(canonical(changed))
                changed_manifest=json.loads(original_manifest);changed_manifest["files"]=_inventory(out)
                (out/"manifest.json").write_bytes(canonical(changed_manifest))
                with self.assertRaises(CalibrationError):verify_calibration_bundle(out)
            (out/"result.json").write_bytes(original_result);(out/"manifest.json").write_bytes(original_manifest)
            (out/"unregistered-empty-dir").mkdir()
            with self.assertRaisesRegex(CalibrationError,"inventory"):verify_calibration_bundle(out)
            (out/"unregistered-empty-dir").rmdir()
            # One corrupted native head is detected by the total bundle inventory.
            target=next((out/"runs").glob("*/native/flow.hds"))
            target.write_bytes(target.read_bytes()+b"tampered")
            with self.assertRaises(CalibrationError):verify_calibration_bundle(out)

    def test_actual_transient_specific_storage_recovery_and_withheld_later_time(self):
        with tempfile.TemporaryDirectory() as td:
            result=run_calibration(problem(transient=True),Path(td)/"fit",exe_name=SOLVER)
            self.assertAlmostEqual(result["best_parameters"]["ss"],.05,delta=.0005)
            self.assertLess(result["training"]["rmse_m"],.0003)
            self.assertLess(result["withheld"]["rmse_m"],.0005)
            self.assertEqual(result["withheld"]["rows"][0]["time_day"],.1)

    def test_actual_flat_fixed_head_data_rejected_even_with_strong_prior(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"flat"
            with self.assertRaisesRegex(CalibrationError,"unidentifiable/flat"):run_calibration(problem(flat=True),out,exe_name=SOLVER)
            result=json.loads((out/"result.json").read_text())
            self.assertEqual(result["status"],"failed")
            self.assertEqual(result["evaluations_consumed"],3)
            self.assertFalse((out/"fitted_case.json").exists())
            self.assertEqual(verify_calibration_bundle(out)["status"],"failed")
            diagnostics=[json.loads(path.read_text()) for path in sorted((out/"checkpoints").iterdir())]
            sensitivity=next(row for row in diagnostics if row["event"]=="initial_sensitivity")
            self.assertEqual(sensitivity["rank"],0)
            self.assertFalse(sensitivity["priors_used_in_rank"])

    def test_actual_invalid_confined_support_failure_retains_completed_native_diagnostics(self):
        c,o,s=problem().documents()
        d=c.to_dict();d["materials"][0]["kx_m_day"]=.001;c=WorkflowCase.from_dict(d)
        o["case_sha256"]=hashlib.sha256(canonical(c.to_dict())).hexdigest()
        s["parameters"][0].update(initial=.001,lower=.0005)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"invalid-support"
            with self.assertRaisesRegex(CalibrationError,"initial solver evaluation failed"):
                run_calibration(CalibrationProblem.from_documents(c,o,s),out,exe_name=SOLVER)
            record=json.loads((out/"evaluations/0001.json").read_text())
            self.assertIn("confined-support gates",record["error"]["message"])
            self.assertTrue((out/"runs/0001/native/flow.hds").is_file())
            self.assertEqual(verify_calibration_bundle(out)["evaluations_verified"],1)

    def test_actual_withheld_offset_changes_metrics_without_changing_optimum(self):
        # Huge withheld mismatch never drives optimization. Independent analytic
        # optimum remainsK4; only the withheld residual reports the added3m.
        with tempfile.TemporaryDirectory() as td:
            result=run_calibration(problem(withheld_offset=3),Path(td)/"fit",exe_name=SOLVER)
            self.assertAlmostEqual(result["best_parameters"]["Kx"],4.,delta=.01)
            self.assertAlmostEqual(result["withheld"]["rmse_m"],3.,delta=.001)
            self.assertLess(result["training"]["rmse_m"],.0002)

    def test_failed_solver_attempts_are_counted_retained_and_fresh_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch("basinlens_ccs.subsurface.calibration.run_workflow",side_effect=RuntimeError("injected native launch failure")):
                with self.assertRaisesRegex(CalibrationError,"initial solver evaluation failed"):
                    run_calibration(problem(),root/"failed",exe_name=SOLVER)
            result=json.loads((root/"failed/result.json").read_text())
            self.assertEqual(result["evaluations_consumed"],1)
            record=json.loads((root/"failed/evaluations/0001.json").read_text())
            self.assertEqual(record["status"],"failed")
            self.assertEqual(record["error"]["message"],"injected native launch failure")
            self.assertEqual(verify_calibration_bundle(root/"failed")["evaluations_verified"],1)
            # A fresh diagnostic correction is run with a small total budget; all
            # sensitivity/evaluation attempts remain included in that budget.
            p=problem();c,o,s=p.documents();s["max_evaluations"]=12
            recovered=run_calibration(CalibrationProblem.from_documents(c,o,s),root/"recovered",exe_name=SOLVER)
            self.assertLessEqual(recovered["evaluations_consumed"],12)
            self.assertEqual(recovered["status"],"completed")
            self.assertEqual(recovered["stop_reason"],"evaluation_budget")


if __name__=="__main__":unittest.main()
