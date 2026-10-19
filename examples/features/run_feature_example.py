"""Run authored local/GeoJSON vector roundtrips; outputs are fresh and synthetic."""
import argparse
import json
from pathlib import Path

from basinlens_ccs.subsurface.features import (
    contains_point, export_geojson, feature_metrics, grid_extent, import_geojson,
    load_coverage, move_node, save_coverage, to_scatter_points, verify_coverage_roundtrip,
)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parent
    case=load_coverage(root/'local_coverage.json')
    saved=save_coverage(case,args.output/'local.json')
    moved=move_node(case,'b',12,0)
    save_coverage(moved,args.output/'edited.json')
    geographic=load_coverage(root/'wgs84_coverage.json')
    geo=export_geojson(geographic,args.output/'wgs84.geojson')
    restored=import_geojson(geo)
    if restored.to_dict()!=geographic.to_dict():raise RuntimeError('GeoJSON semantic roundtrip failed')
    receipt={'validation_level':'authored synthetic geometry; original GMS comparison NOT_OBSERVED',
             'local_roundtrip':verify_coverage_roundtrip(saved),
             'geojson_exact_noding_metadata_roundtrip':True,
             'polygon':feature_metrics(case,'aquifer'),'arc':feature_metrics(case,'river'),
             'inside_region':contains_point(case,'aquifer',1,1),
             'inside_hole':contains_point(case,'aquifer',5,5),
             'grid_frame':grid_extent(case,padding_m=2),
             'scatter':to_scatter_points(case,value_attribute='head_m',sampling='arc_vertices')}
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
