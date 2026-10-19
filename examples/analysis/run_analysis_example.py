"""Run actual synthetic MF6 water flow and export source-bound analyses."""
import argparse
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.analysis import load_analysis_run, verify_analysis_bundle, write_analysis_bundle
from basinlens_ccs.subsurface.model_workflow import load_workflow_case, run_workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", default="mf6")
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    case_path = Path(__file__).resolve().parents[1] / "workflow/layered_background_water.json"
    case = load_workflow_case(case_path)
    native = run_workflow(case, output / "water-run", exe_name=args.exe)
    volume = load_analysis_run(native.workspace)
    section = volume.section([[105., 210.], [145., 210.]], [-5., -20.], 5., time_day=1.)
    clip = volume.clip(time_day=1., scalar_min=10.5, plane=[1., 0., 0., -120.])
    observations = {
        "schema": "basinlens-head-observations-v1", "project_id": case.to_dict()["project"]["id"],
        "case_sha256": volume.case_sha256, "crs": case.to_dict()["project"]["crs"],
        "vertical_datum": case.to_dict()["project"]["vertical_datum"], "units": {"head": "m", "time": "day"},
        "observations": [{"id": "synthetic-head-check", "time_day": 1., "cell": [0, 0, 0],
                          "head_m": 11.5, "sigma_m": .25, "basis": "synthetic",
                          "provenance": "Authored diagnostic: prescribed model CHD is 12 m; synthetic comparison is 11.5 m, not a field measurement."}]}
    comparison = volume.compare_observations(observations)
    (output / "synthetic-observations.json").write_text(json.dumps(observations, indent=2) + "\n")
    for name, result in (("section", section), ("clip", clip), ("comparison", comparison)):
        verify_analysis_bundle(write_analysis_bundle(result, output / name))
    frames = volume.section_frames([
        {"polyline_xy_m": [[105., 210.], [145., 210.]], "z_m": [-5., -20.],
         "spacing_m": 10., "time_day": float(time)} for time in volume.times_day])
    frame_raw = (json.dumps(frames, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    (output / "section-frames.json").write_bytes(frame_raw)
    metrics = comparison["metrics"]
    if abs(metrics["rmse_m"] - .5) > 1e-10 or abs(metrics["objective_chi_square"] - 4.) > 1e-10:
        raise RuntimeError("Independent known-residual diagnostic failed")
    receipt = {"schema": "basinlens-analysis-example-v1", "source": volume.source,
               "section_rows": len(section["rows"]), "visible_clip_cells": clip["visible_cells"],
               "manual_comparison": metrics, "frame_count": frames["frame_count"],
               "frames_sha256": hashlib.sha256(frame_raw).hexdigest(),
               "scope": "authored synthetic confined water, source-bound postprocessing, known manual residual",
               "gms_parity_established": False, "field_validation_established": False}
    (output / "example.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
