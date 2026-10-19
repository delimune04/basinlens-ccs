"""Actual bounded geoscience user flows; no original GMS parity is inferred."""
from __future__ import annotations
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'geoscience_workspace.py'
AVAILABLE=all(importlib.util.find_spec(n) is not None for n in ('streamlit','plotly','flopy'))
MF6=os.environ.get('MF6_EXE') or shutil.which('mf6')
MF2005=os.environ.get('MF2005_EXE')
MFNWT=os.environ.get('MFNWT_EXE')

@unittest.skipUnless(AVAILABLE,'Geoscience UI requires optional Streamlit/Plotly/FloPy')
class GeoscienceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.app=AppTest.from_file(str(APP),default_timeout=90).run()
        self.assertEqual(list(self.app.exception),[])
        self.addCleanup(self._cleanup_package)
    def _cleanup_package(self):
        try:keeper=self.app.session_state['gx_package_keeper']
        except KeyError:return
        keeper.cleanup()
    def button(self,label):return next(x for x in self.app.button if x.label==label)
    def text(self,label):return next(x for x in self.app.text_input if x.label==label)
    def area(self,label):return next(x for x in self.app.text_area if x.label==label)
    def select(self,label):return next(x for x in self.app.selectbox if x.label==label)
    def load(self,title):
        self.button(title+' 합성 예제 불러오기').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertEqual(list(self.app.error),[])
    def test_initial_is_idle_geology_section_edit_and_bad_upload_preserve_valid(self):
        self.assertGreaterEqual(len(self.app.tabs),9)
        self.assertEqual(len(self.app.get('plotly_chart')),0)
        self.assertEqual(list(self.base.iterdir()),[])
        self.load('시추·지질')
        original=self.app.session_state['gx_geo_document'].to_dict()
        self.button('시추 단면 투영').click().run()
        result=self.app.session_state['gx_geo_product_section']
        self.assertFalse(result['geological_interpolation'])
        first=next(h for h in result['boreholes'] if h['borehole_id']=='A')
        self.assertAlmostEqual(first['chainage_m'],3.)
        self.assertAlmostEqual(first['intervals'][0]['bottom_z_m'],97.5)
        self.select('편집할 로그 구간').set_value('a2')
        self.select('적용할 지질 물질').set_value('clay')
        self.button('로그 물질 변경 적용').click().run()
        self.assertEqual(list(self.app.exception),[])
        updated=self.app.session_state['gx_geo_document'].to_dict()
        self.assertEqual(updated['boreholes'][0]['intervals'][1]['material_id'],'clay')
        self.assertEqual(len(updated['history']),1)
        self.assertEqual(original['boreholes'][0]['intervals'][1]['material_id'],'sand')
        upload=next(x for x in self.app.file_uploader if x.key=='gx_geo_upload')
        upload.set_value(('bad.json',b'{"schema":1,"schema":1}','application/json'))
        self.button('시추·지질 업로드 불러오기').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state['gx_geo_document'].to_dict(),updated)
        missing_asset=copy.deepcopy(updated);missing_asset['assets'][0]['relative_path']='assets/no-such-source.txt'
        upload=next(x for x in self.app.file_uploader if x.key=='gx_geo_upload')
        upload.set_value(('missing-asset.json',json.dumps(missing_asset).encode(),'application/json'))
        self.button('시추·지질 업로드 불러오기').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state['gx_geo_document'].to_dict(),updated)
    def test_conceptual_invalid_draft_blocks_and_valid_geometry_edit_applies(self):
        self.load('개념 피처')
        original=self.app.session_state['gx_map_document'].to_dict()
        self.area('개념 피처 JSON 초안').set_value('{"invalid":true}').run()
        self.assertTrue(self.app.error)
        self.assertTrue(self.button('개념 피처 검증한 초안 적용').disabled)
        self.assertEqual(self.app.session_state['gx_map_document'].to_dict(),original)
        changed=copy.deepcopy(original);changed['points'][0]['x']=2.
        self.area('개념 피처 JSON 초안').set_value(json.dumps(changed)).run()
        self.button('개념 피처 검증한 초안 적용').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertEqual(list(self.app.error),[])
        self.assertEqual(self.app.session_state['gx_map_document'].to_dict()['points'][0]['x'],2.)
    def test_scatter_support_tin_math_and_stale_draft_block(self):
        self.load('산점 자료')
        self.button('산점 보간 질의 실행').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertEqual(list(self.app.error),[])
        rows=self.app.session_state['gx_scatter_product_query']['rows']
        self.assertEqual([r['supported'] for r in rows],[True,True,False])
        self.assertEqual(rows[0]['value'],1.)
        self.assertIsNone(rows[2]['value'])
        self.select('산점 보간 방법').set_value('tin').run()
        with self.assertRaises(KeyError):self.app.session_state['gx_scatter_product_query']
        self.button('산점 보간 질의 실행').click().run()
        self.assertEqual(list(self.app.error),[])
        rows=self.app.session_state['gx_scatter_product_query']['rows']
        self.assertAlmostEqual(rows[1]['value'],3.5)
        self.button('산점 자료 연산 실행').click().run()
        self.assertEqual(list(self.app.error),[])
        self.assertTrue(all(p['value']==0 for p in self.app.session_state['gx_scatter_product_math']['points']))
        original=self.app.session_state['gx_scatter_document'].to_dict()
        next(x for x in self.app.number_input if x.label=='편집할 산점 값').set_value(2.)
        self.button('산점 값 변경 적용').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        edited=self.app.session_state['gx_scatter_document'].to_dict()
        self.assertEqual(edited['points'][0]['value'],2.)
        self.assertEqual(edited['basis'],'interpreted')
        self.assertEqual(original['points'][0]['value'],1.)
        self.area('산점 자료 JSON 초안').set_value('{}').run()
        self.assertTrue(self.button('산점 보간 질의 실행').disabled)
        with self.assertRaises(KeyError):self.app.session_state['gx_scatter_product_query']
    def test_nonuniform_generation_refinement_and_closed_prism_volume(self):
        from basinlens_ccs.subsurface.mesh import topology
        self.button('비균일 평면 격자 생성').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertEqual(list(self.app.error),[])
        self.assertEqual(topology(self.app.session_state['gx_mesh_mesh'])['cells'],4)
        self.button('선택 영역 사각 격자 세분화').click().run()
        self.assertEqual(list(self.app.error),[])
        self.assertEqual(topology(self.app.session_state['gx_mesh_mesh'])['cells'],7)
        self.button('닫힌 프리즘 격자 압출').click().run()
        self.assertEqual(list(self.app.exception),[])
        self.assertEqual(list(self.app.error),[])
        prism=self.app.session_state['gx_mesh_product_extruded']
        self.assertEqual(len(prism['cells']),14)
        self.assertAlmostEqual(prism['total_volume_m3'],450.)
        self.assertFalse(prism['horizon_interpolation_performed'])
        before=self.app.session_state['gx_mesh_mesh'].to_dict()
        self.text('격자 x 경계 좌표 JSON (m)').set_value('[1,0]')
        self.button('비균일 평면 격자 생성').click().run()
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state['gx_mesh_mesh'].to_dict(),before)
    @unittest.skipUnless(MF6,'MF6_EXE required for verified actual analysis UI')
    def test_verified_mf6_query_section_clip_and_manual_observation_metrics(self):
        from basinlens_ccs.subsurface.model_workflow import load_workflow_case,run_workflow
        case=load_workflow_case(ROOT/'examples/workflow/layered_background_water.json')
        output=self.base/'mf6';run_workflow(case,output,exe_name=MF6)
        self.text('검증할 MF6 워크플로 실행 폴더').set_value(str(output))
        self.button('검증한 해석 결과 불러오기').click().run()
        self.assertEqual(list(self.app.error),[])
        self.button('후처리 좌표 질의').click().run()
        self.assertEqual(list(self.app.exception),[])
        rows=self.app.session_state['gx_analysis_product_result']['rows']
        self.assertEqual([r['supported'] for r in rows],[True,False]);self.assertAlmostEqual(rows[0]['value'],12.)
        self.button('후처리 단면 추출').click().run();self.assertEqual(list(self.app.error),[])
        self.assertEqual(self.app.session_state['gx_analysis_product_result']['operation'],'section')
        self.text('후처리 검증 묶음 폴더 (새 폴더)').set_value(str(self.base/'analysis-bundle'))
        self.button('후처리 검증 묶음 저장').click().run()
        self.assertEqual(list(self.app.error),[])
        from basinlens_ccs.subsurface.analysis import verify_analysis_bundle
        verify_analysis_bundle(self.base/'analysis-bundle')
        archive=zipfile.ZipFile(io.BytesIO(self.app.session_state['gx_analysis_product_zip']))
        self.assertIn('manifest.json',archive.namelist())
        self.assertIn('samples.csv',archive.namelist())
        self.button('중심 기준 셀 클립').click().run();self.assertEqual(list(self.app.error),[])
        clip=self.app.session_state['gx_analysis_product_result'];self.assertGreater(clip['visible_cells'],0)
        volume=self.app.session_state['gx_analysis_volume']
        doc={'schema':'basinlens-head-observations-v1','project_id':case.to_dict()['project']['id'],
             'case_sha256':volume.case_sha256,'crs':case.to_dict()['project']['crs'],
             'vertical_datum':case.to_dict()['project']['vertical_datum'],'units':{'head':'m','time':'day'},
             'observations':[{'id':'authored','time_day':1.,'cell':[0,0,0],'head_m':11.5,'sigma_m':.25,
                              'basis':'synthetic','provenance':'Authored 0.5 m residual; not field data'}]}
        upload=next(x for x in self.app.file_uploader if x.key=='gx_analysis_observations')
        upload.set_value(('synthetic.json',json.dumps(doc).encode(),'application/json'))
        self.button('관측 잔차·목적함수 계산').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        metrics=self.app.session_state['gx_analysis_product_comparison']['metrics']
        self.assertAlmostEqual(metrics['rmse_m'],.5);self.assertAlmostEqual(metrics['objective_chi_square'],4.)
        self.text('검증할 MF6 워크플로 실행 폴더').set_value(str(self.base/'missing'))
        self.button('검증한 해석 결과 불러오기').click().run()
        self.assertTrue(self.app.error);self.assertEqual(self.app.session_state['gx_analysis_volume'].case_sha256,volume.case_sha256)
        self.assertTrue(self.button('후처리 좌표 질의').disabled)
        self.text('검증할 MF6 워크플로 실행 폴더').set_value(str(output))
        self.button('검증한 해석 결과 불러오기').click().run()
        self.assertFalse(self.button('후처리 좌표 질의').disabled)
        self.button('후처리 좌표 질의').click().run()
        head=output/'native/flow.hds'
        altered=bytearray(head.read_bytes());altered[-1]^=1;head.write_bytes(altered)
        self.app.run()
        self.assertEqual(list(self.app.exception),[])
        self.assertTrue(self.app.error);self.assertTrue(self.button('후처리 좌표 질의').disabled)
        with self.assertRaises(KeyError):self.app.session_state['gx_analysis_product_result']
        self.assertFalse(any(x.label=='원본 파일 무결성 확인 후처리 CSV 다운로드' for x in self.app.get('download_button')))
    def test_classic_export_and_unknown_engine_refusal(self):
        from basinlens_ccs.subsurface.classic import verify_classic_export
        self.load('레거시 물 모델')
        output=self.base/'export';self.text('레거시 출력 폴더 (새 폴더)').set_value(str(output))
        self.button('레거시 입력 내보내기').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        case,record=verify_classic_export(output);self.assertEqual(record['engine'],'mf2005')
        archive=zipfile.ZipFile(io.BytesIO(self.app.session_state['gx_classic_product_export']['bytes']))
        self.assertIn('flow.nam',archive.namelist())
        self.text('레거시 엔진 실행 파일').set_value('/missing/unknown-engine')
        self.text('레거시 출력 폴더 (새 폴더)').set_value(str(self.base/'failed'))
        self.button('지정 레거시 엔진 실제 실행').click().run()
        self.assertTrue(self.app.error)
        with self.assertRaises(KeyError):self.app.session_state['gx_classic_product_run']
    @unittest.skipUnless(MF2005 and MFNWT,'MF2005_EXE and MFNWT_EXE required for both actual classic UI runs')
    def test_actual_pinned_classic_engines_and_captured_csv(self):
        self.load('레거시 물 모델')
        for engine,exe in (('mf2005',MF2005),('mfnwt',MFNWT)):
            self.select('레거시 해석 엔진').set_value(engine)
            self.text('레거시 엔진 실행 파일').set_value(exe)
            self.text('레거시 출력 폴더 (새 폴더)').set_value(str(self.base/engine))
            self.button('지정 레거시 엔진 실제 실행').click().run(timeout=120)
            self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
            products=self.app.session_state['gx_classic_product_run'];result=products['result']
            self.assertEqual(result.summary['solver']['engine'],engine)
            self.assertTrue(result.summary['water_balance_passed']);self.assertTrue(result.summary['boundary_rates_passed'])
            self.assertTrue(result.summary['confined_saturation_support_passed'])
            self.assertAlmostEqual(result.heads_m[0,0,0,0],12.,places=6)
            archive=zipfile.ZipFile(io.BytesIO(products['zip']));self.assertIn('run.json',archive.namelist())
            self.assertIn('native/flow.hds',archive.namelist())
        self.area('레거시 물 모델 JSON 초안').set_value('{}').run()
        self.assertTrue(self.button('지정 레거시 엔진 실제 실행').disabled)
        with self.assertRaises(KeyError):self.app.session_state['gx_classic_product_run']

    def test_raster_north_row_sampling_clip_and_ascii_roundtrip(self):
        self.load('래스터')
        source=self.app.session_state['gx_raster_document'].to_dict()
        self.select('래스터 표본 방법').set_value('bilinear')
        self.button('래스터 좌표 표본 추출').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        rows=self.app.session_state['gx_raster_product_samples']
        self.assertEqual([r['supported'] for r in rows],[True,True,False])
        self.assertAlmostEqual(rows[0]['value'],5.)
        self.assertAlmostEqual(rows[1]['value'],12.)
        self.button('래스터 범위 클립 적용').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        clipped=self.app.session_state['gx_raster_document']
        self.assertEqual(clipped.geometry['ncol'],2)
        self.assertEqual(source['geometry']['ncol'],3)
        self.assertEqual([list(r) for r in clipped.values],[[11.,15.],[5.,9.]])
        self.text('래스터 ASCII 저장 폴더 (새 폴더)').set_value(str(self.base/'ascii'))
        self.button('래스터 ASCII·JSON 왕복 확인').click().run()
        self.assertEqual(list(self.app.error),[])
        from basinlens_ccs.subsurface.raster import open_ascii_bundle
        self.assertEqual(open_ascii_bundle(self.base/'ascii').to_dict(),clipped.to_dict())
        self.area('래스터 JSON 초안').set_value('{}').run()
        self.assertTrue(self.button('래스터 좌표 표본 추출').disabled)
        with self.assertRaises(KeyError):self.app.session_state['gx_raster_product_export']
    def test_pointcloud_real_encoded_filter_bin_and_las_json_roundtrip(self):
        self.load('점군')
        original=self.app.session_state['gx_cloud_document']
        self.assertEqual(original.count,6)
        self.button('점군 셀 집계').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        grid=self.app.session_state['gx_cloud_product_grid']
        self.assertEqual(grid['values'],[[100.,None,None],[None,100.,None],[None,None,110.]])
        self.button('점군 분류·범위 필터 적용').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        cloud=self.app.session_state['gx_cloud_document']
        self.assertEqual(cloud.count,3);self.assertEqual(original.count,6)
        self.text('점군 LAS·JSON 저장 폴더 (새 폴더)').set_value(str(self.base/'cloud'))
        self.button('점군 LAS·JSON 왕복 확인').click().run()
        self.assertEqual(list(self.app.error),[])
        receipt=self.app.session_state['gx_cloud_product_export']['receipt']
        self.assertTrue(receipt['encoded_point_bytes_equal'])
        self.assertTrue(receipt['native_json_identities_equal'])
        self.area('점군 JSON 초안').set_value('{}').run()
        self.assertTrue(self.button('점군 셀 집계').disabled)
    def test_surface_affine_support_solid_integral_edit_and_csv_roundtrip(self):
        self.load('지층면')
        original=self.app.session_state['gx_surface_document'].to_dict()
        self.button('지층면 고도 질의').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        result=self.app.session_state['gx_surface_product_query']
        self.assertEqual([p['supported'] for p in result['points']],[True,False])
        self.assertAlmostEqual(result['points'][0]['elevation_m'],13.)
        self.button('명시적 지층면 사이 솔리드 생성').click().run()
        self.assertAlmostEqual(self.app.session_state['gx_surface_product_solids']['total_volume_m3'],48.)
        self.button('지층면 단면 자르기').click().run()
        self.assertEqual(list(self.app.error),[])
        self.assertTrue(self.app.session_state['gx_surface_product_section']['pieces'])
        self.button('지층면 정점 편집 적용').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        edited=self.app.session_state['gx_surface_document'].to_dict()
        self.assertEqual(edited['horizons'][0]['elevations_m'][0],11.)
        self.assertEqual(original['horizons'][0]['elevations_m'][0],10.)
        self.assertEqual(len(edited['history']),1)
        self.text('지층면 표 저장 폴더 (새 폴더)').set_value(str(self.base/'surfaces'))
        self.button('지층면 CSV 재열기 확인·내보내기').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        from basinlens_ccs.subsurface.surfaces import import_surface_tables
        self.assertEqual(import_surface_tables(self.base/'surfaces').to_dict(),edited)

    def test_mixed_typed_project_save_relocate_open_and_invalid_selected_draft(self):
        self.load('시추·지질');self.load('개념 피처');self.load('혼합 기반 프로젝트')
        geo=self.app.session_state['gx_geo_document'].to_dict()
        feature=self.app.session_state['gx_map_document'].to_dict()
        next(x for x in self.app.checkbox if x.label=='혼합 저장에 포함 · geology').set_value(True)
        next(x for x in self.app.checkbox if x.label=='혼합 저장에 포함 · features').set_value(True)
        self.app.run()
        self.text('혼합 프로젝트 저장 파일 (새 .blproj)').set_value(str(self.base/'mixed.blproj'))
        self.button('혼합 프로젝트 저장·실제 왕복 확인').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        products=self.app.session_state['gx_package_product_saved']
        self.assertTrue(products['receipt']['roundtrip_verified'])
        upload=next(x for x in self.app.file_uploader if x.key=='gx_package_open_upload')
        upload.set_value(('relocated.blproj',products['bytes'],'application/zip'))
        self.button('혼합 프로젝트 다른 위치에 열기').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        self.assertEqual(self.app.session_state['gx_geo_document'].to_dict(),geo)
        self.assertEqual(self.app.session_state['gx_map_document'].to_dict(),feature)
        self.assertFalse(self.app.session_state['gx_package_receipt']['solver_executed'])
        self.assertTrue(Path(self.app.session_state['gx_geo_asset_root']).is_dir())
        self.text('혼합 프로젝트 저장 파일 (새 .blproj)').set_value(str(self.base/'resaved.blproj'))
        self.button('혼합 프로젝트 저장·실제 왕복 확인').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        self.area('개념 피처 JSON 초안').set_value('{}').run()
        self.assertTrue(self.button('혼합 프로젝트 저장·실제 왕복 확인').disabled)
        self.assertEqual(self.app.session_state['gx_map_document'].to_dict(),feature)
        upload=next(x for x in self.app.file_uploader if x.key=='gx_package_open_upload')
        upload.set_value(('damaged.blproj',products['bytes'][:-30],'application/zip'))
        self.button('혼합 프로젝트 다른 위치에 열기').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state['gx_geo_document'].to_dict(),geo)
        # Multiple objects of the same kind keep their original collection IDs.
        from basinlens_ccs.subsurface import load_project
        from basinlens_ccs.subsurface.features import FeatureCoverage
        from basinlens_ccs.subsurface.geoscience_project import ProjectObject,save_geoscience_project,open_geoscience_project
        base=load_project(ROOT/'examples/geoscience_project/project.json')
        maps=[ProjectObject('features',identity,FeatureCoverage.from_dict(feature)) for identity in ('first_map','second_map')]
        multi=save_geoscience_project(base,maps,self.base/'multi.blproj')
        upload=next(x for x in self.app.file_uploader if x.key=='gx_package_open_upload')
        upload.set_value(('multi.blproj',multi.read_bytes(),'application/zip'))
        self.button('혼합 프로젝트 다른 위치에 열기').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        self.assertTrue(any('second_map' in x.label for x in self.app.checkbox))
        self.text('혼합 프로젝트 저장 파일 (새 .blproj)').set_value(str(self.base/'multi-resaved.blproj'))
        self.button('혼합 프로젝트 저장·실제 왕복 확인').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        reopened=open_geoscience_project(self.base/'multi-resaved.blproj',self.base/'multi-reopened')
        self.assertEqual([x.object_id for x in reopened.objects],['first_map','second_map'])
        # Asset preflight refuses an oversized regular file before unbounded hashing.
        oversized=self.base/'oversized.bin'
        with oversized.open('wb') as stream:stream.truncate(32*1024*1024+1)
        metadata=base.to_dict()
        metadata['assets']=[{'asset_id':'too-large','relative_path':'oversized.bin','sha256':'0'*64,
                            'media_type':'application/octet-stream','license':'authored synthetic diagnostic',
                            'source':'Sparse authored fixture; no real data'}]
        original_base=self.app.session_state['gx_package_document'].to_dict()
        self.text('혼합 기반 프로젝트 참조자료 폴더').set_value(str(self.base))
        uploader=next(x for x in self.app.file_uploader if x.key=='gx_package_upload')
        uploader.set_value(('oversized-asset.json',json.dumps(metadata).encode(),'application/json'))
        self.button('혼합 기반 프로젝트 업로드 불러오기').click().run()
        self.assertEqual(list(self.app.exception),[]);self.assertTrue(self.app.error)
        self.assertIn('size budget',self.app.session_state['gx_package_diagnostic']['message'])
        self.assertEqual(self.app.session_state['gx_package_document'].to_dict(),original_base)

    @unittest.skipUnless(MF2005,'MF2005_EXE required for actual failed confined-support UI case')
    def test_actual_classic_failed_support_keeps_diagnostic_record_without_validation_claim(self):
        self.load('레거시 물 모델')
        case=self.app.session_state['gx_classic_document'].to_dict()
        case['grid']['layer_surfaces_m'][0]=20.
        case['initial_head_m']=[22.]*len(case['initial_head_m'])
        case['project']['provenance'].append('Authored diagnostic: initially saturated, fixed heads below top; support gate must fail.')
        self.area('레거시 물 모델 JSON 초안').set_value(json.dumps(case)).run()
        self.button('레거시 물 모델 검증한 초안 적용').click().run()
        self.assertEqual(list(self.app.error),[])
        self.text('레거시 엔진 실행 파일').set_value(MF2005)
        self.text('레거시 출력 폴더 (새 폴더)').set_value(str(self.base/'unsupported-confined'))
        self.button('지정 레거시 엔진 실제 실행').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[])
        result=self.app.session_state['gx_classic_product_run']['result']
        self.assertFalse(result.summary['confined_saturation_support_passed'])
        self.assertTrue(any('통과하지 않은 판정' in x.value for x in self.app.error))
        self.assertFalse(any('판정 통과' in x.value for x in self.app.success))
        labels={x.label for x in self.app.get('download_button')}
        self.assertIn('레거시 실행 기록 ZIP 다운로드',labels)
        self.assertNotIn('검증한 레거시 실행 ZIP 다운로드',labels)

    @unittest.skipUnless(MFNWT,'MFNWT_EXE required for explicit GMRES selection and fractional heads')
    def test_nwt_explicit_gmres_preserves_fractional_heads_and_selection_invalidates_cache(self):
        self.load('레거시 물 모델')
        data=self.app.session_state['gx_classic_document'].to_dict()
        data['project'].update(id='classic_test_fractional_heads',name='Authored classic test fractional_heads',
            provenance=['Independent synthetic software/numerical regression; not GMS or field data'])
        data['grid'].update(nrow=1,ncol=3,dx_m=4.,dy_m=7.,x_origin_m=47.,y_origin_m=-83.,layer_surfaces_m=[0.,-11.])
        west,east=12.3456789123,9.8765432199
        data.update(strata=[dict(id='aquifer',name='Explicit flat unit',layer_indices=[0])],
            materials=[dict(id='rock',name='rock',kx_m_day=10.,ky_m_day=10.,kz_m_day=1.,ss_per_m=.003,porosity=.23)],
            assignments=[dict(material_id='rock',stratum_id='aquifer',cells=[[0,0,c] for c in range(3)])],
            initial_head_m=[15.]*3,periods=[dict(duration_day=1.25,nsteps=1,steady=True)],
            boundaries=[dict(kind='CHD',period=0,cell=[0,0,c],values={'head_m':h},label='authored_CHD_0_0_'+str(c)) for c,h in ((0,west),(2,east))])
        self.area('레거시 물 모델 JSON 초안').set_value(json.dumps(data)).run()
        self.button('레거시 물 모델 검증한 초안 적용').click().run()
        self.select('레거시 해석 엔진').set_value('mfnwt').run()
        self.select('레거시 선형 풀이 방법').set_value('gmres')
        self.text('레거시 엔진 실행 파일').set_value(MFNWT)
        output=self.base/'gmres-explicit'
        self.text('레거시 출력 폴더 (새 폴더)').set_value(str(output))
        self.button('지정 레거시 엔진 실제 실행').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        result=self.app.session_state['gx_classic_product_run']['result']
        self.assertEqual(result.summary['linear_solver'],'gmres')
        np.testing.assert_allclose(result.heads_m[0].reshape(-1),[west,(west+east)/2,east],rtol=0,atol=2e-9)
        self.select('레거시 선형 풀이 방법').set_value('xmd').run()
        with self.assertRaises(KeyError):self.app.session_state['gx_classic_product_run']
        self.assertTrue((output/'run.json').is_file())

    def test_inert_analysis_restore_resets_add_source_controls_and_retains_archived_bytes(self):
        from basinlens_ccs.subsurface.analysis import AnalysisVolume,write_analysis_bundle
        from basinlens_ccs.subsurface.model_workflow import load_workflow_case,WorkflowCase
        data=load_workflow_case(ROOT/'examples/workflow/layered_background_water.json').to_dict()
        data['project']['vertical_datum']='unknown'
        case=WorkflowCase.from_dict(data)
        volume=AnalysisVolume.from_arrays(case,[1.],np.full((1,*case.shape),12.),provenance='Authored inert archive UI regression; not solver/field data')
        bundle=write_analysis_bundle(volume.clip(time_day=1.),self.base/'authored-analysis')
        self.load('혼합 기반 프로젝트')
        next(x for x in self.app.checkbox if x.key=='gx_package_include_analysis').set_value(True)
        self.text('포함할 분석 묶음 폴더').set_value(str(bundle));self.app.run()
        self.text('혼합 프로젝트 저장 파일 (새 .blproj)').set_value(str(self.base/'analysis.blproj'))
        self.button('혼합 프로젝트 저장·실제 왕복 확인').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        archived=self.app.session_state['gx_package_product_saved']['bytes']
        next(x for x in self.app.file_uploader if x.key=='gx_package_open_upload').set_value(('analysis.blproj',archived,'application/zip'))
        self.button('혼합 프로젝트 다른 위치에 열기').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        self.assertFalse(self.app.session_state['gx_package_include_analysis'])
        self.assertEqual(self.app.session_state['gx_package_analysis_path'],'')
        self.assertFalse(self.app.session_state['gx_package_inert_analysis']['live_engine_state_restored'])
        shutil.rmtree(bundle)
        retain=next(x for x in self.app.checkbox if x.key=='gx_package_retain_analysis_files')
        retain.set_value(False).run()
        self.assertTrue(self.button('혼합 프로젝트 저장·실제 왕복 확인').disabled)
        self.button('혼합 프로젝트 다른 위치에 열기').click().run(timeout=120)
        self.assertTrue(next(x for x in self.app.checkbox if x.key=='gx_package_retain_analysis_files').value)
        self.text('혼합 프로젝트 저장 파일 (새 .blproj)').set_value(str(self.base/'analysis-resaved.blproj'))
        self.button('혼합 프로젝트 저장·실제 왕복 확인').click().run(timeout=120)
        self.assertEqual(list(self.app.exception),[]);self.assertEqual(list(self.app.error),[])
        self.assertTrue(self.app.session_state['gx_package_product_saved']['receipt']['roundtrip_verified'])

if __name__=='__main__':unittest.main()
