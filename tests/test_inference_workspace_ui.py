"""Bounded inference controls, independent hand results and actual MF6 fitting."""
from __future__ import annotations
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'inference_workspace.py'
AVAILABLE=all(importlib.util.find_spec(n) is not None for n in ('streamlit','plotly','flopy'))
MF6=os.environ.get('MF6_EXE') or shutil.which('mf6')


@unittest.skipUnless(AVAILABLE,'Inference UI requires optional Streamlit/Plotly/FloPy')
class InferenceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.app=AppTest.from_file(str(APP),default_timeout=120).run()
        self.clean()
    def clean(self):self.assertEqual(list(self.app.exception),[])
    def button(self,label):return next(x for x in self.app.button if x.label==label)
    def text(self,label):return next(x for x in self.app.text_input if x.label==label)
    def area(self,label):return next(x for x in self.app.text_area if x.label==label)
    def number(self,label):return next(x for x in self.app.number_input if x.label==label)
    def load(self,title):
        self.button(title+' 합성 예제 불러오기').click().run();self.clean()
        self.assertEqual(list(self.app.error),[])
    def apply(self,title,data):
        self.area(title+' 입력 초안 JSON').set_value(json.dumps(data)).run()
        self.button(title+' 검증한 초안 적용').click().run();self.clean()
        self.assertEqual(list(self.app.error),[])
    def absent(self,key):
        with self.assertRaises(KeyError):self.app.session_state[key]
    def geo_result(self):return self.app.session_state['ix_geo_product_result']['result']
    def cal_bundle(self):
        case,obs,settings=self.app.session_state['ix_cal_value'].documents()
        return {'case':case.to_dict(),'observations':obs,'settings':settings}
    def set_run(self,path,exe=None):
        self.text('보정 출력 폴더 (새 폴더)').set_value(str(path))
        self.text('보정 MF6 실행 파일').set_value(exe or MF6)
        self.app.run();self.button('명시한 예산으로 MF6 보정 시작').click().run();self.clean()

    def test_idle_explicit_import_and_bad_upload_preserve_last_valid(self):
        from basinlens_ccs.subsurface import calibration
        import inference_workspace as ui
        from inference_workspace import _history_row
        history=_history_row({'evaluation':1,'purpose':'authored namespace check','status':'completed','objective':9.,'parameters':{'objective':4.,'status':7.}})
        self.assertEqual(history['objective'],9.);self.assertEqual(history['status'],'completed')
        self.assertEqual(history['parameter:objective'],4.);self.assertEqual(history['parameter:status'],7.)
        bounded=self.base/'bounded-zip';bounded.mkdir();(bounded/'large.bin').write_bytes(b'x'*256)
        with patch.object(ui,'MAX_ZIP',128),self.assertRaises(ValueError):ui._archive(bounded)
        shutil.rmtree(bounded)
        self.assertEqual(len(self.app.tabs),2)
        self.assertEqual(len(self.app.get('plotly_chart')),0)
        with patch.object(calibration,'run_calibration',side_effect=AssertionError('load must not execute')):
            self.load('지구통계');self.load('물 모델 보정')
        self.assertEqual(list(self.base.iterdir()),[])
        original=copy.deepcopy(self.app.session_state['ix_geo_value'])
        upload=next(x for x in self.app.file_uploader if x.key=='ix_geo_upload')
        upload.set_value(('duplicate.json',b'{"queries":[],"queries":[]}','application/json'))
        self.button('지구통계 입력 불러오기').click().run();self.clean()
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state['ix_geo_value'],original)
        self.assertEqual(self.app.session_state['ix_geo_source'],'명시한 합성 예제')
        self.assertEqual(self.app.session_state['ix_geo_diagnostic']['error_type'],'ValueError')

    def test_known_ordinary_simple_kriging_mask_roundtrip_and_draft_invalidation(self):
        self.load('지구통계')
        self.button('명시적 크리깅 실행').click().run();self.clean()
        result=self.geo_result();rows=result.records
        self.assertEqual([r['supported'] for r in rows],[True,True,True,False])
        self.assertAlmostEqual(rows[1]['prediction'],3.,places=13)
        self.assertAlmostEqual(rows[1]['variance'],.8319087592754217,places=13)
        self.assertIsNone(rows[3]['prediction']);self.assertIsNone(rows[3]['variance'])
        self.assertEqual(next(c['unit'] for c in result.to_dict()['columns'] if c['name']=='variance'),'(m)^2')
        self.button('추론 결과 JSON·CSV 실제 왕복 확인').click().run();self.clean()
        self.assertTrue(self.app.session_state['ix_geo_product_receipt']['json_csv_semantic_equal'])
        original=copy.deepcopy(self.app.session_state['ix_geo_value'])
        self.area('지구통계 입력 초안 JSON').set_value('{"invalid":true}').run();self.clean()
        self.assertTrue(self.button('명시적 크리깅 실행').disabled)
        self.assertTrue(self.button('지구통계 검증한 초안 적용').disabled)
        self.absent('ix_geo_product_result')
        self.assertEqual(self.app.session_state['ix_geo_value'],original)
        changed=copy.deepcopy(original);changed['settings'].update(method='simple',mean=3.)
        self.apply('지구통계',changed)
        self.button('명시적 크리깅 실행').click().run();self.clean()
        self.assertEqual(self.geo_result().to_dict()['metadata']['settings']['method'],'simple')
        self.assertAlmostEqual(self.geo_result().records[1]['prediction'],3.,places=13)

    def test_variogram_conditioned_gaussian_seed_and_independent_lhs(self):
        self.load('지구통계')
        self.button('실험 베리오그램 계산').click().run();self.clean()
        rows=self.geo_result().records
        active=next(r for r in rows if r['pair_count'])
        self.assertEqual(active['pair_count'],1);self.assertAlmostEqual(active['semivariance'],2.)
        self.button('선언한 가우스 확률장 생성').click().run();self.clean()
        first=self.geo_result().to_dict()
        rows=self.geo_result().records
        for row,value in ((rows[0],2.),(rows[2],4.)):
            self.assertAlmostEqual(row['conditional_variance'],0.)
            for name,draw in row.items():
                if name.startswith('r') and name[1:].isdigit():self.assertAlmostEqual(draw,value,places=12)
        self.button('선언한 가우스 확률장 생성').click().run();self.clean()
        self.assertEqual(self.geo_result().to_dict(),first)
        self.number('추론 표본 시드').set_value(43).run();self.absent('ix_geo_product_result')
        self.button('독립 LHS 표본 생성').click().run();self.clean()
        result=self.geo_result().to_dict();rows=self.geo_result().records
        self.assertEqual(len(rows),32)
        strata=sorted(int((r['K']-1.)/4.*32) for r in rows)
        self.assertEqual(strata,list(range(32)))
        self.assertTrue(all(.1<=r['phi']<=.4 for r in rows))
        self.button('독립 LHS 표본 생성').click().run();self.clean()
        self.assertEqual(self.geo_result().to_dict(),result)
        self.area('LHS 독립 주변분포 JSON').set_value(json.dumps([{'name':'prediction','unit':'m','distribution':'uniform','parameters':{'minimum':1.,'maximum':5.}},{'name':'r0000','unit':'1','distribution':'uniform','parameters':{'minimum':0.,'maximum':1.}}])).run()
        self.absent('ix_geo_product_result')
        self.button('독립 LHS 표본 생성').click().run();self.clean()
        self.assertEqual(self.geo_result().to_dict()['operation'],'latin_hypercube')
        self.assertIn('prediction',self.geo_result().records[0])

    def test_missing_engine_source_mismatch_and_invalid_draft_are_recoverable(self):
        self.load('물 모델 보정');original=self.cal_bundle()
        out=self.base/'not-started'
        self.set_run(out,'no-basinlens-mf6-inference-ui')
        self.assertTrue(self.app.error);self.assertFalse(out.exists())
        self.absent('ix_cal_product_run');self.absent('ix_cal_product_failure')
        bad=copy.deepcopy(original);bad['observations']['case_sha256']='0'*64
        upload=next(x for x in self.app.file_uploader if x.key=='ix_cal_upload')
        upload.set_value(('wrong-source.json',json.dumps(bad).encode(),'application/json'))
        self.button('물 모델 보정 입력 불러오기').click().run();self.clean()
        self.assertTrue(self.app.error);self.assertEqual(self.cal_bundle(),original)
        self.area('물 모델 보정 입력 초안 JSON').set_value('{"case":{}}').run();self.clean()
        self.assertTrue(self.button('명시한 예산으로 MF6 보정 시작').disabled)
        self.assertTrue(self.button('물 모델 보정 검증한 초안 적용').disabled)
        self.assertEqual(self.cal_bundle(),original)

    @unittest.skipUnless(MF6,'Actual MF6 required for conductivity recovery')
    def test_actual_mf6_k4_recovery_history_download_and_native_tamper_invalidation(self):
        self.load('물 모델 보정');original=self.cal_bundle();out=self.base/'actual-k4'
        self.set_run(out);self.assertEqual(list(self.app.error),[])
        product=self.app.session_state['ix_cal_product_run'];result=product['result']
        self.assertEqual(result['status'],'completed')
        self.assertAlmostEqual(result['best_parameters']['Kx'],4.,delta=.01)
        self.assertLess(result['training']['rmse_m'],.0002)
        self.assertLess(result['withheld']['rmse_m'],.0002)
        self.assertEqual(result['withheld']['count'],1)
        self.assertTrue(result['initial_sensitivity']['locally_identifiable'])
        self.assertTrue(result['final_sensitivity']['locally_identifiable'])
        self.assertEqual(len(product['history']),result['evaluations_consumed'])
        self.assertEqual(min(r['objective'] for r in product['history'] if r['status']=='completed'),result['objective'])
        self.assertEqual(self.cal_bundle(),original)
        archive=zipfile.ZipFile(io.BytesIO(product['zip']))
        saved=json.loads(archive.read('source/observations.json'))
        self.assertEqual(saved,original['observations'])
        self.assertIn('fitted_case.json',archive.namelist())
        labels={x.label for x in self.app.get('download_button')}
        self.assertIn('보류 잔차 CSV 다운로드',labels)
        self.assertIn('보정 평가 이력 CSV 다운로드',labels)
        native=next((out/'runs').rglob('flow.hds'));native.write_bytes(native.read_bytes()+b'altered')
        self.app.run();self.clean();self.assertTrue(self.app.error)
        self.absent('ix_cal_product_run')
        self.assertNotIn('보정 실행·진단 기록 ZIP 다운로드',{x.label for x in self.app.get('download_button')})
        self.assertEqual(self.cal_bundle(),original)

    @unittest.skipUnless(MF6,'Actual MF6 identity and evaluations required for budget paths')
    def test_expired_deadline_retains_verified_failure_then_explicit_budget_limited_run(self):
        from basinlens_ccs.subsurface import calibration
        self.load('물 모델 보정');out=self.base/'expired'
        self.text('보정 MF6 실행 파일').set_value(MF6)
        self.text('보정 출력 폴더 (새 폴더)').set_value(str(out)).run()
        clock=SimpleNamespace(monotonic=iter([0.,301.]).__next__)
        with patch.object(calibration,'time',clock),patch.object(calibration,'run_workflow',side_effect=AssertionError('expired deadline must not run')):
            self.button('명시한 예산으로 MF6 보정 시작').click().run()
        self.clean();self.assertTrue(self.app.error)
        failed=self.app.session_state['ix_cal_product_failure']
        self.assertEqual(failed['result']['status'],'failed')
        self.assertEqual(failed['result']['evaluations_consumed'],0)
        self.assertFalse(failed['verification']['solver_executed_by_verifier'])
        self.assertFalse(failed['verification']['native_residuals_recomputed'])
        archive=zipfile.ZipFile(io.BytesIO(failed['zip']))
        self.assertIn('manifest.json',archive.namelist());self.assertIn('source/observations.json',archive.namelist())
        changed=self.cal_bundle();changed['settings']['max_evaluations']=12
        self.apply('물 모델 보정',changed);self.absent('ix_cal_product_failure')
        self.set_run(self.base/'budget-12');self.assertEqual(list(self.app.error),[])
        result=self.app.session_state['ix_cal_product_run']['result']
        self.assertEqual(result['stop_reason'],'evaluation_budget')
        self.assertLessEqual(result['evaluations_consumed'],12)
        self.assertTrue(any('평가 예산' in x.value for x in self.app.warning))
        self.assertFalse(any('전역 최적성' not in x.value for x in self.app.success))
        # A different fully valid bundle at the same path must not authorize
        # stale cached tables or ZIP bytes from the preceding successful fit.
        budget=self.base/'budget-12';shutil.rmtree(budget);shutil.copytree(out,budget)
        self.assertEqual(calibration.verify_calibration_bundle(budget)['status'],'failed')
        self.app.run();self.clean();self.assertTrue(self.app.error)
        self.absent('ix_cal_product_run')
        self.assertNotIn('보정 실행·진단 기록 ZIP 다운로드',{x.label for x in self.app.get('download_button')})
        self.text('보정 MF6 실행 파일').set_value('changed-no-engine').run()
        self.absent('ix_cal_product_run')


if __name__=='__main__':unittest.main()
