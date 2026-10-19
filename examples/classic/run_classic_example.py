"""Execute authored confined-water examples; no GMS or multiphase equivalence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.classic import (export_classic, read_classic_results,
                                             verify_classic_roundtrip)
from basinlens_ccs.subsurface.model_workflow import load_workflow_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mf2005-exe", type=Path, required=True)
    parser.add_argument("--mfnwt-exe", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    examples = Path(__file__).resolve().parents[1] / "workflow"
    records = []
    for engine, exe in (("mf2005", args.mf2005_exe), ("mfnwt", args.mfnwt_exe)):
        for filename in ("layered_background_water.json", "head_dependent_water.json"):
            source = examples / filename
            source_bytes = source.read_bytes()
            name = engine + "-" + source.stem
            case = load_workflow_case(source)
            exported = export_classic(case, output / (name + "-inputs"), engine=engine)
            receipt = verify_classic_roundtrip(exported, output / (name + "-roundtrip"),
                                               exe_name=exe, timeout_seconds=60)
            if receipt["numerical_roundtrip_passed"] is not True:
                raise RuntimeError("Actual native roundtrip failed; artifacts retained")
            result = read_classic_results(output / (name + "-roundtrip/original-run"))
            with (output / (name + "-heads.csv")).open("x", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_day", "layer", "south_to_north_row", "column", "head_m"])
                for t, time in enumerate(result.times_day):
                    for k in range(case.shape[0]):
                        for row in range(case.shape[1]):
                            for col in range(case.shape[2]):
                                writer.writerow([float(time), k, row, col, float(result.heads_m[t,k,row,col])])
            if source.read_bytes() != source_bytes:
                raise RuntimeError("Original synthetic fixture changed")
            records.append({"engine": engine, "case": filename,
                            "case_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "source_unchanged": True, "roundtrip": receipt,
                            "summary": result.summary})
    receipt = {"schema": "basinlens-classic-example-v1", "cases": records,
               "actual_native_runs": sum(r["roundtrip"]["native_runs_completed"] for r in records),
               "all_passed": all(r["roundtrip"]["numerical_roundtrip_passed"] for r in records),
               "gms_parity_established": False, "co2_or_oil_multiphase_physics": False}
    (output / "example.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"actual_native_runs": receipt["actual_native_runs"],
                      "all_passed": receipt["all_passed"]}))


if __name__ == "__main__":
    main()
