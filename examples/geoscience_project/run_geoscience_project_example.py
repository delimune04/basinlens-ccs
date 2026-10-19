"""Actual mixed typed-object save/relocate/open/re-save, without solver execution."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import argparse

import numpy as np

from basinlens_ccs.subsurface.geoscience_project import (
    ProjectObject, archive_analysis_bundle, open_geoscience_project,
    save_geoscience_project, verify_geoscience_project_roundtrip,
)
from basinlens_ccs.subsurface.schema import SubsurfaceProject, load_project
from basinlens_ccs.subsurface.geology import load_geology
from basinlens_ccs.subsurface.scatter import load_scatter
from basinlens_ccs.subsurface.features import load_coverage
from basinlens_ccs.subsurface.mesh import structured_mesh
from basinlens_ccs.subsurface.raster import load_raster
from basinlens_ccs.subsurface.pointcloud import load_pointcloud
from basinlens_ccs.subsurface.surfaces import load_surfaces
from basinlens_ccs.subsurface.analysis import AnalysisVolume, write_analysis_bundle
from basinlens_ccs.subsurface.model_workflow import load_workflow_case


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute(); output.mkdir(parents=True, exist_ok=False)
    inputs = [root / name for name in (
        "examples/geoscience_project/project.json", "examples/geoscience_project/scatter.json",
        "examples/geology/synthetic_boreholes.json", "examples/geology/assets/synthetic_notes.txt",
        "examples/features/local_coverage.json", "examples/raster/linear_head.json",
        "examples/pointcloud/synthetic_points.json", "examples/surfaces/tilted_planes.json",
        "examples/workflow/layered_background_water.json")]
    inputs += [Path(__file__), root / "src/basinlens_ccs/subsurface/geoscience_project.py"]
    before = {str(path.relative_to(root)): sha(path) for path in inputs}
    base = load_project(root / "examples/geoscience_project/project.json", check_assets=False)
    mesh = structured_mesh([0., 1., 3.], [0., 2., 5.], crs="unknown")
    view = {"selected_layer": 1, "selected_field": "porosity", "chart_mode": "3d", "show_wells": False}
    with tempfile.TemporaryDirectory(prefix="basinlens-example-original-assets-") as temporary:
        assets = Path(temporary)
        shutil.copytree(root / "examples/geology/assets", assets / "assets")
        geology = load_geology(root / "examples/geology/synthetic_boreholes.json", asset_root=assets).project
        objects = [ProjectObject("geology", "boreholes", geology),
                   ProjectObject("scatter", "samples", load_scatter(root / "examples/geoscience_project/scatter.json")),
                   ProjectObject("features", "coverage", load_coverage(root / "examples/features/local_coverage.json")),
                   ProjectObject("mesh", "mesh", mesh)]
        original = save_geoscience_project(base, objects, output / "mixed.blproj",
            object_asset_roots={"boreholes": assets}, view_state=view)
    # The original dependency root is now gone. Restore only from copied archive.
    relocated = output / "relocated.blproj"; shutil.copyfile(original, relocated)
    loaded = open_geoscience_project(relocated, output / "restored")
    repacked = save_geoscience_project(loaded.project, loaded.objects, output / "repacked.blproj",
                                     asset_root=loaded.asset_root, view_state=loaded.view_state)
    if original.read_bytes() != repacked.read_bytes():
        raise RuntimeError("Mixed save/relocate/re-save archive bytes differ")
    main_receipt = verify_geoscience_project_roundtrip(relocated)
    additional = {}
    # The existing authored fixtures declare DIFFERENT coordinate contracts.
    # Each gets its own explicitly matching base project; no source is retagged.
    extras = [("raster", load_raster(root / "examples/raster/linear_head.json")),
              ("pointcloud", load_pointcloud(root / "examples/pointcloud/synthetic_points.json")),
              ("surfaces", load_surfaces(root / "examples/surfaces/tilted_planes.json"))]
    for kind, value in extras:
        spatial = value.to_dict()["metadata"] if kind == "pointcloud" else value.to_dict()
        data = base.to_dict(); data["spatial_reference"].update(crs=spatial["crs"], vertical_datum=spatial["vertical_datum"])
        matching = SubsurfaceProject.from_dict(data)
        path = save_geoscience_project(matching, [ProjectObject(kind, "authored", value)], output / (kind + ".blproj"))
        restored = open_geoscience_project(path, output / (kind + "-restored"))
        if restored.objects[0].value.to_dict() != value.to_dict():
            raise RuntimeError("Typed canonical source changed: " + kind)
        additional[kind] = verify_geoscience_project_roundtrip(path)
    case = load_workflow_case(root / "examples/workflow/layered_background_water.json")
    volume = AnalysisVolume.from_arrays(case, [1.], np.ones((1, *case.shape))*12.,
                                       provenance="Authored analysis archive fixture; no solver or observations")
    bundle = write_analysis_bundle(volume.clip(), output / "original-analysis")
    archived = archive_analysis_bundle(bundle)
    original_files = {name: hashlib.sha256(raw).hexdigest() for name, raw in archived.files.items()}
    data = base.to_dict(); data["spatial_reference"].update(crs=case.to_dict()["project"]["crs"], vertical_datum=case.to_dict()["project"]["vertical_datum"])
    path = save_geoscience_project(SubsurfaceProject.from_dict(data), [ProjectObject("analysis_archive", "authored", archived)], output / "analysis.blproj")
    shutil.rmtree(bundle)
    restored = open_geoscience_project(path, output / "analysis-restored")
    if restored.objects[0].value.files != archived.files:
        raise RuntimeError("Original inert analysis file bytes changed")
    additional["analysis_archive"] = {**verify_geoscience_project_roundtrip(path), "original_file_sha256": original_files,
                                      "live_engine_state_restored": False}
    after = {str(path.relative_to(root)): sha(path) for path in inputs}
    if before != after:
        raise RuntimeError("Original source fixture/code bytes changed")
    artifacts = {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": sha(path)}
                 for path in sorted(output.rglob("*")) if path.is_file()}
    receipt = {"schema": "basinlens-geoscience-project-example-v1", "input_sha256": before,
               "original_inputs_unchanged": True, "mixed_roundtrip": main_receipt,
               "additional_matching_contract_projects": additional, "artifacts": artifacts,
               "scope": "Unknown metadata labels stay unknown; no spatial registration or object-to-model mapping; incompatible fixtures use separate explicitly matching projects",
               "solver_executed": False, "gms_parity_established": False}
    (output / "example.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(output), "mixed_objects": main_receipt["object_count"],
                      "additional_project_kinds": list(additional), "original_inputs_unchanged": True,
                      "example_receipt_sha256": sha(output / "example.json")}))


if __name__ == "__main__": main()
