"""Authored stationary statistics example with independent hand-matrix acceptance."""
import argparse
import json
import math
from pathlib import Path

from basinlens_ccs.subsurface.scatter import ScatterDataset, save_scatter
from basinlens_ccs.subsurface.geostatistics import (
    CovarianceModel, experimental_variogram, gaussian_field, krige,
    latin_hypercube, kriging_to_scatter, save_result, verify_result_roundtrip,
)


def example_dataset():
    return ScatterDataset.from_dict(dict(schema='basinlens-scatter-v1',id='geostatistics-authored',dimension=2,coordinate_unit='m',crs='LOCAL:authored-metre',vertical_datum='authored-zero',vertical_axis='not_applicable',quantity='head',value_unit='m',basis='synthetic',provenance=['Authored two-point hand-matrix fixture, not measurements'],duplicate_coordinate_policy='reject',points=[dict(id='left',coordinates_m=[0,0],value=2,missing_reason=None),dict(id='right',coordinates_m=[2,0],value=4,missing_reason=None)]))


def example_model():
    return CovarianceModel.from_dict(dict(schema='basinlens-covariance-v1',dimension=2,kind='exponential',partial_sill=1,nugget=0,value_unit='m',ranges_m=[1,1],rotation=[[1,0],[0,1]]))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output;out.mkdir()
    data=example_dataset();model=example_model();save_scatter(data,out/'observations.json');(out/'covariance.json').write_text(json.dumps(model.to_dict(),indent=2)+'\n')
    settings=dict(method='ordinary',mean=None,radius_m=5,min_neighbors=2,max_neighbors=32,domain_bounds_m=[[-1,4],[-1,1]],allow_extrapolation=False)
    queries=[[0,0],[1,0],[2,0],[3,0]]
    (out/'settings.json').write_text(json.dumps(settings,indent=2)+'\n');(out/'queries.json').write_text(json.dumps(queries)+'\n')
    ordinary=krige(data,queries,model,**settings);expected=1.5+.5*math.exp(-2)-2*math.exp(-1)
    assert ordinary.records[1]['prediction']==3
    assert math.isclose(ordinary.records[1]['variance'],expected,abs_tol=1e-14)
    assert ordinary.records[3]['prediction'] is None
    save_scatter(kriging_to_scatter(ordinary,dataset_id='kriged-head'),out/'predicted_head.json')
    save_scatter(kriging_to_scatter(ordinary,dataset_id='kriged-head'),out/'predicted_head.csv')
    meta=dict(crs='LOCAL:authored-metre',vertical_datum='authored-zero',provenance=['Authored explicit simulation sites; known mean and stationary covariance assumed'])
    conditional=gaussian_field([[0,0],[1,0],[2,0]],model,mean=0,seed=42,realizations=16,metadata=meta,conditioning=data)
    assert all(conditional.records[0][f'r{i:04d}']==2 and conditional.records[2][f'r{i:04d}']==4 for i in range(16))
    lhs=latin_hypercube([dict(name='conductivity',unit='m/day',distribution='uniform',parameters=dict(minimum=1,maximum=5)),dict(name='porosity',unit='1',distribution='triangular',parameters=dict(minimum=.1,mode=.2,maximum=.4))],samples=32,seed=42)
    results={'ordinary':ordinary,'variogram':experimental_variogram(data,[0,1,2]),'conditional':conditional,'lhs':lhs}
    receipts={}
    for name,result in results.items():
        save_result(result,out/(name+'.json'));save_result(result,out/(name+'.csv'));receipts[name]=verify_result_roundtrip(result)
    receipt=dict(schema='basinlens-geostatistics-example-v1',ordinary_midpoint_expected_head_m=3,ordinary_midpoint_expected_variance_m2=expected,hand_matrix_passed=True,unsupported_query_remains_missing=True,conditional_original_values_exact=True,roundtrips=receipts,original_gms_comparison='NOT_OBSERVED')
    (out/'example_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
