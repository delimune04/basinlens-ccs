"""Reproduce portable scalar data, interpolation, edits and dataset arithmetic."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface import scatter
from basinlens_ccs.subsurface.scatter import (
    dataset_math, edit_values, interpolate_idw, interpolate_nearest, interpolate_tin,
    load_scatter, save_scatter, verify_scatter_roundtrip,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        parser.error("output must not traverse symbolic links")
    root.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).resolve().parent
    dataset = load_scatter(here/"synthetic_plane.json")
    queries = json.loads((here/"queries_2d.json").read_text())
    triangles = json.loads((here/"triangles.json").read_text())
    source_hash = hashlib.sha256((here/"synthetic_plane.json").read_bytes()).hexdigest()
    save_scatter(dataset, root/"points.csv")
    relocated = load_scatter(root/"points.csv")
    save_scatter(relocated, root/"points.json")
    reports = {"roundtrip": verify_scatter_roundtrip(root/"points.csv"),
               "nearest": interpolate_nearest(relocated, queries),
               "idw": interpolate_idw(relocated, queries, power=2, max_neighbors=4),
               "linear_tin": interpolate_tin(relocated, queries, triangles)}
    for name, report in reports.items():
        (root/(name+".json")).write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+"\n")
    with (root/"linear_tin.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["query_index", "x_m", "y_m", "value_m", "supported", "reason"])
        for row in reports["linear_tin"]["rows"]:
            writer.writerow([row["query_index"], *row["coordinates_m"], row["value"], row["supported"], row["reason"]])
    edited = edit_values(dataset, {"p0": 2, "p1": None}, missing_reason="synthetic example: intentionally removed")
    save_scatter(edited, root/"edited.csv")
    difference = dataset_math(edited, "-", dataset, result_id="edited-minus-original", result_quantity="hydraulic_head", result_unit="m")
    save_scatter(difference, root/"difference.json")
    # Independent authored affine reference: f(x,y)=1+2*x+3*y.
    errors = [abs(row["value"]-(1+2*row["coordinates_m"][0]+3*row["coordinates_m"][1]))
              for row in reports["linear_tin"]["rows"] if row["supported"]]
    assert max(errors) < 1e-12
    assert not reports["linear_tin"]["rows"][-1]["supported"]
    assert source_hash == hashlib.sha256((here/"synthetic_plane.json").read_bytes()).hexdigest()
    receipt = {"schema": "basinlens-scatter-example-v1", "source_sha256": source_hash,
               "scatter_module_sha256": hashlib.sha256(Path(scatter.__file__).read_bytes()).hexdigest(),
               "example_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "source_unchanged": True, "dataset_sha256": dataset.sha256,
               "max_affine_tin_absolute_error_m": max(errors),
               "unsupported_query_preserved": True, "original_gms_comparison": "not_performed",
               "files": {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(root.iterdir())}}
    (root/"receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"output": str(root), "max_affine_tin_absolute_error_m": max(errors), "files": len(receipt["files"])}))


if __name__ == "__main__":
    main()
