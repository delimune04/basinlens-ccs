"""Generate ORIGINAL analytic fixtures; this never runs or emulates GMS.

Usage: PYTHONPATH=src python examples/parity/generate_synthetic.py build/parity-demo
Then: python -m basinlens_ccs.parity compare build/parity-demo/reference.json
      build/parity-demo/candidate.json --output build/parity-demo/comparison.json

The reference is independently expressed as h(x) = 12 - 0.1*x at x=0,10,20 m.
Candidate values are an explicit hand-calculated vector. This checks interchange,
alignment and evidence handling, not a numerical solver or GMS equivalence.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess

import numpy as np

from basinlens_ccs.parity import artifact_record, input_fingerprint


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    physical_case = {"classification": "original synthetic analytic fixture", "equation": "h(x) = 12 - 0.1*x",
                     "x_m": [0, 10, 20], "head_m": [12, 11, 10],
                     "assumption": "steady constant-conductivity 1D confined flow; no source"}
    write_json(destination / "physical_case.json", physical_case)
    input_record = artifact_record(destination / "physical_case.json")
    with (destination / "reference.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_index", "layer", "row", "column", "head"])
        for col, x in enumerate(physical_case["x_m"]):
            writer.writerow([0, 0, 0, col, 12 - 0.1 * x])
    np.savez(destination / "candidate.npz", head=np.array([[[[12.0, 11.0, 10.0]]]]))
    source_path = Path(__file__).resolve()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_path.parent,
                                check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Run from a Git checkout so fixture history has a real commit") from exc
    common = {
        "schema_version": 1,
        "source": {"kind": "synthetic", "system": "Original analytic fixture",
                   "system_version": "1", "description": "Not an observed GMS result"},
        "engine": {"name": "independent analytic arithmetic", "version": "1",
                   "executable_sha256": artifact_record(source_path)["sha256"]},
        "implementation": {"git_commit": commit}, "inputs": [input_record],
        "exact_run_inputs_sha256": input_fingerprint([input_record]),
        "comparison_input": input_record,
        "coordinates": {"crs": "local Cartesian", "vertical_datum": "synthetic local zero",
                        "length_unit": "m", "time_unit": "day"},
        "geometry": {"kind": "rectilinear", "shape": [1, 1, 3], "origin_xy": [0, 0],
                     "rotation_degrees": 0, "x_edges": [-5, 5, 15, 25], "y_edges": [0, 10],
                     "top": [[0, 0, 0]], "bottoms": [[[-10, -10, -10]]]},
        "times": [1],
        "outputs": {"head": {"key": "head", "unit": "m", "quantity": "hydraulic_head",
                             "support": "cell", "sign_convention": "elevation positive upward"}}}
    for role, suffix in (("reference", "csv"), ("candidate", "npz")):
        manifest = dict(common, dataset_id="synthetic-linear-" + role,
                        data=dict(artifact_record(destination / f"{role}.{suffix}"), format=suffix))
        write_json(destination / f"{role}.json", manifest)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    print(generate(parser.parse_args().destination))
