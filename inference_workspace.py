"""Explicit stochastic inference and bounded synthetic water calibration UI."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
ROOT=Path(__file__).resolve().parent
if str(ROOT/'src') not in sys.path:sys.path.insert(0,str(ROOT/'src'))
MAX_JSON=2*1024*1024
MAX_ZIP=128*1024*1024


def _raw(value):
    return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()


def _decode(payload):
    if not isinstance(payload,bytes) or not payload or len(payload)>MAX_JSON:raise ValueError('JSON은 1 byte 이상 2 MiB 이하여야 합니다.')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('Duplicate JSON key')
            value[key]=item
        return value
    def invalid(v):raise ValueError('Nonfinite JSON number')
    value=json.loads(payload.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
    def check(item,depth=0):
        if depth>32:raise ValueError('JSON nesting exceeds 32')
        if isinstance(item,float) and not np.isfinite(item):raise ValueError('Nonfinite JSON number')
        if isinstance(item,dict):
            for x in item.values():check(x,depth+1)
        elif isinstance(item,list):
            if len(item)>100_000:raise ValueError('JSON list budget exceeded')
            for x in item:check(x,depth+1)
    check(value);return value


def _clear(prefix):
    for key in list(st.session_state):
        if key.startswith(prefix+'_product') or key==prefix+'_unverified_failure':st.session_state.pop(key,None)


def _diagnose(prefix,stage,error,path=None):
    st.session_state[prefix+'_diagnostic']={'stage':stage,'error_type':type(error).__name__,'message':str(error),
        'path':None if path is None else str(path),'recovery':'입력·엔진·예산을 확인하고 새 출력 경로에서 명시적으로 다시 실행하세요.',
        'gms_parity_established':False}
    st.error(stage+': '+str(error))


def _diagnostic(prefix):
    if prefix+'_diagnostic' in st.session_state:
        with st.expander('마지막 실패·재개 조건 · '+prefix):
            value=st.session_state[prefix+'_diagnostic'];st.json(value)
            st.download_button('진단 JSON 다운로드 · '+prefix,_raw(value),prefix+'-diagnostic.json','application/json')


def _archive(root):
    from basinlens_ccs.subsurface.project_package import _path_no_links,_read_file
    root=_path_no_links(root,directory=True)
    buffer=io.BytesIO();total=0;paths=[];entries=0
    for path in root.rglob('*'):
        entries+=1
        if entries>10000:raise ValueError('ZIP 경로 항목 10,000개 제한')
        if path.is_symlink():raise ValueError('ZIP에 심볼릭 링크를 포함할 수 없습니다.')
        if path.is_file():
            paths.append(path)
            if len(paths)>5000:raise ValueError('ZIP 5000파일 제한')
        elif not path.is_dir():raise ValueError('ZIP에는 일반 파일과 폴더만 포함할 수 있습니다.')
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as out:
        for path in sorted(paths):
            payload=_read_file(path,MAX_ZIP-total);total+=len(payload)
            if total>MAX_ZIP:raise ValueError('ZIP 128 MiB 제한')
            out.writestr(path.relative_to(root).as_posix(),payload)
            if buffer.tell()>MAX_ZIP:raise ValueError('ZIP 크기 제한')
    if buffer.tell()>MAX_ZIP:raise ValueError('ZIP 크기 제한')
    return buffer.getvalue()


def _geo_validate(data):
    from basinlens_ccs.subsurface import geostatistics as gs
    from basinlens_ccs.subsurface.scatter import ScatterDataset
    if not isinstance(data,dict) or set(data)!={'observations','covariance','settings','queries'}:raise ValueError('observations/covariance/settings/queries 네 문서가 필요합니다.')
    dataset=ScatterDataset.from_dict(data['observations']);model=gs.CovarianceModel.from_dict(data['covariance'])
    gs._observations(dataset,model)
    gs._coordinates(data['queries'],model.to_dict()['dimension'],'queries')
    settings=data['settings'];expected={'method','mean','radius_m','min_neighbors','max_neighbors','domain_bounds_m','allow_extrapolation'}
    if not isinstance(settings,dict) or set(settings)!=expected:raise ValueError('명시적 크리깅 설정 필드가 필요합니다.')
    if settings['method'] not in ('ordinary','simple'):raise ValueError('ordinary/simple 방법을 선택하세요.')
    if settings['method']=='ordinary' and settings['mean'] is not None:raise ValueError('ordinary 방법의 mean은 null이어야 합니다.')
    if settings['method']=='simple':gs._number(settings['mean'],'known mean')
    if gs._number(settings['radius_m'],'radius_m',limit=1e10)<=0:raise ValueError('양의 검색 반경이 필요합니다.')
    gs._integer(settings['min_neighbors'],1,gs.MAX_NEIGHBORS,'min_neighbors')
    gs._integer(settings['max_neighbors'],settings['min_neighbors'],gs.MAX_NEIGHBORS,'max_neighbors')
    gs._bounds(settings['domain_bounds_m'],model.to_dict()['dimension'])
    if type(settings['allow_extrapolation']) is not bool:raise ValueError('외삽 허용 여부를 명시하세요.')
    return {'observations':dataset.to_dict(),'covariance':model.to_dict(),'settings':settings,'queries':data['queries']}


def _read_json(path):
    from basinlens_ccs.subsurface.project_package import _read_file
    return _decode(_read_file(path,MAX_JSON))


def _geo_example():
    directory=ROOT/'examples/geostatistics'
    return _geo_validate({name:_read_json(directory/filename) for name,filename in (
        ('observations','synthetic_observations.json'),('covariance','covariance.json'),('settings','settings.json'),('queries','queries.json'))})


def _cal_validate(data):
    from basinlens_ccs.subsurface.calibration import CalibrationProblem
    from basinlens_ccs.subsurface.model_workflow import WorkflowCase
    if not isinstance(data,dict) or set(data)!={'case','observations','settings'}:raise ValueError('case/observations/settings 세 문서가 필요합니다.')
    return CalibrationProblem.from_documents(WorkflowCase.from_dict(data['case']),data['observations'],data['settings'])


def _cal_dict(problem):
    case,observations,settings=problem.documents()
    return {'case':case.to_dict(),'observations':observations,'settings':settings}


def _set(prefix,value,source,serializer):
    _clear(prefix);st.session_state[prefix+'_value']=value;st.session_state[prefix+'_source']=source
    st.session_state[prefix+'_draft']=_raw(serializer(value)).decode()


def _editor(prefix,title,example,validator,serializer=lambda x:x):
    if st.button(title+' 합성 예제 불러오기',key=prefix+'_example'):
        try:_set(prefix,example(),'명시한 합성 예제',serializer)
        except Exception as error:_diagnose(prefix,title+' 예제',error)
    upload=st.file_uploader(title+' 입력 묶음 JSON (2 MiB)',type=['json'],key=prefix+'_upload')
    if st.button(title+' 입력 불러오기',key=prefix+'_load'):
        try:
            if upload is None or upload.size>MAX_JSON:raise ValueError('2 MiB 이하 JSON을 선택하세요.')
            _set(prefix,validator(_decode(upload.getvalue())),'검증한 업로드',serializer)
        except Exception as error:_diagnose(prefix,title+' 불러오기',error)
    value=st.session_state.get(prefix+'_value')
    if value is None:_diagnostic(prefix);return None,False
    st.caption('적용한 입력: '+st.session_state[prefix+'_source'])
    text=st.text_area(title+' 입력 초안 JSON',height=240,key=prefix+'_draft',max_chars=MAX_JSON,on_change=_clear,args=(prefix,))
    draft=None
    try:draft=validator(_decode(text.encode()))
    except Exception as error:st.error(title+' 초안 오류: '+str(error))
    changed=draft is None or serializer(draft)!=serializer(value)
    if changed:_clear(prefix)
    if st.button(title+' 검증한 초안 적용',disabled=draft is None,key=prefix+'_apply'):
        _clear(prefix);value=draft;st.session_state[prefix+'_value']=value;st.session_state[prefix+'_source']='검증해 적용한 편집 초안';changed=False
    if changed:st.warning('유효한 초안을 적용한 뒤 실행할 수 있습니다.')
    st.download_button(title+' 적용 입력 JSON 다운로드',_raw(serializer(value)),prefix+'-input.json','application/json')
    return value,not changed


def _show_geostatistic(prefix,product):
    from basinlens_ccs.subsurface.geostatistics import save_result,verify_result_roundtrip,MAX_BYTES
    from basinlens_ccs.subsurface.project_package import _read_file
    result=product['result'];data=result.to_dict();frame=pd.DataFrame(result.records)
    columns={c['name']:c['unit'] for c in data['columns']}
    st.caption('열 단위: '+', '.join(k+' ('+v+')' for k,v in columns.items()))
    st.dataframe(frame,use_container_width=True,hide_index=True)
    if data['operation']=='kriging':
        supported=frame[frame.supported]
        if not supported.empty:
            fig=go.Figure(go.Scatter(x=supported.x_m,y=supported.prediction,mode='markers+lines',name='예측'))
            fig.update_xaxes(title='x (m)');fig.update_yaxes(title='예측 ('+columns['prediction']+')')
            st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
            variance=go.Figure(go.Scatter(x=supported.x_m,y=supported.variance,mode='markers',name='모형 기반 예측오차 분산'))
            variance.update_xaxes(title='x (m)');variance.update_yaxes(title=columns['variance'])
            st.plotly_chart(variance,use_container_width=True,key=prefix+'_variance')
    elif data['operation']=='experimental_variogram':
        fig=go.Figure(go.Scatter(x=frame.mean_distance_m,y=frame.semivariance,mode='markers',text=frame.pair_count))
        fig.update_xaxes(title='점쌍 평균 거리 (m)');fig.update_yaxes(title=columns['semivariance'])
        st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
    elif data['operation']=='gaussian_field':
        fig=go.Figure()
        for name in [c for c in frame if c.startswith('r')][:16]:fig.add_trace(go.Scatter(x=frame.x_m,y=frame[name],mode='markers+lines',name=name))
        fig.update_xaxes(title='x (m)');fig.update_yaxes(title=columns['r0000'])
        st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
    elif len(frame.columns)>1:
        names=[c for c in frame if c!='sample_id']
        fig=go.Figure(go.Scatter(x=frame[names[0]],y=frame[names[1]] if len(names)>1 else frame.sample_id,mode='markers'))
        fig.update_xaxes(title=names[0]+' ('+columns[names[0]]+')')
        fig.update_yaxes(title=(names[1]+' ('+columns[names[1]]+')') if len(names)>1 else '표본 ID')
        st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
    with tempfile.TemporaryDirectory(prefix='basinlens-inference-csv-') as directory:
        csv_path=Path(directory)/'inference.csv';save_result(result,csv_path)
        csv_bytes=_read_file(csv_path,MAX_BYTES)
    st.download_button('추론 결과 CSV 다운로드',csv_bytes,'inference.csv','text/csv')
    st.download_button('추론 설정·출처 포함 JSON 다운로드',_raw(data),'inference.json','application/json')
    with st.expander('모형·지지·시드·단위 근거'):
        st.json(data['metadata'])
    if st.button('추론 결과 JSON·CSV 실제 왕복 확인',key=prefix+'_roundtrip'):
        try:st.session_state[prefix+'_product_receipt']=verify_result_roundtrip(result)
        except Exception as error:_diagnose(prefix,'추론 결과 왕복',error)
    if prefix+'_product_receipt' in st.session_state:st.json(st.session_state[prefix+'_product_receipt'])


def _geostatistics():
    from basinlens_ccs.subsurface import geostatistics as gs
    from basinlens_ccs.subsurface.scatter import ScatterDataset
    prefix='ix_geo'
    st.subheader('명시적 공분산 기반 추론·표본')
    st.info('정상성·평균·공분산을 사용자가 선언한 제한된 크리깅과 확률장입니다. 표시한 분산은 해당 모형 가정 아래의 예측오차이며 측정한 지질 불확실성이나 현장 검증이 아닙니다.')
    bundle,enabled=_editor(prefix,'지구통계',_geo_example,_geo_validate)
    if bundle is None:return
    dataset=ScatterDataset.from_dict(bundle['observations']);model=gs.CovarianceModel.from_dict(bundle['covariance']);meta=dataset.to_dict()
    st.caption(f"좌표 m · 값 {meta['value_unit']} · CRS: {meta['crs']} · 기준면: {meta['vertical_datum']} · 방법: {bundle['settings']['method']}")
    a,b=st.columns(2)
    bins=st.text_input('실험 베리오그램 거리 경계 JSON','[0,1,2,3]',key=prefix+'_bins')
    seed=st.number_input('추론 표본 시드',min_value=0,max_value=2**31-1,value=42,key=prefix+'_seed')
    draws=st.number_input('가우스 확률장 실현 수',min_value=1,max_value=256,value=8,key=prefix+'_draws')
    mean=st.number_input('가우스 확률장 선언 평균',value=3.,key=prefix+'_mean')
    conditional=st.checkbox('가우스 확률장을 적용한 관측점에 조건화',value=True,key=prefix+'_conditional')
    st.caption('가우스 확률장은 선언한 queries 좌표 모두에서 생성하며 관측점의 외곽에도 조건부 값을 만들 수 있습니다. 지정한 시드·공분산·평균 가정에 따른 모의입니다.')
    marginals=st.text_area('LHS 독립 주변분포 JSON',json.dumps([{'name':'K','unit':'m/day','distribution':'uniform','parameters':{'minimum':1.,'maximum':5.}},{'name':'phi','unit':'1','distribution':'triangular','parameters':{'minimum':.1,'mode':.2,'maximum':.4}}]),key=prefix+'_marginals')
    samples=st.number_input('LHS 표본 수',min_value=1,max_value=4096,value=32,key=prefix+'_samples')
    request=hashlib.sha256(_raw([bundle,bins,seed,draws,mean,conditional,marginals,samples])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    action=None
    for column,label,code in ((a,'명시적 크리깅 실행','kriging'),(b,'실험 베리오그램 계산','variogram')):
        if column.button(label,disabled=not enabled,key=prefix+'_'+code):action=code
    c,d=st.columns(2)
    if c.button('선언한 가우스 확률장 생성',disabled=not enabled,key=prefix+'_gaussian'):action='gaussian'
    if d.button('독립 LHS 표본 생성',disabled=not enabled,key=prefix+'_lhs'):action='lhs'
    if action:
        _clear(prefix)
        try:
            if action=='kriging':result=gs.krige(dataset,bundle['queries'],model,**bundle['settings'])
            elif action=='variogram':result=gs.experimental_variogram(dataset,_decode(bins.encode()))
            elif action=='gaussian':result=gs.gaussian_field(bundle['queries'],model,mean=mean,seed=int(seed),realizations=int(draws),metadata={'crs':meta['crs'],'vertical_datum':meta['vertical_datum'],'provenance':['User-declared synthetic covariance experiment; no field verification']},conditioning=dataset if conditional else None)
            else:result=gs.latin_hypercube(_decode(marginals.encode()),samples=int(samples),seed=int(seed))
            st.session_state[prefix+'_product_result']={'result':result}
        except Exception as error:_diagnose(prefix,'지구통계 '+action,error)
    if prefix+'_product_result' in st.session_state:_show_geostatistic(prefix,st.session_state[prefix+'_product_result'])
    _diagnostic(prefix)


def _history_row(record):
    return {'evaluation':record['evaluation'],'purpose':record['purpose'],'status':record['status'],
        'objective':record.get('objective'),'training_sse':record.get('training',{}).get('data_sse'),
        'withheld_sse':record.get('withheld',{}).get('data_sse'),
        **{'parameter:'+name:value for name,value in record['parameters'].items()},
        'error':record.get('error',{}).get('message')}


def _capture_calibration(path,result,verification,problem):
    """Bind cached tables/downloads to the exact verified manifest and result."""
    from basinlens_ccs.subsurface.project_package import _read_file
    root=Path(path).expanduser().absolute()
    saved=_read_json(root/'result.json')
    if saved!=result:raise ValueError('반환된 보정 결과와 저장한 결과가 다릅니다.')
    manifest_hash=hashlib.sha256(_read_file(root/'manifest.json',MAX_JSON)).hexdigest()
    result_hash=hashlib.sha256(_read_file(root/'result.json',MAX_JSON)).hexdigest()
    inputs=_cal_dict(problem)
    for name,value in inputs.items():
        if _read_json(root/'source'/(name+'.json'))!=value:raise ValueError('실행 기록의 입력이 선택한 보정 문제와 다릅니다.')
    paths=sorted((root/'evaluations').glob('*.json'))
    if len(paths)>100:raise ValueError('보정 평가 기록 100회 제한')
    history=[]
    for path in paths:
        record=_read_json(path)
        history.append(_history_row(record))
    return {'path':str(root),'result':saved,'verification':verification,'manifest_sha256':manifest_hash,'result_sha256':result_hash,'input':inputs,
            'history':history,'zip':_archive(root)}


def _calibration():
    from basinlens_ccs.subsurface.calibration import load_calibration_problem,run_calibration,verify_calibration_bundle
    prefix='ix_cal'
    st.subheader('실제 MF6를 사용하는 제한된 합성 보정')
    st.info('선언한 물성 1–3개만 정해진 범위에서 탐색합니다. 훈련/보류 관측을 분리하고 유한차분 민감도와 목적함수를 기록합니다. PEST·전역 최적성·식별가능성의 일반 보장·원본 GMS 동등성은 미구현입니다.')
    example=lambda:load_calibration_problem(*(ROOT/'examples/calibration'/('steady_'+name+'.json') for name in ('case','observations','settings')))
    problem,enabled=_editor(prefix,'물 모델 보정',example,_cal_validate,_cal_dict)
    if problem is None:return
    case,observations,settings=problem.documents()
    st.caption(f"좌표/수두 m · 시간 day · CRS: {case.to_dict()['project']['crs']} · 기준면: {case.to_dict()['project']['vertical_datum']}")
    st.dataframe(pd.DataFrame(settings['parameters']),use_container_width=True,hide_index=True)
    st.caption(f"실패·민감도 계산을 포함해 최대 {settings['max_evaluations']}회 · 총 {settings['max_total_seconds']:g}초 · 각 엔진 실행 {settings['per_run_timeout_seconds']:g}초 · 훈련 {len(settings['training_ids'])}개 / 보류 {len(settings['withheld_ids'])}개")
    st.caption('위 JSON 초안을 편집·적용하면 예산과 분리 기준을 명시적으로 바꿀 수 있습니다. 입력을 불러올 때 엔진을 실행하지 않습니다.')
    exe=st.text_input('보정 MF6 실행 파일',os.environ.get('MF6_EXE','mf6'),key=prefix+'_exe')
    output=st.text_input('보정 출력 폴더 (새 폴더)','build/calibration',key=prefix+'_output')
    request=hashlib.sha256(_raw([_cal_dict(problem),exe,output])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    if st.button('명시한 예산으로 MF6 보정 시작',disabled=not enabled,key=prefix+'_run'):
        _clear(prefix);existed=Path(output).expanduser().exists()
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            result=run_calibration(problem,output,exe_name=exe.strip())
            verification=verify_calibration_bundle(output)
            st.session_state[prefix+'_product_run']=_capture_calibration(output,result,verification,problem)
        except Exception as error:
            _diagnose(prefix,'MF6 보정',error,output)
            if not existed:
                try:
                    verification=verify_calibration_bundle(output)
                    result=_read_json(Path(output)/'result.json')
                    if result.get('status')!='failed':raise ValueError('현재 실패 시도의 기록이 아닙니다.')
                    st.session_state[prefix+'_product_failure']=_capture_calibration(output,result,verification,problem)
                except Exception as diagnostic_error:
                    st.session_state[prefix+'_unverified_failure']={'path':output,'reason':str(diagnostic_error)}
    products=st.session_state.get(prefix+'_product_run') or st.session_state.get(prefix+'_product_failure')
    if products and enabled:
        try:
            verify_calibration_bundle(products['path'])
            from basinlens_ccs.subsurface.project_package import _read_file
            current=hashlib.sha256(_read_file(Path(products['path'])/'manifest.json',MAX_JSON)).hexdigest()
            if current!=products['manifest_sha256']:raise ValueError('표시한 보정 기록의 출처 manifest가 바뀌었습니다. 새 출력에서 다시 실행하세요.')
            current_result=hashlib.sha256(_read_file(Path(products['path'])/'result.json',MAX_JSON)).hexdigest()
            if current_result!=products['result_sha256'] or _cal_dict(problem)!=products['input']:raise ValueError('표시한 보정 결과 또는 선택한 입력이 바뀌었습니다.')
            for name,value in products['input'].items():
                if _read_json(Path(products['path'])/'source'/(name+'.json'))!=value:raise ValueError('보정 기록의 입력 출처가 바뀌었습니다.')
        except Exception as error:
            _clear(prefix);_diagnose(prefix,'보정 기록 원본 재확인',error,products['path']);products=None
        if products:
            result=products['result']
            st.caption(f"실행 기록: {products['path']} · 엔진: {result['engine']['name']} · 평가 {result['evaluations_consumed']}회 · 종료: {result.get('stop_reason',result.get('error',{}).get('message','unknown'))}")
            if result['status']=='completed':
                if result.get('stop_reason')=='evaluation_budget':st.warning('평가 예산에 도달하여 탐색을 마쳤습니다. 가장 좋은 실제 평가를 보존했으며 수렴·통계적 적합을 확정하지 않습니다.')
                else:st.success('선언한 범위의 보정 실행을 마쳤습니다. 전역 최적성·통계적 적합·현장·원본 GMS 검증은 미완료입니다.')
                st.dataframe(pd.DataFrame([result['best_parameters']]),use_container_width=True,hide_index=True)
                a,b=st.columns(2)
                for col,name in ((a,'training'),(b,'withheld')):
                    with col:
                        st.write('훈련' if name=='training' else '보류')
                        summary=result.get(name,{})
                        st.json({k:v for k,v in summary.items() if k!='rows'})
                        if summary.get('rows'):
                            frame=pd.DataFrame(summary['rows']);st.dataframe(frame,use_container_width=True,hide_index=True)
                            st.download_button(('훈련' if name=='training' else '보류')+' 잔차 CSV 다운로드',frame.to_csv(index=False).encode(),name+'-residuals.csv','text/csv')
                with st.expander('유한차분 민감도·식별·목적함수 근거'):
                    for name in ('initial_sensitivity','final_sensitivity','objective','prior_sse','evaluations_consumed','successful_evaluations','failed_evaluations'):
                        if name in result:st.write(name);st.json(result[name])
                residuals=result.get('training',{}).get('rows',[])+result.get('withheld',{}).get('rows',[])
                if residuals:
                    fig=go.Figure(go.Scatter(x=[r['observed_head_m'] for r in residuals],y=[r['simulated_head_m'] for r in residuals],mode='markers',text=[r['id'] for r in residuals]))
                    fig.update_xaxes(title='선언한 관측 수두 (m)');fig.update_yaxes(title='시뮬레이션 수두 (m)')
                    st.plotly_chart(fig,use_container_width=True,key=prefix+'_fit_plot')
            else:st.error('보정이 중단되었습니다. 저장된 시도·평가·실패 기록과 재개 조건을 확인하세요.')
            history=pd.DataFrame(products['history'])
            if not history.empty:
                st.write('실제 평가 이력 · 목적함수는 훈련 잔차의 제곱합 + 선언한 사전 항')
                st.dataframe(history,use_container_width=True,hide_index=True)
                accepted=history[history.status=='completed']
                if not accepted.empty:
                    fig=go.Figure(go.Scatter(x=accepted.evaluation,y=accepted.objective,mode='markers+lines'))
                    fig.update_xaxes(title='실제 엔진 평가 순서');fig.update_yaxes(title='무차원 목적함수')
                    st.plotly_chart(fig,use_container_width=True,key=prefix+'_history_plot')
                st.download_button('보정 평가 이력 CSV 다운로드',history.to_csv(index=False).encode(),'calibration-history.csv','text/csv')
            st.download_button('보정 실행·진단 기록 ZIP 다운로드',products['zip'],'calibration-record.zip','application/zip')
            st.download_button('보정 결과 근거 JSON 다운로드',_raw(result),'calibration-result.json','application/json')
            st.caption('설정·원본 관측·평가별 엔진 입력/출력은 실행 기록에 포함됩니다. 자동 재개 없이 수정한 조건으로 새 폴더에서 시작합니다.')
    if prefix+'_unverified_failure' in st.session_state:
        st.caption('완전한 무결성이 확인되지 않은 실패 경로입니다. 이 경로의 기록을 성공 결과로 사용하지 않습니다.')
        st.json(st.session_state[prefix+'_unverified_failure'])
    _diagnostic(prefix)


def render_inference_workspace():
    st.subheader('공분산 추론 · 제한된 물 모델 보정')
    tabs=st.tabs(['지구통계·확률 표본','실제 MF6 보정'])
    with tabs[0]:_geostatistics()
    with tabs[1]:_calibration()


if __name__=='__main__':
    st.set_page_config(page_title='BasinLens · 추론 작업공간',layout='wide')
    render_inference_workspace()
