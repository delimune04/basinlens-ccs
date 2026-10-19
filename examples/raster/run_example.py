"""Authored constant/linear pixel-centre checks and actual file operations.

Run from repo root: PYTHONPATH=src python examples/raster/run_example.py OUTPUT
The output must be new. No original GMS, solver, or field dataset is executed.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.raster import (
    clip_raster, create_catalog, export_ascii_bundle, load_raster,
    merge_rasters, open_ascii_bundle, open_catalog, raster_to_scatter,
    resample_raster, sample_raster, save_raster, verify_roundtrip,
)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    args.output.mkdir()
    source=Path(__file__).with_name("linear_head.json")
    original=source.read_bytes()
    grid=load_raster(source)
    save_raster(grid,args.output/"captured_source.json")
    receipt=verify_roundtrip(grid)
    export_ascii_bundle(grid,args.output/"ascii")
    assert open_ascii_bundle(args.output/"ascii").to_dict()==grid.to_dict()
    points=json.loads(Path(__file__).with_name("query_points.json").read_text())
    samples=sample_raster(grid,points,method="bilinear")
    assert samples==[10.0,13.75,None],samples
    target=json.loads(Path(__file__).with_name("target_geometry.json").read_text())
    resampled=resample_raster(grid,target,method="bilinear",asset_id="linear-head-resampled")
    expected=((10.5,12.5,14.5,16.5),(7.5,9.5,11.5,13.5))
    assert resampled.values==expected
    constant=replace(grid,asset_id="constant",values=((7,7,7),(7,7,7)))
    assert resample_raster(constant,target,method="bilinear").values==((7,7,7,7),(7,7,7,7))
    save_raster(resampled,args.output/"resampled.json")
    left=clip_raster(grid,[100,200,102,204],asset_id="left")
    right=clip_raster(grid,[102,200,106,204],asset_id="right")
    assert left.extent==[100,200,102,204]
    merged=merge_rasters([left,right],conflict_policy="error",asset_id="merged")
    assert merged.values==grid.values and merged.extent==grid.extent
    save_raster(merged,args.output/"merged.json")
    create_catalog([args.output/"captured_source.json",args.output/"resampled.json",args.output/"merged.json"],args.output/"catalog.json")
    assert len(open_catalog(args.output/"catalog.json"))==3
    scatter=raster_to_scatter(grid)
    assert len(scatter["points"])==6 and scatter["points"][0]["y_m"]==203
    (args.output/"scatter.json").write_text(json.dumps(scatter,indent=2)+"\n")
    assert source.read_bytes()==original
    record={"schema":"basinlens-raster-example-v1","source_sha256":hashlib.sha256(original).hexdigest(),
            "source_unchanged":True,"roundtrip":receipt,"bilinear_query_values":samples,
            "linear_resample_exact":True,"constant_resample_exact":True,"clip_merge_values_extent_equal":True,
            "catalogue_assets_reopened":3,"scatter_valid_cells":6,"original_gms_comparison":"NOT_OBSERVED"}
    (args.output/"receipt.json").write_text(json.dumps(record,sort_keys=True,indent=2)+"\n")
    print(json.dumps(record,sort_keys=True))


if __name__=="__main__":main()
