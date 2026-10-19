"""Explicit actual MF6 demonstration; no run occurs when this file is imported.

PYTHONPATH=src python examples/calibration/run_example.py OUTPUT --exe /path/to/mf6
The new output retains every actual trial, original document byte and diagnostics.
"""
import argparse
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.calibration import (
    CalibrationError, load_calibration_problem, run_calibration, verify_calibration_bundle,
)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--exe",required=True)
    args=parser.parse_args()
    args.output.mkdir()
    example=Path(__file__).parent
    originals={p:p.read_bytes() for p in example.glob("*.json") if not p.name.startswith("expected_")}
    record={"schema":"basinlens-calibration-example-v1","engine":"actual MODFLOW 6 GWF",
            "truth_basis":"independently authored finite-volume and backward-Euler calculations; synthetic only",
            "original_gms_comparison":"NOT_OBSERVED","pest_implemented":False,"cases":{}}
    for name,true_parameter in (("steady",4.),("transient",.05)):
        problem=load_calibration_problem(*[example/f"{name}_{kind}.json" for kind in ("case","observations","settings")])
        result=run_calibration(problem,args.output/name,exe_name=args.exe)
        verified=verify_calibration_bundle(args.output/name)
        value=next(iter(result["best_parameters"].values()))
        assert abs(value-true_parameter)<(.01 if name=="steady" else .0005)
        assert result["withheld"]["rmse_m"]<.0005
        record["cases"][name]={"best_parameters":result["best_parameters"],"authored_truth":true_parameter,
            "training_rmse_m":result["training"]["rmse_m"],"withheld_rmse_m":result["withheld"]["rmse_m"],
            "evaluations_consumed":result["evaluations_consumed"],"failed_evaluations":result["failed_evaluations"],
            "initial_data_jacobian_rank":result["initial_sensitivity"]["rank"],"final_data_jacobian_rank":result["final_sensitivity"]["rank"],
            "engine":result["engine"],"verification":verified}
    flat=load_calibration_problem(*[example/f"flat_{kind}.json" for kind in ("case","observations","settings")])
    try:run_calibration(flat,args.output/"flat",exe_name=args.exe)
    except CalibrationError as exc:
        assert "unidentifiable/flat" in str(exc),str(exc)
    else:raise AssertionError("Fixed-head-only data must not identify conductivity")
    rejected=json.loads((args.output/"flat/result.json").read_text())
    record["cases"]["flat"]={"status":rejected["status"],"expected_rejection":"unidentifiable fixed-head-only data despite strong conductivity prior",
                              "evaluations_consumed":rejected["evaluations_consumed"],"verification":verify_calibration_bundle(args.output/"flat")}
    assert all(p.read_bytes()==raw for p,raw in originals.items())
    record["source_documents_unchanged"]=True
    record["source_sha256"]={p.name:hashlib.sha256(raw).hexdigest() for p,raw in originals.items()}
    (args.output/"receipt.json").write_text(json.dumps(record,sort_keys=True,indent=2)+"\n")
    print(json.dumps(record,sort_keys=True))


if __name__=="__main__":main()
