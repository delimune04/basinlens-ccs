"""Independent arithmetic/topology and exact file/edit roundtrip regressions."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.subsurface.features import (
    FeatureCoverage, FeatureError, add_feature, contains_point, delete_feature,
    export_geojson, feature_metrics, feature_table, grid_extent, import_geojson,
    load_coverage, move_node, move_point, polygon_contains_xy, save_coverage, select_features,
    to_scatter_points, verify_coverage_roundtrip, prepare_polygon, prepare_polygon_xy,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples' / 'features'


def fixture():
    return json.loads((EXAMPLES/'local_coverage.json').read_text())


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.case = FeatureCoverage.from_dict(fixture())
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_square_hole_area_length_centroid_and_edge_policies(self):
        # Hand arithmetic: 10*10 - 2*2 = 96; perimeter 40+8=48.
        self.assertEqual(feature_metrics(self.case,'aquifer'),{'area_m2':96,'perimeter_m':48})
        self.assertEqual(feature_metrics(self.case,'river'),{'length_m':20})
        self.assertTrue(contains_point(self.case,'aquifer',1,1))
        self.assertFalse(contains_point(self.case,'aquifer',5,5))
        self.assertFalse(contains_point(self.case,'aquifer',11,5))
        for point in [(0,5),(4,5),(0,0),(4,4)]:
            self.assertTrue(contains_point(self.case,'aquifer',*point,edge_policy='include'))
            self.assertFalse(contains_point(self.case,'aquifer',*point,edge_policy='exclude'))
        sample=to_scatter_points(self.case,value_attribute='kx_m_day',sampling='polygon_centroids')
        self.assertEqual((sample['samples'][0]['x'],sample['samples'][0]['y']),(5,5))
        self.assertTrue(sample['centroid_may_lie_outside_region'])
        self.assertFalse(sample['interpolation_performed'])

    def test_large_origin_does_not_cancel_small_area(self):
        data=fixture()
        for node in data['nodes']:
            node['x']+=350000;node['y']+=4100000
        case=FeatureCoverage.from_dict(data)
        self.assertEqual(feature_metrics(case,'aquifer')['area_m2'],96)
        self.assertTrue(contains_point(case,'aquifer',350001,4100001))
        sample=to_scatter_points(case,value_attribute='kx_m_day',sampling='polygon_centroids')['samples'][0]
        self.assertEqual((sample['x'],sample['y']),(350005,4100005))

    def test_immutable_edit_select_attributes_and_dependency_deletion(self):
        selected=select_features(self.case,kind='points',attribute=('head_m',10))
        self.assertEqual([row['id'] for row in selected],['observation'])
        selected[0]['attributes']['nested']['preserve'][0]=99
        self.assertEqual(self.case.to_dict()['points'][0]['attributes']['nested']['preserve'][0],1)
        moved=move_node(self.case,'b',12,0)
        self.assertEqual(moved.to_dict()['arcs'][0]['attributes'],self.case.to_dict()['arcs'][0]['attributes'])
        self.assertEqual(self.case.to_dict()['nodes'][1]['x'],10)
        with self.assertRaisesRegex(FeatureError,'Referenced node'):delete_feature(self.case,'b')
        deleted=delete_feature(self.case,'b',cascade=True)
        self.assertEqual(deleted.to_dict()['arcs'],[])
        self.assertEqual(deleted.to_dict()['polygons'],[])
        self.assertEqual(deleted.to_dict()['points'],self.case.to_dict()['points'])
        added=add_feature(self.case,'points',{'id':'second','x':2,'y':3,'attributes':{'head_m':11}})
        self.assertEqual(len(added.to_dict()['points']),2)
        self.assertEqual(len(delete_feature(added,'second').to_dict()['points']),1)

    def test_point_edit_retains_attributes_and_source_bound_provenance(self):
        original=self.case.to_dict()
        moved=move_point(self.case,'observation',2,3)
        self.assertEqual(moved.to_dict()['points'][0]['attributes'],original['points'][0]['attributes'])
        self.assertEqual((moved.to_dict()['points'][0]['x'],moved.to_dict()['points'][0]['y']),(2,3))
        self.assertIn('source_sha256=',moved.to_dict()['provenance'][-1])
        self.assertIn('not a measured observation',moved.to_dict()['provenance'][-1])
        self.assertEqual(self.case.to_dict(),original)
        for crs in ['epsg:4326','EPSG:4269','OGC:CRS84']:
            data=fixture();data['coordinate_system']['crs']=crs
            with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)

    def test_invalid_edit_is_atomic_and_does_not_change_original(self):
        original=self.case.to_dict()
        with self.assertRaises(FeatureError):move_node(self.case,'b',-1,8)
        with self.assertRaises(FeatureError):add_feature(self.case,'points',{'id':'a','x':1,'y':1,'attributes':{}})
        self.assertEqual(self.case.to_dict(),original)

    def test_file_roundtrip_exact_metadata_attrs_and_immutability(self):
        first=save_coverage(self.case,self.root/'original.json')
        second=save_coverage(load_coverage(first),self.root/'relocated.json')
        self.assertEqual(first.read_bytes(),second.read_bytes())
        self.assertTrue(verify_coverage_roundtrip(second)['semantic_roundtrip'])
        self.assertEqual(verify_coverage_roundtrip(second)['original_gms_comparison'],'NOT_OBSERVED')
        with self.assertRaises(FeatureError):save_coverage(self.case,first)
        self.assertEqual(load_coverage(first).to_dict(),self.case.to_dict())

    def test_unknown_fields_versions_duplicate_ids_references_and_json_keys_fail(self):
        alterations=[]
        data=fixture();data['schema']='future';alterations.append(data)
        data=fixture();data['unknown']=1;alterations.append(data)
        data=fixture();data['points'][0]['id']='a';alterations.append(data)
        data=fixture();data['arcs'][0]['node_ids'][1]='missing';alterations.append(data)
        data=fixture();data['coordinate_system']['axis_order']='y,x';alterations.append(data)
        data=fixture();data['coordinate_system']['units']='ft';alterations.append(data)
        for data in alterations:
            with self.subTest(data=data):
                with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)
        bad=self.root/'duplicate.json';bad.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(FeatureError,'Duplicate JSON key'):load_coverage(bad)

    def test_nonfinite_bools_strings_huge_values_and_nonjson_attributes_fail(self):
        for value in [True,'10',float('nan'),float('inf'),10**10000]:
            data=fixture();data['points'][0]['x']=value
            with self.subTest(type=type(value)):
                with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)
        data=fixture();data['points'][0]['attributes']['object']=object()
        with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)
        data=fixture();data['nodes'][0]['attributes']={'a':float('nan')}
        with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)

    def test_self_intersection_self_touch_fold_and_unclosed_ring_rejected(self):
        with self.assertRaisesRegex(FeatureError,'self-intersection'):
            load_coverage(EXAMPLES/'invalid_self_intersection.json')
        alterations=[]
        data=fixture();data['polygons'][0]['shell']=['a','b','c','a','d','a'];alterations.append(data)
        data=fixture();data['polygons'][0]['shell']=['a','b','c','d'];alterations.append(data)
        data=fixture();data['arcs'][0]['node_ids']=['a','b','a'];alterations.append(data)
        data=fixture();data['arcs'][0]['node_ids']=['a','a'];alterations.append(data)
        for data in alterations:
            with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)

    def test_hole_outside_touches_crosses_overlaps_and_nests_rejected(self):
        for x,y in [(-1,4),(0,4),(11,4),(5,-1)]:
            data=fixture();data['nodes'][4].update(x=x,y=y)
            with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)
        data=fixture();data['polygons'][0]['holes'].append(data['polygons'][0]['holes'][0])
        with self.assertRaises(FeatureError):FeatureCoverage.from_dict(data)
        data=fixture()
        for identity,x,y in [('i',4.5,4.5),('j',5.5,4.5),('k',5.5,5.5),('l',4.5,5.5)]:
            data['nodes'].append({'id':identity,'x':x,'y':y,'attributes':{}})
        data['polygons'][0]['holes'].append(['i','j','k','l','i'])
        with self.assertRaisesRegex(FeatureError,'nest'):FeatureCoverage.from_dict(data)

    def test_shared_planar_predicate_and_grid_frame_match(self):
        rings=[[(0,0),(10,0),(10,10),(0,10),(0,0)],[(4,4),(6,4),(6,6),(4,6),(4,4)]]
        with self.assertRaises(FeatureError):
            prepare_polygon_xy([[[1,0],[2,0],[2,1],[1,1],[True,False]]])
        prepared=prepare_polygon(self.case,"aquifer")
        prepared_xy=prepare_polygon_xy(rings)
        for point in [(1,1),(5,5),(4,5),(10,10),(20,20)]:
            for policy in ['include','exclude']:
                expected=contains_point(self.case,"aquifer",*point,edge_policy=policy)
                self.assertEqual(polygon_contains_xy(rings,*point,edge_policy=policy),expected)
                self.assertEqual(prepared.contains(*point,edge_policy=policy),expected)
                self.assertEqual(prepared_xy.contains(*point,edge_policy=policy),expected)
        frame=grid_extent(self.case,padding_m=2)
        self.assertEqual((frame['x_origin_m'],frame['y_origin_m'],frame['width_m'],frame['height_m']),(-2,-2,14,14))
        self.assertEqual(frame['row_axis'],'south_to_north')
        self.assertEqual(len(feature_table(self.case)),11)

    def test_scatter_vertices_endpoints_and_explicit_units(self):
        vertices=to_scatter_points(self.case,value_attribute='head_m',sampling='arc_vertices')
        self.assertEqual([(p['x'],p['y'],p['value']) for p in vertices['samples']],[(0,0,9),(10,0,9),(10,10,9)])
        endpoints=to_scatter_points(self.case,value_attribute='head_m',sampling='arc_endpoints')
        self.assertEqual(len(endpoints['samples']),2)
        self.assertTrue(endpoints['value_units'].startswith('unknown'))
        with self.assertRaisesRegex(FeatureError,'missing'):to_scatter_points(self.case,value_attribute='nonexistent')
        self.assertEqual(to_scatter_points(self.case,value_attribute='head_m')['samples'][0]['source_feature_id'],'observation')

    def test_projected_metre_geojson_is_refused_and_degrees_have_no_metric_area(self):
        with self.assertRaisesRegex(FeatureError,'metres refused'):export_geojson(self.case,self.root/'false.geojson')
        self.assertFalse((self.root/'false.geojson').exists())
        geographic=load_coverage(EXAMPLES/'wgs84_coverage.json')
        for action in [lambda:feature_metrics(geographic,'aquifer'),lambda:grid_extent(geographic),lambda:to_scatter_points(geographic,value_attribute='kx_m_day',sampling='polygon_centroids')]:
            with self.assertRaises(FeatureError):action()

    def test_geojson_own_roundtrip_preserves_noding_all_attributes_and_order(self):
        case=load_coverage(EXAMPLES/'wgs84_coverage.json')
        path=export_geojson(case,self.root/'coverage.geojson')
        restored=import_geojson(path)
        self.assertEqual(restored.to_dict(),case.to_dict())
        document=json.loads(path.read_text())
        # Visible polygon outer ring is counter-clockwise, hole clockwise.
        shell,hole=document['features'][2]['geometry']['coordinates']
        self.assertEqual(shell[0],shell[-1]);self.assertEqual(hole[0],hole[-1])
        document['features'][0]['properties']['head_m']=99
        altered=self.root/'altered.geojson';altered.write_text(json.dumps(document))
        with self.assertRaisesRegex(FeatureError,'disagree'):import_geojson(altered)
        with self.assertRaisesRegex(FeatureError,'overrides'):import_geojson(path,name='new name')

    def test_general_geojson_requires_provenance_preserves_ids_and_never_infers_projected_coordinates(self):
        document={'type':'FeatureCollection','features':[
            {'type':'Feature','id':'001','properties':{'owner':'synthetic'},'geometry':{'type':'Point','coordinates':[127,37]}},
            {'type':'Feature','id':'edge','properties':{'value':2},'geometry':{'type':'LineString','coordinates':[[127,37],[127.01,37]]}},
            {'type':'Feature','id':'area','properties':{},'geometry':{'type':'Polygon','coordinates':[[[127,37],[127.01,37],[127.01,37.01],[127,37.01],[127,37]]]}}
        ]}
        path=self.root/'general.geojson';path.write_text(json.dumps(document))
        with self.assertRaises(FeatureError):import_geojson(path)
        case=import_geojson(path,coverage_id='import',name='Imported synthetic',provenance=['Authored synthetic RFC7946 input'])
        self.assertEqual(case.to_dict()['points'][0]['id'],'001')
        self.assertEqual(case.to_dict()['points'][0]['attributes'],{'owner':'synthetic'})
        self.assertEqual(case.to_dict()['coordinate_system']['units'],'degrees')
        document['features'][0]['geometry']['coordinates']=[350000,4100000]
        path2=self.root/'projected.geojson';path2.write_text(json.dumps(document))
        with self.assertRaisesRegex(FeatureError,'longitude/latitude'):import_geojson(path2,coverage_id='bad',name='Bad',provenance=['Unknown projected input'])

    def test_geojson_z_crs_multigeometry_legacy_and_antimeridian_fail(self):
        base={'type':'FeatureCollection','features':[{'type':'Feature','id':'x','properties':{},'geometry':{'type':'Point','coordinates':[127,37]}}]}
        cases=[]
        data=deepcopy(base);data['crs']={'name':'EPSG:4326'};cases.append(data)
        data=deepcopy(base);data['features'][0]['geometry']['coordinates']=[127,37,5];cases.append(data)
        data=deepcopy(base);data['features'][0]['geometry']['type']='MultiPoint';cases.append(data)
        data=deepcopy(base);data['features'][0]['geometry']={'type':'LineString','coordinates':[[179,0],[-179,0]]};cases.append(data)
        for i,document in enumerate(cases):
            path=self.root/f'bad{i}.geojson';path.write_text(json.dumps(document))
            with self.assertRaises(FeatureError):import_geojson(path,coverage_id='bad',name='Bad',provenance=['Synthetic invalid'])

    def test_bounded_files_links_fifo_and_comparison_work(self):
        source=save_coverage(self.case,self.root/'source.json')
        link=self.root/'link.json';link.symlink_to(source)
        with self.assertRaises(FeatureError):load_coverage(link)
        if hasattr(os,'mkfifo'):
            fifo=self.root/'fifo';os.mkfifo(fifo)
            with self.assertRaises(FeatureError):load_coverage(fifo)
        with patch('basinlens_ccs.subsurface.features.MAX_BYTES',8):
            with self.assertRaises(FeatureError):load_coverage(source)
        with patch('basinlens_ccs.subsurface.features.MAX_TOPOLOGY_WORK',1):
            with self.assertRaisesRegex(FeatureError,'comparison budget'):FeatureCoverage.from_dict(fixture())
        data=fixture();data['points'][0]['attributes']={'nested':[[[[[[[[[[1]]]]]]]]]]}
        with self.assertRaisesRegex(FeatureError,'eight'):FeatureCoverage.from_dict(data)

    def test_geojson_invalid_boolean_closing_coordinates_never_get_dropped(self):
        for kind,coords in [
            ('Polygon',[[[1,0],[2,0],[2,1],[1,1],[True,False]]]),
            ('LineString',[[1,0],[2,0],[2,1],[True,False]]),
        ]:
            document={'type':'FeatureCollection','features':[{'type':'Feature','id':'x','properties':{},'geometry':{'type':kind,'coordinates':coords}}]}
            path=self.root/(kind+'.geojson');path.write_text(json.dumps(document))
            with self.assertRaisesRegex(FeatureError,'finite numeric'):
                import_geojson(path,coverage_id='bad',name='Bad',provenance=['Synthetic invalid bool closure'])

    def test_atomic_write_fault_and_parent_symlink_rejection(self):
        source=save_coverage(self.case,self.root/'source.json')
        real=self.root/'real';real.mkdir()
        linked=self.root/'linked';linked.symlink_to(real,target_is_directory=True)
        (real/'input.json').write_bytes(source.read_bytes())
        with self.assertRaises(FeatureError):load_coverage(linked/'input.json')
        with self.assertRaises(FeatureError):save_coverage(self.case,linked/'output.json')
        self.assertFalse((real/'output.json').exists())
        with patch('basinlens_ccs.subsurface.features.os.fsync',side_effect=OSError('simulated disk error')):
            with self.assertRaisesRegex(FeatureError,'atomic'):save_coverage(self.case,self.root/'incomplete.json')
        self.assertFalse((self.root/'incomplete.json').exists())
        self.assertFalse(list(self.root.glob('.features-*')))
        self.assertEqual(load_coverage(source).to_dict(),self.case.to_dict())
        save_coverage(self.case,self.root/'recovered.json')

    def test_embedded_geojson_boolean_numeric_tampering_is_detected(self):
        data=load_coverage(EXAMPLES/'wgs84_coverage.json').to_dict()
        data['points'][0].update(x=1,y=0)
        data['points'][0]['attributes']={'n':1}
        case=FeatureCoverage.from_dict(data)
        path=export_geojson(case,self.root/'valid.geojson')
        document=json.loads(path.read_text())
        document['features'][0]['geometry']['coordinates']=[True,False]
        document['features'][0]['properties']['n']=True
        bad=self.root/'bool-tamper.geojson';bad.write_text(json.dumps(document))
        with self.assertRaisesRegex(FeatureError,'disagree'):import_geojson(bad)

    def test_cli_check_edit_export_selection_and_invalid_failure(self):
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
        def run(*args):
            return subprocess.run([sys.executable,'-m','basinlens_ccs.subsurface.features',*map(str,args)],capture_output=True,text=True,env=env,timeout=15)
        source=EXAMPLES/'local_coverage.json'
        check=run('check',source);self.assertEqual(check.returncode,0,check.stderr)
        self.assertTrue(json.loads(check.stdout)['semantic_roundtrip'])
        out=self.root/'moved.json'
        edit=run('move-node',source,'b','12','0',out);self.assertEqual(edit.returncode,0,edit.stderr)
        self.assertEqual(load_coverage(out).to_dict()['nodes'][1]['x'],12)
        selected=run('select',source,'--kind','points');self.assertEqual(selected.returncode,0,selected.stderr)
        self.assertEqual(json.loads(selected.stdout)[0]['id'],'observation')
        bad=run('check',EXAMPLES/'invalid_self_intersection.json');self.assertEqual(bad.returncode,2)
        self.assertIn('self-intersection',bad.stderr)
        export=run('export',source,self.root/'copy.json');self.assertEqual(export.returncode,0,export.stderr)
        deleted=run('delete',source,'b',self.root/'deleted.json','--cascade');self.assertEqual(deleted.returncode,0,deleted.stderr)


if __name__=='__main__':unittest.main()
