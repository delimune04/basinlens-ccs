"""Explicit, bounded geoscience tools; ``streamlit run geoscience_workspace.py``."""
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

ROOT = Path(__file__).resolve().parent
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))
MAX_JSON = 2 * 1024 * 1024
MAX_DOWNLOAD = 128 * 1024 * 1024


def _raw(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def _decode(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_JSON:
        raise ValueError('JSON은 1 byte 이상 2 MiB 이하여야 합니다.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON value')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    def check(v, depth=0):
        if depth > 32:
            raise ValueError('JSON nesting exceeds 32')
        if isinstance(v, float) and not np.isfinite(v):
            raise ValueError('Nonfinite JSON number')
        if isinstance(v, dict):
            for x in v.values(): check(x, depth + 1)
        elif isinstance(v, list):
            if len(v) > 100_000: raise ValueError('JSON list budget exceeded')
            for x in v: check(x, depth + 1)
    check(value)
    return value


def _clear(prefix):
    for key in list(st.session_state):
        if key.startswith(prefix + '_product'):
            st.session_state.pop(key, None)


def _error(prefix, stage, error, path=None):
    st.session_state[prefix + '_diagnostic'] = {
        'stage': stage, 'error_type': type(error).__name__, 'message': str(error),
        'output_path': None if path is None else str(path),
        'recovery': '입력/자료 경로/엔진을 수정하고 새 출력 경로에서 다시 실행하세요.',
        'gms_parity_established': False}
    st.error(f'{stage}: {error}')


def _diagnostic(prefix):
    value = st.session_state.get(prefix + '_diagnostic')
    if value:
        with st.expander('마지막 작업 진단 · ' + prefix):
            st.json(value)
            st.download_button('진단 JSON · ' + prefix, _raw(value), prefix + '-diagnostic.json',
                               'application/json', key=prefix + '_diagnostic_download')


def _load_bytes(payload, loader, suffix='.json'):
    if not payload or len(payload) > MAX_JSON:
        raise ValueError('업로드는 2 MiB 이하여야 합니다.')
    with tempfile.TemporaryDirectory(prefix='basinlens-gx-read-') as temporary:
        path = Path(temporary) / ('document' + suffix)
        path.write_bytes(payload)
        return loader(path)


def _set_document(prefix, document, source):
    _clear(prefix)
    st.session_state[prefix + '_document'] = document
    st.session_state[prefix + '_source'] = source
    st.session_state[prefix + '_draft'] = _raw(document.to_dict()).decode()


def _document(prefix, title, example, loader, *, csv=False):
    pending = st.session_state.pop(prefix + '_pending_document', None)
    if pending is not None:
        _set_document(prefix, pending, '검증해 적용한 편집 기록')
    left, right = st.columns(2)
    if left.button(title + ' 합성 예제 불러오기', key=prefix + '_load_example'):
        try: _set_document(prefix, loader(ROOT / example), '합성 예제 ' + example)
        except Exception as error: _error(prefix, title + ' 예제 읽기', error)
    upload = right.file_uploader(title + ' 파일 (2 MiB)', type=['json', 'csv'] if csv else ['json'],
                                 key=prefix + '_upload')
    if right.button(title + ' 업로드 불러오기', key=prefix + '_load_upload'):
        try:
            if upload is None: raise ValueError('파일을 선택하세요.')
            if upload.size > MAX_JSON: raise ValueError('업로드는 2 MiB 이하여야 합니다.')
            _set_document(prefix, _load_bytes(upload.getvalue(), loader, Path(upload.name).suffix.lower()),
                          '검증한 업로드 ' + upload.name)
        except Exception as error: _error(prefix, title + ' 업로드 읽기', error)
    document = st.session_state.get(prefix + '_document')
    if document is None:
        st.session_state[prefix+'_applied_ready']=False
        _diagnostic(prefix)
        return None, False
    st.caption('적용한 자료: ' + st.session_state[prefix + '_source'])
    draft_text = st.text_area(title + ' JSON 초안', key=prefix + '_draft', height=180,
                              max_chars=MAX_JSON, on_change=_clear, args=(prefix,))
    draft, validation_error = None, None
    try:
        # Parse through the backend loader, including duplicate-key and asset checks.
        _decode(draft_text.encode())
        draft = _load_bytes(draft_text.encode(), loader)
    except Exception as error:
        validation_error = error
        st.error(f'{title} 초안 오류: {error}')
    changed = draft is None or draft.to_dict() != document.to_dict()
    if changed: _clear(prefix)
    if st.button(title + ' 검증한 초안 적용', key=prefix + '_apply', disabled=draft is None):
        _clear(prefix)
        document = draft
        st.session_state[prefix + '_document'] = document
        st.session_state[prefix + '_source'] = '검증해 적용한 편집 초안'
        changed = False
    if changed: st.warning('초안을 검증해 적용한 뒤 이 자료의 작업을 실행할 수 있습니다.')
    st.download_button(title + ' 적용 JSON 다운로드', _raw(document.to_dict()), prefix + '.json',
                       'application/json', key=prefix + '_json_download')
    ready=not changed and validation_error is None
    st.session_state[prefix+'_applied_ready']=ready
    return document,ready


def _plot_xy(fig, key, units='m'):
    fig.update_xaxes(title='x (' + units + ')', constrain='domain')
    fig.update_yaxes(title='y (' + units + ')', scaleanchor='x', scaleratio=1)
    st.plotly_chart(fig, use_container_width=True, key=key)


def _archive(root):
    from basinlens_ccs.subsurface.workspace_archive import create_workspace_zip
    return create_workspace_zip(root, max_bytes=MAX_DOWNLOAD)


def _geology():
    from basinlens_ccs.subsurface.geology import (load_geology, project_section, edit_interval_material,
                                                 export_geology_csv)
    prefix = 'gx_geo'
    st.caption('수직 시추공·명시한 로그 구간과 지층 ID만 다룹니다. 지질면을 추정하지 않습니다.')
    asset_root = st.text_input('지질 참조자료 서버 폴더', str(ROOT / 'examples/geology'), key=prefix + '_asset_root')
    loader = lambda path: load_geology(path, asset_root=asset_root.strip() or None).project
    document, enabled = _document(prefix, '시추·지질', 'examples/geology/synthetic_boreholes.json', loader)
    if document is None: return
    data = document.to_dict()
    st.caption(f"m · Z 위쪽 · CRS: {data['crs']} · 기준면: {data['vertical_datum']}")
    figure = go.Figure()
    for hole in data['boreholes']:
        for interval in hole['intervals']:
            figure.add_trace(go.Scatter3d(x=[hole['x_m']] * 2, y=[hole['y_m']] * 2,
                z=[hole['z_m'] - interval['top_depth_m'], hole['z_m'] - interval['bottom_depth_m']],
                mode='lines', line={'width': 8, 'dash': 'dash' if interval['kind'] == 'gap' else 'solid'},
                name=f"{hole['id']} · {interval['id']} · {interval['material_id'] or '기록 없음'}"))
    figure.update_layout(scene={'xaxis_title':'x (m)', 'yaxis_title':'y (m)', 'zaxis_title':'고도 (m)', 'aspectmode':'data'})
    st.plotly_chart(figure, use_container_width=True, key=prefix + '_boreholes')
    line = st.text_area('시추 단면 XY 선 JSON', '[[0,0],[10,0],[10,10]]', key=prefix + '_line')
    distance = st.number_input('시추 단면 최대 거리 (m)', min_value=0., value=5., key=prefix + '_distance')
    section_request = hashlib.sha256(_raw([line, distance, document.to_dict()])).hexdigest()
    if st.session_state.get(prefix + '_section_request') != section_request:
        st.session_state.pop(prefix + '_product_section', None)
        st.session_state[prefix + '_section_request'] = section_request
    if st.button('시추 단면 투영', disabled=not enabled, key=prefix + '_section'):
        try: st.session_state[prefix + '_product_section'] = project_section(document, _decode(line.encode()), max_distance_m=distance)
        except Exception as error: _error(prefix, '시추 단면', error)
    section = st.session_state.get(prefix + '_product_section')
    if section:
        fig = go.Figure()
        for hole in section['boreholes']:
            for interval in hole['intervals']:
                fig.add_trace(go.Scatter(x=[hole['chainage_m']] * 2, y=[interval['top_z_m'], interval['bottom_z_m']],
                    mode='lines', line={'width':8}, name=hole['borehole_id'] + '/' + interval['id']))
        fig.update_xaxes(title='단면 거리 (m)'); fig.update_yaxes(title='고도 (m)')
        st.plotly_chart(fig, use_container_width=True, key=prefix + '_section_plot')
        st.json({k:v for k,v in section.items() if k != 'boreholes'})
        st.download_button('시추 단면 JSON 다운로드', _raw(section), 'borehole-section.json', 'application/json')
    a, b, c = st.columns(3)
    hole_id = a.selectbox('편집할 시추공', [h['id'] for h in data['boreholes']], key=prefix + '_hole')
    selected_hole = next(h for h in data['boreholes'] if h['id'] == hole_id)
    interval_id = b.selectbox('편집할 로그 구간', [i['id'] for i in selected_hole['intervals'] if i['kind'] == 'logged'], key=prefix + '_interval')
    material_id = c.selectbox('적용할 지질 물질', [m['id'] for m in data['materials']], key=prefix + '_material')
    reason = st.text_input('지질 편집 근거', '사용자가 선언한 해석 변경', key=prefix + '_reason')
    provenance = st.selectbox('지질 편집 출처 ID', [p['id'] for p in data['provenance']], key=prefix + '_provenance')
    if st.button('로그 물질 변경 적용', disabled=not enabled, key=prefix + '_edit'):
        try:
            updated = edit_interval_material(document, hole_id, interval_id, material_id, reason=reason, provenance_id=provenance)
            st.session_state[prefix + '_pending_document'] = updated
            st.rerun()
        except Exception as error: _error(prefix, '로그 물질 변경', error)
    output = st.text_input('지질 CSV 저장 폴더 (새 폴더)', 'build/geology-csv', key=prefix + '_output')
    if st.button('지질 CSV·참조자료 내보내기', disabled=not enabled, key=prefix + '_save'):
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True, exist_ok=True)
            export_geology_csv(document, output, asset_root=asset_root.strip() or None)
            st.session_state[prefix + '_product_zip'] = _archive(output)
        except Exception as error: _error(prefix, '지질 CSV 내보내기', error, output)
    if prefix + '_product_zip' in st.session_state:
        st.download_button('지질 CSV 묶음 다운로드', st.session_state[prefix + '_product_zip'], 'geology-csv.zip', 'application/zip')
    _diagnostic(prefix)


def _features():
    from basinlens_ccs.subsurface.features import load_coverage, feature_table, move_point, grid_extent
    prefix = 'gx_map'
    st.caption('명시한 점·노드·호·다각형과 속성의 개념 모델입니다. 자동 경계조건 변환은 수행하지 않습니다.')
    document, enabled = _document(prefix, '개념 피처', 'examples/features/local_coverage.json', load_coverage)
    if document is None: return
    data = document.to_dict(); coords = data['coordinate_system']
    st.caption(f"좌표 단위: {coords['units']} · CRS: {coords['crs']} · 축: {coords['axis_order']}")
    nodes = {n['id']: [n['x'], n['y']] for n in data['nodes']}
    figure = go.Figure()
    for polygon in data['polygons']:
        for index, ids in enumerate([polygon['shell'], *polygon['holes']]):
            xy = np.asarray([nodes[i] for i in ids])
            figure.add_trace(go.Scatter(x=xy[:,0], y=xy[:,1], mode='lines', name=polygon['id'] + (' 외곽' if index == 0 else ' 구멍')))
    for arc in data['arcs']:
        xy = np.asarray([nodes[i] for i in arc['node_ids']])
        figure.add_trace(go.Scatter(x=xy[:,0], y=xy[:,1], mode='lines+markers', name=arc['id']))
    for point in data['points']:
        figure.add_trace(go.Scatter(x=[point['x']], y=[point['y']], mode='markers+text', text=[point['id']], name=point['id']))
    _plot_xy(figure, prefix + '_plot', coords['units'])
    table = pd.DataFrame(feature_table(document))
    table['attributes'] = table['attributes'].map(lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
    st.dataframe(table, use_container_width=True, hide_index=True)
    if coords['units'] == 'm': st.json(grid_extent(document))
    st.caption('추가·이동·삭제·속성 편집은 위 JSON 초안을 수정하고 검증하여 적용할 수 있습니다.')
    _diagnostic(prefix)


def _scatter():
    from basinlens_ccs.subsurface.scatter import (load_scatter, interpolate_idw, interpolate_nearest,
        interpolate_tin, edit_values, dataset_math, save_scatter, verify_scatter_roundtrip)
    prefix = 'gx_scatter'
    st.caption('최근접·거리역수 가중(IDW)·명시적 TIN 보간입니다. IDW/최근접은 원본 좌표의 축 정렬 상자 밖을 마스킹합니다. TIN은 명시한 삼각형 밖을 마스킹하며 불확실성을 추정하지 않습니다.')
    document, enabled = _document(prefix, '산점 자료', 'examples/scatter/synthetic_plane.json', load_scatter, csv=True)
    if document is None: return
    data = document.to_dict()
    st.caption(f"{data['quantity']} ({data['value_unit']}) · 좌표 m · CRS: {data['crs']} · 기준면: {data['vertical_datum']}")
    st.dataframe(pd.DataFrame(data['points']), use_container_width=True, hide_index=True)
    query_text = st.text_area('산점 질의 좌표 JSON', '[[0,0],[0.5,0.5],[2,2]]', key=prefix + '_queries')
    method = st.selectbox('산점 보간 방법', ['idw','nearest','tin'], key=prefix + '_method')
    a,b,c = st.columns(3)
    power = a.number_input('IDW 지수', min_value=.1, max_value=16., value=2., key=prefix + '_power')
    neighbors = b.number_input('산점 최대 이웃 수', min_value=1, max_value=1000, value=8, key=prefix + '_neighbors')
    radius = c.number_input('산점 반경 (m, 0은 제한 없음)', min_value=0., value=0., key=prefix + '_radius')
    vertical_scale = st.number_input('산점 수직 거리 배율 (3D만, 무차원)', min_value=.001, max_value=1000., value=1., disabled=data['dimension']==2, key=prefix + '_vertical_scale')
    minimum = st.number_input('IDW 최소 이웃 수', min_value=1, max_value=1000, value=1, key=prefix + '_minimum')
    triangles = st.text_area('명시적 TIN 삼각형 점 ID JSON', '[["p0","p1","p2"],["p1","p3","p2"]]', key=prefix + '_triangles')
    settings = [query_text,method,power,neighbors,radius,vertical_scale,minimum,triangles,document.sha256]
    request = hashlib.sha256(_raw(settings)).hexdigest()
    if st.session_state.get(prefix + '_request') != request:
        _clear(prefix); st.session_state[prefix + '_request'] = request
    if st.button('산점 보간 질의 실행', disabled=not enabled, key=prefix + '_query'):
        try:
            points = _decode(query_text.encode())
            if method == 'tin': result = interpolate_tin(document, points, _decode(triangles.encode()))
            elif method == 'nearest': result = interpolate_nearest(document, points, radius_m=radius or None, vertical_scale=vertical_scale if data['dimension']==3 else 1., bounds_policy='mask')
            else: result = interpolate_idw(document, points, power=power, max_neighbors=int(neighbors), min_neighbors=int(minimum), radius_m=radius or None, vertical_scale=vertical_scale if data['dimension']==3 else 1., bounds_policy='mask')
            st.session_state[prefix + '_product_query'] = result
        except Exception as error: _error(prefix, '산점 질의', error)
    result = st.session_state.get(prefix + '_product_query')
    if result:
        frame = pd.DataFrame(result['rows'])
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.json(result['receipt'])
        st.download_button('산점 질의 CSV 다운로드', frame.to_csv(index=False).encode(), 'scatter-query.csv','text/csv')
        st.download_button('산점 질의 근거 JSON 다운로드',_raw(result),'scatter-query.json','application/json')
        supported = [row for row in result['rows'] if row['supported']]
        if supported:
            xy=np.asarray([r['coordinates_m'] for r in supported]); vals=[r['value'] for r in supported]
            marker={'color':vals,'showscale':True,'colorbar':{'title':data['value_unit']}}
            if data['dimension']==3:
                fig=go.Figure(go.Scatter3d(x=xy[:,0],y=xy[:,1],z=xy[:,2],mode='markers',marker=marker))
                fig.update_layout(scene={'xaxis_title':'x (m)','yaxis_title':'y (m)','zaxis_title':'고도 (m)','aspectmode':'data'})
                st.plotly_chart(fig,use_container_width=True,key=prefix+'_query_plot')
            else:
                fig=go.Figure(go.Scatter(x=xy[:,0],y=xy[:,1],mode='markers',marker=marker))
                _plot_xy(fig,prefix + '_query_plot')
    st.caption('산점 값 편집은 출처와 부모 해시를 기록합니다. 자료 연산은 점 ID·좌표·단위가 호환될 때만 수행합니다.')
    a,b,c=st.columns(3)
    point_id=a.selectbox('편집할 산점 ID',[p['id'] for p in data['points']],key=prefix+'_edit_id')
    new_value=b.number_input('편집할 산점 값',value=0.,key=prefix+'_edit_value')
    missing=c.checkbox('산점 값을 결측으로 변경',key=prefix+'_edit_missing')
    missing_reason=st.text_input('산점 결측 사유','사용자가 선언한 자료 없음',key=prefix+'_missing_reason')
    if st.button('산점 값 변경 적용',disabled=not enabled,key=prefix+'_edit'):
        try:
            updated=edit_values(document,{point_id:None if missing else new_value},missing_reason=missing_reason)
            st.session_state[prefix+'_pending_document']=updated
            st.rerun()
        except Exception as error:_error(prefix,'산점 값 편집',error)
    right_upload=st.file_uploader('산점 연산 두 번째 자료 (JSON/CSV, 2 MiB)',type=['json','csv'],key=prefix+'_math_right')
    operator=st.selectbox('산점 자료 연산자',['-','+','*','/'],key=prefix+'_operator')
    same=st.checkbox('현재 자료를 두 번째 피연산자로 사용',value=True,key=prefix+'_math_same')
    result_quantity=st.text_input('산점 연산 결과 물리량',data['quantity'],key=prefix+'_math_quantity')
    result_unit=st.text_input('산점 연산 결과 단위',data['value_unit'],key=prefix+'_math_unit')
    if st.button('산점 자료 연산 실행', disabled=not enabled, key=prefix + '_math'):
        try:
            if same:right=document
            elif right_upload is not None and right_upload.size<=MAX_JSON:
                right=_load_bytes(right_upload.getvalue(),load_scatter,Path(right_upload.name).suffix.lower())
            else:raise ValueError('두 번째 자료를 선택하거나 현재 자료 사용을 지정하세요.')
            out=dataset_math(document,operator,right,result_id=data['id']+'-computed',result_quantity=result_quantity,result_unit=result_unit)
            st.session_state[prefix + '_product_math']=out.to_dict()
        except Exception as error:_error(prefix,'산점 자료 연산',error)
    if prefix + '_product_math' in st.session_state:
        st.json(st.session_state[prefix+'_product_math'])
        st.download_button('산점 연산 자료 JSON 다운로드',_raw(st.session_state[prefix+'_product_math']),'scatter-math.json','application/json')
    _diagnostic(prefix)


def _mesh():
    from basinlens_ccs.subsurface.mesh import structured_mesh, refine_quadtree, extrude_mesh, render_data, topology
    prefix='gx_mesh'
    st.caption('비균일 직교·삼각 격자 생성, 사각 격자 선택 세분화, 명시적 평탄 층의 닫힌 프리즘입니다. 지질면 보간이나 일반 비정형 격자 생성은 지원하지 않습니다.')
    x=st.text_input('격자 x 경계 좌표 JSON (m)','[0,1,3]',key=prefix+'_x')
    y=st.text_input('격자 y 경계 좌표 JSON (m)','[0,2,5]',key=prefix+'_y')
    crs=st.text_input('생성 격자 CRS','unknown',key=prefix+'_crs')
    triangles=st.checkbox('직교 셀을 삼각형으로 나누기',key=prefix+'_triangles')
    if st.button('비균일 평면 격자 생성',key=prefix+'_generate'):
        try:
            mesh=structured_mesh(_decode(x.encode()),_decode(y.encode()),crs=crs,triangulate='sw_ne' if triangles else None)
            st.session_state[prefix+'_mesh']=mesh;_clear(prefix)
        except Exception as error:_error(prefix,'격자 생성',error)
    mesh=st.session_state.get(prefix+'_mesh')
    if mesh is None:return
    bbox=st.text_input('격자 세분화 영역 [xmin,ymin,xmax,ymax]','[0,0,1,2]',key=prefix+'_bbox')
    levels=st.number_input('격자 세분화 단계',min_value=1,max_value=4,value=1,key=prefix+'_levels')
    if st.button('선택 영역 사각 격자 세분화',key=prefix+'_refine'):
        try:
            mesh=refine_quadtree(mesh,levels=int(levels),bbox_m=_decode(bbox.encode()))
            st.session_state[prefix+'_mesh']=mesh;_clear(prefix)
        except Exception as error:_error(prefix,'격자 세분화',error)
    actual=mesh.to_dict();vertices=actual['vertices']
    bounds=[min(v['x_m'] for v in vertices),min(v['y_m'] for v in vertices),max(v['x_m'] for v in vertices),max(v['y_m'] for v in vertices)]
    st.caption(f"현재 생성·보존한 격자: CRS {actual['crs']} · 범위 [xmin,ymin,xmax,ymax] {bounds} m. 위 생성 입력은 생성 버튼을 눌러 적용하며, 세분화·압출은 이 보존한 격자에 적용합니다.")
    info=render_data(mesh);figure=go.Figure()
    for cell in info['cells'][:2000]:
        xy=np.asarray(cell['ring_m']);figure.add_trace(go.Scatter(x=xy[:,0],y=xy[:,1],mode='lines',name=str(cell['id']),showlegend=False))
    _plot_xy(figure,prefix+'_planar')
    st.caption('최대 첫 2,000개의 실제 닫힌 셀 테두리를 표시합니다. 전체 연결성은 JSON에 포함됩니다.')
    st.json({k:v for k,v in topology(mesh).items() if k not in ('areas_m2','centres_m','boundary_edges','interior_edges')})
    st.download_button('생성 평면 격자 JSON 다운로드',_raw(mesh.to_dict()),'mesh.json','application/json')
    surfaces=st.text_input('압출 층 경계 고도 JSON (m)','[10,0,-20]',key=prefix+'_surfaces')
    datum=st.text_input('압출 수직 기준면','unknown',key=prefix+'_datum')
    extrusion_request = hashlib.sha256(_raw([surfaces, datum, mesh.to_dict()])).hexdigest()
    if st.session_state.get(prefix+'_extrusion_request') != extrusion_request:
        st.session_state.pop(prefix+'_product_extruded',None)
        st.session_state[prefix+'_extrusion_request'] = extrusion_request
    if st.button('닫힌 프리즘 격자 압출',key=prefix+'_extrude'):
        try:st.session_state[prefix+'_product_extruded']=extrude_mesh(mesh,_decode(surfaces.encode()),vertical_datum=datum)
        except Exception as error:_error(prefix,'격자 압출',error)
    extruded=st.session_state.get(prefix+'_product_extruded')
    if extruded:
        nodes=extruded['nodes'];verts=np.asarray([[n['x_m'],n['y_m'],n['z_m']] for n in nodes]);i=[];j=[];k=[]
        for cell in extruded['cells'][:2000]:
            for face in cell['faces']:
                for offset in range(1,len(face)-1):i.append(face[0]);j.append(face[offset]);k.append(face[offset+1])
        fig=go.Figure(go.Mesh3d(x=verts[:,0],y=verts[:,1],z=verts[:,2],i=i,j=j,k=k,opacity=.55))
        fig.update_layout(scene={'xaxis_title':'x (m)','yaxis_title':'y (m)','zaxis_title':'고도 (m)','aspectmode':'data'})
        st.plotly_chart(fig,use_container_width=True,key=prefix+'_prisms')
        st.json({k:v for k,v in extruded.items() if k not in ('nodes','cells')})
        st.download_button('닫힌 프리즘 격자 JSON 다운로드',_raw(extruded),'prism-mesh.json','application/json')
    _diagnostic(prefix)


def _analysis():
    from basinlens_ccs.subsurface.analysis import load_analysis_run, write_analysis_bundle, verify_analysis_bundle
    prefix='gx_analysis'
    st.caption('검증한 공간 워크플로 실행만 불러옵니다. 셀/중심 보간·단면·중심 기준 가시성 클립·수동 잔차이며 자동 보정은 수행하지 않습니다.')
    path=st.text_input('검증할 MF6 워크플로 실행 폴더','',key=prefix+'_path')
    requested_path = str(Path(path).expanduser().absolute()) if path.strip() else None
    if st.session_state.get(prefix+'_requested_path') != requested_path:
        _clear(prefix)
        st.session_state[prefix+'_active'] = False
        st.session_state[prefix+'_requested_path'] = requested_path
    if st.button('검증한 해석 결과 불러오기',key=prefix+'_load'):
        try:
            volume=load_analysis_run(path);st.session_state[prefix+'_volume']=volume;_clear(prefix)
            st.session_state[prefix+'_active'] = True
        except Exception as error:
            _clear(prefix);st.session_state[prefix+'_active'] = False
            _error(prefix,'해석 결과 불러오기',error,path)
    volume=st.session_state.get(prefix+'_volume')
    if volume is None:return
    active = st.session_state.get(prefix+'_active',False)
    if active:
        try:
            from basinlens_ccs.groundwater.native_run import verify_native_run
            if requested_path != str(Path(volume.source['workspace']).absolute()):
                raise ValueError('현재 경로와 캡처한 원본 실행 경로가 다릅니다. 명시적으로 다시 불러오세요.')
            metadata=verify_native_run(requested_path)
            if hashlib.sha256(_raw(metadata)).hexdigest()!=volume.source['run_metadata_sha256']:
                raise ValueError('캡처 뒤 원본 실행 기록이 변경되었습니다. 다시 검증해 불러오세요.')
        except Exception as error:
            active=False;_clear(prefix);st.session_state[prefix+'_active']=False
            _error(prefix,'후처리 원본 무결성 재확인',error,requested_path)
    if not active:st.warning('마지막 유효 결과는 비활성 상태로 보존했습니다. 현재 경로를 명시적으로 검증해 불러온 뒤 분석할 수 있습니다.')
    st.caption('파일 무결성·캡처한 입력 일치를 확인합니다. 분석 수치 재계산·현장 검증·원본 GMS 동등성 검증을 의미하지 않습니다.')
    spatial=volume.case.to_dict()['project']
    st.caption(f"후처리 좌표 m · 고도 Z 위쪽 · 수두 m · CRS: {spatial['crs']} · 기준면: {spatial['vertical_datum']} · 저장 시각 day: {volume.times_day.tolist()}")
    st.json(volume.source)
    time=st.selectbox('후처리 저장 시각 (day)',list(volume.times_day),key=prefix+'_time')
    points=st.text_area('후처리 XYZ 질의 JSON','[[105,210,-5],[999,999,-5]]',key=prefix+'_points')
    method=st.selectbox('후처리 공간 지지',['cell','linear_centres'],key=prefix+'_method')
    line=st.text_area('후처리 단면 XY JSON','[[105,210],[145,210]]',key=prefix+'_line')
    zs=st.text_input('후처리 단면 고도 JSON','[-5,-20]',key=prefix+'_zs')
    spacing=st.number_input('후처리 단면 간격 (m)',min_value=.01,value=5.,key=prefix+'_spacing')
    scalar=st.number_input('클립 최소 수두 (m)',value=10.5,key=prefix+'_scalar')
    plane=st.text_input('클립 평면 [nx,ny,nz,offset_m]','[1,0,0,-120]',key=prefix+'_plane')
    settings=[float(time),points,method,line,zs,spacing,scalar,plane,volume.case_sha256]
    request=hashlib.sha256(_raw(settings)).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    a,b,c=st.columns(3)
    if a.button('후처리 좌표 질의',disabled=not active,key=prefix+'_query'):
        try:st.session_state[prefix+'_product_result']=volume.query(_decode(points.encode()),time_day=float(time),spatial_method=method)
        except Exception as error:_error(prefix,'후처리 좌표 질의',error)
    if b.button('후처리 단면 추출',disabled=not active,key=prefix+'_section'):
        try:st.session_state[prefix+'_product_result']=volume.section(_decode(line.encode()),_decode(zs.encode()),spacing,time_day=float(time),spatial_method=method)
        except Exception as error:_error(prefix,'후처리 단면',error)
    if c.button('중심 기준 셀 클립',disabled=not active,key=prefix+'_clip'):
        try:st.session_state[prefix+'_product_result']=volume.clip(time_day=float(time),scalar_min=scalar,plane=_decode(plane.encode()))
        except Exception as error:_error(prefix,'후처리 클립',error)
    result=st.session_state.get(prefix+'_product_result')
    if result:
        frame=pd.DataFrame(result['rows']);st.dataframe(frame,use_container_width=True,hide_index=True)
        st.download_button('원본 파일 무결성 확인 후처리 CSV 다운로드',frame.to_csv(index=False).encode(),'analysis.csv','text/csv')
        st.download_button('후처리 근거 JSON 다운로드',_raw(result),'analysis.json','application/json')
        bundle_output = st.text_input('후처리 검증 묶음 폴더 (새 폴더)', 'build/result-analysis', key=prefix+'_output')
        if st.button('후처리 검증 묶음 저장', key=prefix+'_save_bundle'):
            try:
                written = write_analysis_bundle(result,bundle_output)
                verify_analysis_bundle(written)
                st.session_state[prefix+'_product_zip'] = _archive(written)
            except Exception as error: _error(prefix,'후처리 검증 묶음',error,bundle_output)
        if prefix+'_product_zip' in st.session_state:
            st.download_button('파일 무결성 확인 후처리 ZIP 다운로드',st.session_state[prefix+'_product_zip'],'analysis-bundle.zip','application/zip')
        valid=[r for r in result['rows'] if r.get('supported',r.get('visible',True))]
        if valid:
            fig=go.Figure(go.Scatter3d(x=[r['x_m'] for r in valid],y=[r['y_m'] for r in valid],z=[r['z_m'] for r in valid],mode='markers',marker={'color':[r['value'] for r in valid],'showscale':True}))
            fig.update_layout(scene={'xaxis_title':'x (m)','yaxis_title':'y (m)','zaxis_title':'고도 (m)'})
            st.plotly_chart(fig,use_container_width=True,key=prefix+'_result_plot')
    observations=st.file_uploader('관측 수두 JSON (2 MiB, 캡처한 모델 ID·해시·단위 일치 필수)',type=['json'],key=prefix+'_observations')
    observation_request = None if observations is None else (hashlib.sha256(observations.getvalue()).hexdigest() if observations.size <= MAX_JSON else 'over-budget')
    if st.session_state.get(prefix+'_observation_request') != observation_request:
        st.session_state.pop(prefix+'_product_comparison',None)
        st.session_state[prefix+'_observation_request'] = observation_request
    if st.button('관측 잔차·목적함수 계산',disabled=not active,key=prefix+'_compare'):
        try:
            if observations is None:raise ValueError('관측 JSON을 선택하세요. 합성값을 측정으로 생성하지 않습니다.')
            if observations.size>MAX_JSON:raise ValueError('관측 JSON 2 MiB 제한')
            st.session_state[prefix+'_product_comparison']=volume.compare_observations(_decode(observations.getvalue()))
        except Exception as error:_error(prefix,'관측 비교',error)
    comparison=st.session_state.get(prefix+'_product_comparison')
    if comparison:
        st.json(comparison['metrics']);st.dataframe(pd.DataFrame(comparison['rows']),use_container_width=True,hide_index=True)
        st.download_button('수동 관측 잔차 CSV 다운로드',pd.DataFrame(comparison['rows']).to_csv(index=False).encode(),'observations.csv','text/csv')
        st.download_button('관측 비교 근거 JSON 다운로드',_raw(comparison),'observation-comparison.json','application/json')
    _diagnostic(prefix)


def _classic():
    from basinlens_ccs.subsurface.classic import export_classic, verify_classic_export, run_classic, read_classic_results
    from basinlens_ccs.subsurface.model_workflow import load_workflow_case, preview_grid
    prefix='gx_classic'
    st.caption('공식 공개 엔진의 제한된 피압 단상 물 모델입니다. 알려진 해시의 MODFLOW-2005/NWT 배정만 실행하며 일반 레거시 입력 가져오기·비피압/건조·GMS 동등성은 미검증입니다.')
    case,enabled=_document(prefix,'레거시 물 모델','examples/workflow/layered_background_water.json',load_workflow_case)
    if case is None:return
    engine=st.selectbox('레거시 해석 엔진',['mf2005','mfnwt'],key=prefix+'_engine')
    methods=['pcg'] if engine=='mf2005' else ['xmd','gmres']
    if st.session_state.get(prefix+'_linear_solver',methods[0]) not in methods:
        st.session_state[prefix+'_linear_solver']=methods[0]
    linear_solver=st.selectbox('레거시 선형 풀이 방법',methods,key=prefix+'_linear_solver')
    st.caption('풀이 방법별 수렴 여부는 모델에 따라 다릅니다. 실패 진단을 확인해 방법을 직접 선택하고 새 출력에서 재실행하세요.')
    exe=st.text_input('레거시 엔진 실행 파일',os.environ.get('MF2005_EXE',''),key=prefix+'_exe')
    output=st.text_input('레거시 출력 폴더 (새 폴더)','build/classic-water',key=prefix+'_output')
    timeout=st.number_input('레거시 제한 시간 (초)',min_value=1,max_value=1800,value=300,key=prefix+'_timeout')
    classic_request = hashlib.sha256(_raw([case.to_dict(),engine,linear_solver,exe,timeout,output])).hexdigest()
    if st.session_state.get(prefix+'_request')!=classic_request:
        _clear(prefix);st.session_state[prefix+'_request']=classic_request
    a,b=st.columns(2)
    if a.button('레거시 입력 내보내기',disabled=not enabled,key=prefix+'_export'):
        _clear(prefix)
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            root=export_classic(case,output,engine=engine,linear_solver=linear_solver);verify_classic_export(root)
            st.session_state[prefix+'_product_export']={'bytes':_archive(root),'engine':engine}
        except Exception as error:_error(prefix,'레거시 입력 내보내기',error,output)
    if b.button('지정 레거시 엔진 실제 실행',disabled=not enabled,key=prefix+'_run'):
        _clear(prefix)
        try:
            if not exe.strip():raise ValueError('해당 엔진의 허용된 실행 파일 경로를 입력하세요.')
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            run_classic(case,output,engine=engine,exe_name=exe,timeout_seconds=int(timeout),linear_solver=linear_solver)
            result=read_classic_results(output)
            if result.case.to_dict()!=case.to_dict():raise ValueError('실행에 캡처한 모델 불일치')
            st.session_state[prefix+'_product_run']={'result':result,'zip':_archive(output),'path':output}
        except Exception as error:_error(prefix,'레거시 실제 실행',error,output)
    if prefix+'_product_export' in st.session_state:
        st.caption('입력 생성 엔진: '+st.session_state[prefix+'_product_export']['engine'])
        st.download_button('검증한 레거시 입력 ZIP 다운로드',st.session_state[prefix+'_product_export']['bytes'],'classic-input.zip','application/zip')
    products=st.session_state.get(prefix+'_product_run')
    if products and enabled:
        try:
            result=read_classic_results(products['path'])
            if result.case.to_dict()!=case.to_dict():raise ValueError('캡처한 레거시 원본 모델이 현재 모델과 다릅니다.')
        except Exception as error:
            _clear(prefix);_error(prefix,'레거시 원본 무결성 재확인',error,products['path']);_diagnostic(prefix)
            return
        spatial=result.case.to_dict()['project']
        st.caption(f"캡처한 엔진: {result.summary['engine']} · 좌표/수두 m · 시간 day · CRS: {spatial['crs']} · 기준면: {spatial['vertical_datum']}")
        st.json(result.summary)
        checks=('water_balance_passed','boundary_rates_passed','confined_saturation_support_passed')
        if all(result.summary.get(k) is True for k in checks):st.success('캡처한 레거시 실행의 물수지·경계 유량·포화 가정 판정 통과. GMS 동등성 미검증.')
        else:st.error('레거시 실행의 물수지·경계·포화 가정 중 통과하지 않은 판정이 있습니다.')
        layer=st.selectbox('레거시 결과 층',list(range(result.case.shape[0])),key=prefix+'_layer')
        time=st.selectbox('레거시 결과 시각 번호',list(range(len(result.times_day))),key=prefix+'_time')
        cells=pd.DataFrame(preview_grid(result.case)['cells']);heads=result.heads_m[time].reshape(-1)
        selected=cells.copy();selected['head_m']=heads;selected['time_day']=float(result.times_day[time])
        visible=selected[selected.layer==layer]
        fig=go.Figure(go.Scatter(x=visible.x_m,y=visible.y_m,mode='markers',marker={'color':visible.head_m,'showscale':True,'colorbar':{'title':'수두 (m)'}}))
        _plot_xy(fig,prefix+'_result_plot')
        st.dataframe(pd.DataFrame(result.budget),use_container_width=True,hide_index=True)
        st.download_button('레거시 선택 시각 수두 CSV 다운로드',selected.to_csv(index=False).encode(),'classic-heads.csv','text/csv')
        st.download_button('레거시 실행 기록 ZIP 다운로드',products['zip'],'classic-run.zip','application/zip')
    _diagnostic(prefix)



def _raster():
    from basinlens_ccs.subsurface.raster import (load_raster,sample_raster,clip_raster,
        resample_raster,merge_rasters,raster_to_scatter,export_ascii_bundle,open_ascii_bundle,verify_roundtrip)
    prefix='gx_raster'
    st.caption('명시적 m 좌표의 픽셀 중심 값입니다. 행 0은 북쪽이며 NODATA는 보간으로 메우지 않습니다. CRS 변환은 수행하지 않습니다.')
    grid,enabled=_document(prefix,'래스터','examples/raster/linear_head.json',load_raster)
    if grid is None:return
    g=dict(grid.geometry);values=np.array([[np.nan if v is None else v for v in row] for row in grid.values])
    xs=g['xllcorner_m']+(np.arange(g['ncol'])+.5)*g['dx_m']
    ys=g['yllcorner_m']+(g['nrow']-np.arange(g['nrow'])-.5)*g['dy_m']
    fig=go.Figure(go.Heatmap(x=xs,y=ys,z=values,colorbar={'title':grid.quantity+' ('+grid.unit+')'},hoverongaps=False))
    _plot_xy(fig,prefix+'_plot')
    st.caption(f'CRS: {grid.crs} · 기준면: {grid.vertical_datum} · 범위 {grid.extent} m · NODATA는 빈칸')
    method=st.selectbox('래스터 표본 방법',['nearest','bilinear'],key=prefix+'_method')
    query=st.text_area('래스터 XY 질의 JSON','[[101,201],[103,202],[999,999]]',key=prefix+'_query_points')
    request=hashlib.sha256(_raw([grid.to_dict(),method,query])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    if st.button('래스터 좌표 표본 추출',disabled=not enabled,key=prefix+'_query'):
        try:
            points=_decode(query.encode());out=sample_raster(grid,points,method=method)
            st.session_state[prefix+'_product_samples']=[{'x_m':p[0],'y_m':p[1],'value':v,'supported':v is not None} for p,v in zip(points,out)]
        except Exception as error:_error(prefix,'래스터 표본',error)
    if prefix+'_product_samples' in st.session_state:
        frame=pd.DataFrame(st.session_state[prefix+'_product_samples']);st.dataframe(frame,use_container_width=True,hide_index=True)
        st.download_button('래스터 표본 CSV 다운로드',frame.to_csv(index=False).encode(),'raster-samples.csv','text/csv')
    bbox=st.text_input('래스터 클립 범위 [xmin,ymin,xmax,ymax]','[100,200,104,204]',key=prefix+'_bbox')
    target=st.text_area('래스터 재표본 격자 JSON',json.dumps(g),key=prefix+'_target')
    a,b=st.columns(2)
    for column,label,action in ((a,'래스터 범위 클립 적용',lambda:clip_raster(grid,_decode(bbox.encode()))),
                                (b,'래스터 재표본 적용',lambda:resample_raster(grid,_decode(target.encode()),method=method))):
        if column.button(label,disabled=not enabled,key=prefix+'_'+('clip' if column is a else 'resample')):
            try:
                st.session_state[prefix+'_pending_document']=action();st.rerun()
            except Exception as error:_error(prefix,label,error)
    second=st.file_uploader('병합할 두 번째 래스터 JSON (2 MiB)',type=['json'],key=prefix+'_second')
    policy=st.selectbox('래스터 중복 셀 정책',['error','first','last'],key=prefix+'_policy')
    if st.button('래스터 병합 적용',disabled=not enabled,key=prefix+'_merge'):
        try:
            if second is None or second.size>MAX_JSON:raise ValueError('2 MiB 이하 두 번째 JSON을 선택하세요.')
            right=_load_bytes(second.getvalue(),load_raster)
            st.session_state[prefix+'_pending_document']=merge_rasters([grid,right],conflict_policy=policy,asset_id=grid.asset_id+'-merged')
            st.rerun()
        except Exception as error:_error(prefix,'래스터 병합',error)
    output=st.text_input('래스터 ASCII 저장 폴더 (새 폴더)','build/raster-ascii',key=prefix+'_output')
    if st.button('래스터 ASCII·JSON 왕복 확인',disabled=not enabled,key=prefix+'_export'):
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            export_ascii_bundle(grid,output)
            if open_ascii_bundle(output).to_dict()!=grid.to_dict():raise ValueError('ASCII 재열기 의미 불일치')
            receipt=verify_roundtrip(grid)
            st.session_state[prefix+'_product_export']={'receipt':receipt,'zip':_archive(output)}
        except Exception as error:_error(prefix,'래스터 내보내기',error,output)
    if prefix+'_product_export' in st.session_state:
        product=st.session_state[prefix+'_product_export'];st.json(product['receipt'])
        st.download_button('래스터 ASCII 묶음 다운로드',product['zip'],'raster-ascii.zip','application/zip')
    samples=raster_to_scatter(grid)
    st.download_button('래스터 유효 픽셀 중심 CSV 다운로드',pd.DataFrame(samples['points']).to_csv(index=False).encode(),'raster-centres.csv','text/csv')
    _diagnostic(prefix)


def _pointcloud():
    from basinlens_ccs.subsurface.pointcloud import (load_pointcloud,read_las,inspect_pointcloud,
        render_points,filter_points,aggregate_grid,verify_pointcloud_roundtrip)
    prefix='gx_cloud'
    st.caption('비압축 LAS 1.2 형식 0–3과 명시한 좌표 메타데이터를 사용합니다. VLR에서 CRS를 추측하지 않으며 LAZ는 지원하지 않습니다.')
    las=st.file_uploader('LAS 1.2 파일 (2 MiB)',type=['las'],key=prefix+'_las')
    metadata=st.text_area('LAS 좌표 메타데이터 JSON',json.dumps({'crs':'unknown','horizontal_unit':'unknown','vertical_unit':'unknown','vertical_datum':'unknown','provenance':['User-supplied metadata; unknown values remain unknown']}),key=prefix+'_metadata')
    if st.button('명시적 메타데이터로 LAS 불러오기',key=prefix+'_load_las'):
        try:
            if las is None or las.size>MAX_JSON:raise ValueError('2 MiB 이하 비압축 LAS를 선택하세요.')
            cloud=_load_bytes(las.getvalue(),lambda path:read_las(path,metadata=_decode(metadata.encode())),'.las')
            _set_document(prefix,cloud,'메타데이터를 명시해 불러온 LAS')
        except Exception as error:_error(prefix,'LAS 불러오기',error)
    cloud,enabled=_document(prefix,'점군','examples/pointcloud/synthetic_points.json',load_pointcloud)
    if cloud is None:return
    meta=cloud.metadata;rendered=render_points(cloud,max_points=10_000);pts=rendered['points']
    st.caption(f"수평 단위 {meta['horizontal_unit']} · 수직 단위 {meta['vertical_unit']} · CRS: {meta['crs']} · 기준면: {meta['vertical_datum']} · 표시 {rendered['rendered_count']}/{rendered['stored_count']}점")
    if pts:
        fig=go.Figure(go.Scatter3d(x=[p['x'] for p in pts],y=[p['y'] for p in pts],z=[p['z'] for p in pts],mode='markers',marker={'color':[p['classification'] for p in pts],'showscale':True,'colorbar':{'title':'LAS 분류'}}))
        fig.update_layout(scene={'xaxis_title':'x ('+meta['horizontal_unit']+')','yaxis_title':'y ('+meta['horizontal_unit']+')','zaxis_title':'z ('+meta['vertical_unit']+')','aspectmode':'data'})
        st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
    st.json(inspect_pointcloud(cloud))
    classes=st.text_input('점군 유지 분류 JSON (null은 전체)','[2]',key=prefix+'_classes')
    bounds=st.text_input('점군 XY 범위 JSON (null은 전체)','null',key=prefix+'_bbox')
    heights=st.text_input('점군 높이 범위 JSON (null은 전체)','null',key=prefix+'_height')
    if st.button('점군 분류·범위 필터 적용',disabled=not enabled,key=prefix+'_filter'):
        try:
            filtered=filter_points(cloud,classifications=_decode(classes.encode()),bbox=_decode(bounds.encode()),height=_decode(heights.encode()))
            st.session_state[prefix+'_pending_document']=filtered;st.rerun()
        except Exception as error:_error(prefix,'점군 필터',error)
    geometry=st.text_area('점군 집계 격자 JSON',json.dumps({'x_origin':1000.,'y_origin':2000.,'dx':1.,'dy':1.,'nrow':3,'ncol':3}),key=prefix+'_grid')
    statistic=st.selectbox('점군 집계 통계',['mean','min','max','count'],key=prefix+'_statistic')
    field=st.selectbox('점군 집계 값',['z','intensity'],key=prefix+'_field')
    request=hashlib.sha256(_raw([cloud.to_dict(),geometry,statistic,field])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    if st.button('점군 셀 집계',disabled=not enabled,key=prefix+'_aggregate'):
        try:
            grid=_decode(geometry.encode())
            if set(grid)!={'x_origin','y_origin','dx','dy','nrow','ncol'}:raise ValueError('집계 격자에는 위치·간격·행열 6필드가 필요합니다.')
            st.session_state[prefix+'_product_grid']=aggregate_grid(cloud,**grid,crs=meta['crs'],horizontal_unit=meta['horizontal_unit'],vertical_datum=meta['vertical_datum'],statistic=statistic,field=field)
        except Exception as error:_error(prefix,'점군 집계',error)
    if prefix+'_product_grid' in st.session_state:
        result=st.session_state[prefix+'_product_grid'];st.json(result)
        rg=result['grid'];z=[[np.nan if v is None else v for v in row] for row in result['values']]
        fig=go.Figure(go.Heatmap(x=rg['x_origin']+(np.arange(rg['ncol'])+.5)*rg['dx'],y=rg['y_origin']+(np.arange(rg['nrow'])+.5)*rg['dy'],z=z,hoverongaps=False,colorbar={'title':result['value_unit']}))
        _plot_xy(fig,prefix+'_grid_plot',meta['horizontal_unit'])
        st.caption('집계 행 0은 남쪽입니다. 빈 셀은 지지 없음이며 보간으로 채우지 않습니다.')
        st.download_button('점군 집계·지지 근거 JSON 다운로드',_raw(result),'pointcloud-grid.json','application/json')
    output=st.text_input('점군 LAS·JSON 저장 폴더 (새 폴더)','build/pointcloud-roundtrip',key=prefix+'_output')
    if st.button('점군 LAS·JSON 왕복 확인',disabled=not enabled,key=prefix+'_export'):
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            receipt=verify_pointcloud_roundtrip(cloud,output)
            st.session_state[prefix+'_product_export']={'receipt':receipt,'zip':_archive(output)}
        except Exception as error:_error(prefix,'점군 내보내기',error,output)
    if prefix+'_product_export' in st.session_state:
        product=st.session_state[prefix+'_product_export'];st.json(product['receipt'])
        st.download_button('점군 LAS·JSON 묶음 다운로드',product['zip'],'pointcloud-roundtrip.zip','application/zip')
    _diagnostic(prefix)


def _surfaces():
    from basinlens_ccs.subsurface.surfaces import (load_surfaces,query_surface,section_surfaces,
        extrude_solids,edit_vertices,smooth_horizon,export_surface_tables,import_surface_tables)
    prefix='gx_surface'
    st.caption('사용자가 지정한 XY 삼각형 연결성과 위·아래 지층면입니다. 지질 상관이나 지층면을 자동 추정하지 않으며 경계 밖에는 외삽하지 않습니다.')
    model,enabled=_document(prefix,'지층면','examples/surfaces/tilted_planes.json',load_surfaces)
    if model is None:return
    data=model.to_dict();xy={v['id']:(v['x_m'],v['y_m']) for v in data['vertices']};order={v['id']:i for i,v in enumerate(data['vertices'])}
    fig=go.Figure()
    for horizon in data['horizons']:
        triangles=[[order[i] for i in t['vertex_ids']] for t in data['triangles']]
        fig.add_trace(go.Mesh3d(x=[v['x_m'] for v in data['vertices']],y=[v['y_m'] for v in data['vertices']],z=horizon['elevations_m'],i=[t[0] for t in triangles],j=[t[1] for t in triangles],k=[t[2] for t in triangles],name=horizon['id'],opacity=.65))
    fig.update_layout(scene={'xaxis_title':'x (m)','yaxis_title':'y (m)','zaxis_title':'고도 (m)','aspectmode':'data'})
    st.plotly_chart(fig,use_container_width=True,key=prefix+'_plot')
    st.caption(f"m · Z 위쪽 · CRS: {data['crs']} · 기준면: {data['vertical_datum']}")
    horizon=st.selectbox('질의·편집할 지층면',[h['id'] for h in data['horizons']],key=prefix+'_horizon')
    queries=st.text_area('지층면 XY 질의 JSON','[[1,1],[99,99]]',key=prefix+'_queries')
    line=st.text_area('지층면 단면 XY JSON','[[-1,1],[5,1]]',key=prefix+'_line')
    request=hashlib.sha256(_raw([model.to_dict(),horizon,queries,line])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    a,b,c=st.columns(3)
    if a.button('지층면 고도 질의',disabled=not enabled,key=prefix+'_query'):
        try:st.session_state[prefix+'_product_query']=query_surface(model,horizon,_decode(queries.encode()))
        except Exception as error:_error(prefix,'지층면 질의',error)
    if b.button('지층면 단면 자르기',disabled=not enabled,key=prefix+'_section'):
        try:st.session_state[prefix+'_product_section']=section_surfaces(model,_decode(line.encode()))
        except Exception as error:_error(prefix,'지층면 단면',error)
    if c.button('명시적 지층면 사이 솔리드 생성',disabled=not enabled,key=prefix+'_solids'):
        try:st.session_state[prefix+'_product_solids']=extrude_solids(model)
        except Exception as error:_error(prefix,'지층 솔리드',error)
    for label,key in (('지층면 표본','query'),('지층면 단면','section'),('지층 솔리드','solids')):
        result=st.session_state.get(prefix+'_product_'+key)
        if result:
            st.json(result)
            st.download_button(label+' 근거 JSON 다운로드',_raw(result),'surface-'+key+'.json','application/json')
    section=st.session_state.get(prefix+'_product_section')
    if section:
        section_fig=go.Figure()
        for piece in section['pieces']:
            for band in piece['bands']:
                polygon=band['polygon_distance_elevation_m'];closed=polygon+[polygon[0]]
                section_fig.add_trace(go.Scatter(x=[p[0] for p in closed],y=[p[1] for p in closed],mode='lines',fill='toself',name=band['layer_id']+' · '+band['material_id']))
        section_fig.update_xaxes(title='전체 단면 거리 (m)');section_fig.update_yaxes(title='고도 (m)')
        st.plotly_chart(section_fig,use_container_width=True,key=prefix+'_section_plot')
        st.caption('지원되는 삼각형 안의 단면 조각만 표시하며 바깥·구멍 구간은 비워 둡니다.')
    solids=st.session_state.get(prefix+'_product_solids')
    if solids:
        vertices=[];ii=[];jj=[];kk=[]
        for solid in solids['solids'][:2000]:
            offset=len(vertices);vertices.extend(solid['vertices_xyz_m'])
            for face in solid['faces']:
                for index in range(1,len(face)-1):ii.append(offset+face[0]);jj.append(offset+face[index]);kk.append(offset+face[index+1])
        if vertices:
            xyz=np.asarray(vertices);solid_fig=go.Figure(go.Mesh3d(x=xyz[:,0],y=xyz[:,1],z=xyz[:,2],i=ii,j=jj,k=kk,opacity=.5))
            solid_fig.update_layout(scene={'xaxis_title':'x (m)','yaxis_title':'y (m)','zaxis_title':'고도 (m)','aspectmode':'data'})
            st.plotly_chart(solid_fig,use_container_width=True,key=prefix+'_solids_plot')
            st.caption('최대 첫 2,000개 닫힌 프리즘을 표시합니다. 인접 내부면은 겹쳐 보일 수 있으며 전체 연결성·체적은 JSON에 포함됩니다.')
    edits=st.text_input('지층면 정점 고도 편집 JSON (정점 ID:고도 m)','{"A":11}',key=prefix+'_edits')
    reason=st.text_input('지층면 편집·평활 근거','사용자가 선언한 대안 해석',key=prefix+'_reason')
    if st.button('지층면 정점 편집 적용',disabled=not enabled,key=prefix+'_edit'):
        try:
            st.session_state[prefix+'_pending_document']=edit_vertices(model,horizon_id=horizon,elevations=_decode(edits.encode()),reason=reason);st.rerun()
        except Exception as error:_error(prefix,'지층면 정점 편집',error)
    iterations=st.number_input('지층면 평활 반복 수',min_value=1,max_value=100,value=1,key=prefix+'_iterations')
    weight=st.number_input('지층면 평활 가중치',min_value=.001,max_value=1.,value=.5,key=prefix+'_weight')
    if st.button('경계 고정 지층면 수치 평활 적용',disabled=not enabled,key=prefix+'_smooth'):
        try:
            st.session_state[prefix+'_pending_document']=smooth_horizon(model,horizon,iterations=int(iterations),weight=weight,reason=reason);st.rerun()
        except Exception as error:_error(prefix,'지층면 평활',error)
    output=st.text_input('지층면 표 저장 폴더 (새 폴더)','build/surface-tables',key=prefix+'_output')
    if st.button('지층면 CSV 재열기 확인·내보내기',disabled=not enabled,key=prefix+'_export'):
        try:
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            export_surface_tables(model,output)
            if import_surface_tables(output).to_dict()!=model.to_dict():raise ValueError('지층면 표 의미 불일치')
            st.session_state[prefix+'_product_export']=_archive(output)
        except Exception as error:_error(prefix,'지층면 표 내보내기',error,output)
    if prefix+'_product_export' in st.session_state:
        st.download_button('지층면 표 묶음 다운로드',st.session_state[prefix+'_product_export'],'surface-tables.zip','application/zip')
    _diagnostic(prefix)


MIXED_OBJECTS=(('geology','boreholes','gx_geo'),('features','conceptual','gx_map'),
    ('scatter','scalar_points','gx_scatter'),('mesh','planar_mesh','gx_mesh'),
    ('raster','pixel_grid','gx_raster'),('pointcloud','encoded_points','gx_cloud'),
    ('surfaces','interpreted_horizons','gx_surface'))


def _restore_mixed_project():
    restored=st.session_state.pop('gx_package_pending_restore',None)
    if restored is None:return
    loaded,keeper=restored
    st.session_state['gx_package_include_analysis']=False
    st.session_state['gx_package_analysis_path']=''
    for key in list(st.session_state):
        if key.startswith('gx_package_retain_'):st.session_state.pop(key,None)
    for kind,object_id,prefix in MIXED_OBJECTS:
        st.session_state['gx_package_include_'+kind]=False
        _clear(prefix)
        for suffix in ('_document','_draft','_source','_pending_document','_applied_ready'):
            st.session_state.pop(prefix+suffix,None)
        if kind=='mesh':st.session_state.pop(prefix+'_mesh',None)
    st.session_state['gx_package_retained_objects']=list(loaded.objects)
    active_ids={}
    st.session_state.pop('gx_package_inert_analysis',None)
    for item in loaded.objects:
        entry=next((x for x in MIXED_OBJECTS if x[0]==item.kind),None)
        if entry is None:
            if item.kind=='analysis_archive':st.session_state['gx_package_inert_analysis']=item.value.to_dict()
            continue
        if item.kind in active_ids or (item.kind!='mesh' and len(_raw(item.value.to_dict()))>MAX_JSON):
            continue
        active_ids[item.kind]=item.object_id
        prefix=entry[2]
        if item.kind=='mesh':st.session_state[prefix+'_mesh']=item.value
        else:_set_document(prefix,item.value,'혼합 프로젝트에서 검증해 복원한 '+item.object_id)
        st.session_state['gx_package_include_'+item.kind]=True
    st.session_state['gx_package_active_ids']=active_ids
    _set_document('gx_package',loaded.project,'검증해 복원한 혼합 프로젝트')
    st.session_state['gx_package_asset_root']=str(loaded.asset_root)
    st.session_state['gx_geo_asset_root']=str(loaded.asset_root)
    st.session_state['gx_package_view']=_raw(loaded.view_state).decode()
    st.session_state['gx_package_receipt']=loaded.receipt
    _clear('gx_analysis');st.session_state['gx_analysis_active']=False
    st.session_state.pop('gx_analysis_volume',None)
    _clear('gx_classic')
    old=st.session_state.get('gx_package_keeper')
    st.session_state['gx_package_keeper']=keeper
    if old is not None:old.cleanup()


def _mixed_project():
    from basinlens_ccs.subsurface import load_project
    from basinlens_ccs.subsurface.geoscience_project import (ProjectObject,save_geoscience_project,
        open_geoscience_project,verify_geoscience_project_roundtrip,archive_analysis_bundle)
    prefix='gx_package'
    st.caption('공통 프로젝트와 선택한 형식별 자료를 하나의 자체 .blproj에 보존합니다. 좌표·기준면·단위가 다르면 저장을 거부하며 변환이나 해석 실행을 수행하지 않습니다.')
    assets=st.text_input('혼합 기반 프로젝트 참조자료 폴더',str(ROOT/'examples/geoscience_project'),key=prefix+'_asset_root')
    def base_loader(path):
        from basinlens_ccs.subsurface import project_package as bounded
        project=load_project(path,check_assets=False)
        _,project_bytes,expected=bounded._project(project)
        if expected:
            if not assets.strip():raise ValueError('등록된 기반 자료가 있는 명시적 참조자료 폴더가 필요합니다.')
            root=bounded._path_no_links(assets.strip(),directory=True)
            total=len(project_bytes)
            for relative,digest in sorted(expected.items()):
                candidate=bounded._path_no_links(root/relative)
                if total+candidate.stat().st_size>bounded.MAX_TOTAL_BYTES:
                    raise ValueError('기반 자료 합계 128 MiB 제한')
                payload=bounded._read_file(candidate,bounded.MAX_ASSET_BYTES)
                if total+len(payload)>bounded.MAX_TOTAL_BYTES:raise ValueError('기반 자료 합계 128 MiB 제한')
                if hashlib.sha256(payload).hexdigest()!=digest:raise ValueError('등록한 기반 자료 해시 불일치')
                total+=len(payload)
        return project
    project,enabled=_document(prefix,'혼합 기반 프로젝트','examples/geoscience_project/project.json',base_loader)
    view=st.text_area('혼합 공통 화면 설정 JSON',json.dumps({'selected_layer':0,'selected_field':'head','chart_mode':'3d','show_wells':False}),key=prefix+'_view')
    objects=[];invalid_selected=False
    for kind,object_id,source_prefix in MIXED_OBJECTS:
        value=st.session_state.get(source_prefix+('_mesh' if kind=='mesh' else '_document'))
        ready=value is not None and (kind=='mesh' or st.session_state.get(source_prefix+'_applied_ready',False))
        selected=st.checkbox('혼합 저장에 포함 · '+kind,value=False,disabled=not ready,key=prefix+'_include_'+kind)
        active_id=st.session_state.get(prefix+'_active_ids',{}).get(kind,object_id)
        if selected and ready:objects.append(ProjectObject(kind,active_id,value))
        elif selected and not ready:
            invalid_selected=True
            st.warning(kind+' 자료의 유효한 적용 상태를 확인한 뒤 저장하세요.')
    active_ids=st.session_state.get(prefix+'_active_ids',{})
    for retained in st.session_state.get(prefix+'_retained_objects',[]):
        if active_ids.get(retained.kind)==retained.object_id:continue
        keep=st.checkbox('복원한 추가 자료 유지 · '+retained.kind+' / '+retained.object_id,value=True,key=prefix+'_retain_'+retained.object_id)
        if keep:objects.append(retained)
        st.caption('추가 동종 자료·큰 객체·분석 파일은 원래 ID로 보존합니다. 분석 파일을 실행 상태로 되살리지 않습니다.')
    inert=st.checkbox('파일로 내보낸 분석 묶음을 불활성 자료로 포함',key=prefix+'_include_analysis')
    analysis_path=st.text_input('포함할 분석 묶음 폴더','',key=prefix+'_analysis_path')
    request=hashlib.sha256(_raw([None if project is None else project.to_dict(),
        [{'kind':o.kind,'id':o.object_id,'sha256':hashlib.sha256(_raw(o.value.to_dict())).hexdigest()} for o in objects],assets,view,inert,analysis_path])).hexdigest()
    if st.session_state.get(prefix+'_request')!=request:_clear(prefix);st.session_state[prefix+'_request']=request
    output=st.text_input('혼합 프로젝트 저장 파일 (새 .blproj)','build/geoscience.blproj',key=prefix+'_output')
    if st.button('혼합 프로젝트 저장·실제 왕복 확인',disabled=not enabled or invalid_selected or not(objects or inert),key=prefix+'_save'):
        _clear(prefix)
        try:
            selected=list(objects)
            if inert:selected.append(ProjectObject('analysis_archive','analysis_files',archive_analysis_bundle(analysis_path)))
            roots={o.object_id:st.session_state.get('gx_geo_asset_root','') for o in selected if o.kind=='geology'}
            Path(output).expanduser().absolute().parent.mkdir(parents=True,exist_ok=True)
            saved=save_geoscience_project(project,selected,output,asset_root=assets.strip() or None,
                object_asset_roots=roots,view_state=_decode(view.encode()))
            receipt=verify_geoscience_project_roundtrip(saved)
            payload=Path(saved).read_bytes()
            if len(payload)>MAX_DOWNLOAD:raise ValueError('혼합 프로젝트 다운로드 128 MiB 제한')
            st.session_state[prefix+'_product_saved']={'path':str(saved),'bytes':payload,'receipt':receipt}
        except Exception as error:_error(prefix,'혼합 프로젝트 저장·왕복',error,output)
    if prefix+'_product_saved' in st.session_state:
        saved=st.session_state[prefix+'_product_saved'];st.json(saved['receipt'])
        st.download_button('왕복 확인한 혼합 프로젝트 다운로드',saved['bytes'],'geoscience.blproj','application/zip')
    upload=st.file_uploader('혼합 .blproj 패키지 (32 MiB)',type=['blproj'],key=prefix+'_open_upload')
    if st.button('혼합 프로젝트 다른 위치에 열기',key=prefix+'_open'):
        keeper=None
        try:
            if upload is None or upload.size>32*1024*1024:raise ValueError('32 MiB 이하 .blproj를 선택하세요.')
            keeper=tempfile.TemporaryDirectory(prefix='basinlens-gx-restored-')
            source=Path(keeper.name)/'relocated.blproj';source.write_bytes(upload.getvalue())
            loaded=open_geoscience_project(source,Path(keeper.name)/'opened')
            st.session_state['gx_package_pending_restore']=(loaded,keeper)
            keeper=None;st.rerun()
        except Exception as error:
            if keeper is not None:keeper.cleanup()
            _error(prefix,'혼합 프로젝트 열기',error)
    if prefix+'_receipt' in st.session_state:
        st.caption('불러온 패키지의 형식·내용 무결성 확인 기록입니다. 편집한 자료의 새 검증 결과는 저장·왕복에서 확인하세요.')
        st.json(st.session_state[prefix+'_receipt'])
    if prefix+'_inert_analysis' in st.session_state:
        st.caption('이 분석 자료는 보존한 파일이며 실행 중인 엔진·해석 상태로 복원되지 않았습니다.')
        st.json(st.session_state[prefix+'_inert_analysis'])
    _diagnostic(prefix)

def render_geoscience_workspace():
    _restore_mixed_project()
    st.subheader('지질·개념 모델·보간·격자·후처리·레거시 해석')
    st.info('각 도구는 명시한 자료와 제한된 알고리즘을 사용합니다. 전체 GMS 구현·원본 비교 동등성·CO₂/석유 다상유동은 미완료입니다.')
    labels=['시추·지질','개념 피처','산점 보간','격자 생성','결과 후처리','MODFLOW-2005/NWT','래스터','점군','지층면','혼합 프로젝트']
    for tab,render in zip(st.tabs(labels),(_geology,_features,_scatter,_mesh,_analysis,_classic,_raster,_pointcloud,_surfaces,_mixed_project)):
        with tab:render()


if __name__=='__main__':
    st.set_page_config(page_title='BasinLens · 지질 작업공간',layout='wide')
    render_geoscience_workspace()
