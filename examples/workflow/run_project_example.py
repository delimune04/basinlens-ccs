"""Save, relocate, reload, export and roundtrip an original synthetic water model.

Use --exe /absolute/path/to/mf6 to run both native decks and export verified heads.
The default performs no numerical run or solver download.
"""
import argparse
import csv
import json
from pathlib import Path

from basinlens_ccs.subsurface.model_workflow import (
    load_workflow_case, preview_grid, export_workflow, verify_workflow_roundtrip,
    read_workflow_results,
)
from basinlens_ccs.subsurface.workflow_project import (
    save_workflow_project, open_workflow_project, verify_workflow_project_roundtrip,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", default=None)
    args = parser.parse_args(argv)
    root = args.output.absolute()
    if root.exists() or root.is_symlink():
        parser.error("Choose a fresh output directory")
    root.mkdir(parents=True, exist_ok=False)
    case = load_workflow_case(Path(__file__).with_name("layered_background_water.json"))
    view = {"selected_layer": 1, "selected_field": "hydraulic_conductivity_x",
            "chart_mode": "3d", "show_wells": True}
    package = save_workflow_project(case, root / "synthetic.blproj", view_state=view)
    loaded = open_workflow_project(package, root / "relocated")
    if loaded.case != case or loaded.view_state != view:
        raise RuntimeError("Reload changed model or view state")
    package_receipt = verify_workflow_project_roundtrip(package)
    export = export_workflow(loaded.case, root / "native-export")
    native_receipt = verify_workflow_roundtrip(export, root / "native-roundtrip", exe_name=args.exe)
    if args.exe is not None and native_receipt.get("numerical_roundtrip_passed") is not True:
        raise RuntimeError("Native numerical roundtrip failed; receipt and outputs retained for diagnosis")
    receipt = {"schema": "basinlens-workflow-example-v1", "synthetic_input": True,
        "package_roundtrip": package_receipt, "native_roundtrip": native_receipt,
        "original_gms_comparison_performed": False, "whole_gms_complete": False,
        "co2_or_oil_multiphase_physics": False}
    if args.exe is not None:
        result = read_workflow_results(root / "native-roundtrip/original-run")
        if not all(result.summary[k] for k in ("water_balance_passed", "boundary_rates_passed",
                                               "confined_saturation_support_passed")):
            raise RuntimeError("Numerical validation gate failed; outputs retained for diagnosis")
        cells = preview_grid(loaded.case)["cells"]
        with (root / "heads.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_day", "layer", "row", "column", "x_m", "y_m", "head_m"])
            for time, heads in zip(result.times_day, result.heads_m):
                for cell, head in zip(cells, heads.ravel()):
                    writer.writerow([time, cell["layer"], cell["row"], cell["column"],
                                     cell["x_m"], cell["y_m"], float(head)])
        receipt["numerical_result"] = result.summary
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
