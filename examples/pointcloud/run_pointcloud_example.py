"""Create original synthetic LAS and exercise real file/selection/grid operations."""
import argparse
import json
from pathlib import Path
import struct

from basinlens_ccs.subsurface.pointcloud import (
    aggregate_grid, filter_points, inspect_pointcloud, merge_pointclouds, read_las,
    render_points, save_pointcloud, verify_pointcloud_roundtrip, write_las,
)

METADATA = dict(crs="LOCAL:authored-planar", horizontal_unit="m", vertical_unit="m",
                vertical_datum="authored elevation zero",
                provenance=["Original synthetic six-point LAS; authored example, not survey measurements"])


def authored_las():
    # Raw XYZ * [.01,.1,.5] + [1000,2000,100].
    xyz = [(-100,0,50),(0,0,0),(100,10,-10),(100,10,10),(200,20,20),(300,30,40)]
    header = bytearray(227)
    header[:4] = b"LASF"; header[24:26] = b"\x01\x02"
    header[26:58] = b"BasinLens original synthetic".ljust(32, b"\0")
    header[58:90] = b"BasinLens example-v1".ljust(32,b"\0")
    struct.pack_into('<HII',header,94,227,227,0)
    struct.pack_into('<BHI',header,104,3,34,6)
    struct.pack_into('<5I',header,111,6,0,0,0,0)
    struct.pack_into('<3d',header,131,.01,.1,.5)
    struct.pack_into('<3d',header,155,1000,2000,100)
    struct.pack_into('<6d',header,179,1003,999,2003,2000,125,95)
    records = []
    for i,(x,y,z) in enumerate(xyz):
        records.append(struct.pack('<iiiHBBbBHd3H',x,y,z,100+i,9,2 if i in (1,2,3) else 5,0,0,1,123456.125+i,65535,i,1024))
    return bytes(header) + b''.join(records)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output;out.mkdir()
    source=out/'authored.las';source.write_bytes(authored_las())
    (out/'metadata.json').write_text(json.dumps(METADATA,indent=2)+'\n')
    cloud=read_las(source,metadata=METADATA);save_pointcloud(cloud,out/'points.json')
    ground=filter_points(cloud,classifications=[2]);other=filter_points(cloud,classifications=[5])
    save_pointcloud(ground,out/'class2.json');write_las(ground,out/'class2.las')
    merged=merge_pointclouds([ground,other]);save_pointcloud(merged,out/'merged.json')
    receipt=verify_pointcloud_roundtrip(cloud,out/'roundtrip')
    grid=aggregate_grid(cloud,x_origin=1000,y_origin=2000,dx=1,dy=1,nrow=3,ncol=3,
                        crs=METADATA['crs'],horizontal_unit='m',vertical_datum=METADATA['vertical_datum'])
    assert grid['values']==[[100.,None,None],[None,100.,None],[None,None,110.]]
    assert len(set(merged.identities))==cloud.count==6
    assert source.read_bytes()==authored_las()
    (out/'grid.json').write_text(json.dumps(grid,indent=2)+'\n')
    result=dict(inspect=inspect_pointcloud(cloud),roundtrip=receipt,render=render_points(cloud,max_points=4),
                grid_known_values_equal=True,source_unchanged=True,merged_all_identities_retained=True)
    (out/'example_receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(output=str(out),point_count=cloud.count,known_bin_means_equal=True,original_gms_comparison='NOT_OBSERVED'),indent=2))


if __name__=='__main__':main()
