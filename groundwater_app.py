"""Original groundwater workbench: ``streamlit run groundwater_app.py``.

The interface drives the open MODFLOW 6 engine through the project's validated
case contract. It does not reproduce a proprietary application's code or assets.
"""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from basinlens_ccs.groundwater import (  # noqa: E402
    GroundwaterCase,
    demo_case,
    load_case,
)
from basinlens_ccs.subsurface import (  # noqa: E402
    Modflow6Adapter, SubsurfaceProject, default_registry, load_project,
    project_from_groundwater, verify_project_bundle,
)
from basinlens_ccs.groundwater.native_run import _preflight, run_native_simulation  # noqa: E402
from basinlens_ccs.groundwater.gpr_hdf5 import MAX_GPR_BYTES, inventory_gpr, read_gpr_numeric_array  # noqa: E402
from basinlens_ccs.groundwater.gpr_geometry import read_gpr_rectilinear  # noqa: E402

MAX_UPLOAD_BYTES = 2_000_000
MAX_CELLS = 100_000
MAX_CELL_TIMES = 2_000_000
DOMAIN_LABELS = {
    "groundwater": "지하수 유동",
    "ccs": "CCS 프로젝트 · 배경 지하수",
    "oil_exploration": "석유 탐사 프로젝트 · 배경 지하수",
}


def case_bytes(case_dict: dict[str, Any]) -> bytes:
    return json.dumps(case_dict, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def case_fingerprint(case_dict: dict[str, Any]) -> str:
    payload = json.dumps(case_dict, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def zip_directory(directory: Path) -> bytes:
    """Archive only ordinary files produced inside this run workspace."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(directory).as_posix())
    return buffer.getvalue()


def layer_values(value: float | list[float], count: int) -> list[float]:
    return [float(value)] * count if np.isscalar(value) else list(value)


def layer_frame(case: dict[str, Any]) -> pd.DataFrame:
    count = case["grid"]["nlay"]
    return pd.DataFrame(
        {
            "bottom_m": case["grid"]["layer_bottoms_m"],
            **{
                name: layer_values(case["properties"][name], count)
                for name in (
                    "kx_m_per_day", "ky_m_per_day", "kz_m_per_day", "specific_storage_per_m"
                )
            },
        }
    )


def editor_records(frame: pd.DataFrame, integer_columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Recover integral editor cells without silently rounding fractional indices.

    Adding a blank row can make pandas represent integer columns as floats.
    This conversion is confined to GUI dataframes; the JSON contract stays strict.
    """
    records = frame.to_dict("records")
    for row in records:
        for column in integer_columns:
            value = row[column]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{column}: 정수를 입력하세요.")
            if not np.isfinite(value) or float(value) != int(value):
                raise ValueError(f"{column}: 정수를 입력하세요.")
            row[column] = int(value)
    return records


def heads_csv(heads: np.ndarray, times: np.ndarray, case: dict[str, Any]) -> bytes:
    """Export every saved cell with explicit zero-based indices and units."""
    nt, nl, nr, nc = heads.shape
    ti, li, ri, ci = np.indices((nt, nl, nr, nc))
    frame = pd.DataFrame(
        {
            "time_days": np.asarray(times)[ti.ravel()],
            "layer": li.ravel(),
            "row": ri.ravel(),
            "column": ci.ravel(),
            "x_center_m": (ci.ravel() + 0.5) * case["grid"]["delr_m"],
            "y_center_m": (ri.ravel() + 0.5) * case["grid"]["delc_m"],
            "head_m": heads.ravel(),
        }
    )
    return frame.to_csv(index=False).encode("utf-8")


def validate_ui_case(candidate: dict[str, Any]) -> dict[str, Any]:
    validated = GroundwaterCase.from_dict(candidate).to_dict()
    grid = validated["grid"]
    cells = grid["nlay"] * grid["nrow"] * grid["ncol"]
    saved = sum(period["steps"] for period in validated["periods"])
    if cells > MAX_CELLS or cells * saved > MAX_CELL_TIMES:
        raise ValueError("이 화면은 최대 100,000셀, 저장 시각 × 셀 수 2,000,000까지 지원합니다.")
    return validated


def common_project_for_case(case: dict[str, Any], domain: str,
                            template: SubsurfaceProject | None = None) -> SubsurfaceProject:
    """Preserve evidence when editing the native-water subset of a common project."""
    native = GroundwaterCase.from_dict(case)
    project = project_from_groundwater(native, domain=domain)
    if template is None:
        return project
    original_case, _ = Modflow6Adapter().prepare(template)
    old_fields = {field.name: field for field in template.rock_properties}
    native_names = {
        "hydraulic_conductivity_x": "kx_m_per_day", "hydraulic_conductivity_y": "ky_m_per_day",
        "hydraulic_conductivity_z": "kz_m_per_day", "specific_storage": "specific_storage_per_m",
    }
    fields, edited_properties = [], False
    for field in project.rock_properties:
        old = old_fields[field.name]
        key = native_names[field.name]
        if original_case.properties[key] == native.properties[key]:
            fields.append(old)
        else:
            fields.append(replace(field, source_asset_ids=old.source_asset_ids, basis="assumed"))
            edited_properties = True
    fields.extend(field for field in template.rock_properties if field.name not in native_names)
    assumptions = project.provenance.assumptions
    edit_note = "Hydraulic property values edited in workbench; edited fields are assumptions, not new measurements"
    if edited_properties and edit_note not in assumptions:
        assumptions = (*assumptions, edit_note)
    project = replace(project,
        spatial_reference=replace(template.spatial_reference,
            crs=native.provenance["crs"], vertical_datum=native.provenance["vertical_datum"]),
        geometry=replace(project.geometry, origin_x_m=template.geometry.origin_x_m,
            origin_y_m=template.geometry.origin_y_m),
        rock_properties=tuple(fields), assets=template.assets, stratigraphy=template.stratigraphy,
        observations=template.observations, reference_mesh_asset_ids=template.reference_mesh_asset_ids,
        provenance=replace(project.provenance, assumptions=assumptions))
    # Support outside a changed grid fails here instead of dropping evidence.
    default_registry().validate(project)
    return project


def project_from_upload(payload: bytes) -> SubsurfaceProject:
    """Strict common JSON import; source asset bytes are checked before export/run."""
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError("공통 프로젝트 JSON은 2 MB 이하여야 합니다.")
    with tempfile.TemporaryDirectory(prefix="basinlens-project-import-") as tmp:
        path = Path(tmp) / "project.json"
        path.write_bytes(payload)
        project = load_project(path, check_assets=False)
    default_registry().validate(project)
    return project


def replace_common_project(project: SubsurfaceProject, message: str) -> None:
    project = SubsurfaceProject.from_dict(project.to_dict())
    default_registry().validate(project)
    native, _ = Modflow6Adapter().prepare(project)
    validated = validate_ui_case(native.to_dict())
    old = st.session_state.get("gw_project")
    if old is None or case_fingerprint(old) != case_fingerprint(project.to_dict()):
        st.session_state.gw_case = validated
        st.session_state.gw_project = project.to_dict()
        st.session_state.gw_revision = st.session_state.get("gw_revision", 0) + 1
        for key in ("gw_result", "gw_input_zip", "gw_project_input_zip", "gw_csv", "gw_failed_run_zip"):
            st.session_state.pop(key, None)
        message += " 이전 입력의 계산 결과는 비웠습니다."
    st.session_state.gw_notice = message


def replace_case(candidate: dict[str, Any], message: str, *, reset_metadata=False) -> None:
    validated = validate_ui_case(candidate)
    stored = st.session_state.get("gw_project")
    template = SubsurfaceProject.from_dict(stored) if stored is not None else None
    domain = template.domain if template else "groundwater"
    project = common_project_for_case(validated, domain, None if reset_metadata else template)
    replace_common_project(project, message)
    if reset_metadata:
        st.session_state.pop("gw_asset_root", None)


def apply_edit(candidate: dict[str, Any], message: str, *, reset_metadata=False) -> None:
    try:
        replace_case(candidate, message, reset_metadata=reset_metadata)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        st.error(f"입력을 적용하지 못했습니다: {exc}")
    else:
        st.rerun()


def model_figure(case: dict[str, Any], head: np.ndarray | None = None) -> go.Figure:
    grid = case["grid"]
    xs = np.linspace(0, grid["ncol"] * grid["delr_m"], min(grid["ncol"] + 1, 40))
    ys = np.linspace(0, grid["nrow"] * grid["delc_m"], min(grid["nrow"] + 1, 40))
    xx, yy = np.meshgrid(xs, ys)
    fig = go.Figure()
    bottoms = grid["layer_bottoms_m"]
    colors = ["#164e63", "#0369a1", "#38bdf8", "#818cf8", "#a78bfa", "#c084fc"]
    for index, elevation in enumerate([grid["top_m"], *bottoms]):
        color = colors[index % len(colors)]
        fig.add_trace(
            go.Surface(
                x=xx, y=yy, z=np.full_like(xx, elevation),
                colorscale=[[0, color], [1, color]], showscale=False,
                opacity=0.20 if index == 0 else 0.42,
                name="상면" if index == 0 else f"층 {index - 1} 하면",
                hovertemplate="x=%{x:.1f} m<br>y=%{y:.1f} m<br>표고=%{z:.2f} m<extra>%{fullData.name}</extra>",
            )
        )
    if head is not None:
        row_stride = max(1, int(np.ceil(grid["nrow"] / 50)))
        col_stride = max(1, int(np.ceil(grid["ncol"] / 50)))
        hx = (np.arange(grid["ncol"])[::col_stride] + 0.5) * grid["delr_m"]
        hy = (np.arange(grid["nrow"])[::row_stride] + 0.5) * grid["delc_m"]
        fig.add_trace(go.Surface(
            x=hx, y=hy, z=head[::row_stride, ::col_stride],
            colorscale="Viridis", opacity=0.88, name="계산 수두",
            colorbar={"title": "수두 (m)", "len": 0.55},
            hovertemplate="x=%{x:.1f} m<br>y=%{y:.1f} m<br>수두=%{z:.3f} m<extra>계산 수두</extra>",
        ))
    layer_tops = [grid["top_m"], *bottoms[:-1]]
    for well in case["wells"]:
        layer = well["layer"]
        x = (well["column"] + 0.5) * grid["delr_m"]
        y = (well["row"] + 0.5) * grid["delc_m"]
        z = (layer_tops[layer] + bottoms[layer]) / 2
        fig.add_trace(go.Scatter3d(
            x=[x, x], y=[y, y], z=[grid["top_m"] + 2, z],
            mode="lines+markers", name=well["name"],
            line={"width": 6, "color": "#e11d48" if well["rate_m3_per_day"] < 0 else "#10b981"},
            marker={"size": 3},
            hovertemplate=f"{well['name']}<br>층 {layer}<extra></extra>",
        ))
    fig.update_layout(
        height=500, margin={"l": 0, "r": 0, "t": 15, "b": 0},
        scene={
            "xaxis_title": "x (m)", "yaxis_title": "y (m)", "zaxis_title": "표고 / 수두 (m)",
            "yaxis": {"autorange": "reversed"}, "aspectmode": "auto",
            "camera": {"eye": {"x": 1.5, "y": -1.7, "z": 1.1}},
        }, showlegend=False,
    )
    return fig


def map_figure(case: dict[str, Any], head: np.ndarray, wells: list[dict[str, Any]], layer: int) -> go.Figure:
    grid = case["grid"]
    x = (np.arange(grid["ncol"]) + 0.5) * grid["delr_m"]
    y = (np.arange(grid["nrow"]) + 0.5) * grid["delc_m"]
    fig = go.Figure(go.Heatmap(
        x=x, y=y, z=head, colorscale="Viridis", colorbar={"title": "수두 (m)"},
        hovertemplate="x=%{x:.1f} m<br>y=%{y:.1f} m<br>수두=%{z:.4f} m<extra></extra>",
    ))
    if float(np.ptp(head)) > 1e-8 and min(head.shape) > 1:
        fig.add_trace(go.Contour(
            x=x, y=y, z=head, showscale=False, line={"color": "#f8fafc", "width": 1},
            contours={"coloring": "none", "showlabels": True}, hoverinfo="skip",
        ))
    for well in wells:
        if well["layer"] == layer:
            fig.add_trace(go.Scatter(
                x=[(well["column"] + 0.5) * grid["delr_m"]],
                y=[(well["row"] + 0.5) * grid["delc_m"]],
                mode="markers+text", text=[well["name"]], textposition="top center",
                marker={"color": "#fb7185" if well["rate_m3_per_day"] < 0 else "#34d399", "size": 11, "symbol": "diamond"},
                hovertemplate=f"{well['name']}<br>{well['rate_m3_per_day']:g} m³/day<extra></extra>",
            ))
    fig.update_layout(
        height=500, margin={"l": 10, "r": 10, "t": 15, "b": 10},
        xaxis={"title": "x (m)", "constrain": "domain"},
        yaxis={"title": "y (m, 행 증가 방향)", "autorange": "reversed", "scaleanchor": "x"},
        showlegend=False,
    )
    return fig


def sidebar(case: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown("### BasinLens\n지하수 모델 작업대")
        st.caption("MODFLOW 6 · confined GWF")
        project = SubsurfaceProject.from_dict(st.session_state.gw_project)
        domains = list(DOMAIN_LABELS)
        selected = st.selectbox("프로젝트 분야", domains, index=domains.index(project.domain),
            format_func=DOMAIN_LABELS.get, key=f"gw_domain_selector_{st.session_state.gw_revision}")
        if selected != project.domain:
            role = "groundwater_flow" if selected == "groundwater" else "background_water"
            replace_common_project(replace(project, domain=selected, model=replace(project.model, role=role)), "프로젝트 분야를 적용했습니다.")
            st.rerun()
        st.caption("CCS·석유 탐사 분야에서도 현재 엔진의 역할은 배경 지하수 유동입니다.")
        common_upload = st.file_uploader("공통 지질 프로젝트 JSON 열기", type=["json"], key="gw_common_upload")
        if st.button("공통 프로젝트 불러오기", disabled=common_upload is None, use_container_width=True):
            try:
                imported = project_from_upload(common_upload.getvalue())
                replace_common_project(imported, "공통 프로젝트와 근거 메타데이터를 불러왔습니다.")
                st.session_state.gw_asset_root = ""
                st.rerun()
            except (ValueError, RuntimeError, TypeError, OSError) as exc:
                st.error(f"공통 프로젝트를 적용하지 못했습니다: {exc}")
        st.download_button("공통 프로젝트 JSON 저장", project.to_json().encode("utf-8"),
            "subsurface_project.json", "application/json", use_container_width=True)
        if project.assets:
            st.text_input("원본 자료가 있는 실행 서버 폴더", key="gw_asset_root",
                help="등록된 상대 경로와 SHA-256을 이 폴더에서 검사합니다. 브라우저가 실행되는 기기의 폴더가 아닌, 앱 서버의 폴더입니다.")
            st.caption(f"참조 자료 {len(project.assets)}개 · 입력 생성/계산 전에 실제 파일과 해시를 검사합니다.")
        with st.expander("공통 프로젝트 근거 · 확장 상태"):
            st.caption(f"역할: {project.model.role} · 관측 {len(project.observations)}개 · 층서 {len(project.stratigraphy)}개")
            st.caption(f"CRS: {project.spatial_reference.crs} · 원점 ({project.geometry.origin_x_m:g}, {project.geometry.origin_y_m:g}) m")
            st.caption("관측·메시 참조·추가 암석 물성은 메타데이터로 보존되며 현재 계산에는 자동 동화되지 않습니다.")
            st.caption("현재 연결: MODFLOW 6 · 단상 피압 물 유동")
            for engine in default_registry().engines():
                if engine["implementation_status"] == "NOT_AVAILABLE":
                    st.button(f"{engine['name']} · 미구현", disabled=True, key=f"gw_unavailable_{engine['engine_id']}", use_container_width=True)
            st.caption("다상 CO₂·black-oil·지진 해석 어댑터는 아직 구현되지 않았습니다.")
        st.divider()
        st.markdown("**기존 지하수 케이스**")
        upload = st.file_uploader("지하수 케이스 JSON 열기", type=["json"], key="gw_upload")
        if st.button("업로드 파일 불러오기", disabled=upload is None, use_container_width=True):
            if upload is not None:
                try:
                    if upload.size > MAX_UPLOAD_BYTES:
                        raise ValueError("프로젝트 JSON은 2 MB 이하여야 합니다.")
                    with tempfile.TemporaryDirectory(prefix="basinlens-gw-import-") as tmp:
                        path = Path(tmp) / "case.json"
                        path.write_bytes(upload.getvalue())
                        candidate = load_case(path).to_dict()
                    apply_edit(candidate, "지하수 케이스를 새 공통 프로젝트로 불러왔습니다.", reset_metadata=True)
                except (ValueError, UnicodeError, TypeError, KeyError, OSError) as exc:
                    st.error(f"프로젝트를 읽지 못했습니다: {exc}")
        if st.button("합성 예제로 새로 시작", use_container_width=True):
            apply_edit(demo_case().to_dict(), "합성 예제를 열었습니다.", reset_metadata=True)
        st.download_button("지하수 케이스 JSON 저장", case_bytes(case), "groundwater_case.json", "application/json", use_container_width=True)
        st.divider()
        st.markdown("**모델 구성**")
        with st.expander("격자와 층", expanded=True):
            g = case["grid"]
            st.write(f"층 {g['nlay']} · 행 {g['nrow']} · 열 {g['ncol']}")
            st.caption(f"Δx {g['delr_m']:g} m · Δy {g['delc_m']:g} m")
            for index, bottom in enumerate(g["layer_bottoms_m"]):
                st.caption(f"층 {index}: 하면 {bottom:g} m")
        with st.expander("경계 · 외력"):
            st.write(f"좌/우 고정수두: {case['boundaries']['left_head_m']:g} / {case['boundaries']['right_head_m']:g} m")
            st.caption("상면 함양 · 나머지 외곽 불투수")
            st.write(f"기본 우물 {len(case['wells'])}개 · 응력기간 {len(case['periods'])}개")
        st.caption("로컬 좌표와 동일한 표고 기준을 사용합니다. 행·열·층 번호는 0부터 시작합니다.")


def editor(case: dict[str, Any], revision: int) -> None:
    st.caption("각 양식의 적용 버튼을 눌러 입력을 확정하세요. 미적용 편집은 계산에 사용되지 않습니다.")
    geometry, forcings, schedule, provenance = st.tabs(["격자 · 물성", "경계 · 우물", "시간 설정", "프로젝트 · 근거"])
    g = case["grid"]
    with geometry, st.form(f"geometry_{revision}"):
        a, b, c = st.columns(3)
        nrow = a.number_input("행 수", 1, 500, int(g["nrow"]), step=1)
        ncol = b.number_input("열 수", 3, 500, int(g["ncol"]), step=1)
        top = c.number_input("모델 상면 표고 (m)", value=float(g["top_m"]))
        a, b = st.columns(2)
        delr = a.number_input("열 너비 Δx (m)", min_value=0.0, value=float(g["delr_m"]), format="%.6g")
        delc = b.number_input("행 너비 Δy (m)", min_value=0.0, value=float(g["delc_m"]), format="%.6g")
        st.caption("표의 한 행이 한 층입니다. 위에서 아래 순서로 입력하며 + 버튼으로 층을 추가할 수 있습니다. 모든 층은 피압 조건입니다.")
        layers = st.data_editor(
            layer_frame(case), num_rows="dynamic", hide_index=True, use_container_width=True,
            column_config={
                "bottom_m": st.column_config.NumberColumn("하면 표고 (m)", required=True),
                "kx_m_per_day": st.column_config.NumberColumn("Kx (m/day)", min_value=0.0, required=True, format="%.6g"),
                "ky_m_per_day": st.column_config.NumberColumn("Ky (m/day)", min_value=0.0, required=True, format="%.6g"),
                "kz_m_per_day": st.column_config.NumberColumn("Kz (m/day)", min_value=0.0, required=True, format="%.6g"),
                "specific_storage_per_m": st.column_config.NumberColumn("비저류계수 Ss (1/m)", min_value=0.0, required=True, format="%.6g"),
            }, key=f"layers_{revision}",
        )
        if st.form_submit_button("격자와 물성 적용", type="primary"):
            candidate = copy.deepcopy(case)
            candidate["grid"] = {"nlay": len(layers), "nrow": int(nrow), "ncol": int(ncol), "delr_m": delr, "delc_m": delc, "top_m": top, "layer_bottoms_m": layers["bottom_m"].tolist()}
            candidate["properties"] = {key: layers[key].tolist() for key in case["properties"]}
            apply_edit(candidate, "격자와 물성을 적용했습니다.")
    with forcings:
        with st.form(f"boundaries_{revision}"):
            a, b, c = st.columns(3)
            left = a.number_input("좌측 고정수두 (m)", value=float(case["boundaries"]["left_head_m"]))
            right = b.number_input("우측 고정수두 (m)", value=float(case["boundaries"]["right_head_m"]))
            recharge = c.number_input("상면 함양률 (m/day)", min_value=0.0, value=float(case["recharge_m_per_day"]), format="%.7f")
            automatic = st.checkbox("초기수두를 좌우 경계 사이 선형 분포로 설정", value=case.get("initial_head_m") is None)
            initial_value = case.get("initial_head_m")
            initial = st.number_input("일정 초기수두 (m, 자동 설정 해제 시)", value=float(initial_value if initial_value is not None else (left + right) / 2))
            st.caption("수두는 모델 상면 이상이어야 합니다. 수평 외곽의 좌우 열만 고정수두이며, 앞·뒤·바닥은 무유량 경계입니다.")
            if st.form_submit_button("경계와 함양 적용"):
                candidate = copy.deepcopy(case)
                candidate["boundaries"] = {"left_head_m": left, "right_head_m": right}
                candidate["recharge_m_per_day"] = recharge
                candidate["initial_head_m"] = None if automatic else initial
                apply_edit(candidate, "경계와 함양을 적용했습니다.")
        with st.form(f"wells_{revision}"):
            st.caption("우물 유량: 양의 유량(+)은 물 주입, 음의 유량(-)은 취수입니다. 고정수두 열에는 우물을 둘 수 없습니다.")
            wells = st.data_editor(
                pd.DataFrame(case["wells"], columns=["name", "layer", "row", "column", "rate_m3_per_day"]),
                num_rows="dynamic", hide_index=True, use_container_width=True,
                column_config={
                    "name": st.column_config.TextColumn("우물 이름", required=True),
                    "layer": st.column_config.NumberColumn("층 (0부터)", min_value=0, step=1, required=True),
                    "row": st.column_config.NumberColumn("행 (0부터)", min_value=0, step=1, required=True),
                    "column": st.column_config.NumberColumn("열 (0부터)", min_value=1, step=1, required=True),
                    "rate_m3_per_day": st.column_config.NumberColumn("유량 (m³/day)", required=True),
                }, key=f"wells_table_{revision}",
            )
            if st.form_submit_button("기본 우물 적용"):
                try:
                    candidate = copy.deepcopy(case)
                    candidate["wells"] = editor_records(wells, ("layer", "row", "column"))
                    apply_edit(candidate, "기본 우물을 적용했습니다.")
                except ValueError as exc:
                    st.error(f"우물 입력을 확인하세요: {exc}")
    with schedule, st.form(f"periods_{revision}"):
        st.caption("각 기간의 길이는 일(day)입니다. 시간 단계는 등간격이며 모든 단계의 결과를 저장합니다.")
        periods = pd.DataFrame([
            {"length_days": p["length_days"], "steps": p["steps"], "transient": p["transient"], "wells_override_json": json.dumps(p["wells"], ensure_ascii=False) if "wells" in p and p["wells"] is not None else ""}
            for p in case["periods"]
        ])
        edited = st.data_editor(
            periods, num_rows="dynamic", hide_index=True, use_container_width=True,
            column_config={
                "length_days": st.column_config.NumberColumn("기간 (day)", min_value=0.000001, required=True),
                "steps": st.column_config.NumberColumn("시간 단계 수", min_value=1, step=1, required=True),
                "transient": st.column_config.CheckboxColumn("비정상류", required=True),
                "wells_override_json": st.column_config.TextColumn("기간별 우물 JSON (선택)"),
            }, key=f"periods_table_{revision}",
        )
        st.caption('기간별 우물 칸이 비어 있으면 기본 우물을 씁니다. []는 해당 기간의 우물을 모두 끕니다. 우물 객체의 필드는 name, layer, row, column, rate_m3_per_day입니다.')
        if st.form_submit_button("시간 설정 적용", type="primary"):
            try:
                records = []
                for row in editor_records(edited, ("steps",)):
                    override = row.pop("wells_override_json")
                    if isinstance(override, str) and override.strip():
                        row["wells"] = json.loads(override)
                    records.append(row)
                candidate = copy.deepcopy(case)
                candidate["periods"] = records
                apply_edit(candidate, "시간 설정을 적용했습니다.")
            except (ValueError, TypeError) as exc:
                st.error(f"기간별 우물 JSON을 확인하세요: {exc}")
    with provenance, st.form(f"provenance_{revision}"):
        prov = case.get("provenance", {})
        a, b = st.columns(2)
        case_id = a.text_input("프로젝트 ID", value=case["case_id"])
        name = b.text_input("프로젝트 이름", value=case["name"])
        source = st.text_input("자료 출처", value=str(prov.get("source", "")))
        a, b = st.columns(2)
        crs = a.text_input("좌표계 / 로컬 좌표 설명", value=str(prov.get("crs", "")))
        datum = b.text_input("표고 기준", value=str(prov.get("vertical_datum", "")))
        assumptions = prov.get("assumptions", [])
        assumptions_text = st.text_area("가정 (한 줄에 하나)", value="\n".join(assumptions) if isinstance(assumptions, list) else str(assumptions))
        if st.form_submit_button("프로젝트 정보 적용"):
            candidate = copy.deepcopy(case)
            candidate.update(case_id=case_id, name=name)
            candidate["provenance"] = {"source": source, "crs": crs, "vertical_datum": datum, "assumptions": [line.strip() for line in assumptions_text.splitlines() if line.strip()]}
            apply_edit(candidate, "프로젝트 정보와 근거를 적용했습니다.")


def execute(case: dict[str, Any]) -> None:
    st.subheader("계산과 내보내기")
    project = SubsurfaceProject.from_dict(st.session_state.gw_project)
    registry = default_registry()
    asset_root = st.session_state.get("gw_asset_root", "").strip() or None
    a, b = st.columns([3, 1])
    executable = a.text_input("MODFLOW 6 실행 파일", value="mf6", key="gw_solver_path", help="서버에 설치된 mf6 또는 실행 파일의 절대 경로를 입력하세요. 설치·다운로드는 자동으로 수행하지 않습니다.")
    b.caption("실제 엔진이 필요합니다.")
    run_clicked = b.button("MODFLOW 6 계산", type="primary", use_container_width=True)
    export_clicked = st.button("엔진 없이 MF6 입력 파일 만들기")
    if export_clicked:
        try:
            with tempfile.TemporaryDirectory(prefix="basinlens-gw-input-") as tmp:
                with st.spinner("검증한 프로젝트를 MF6 입력으로 변환합니다…"):
                    exported = registry.export(project, Path(tmp) / "input", asset_root=asset_root)
                    verify_project_bundle(exported.workspace)
                    st.session_state.gw_input_zip = zip_directory(exported.workspace / "engine")
                    st.session_state.gw_project_input_zip = zip_directory(exported.workspace)
            st.success("MF6 입력 파일을 만들었습니다. 계산은 실행하지 않았습니다.")
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(f"입력 파일 생성 실패: {exc}")
    if run_clicked:
        st.session_state.pop("gw_failed_run_zip", None)
        st.session_state.pop("gw_result", None)
        st.session_state.pop("gw_csv", None)
        try:
            with tempfile.TemporaryDirectory(prefix="basinlens-gw-run-") as tmp:
                output = Path(tmp) / "run"
                try:
                    with st.spinner("MODFLOW 6에서 실제 지하수 유동을 계산합니다…"):
                        run = registry.run(project, output, exe_name=executable.strip() or "mf6", asset_root=asset_root)
                        verify_project_bundle(run.workspace)
                        result = run.engine_result
                        products = {
                            "fingerprint": case_fingerprint(case), "heads": result.heads,
                            "project_fingerprint": case_fingerprint(project.to_dict()),
                            "times": result.times_days, "summary": result.summary,
                            "bundle": zip_directory(output / "engine"),
                            "project_bundle": zip_directory(output), "project_summary": run.summary,
                        }
                except Exception:
                    if output.exists():
                        st.session_state.gw_failed_run_zip = zip_directory(output)
                    raise
            st.session_state.gw_result = products
            st.session_state.pop("gw_csv", None)
            st.success("계산을 완료했습니다. 아래에서 수두와 실행 기록을 확인하세요.")
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(f"계산 실패: {exc}")
            st.caption("실행 파일 경로와 입력값을 확인하세요. 실패한 계산을 새 결과로 표시하지 않습니다.")
    if "gw_input_zip" in st.session_state:
        st.download_button("MF6 입력 ZIP 다운로드", st.session_state.gw_input_zip, "groundwater_mf6_inputs.zip", "application/zip")
    if "gw_project_input_zip" in st.session_state:
        st.download_button("공통 프로젝트 + MF6 입력 ZIP 다운로드", st.session_state.gw_project_input_zip, "subsurface_project_inputs.zip", "application/zip")
        st.caption("공통 ZIP은 프로젝트·변환 근거·검증 기록을 포함합니다. 참조 원본 자료는 해시와 경로로 보존되며 ZIP에 복사되지 않습니다.")
    if "gw_failed_run_zip" in st.session_state:
        st.download_button("실패한 실행의 진단 파일 다운로드", st.session_state.gw_failed_run_zip, "groundwater_failed_run.zip", "application/zip")


def results(case: dict[str, Any]) -> None:
    products = st.session_state.get("gw_result")
    if products is None:
        st.subheader("모델 미리보기")
        st.plotly_chart(model_figure(case), use_container_width=True, key="model_preview")
        st.info("입력된 지층과 기본 우물의 위치입니다. 수두 결과를 보려면 MODFLOW 6 계산을 실행하세요.")
        return
    if (products["fingerprint"] != case_fingerprint(case)
            or products.get("project_fingerprint") != case_fingerprint(st.session_state.gw_project)):
        st.warning("현재 입력과 다른 계산 결과입니다. 다시 계산하세요.")
        return
    heads, times = products["heads"], products["times"]
    st.subheader("수두 결과")
    a, b = st.columns([1, 2])
    layer = a.selectbox("표시할 층 (0부터)", list(range(case["grid"]["nlay"])))
    time_index = b.select_slider("저장 시각 (day)", options=list(range(len(times))), value=len(times) - 1, format_func=lambda i: f"{times[i]:.6g}")
    selected = heads[time_index, layer]
    a, b, c = st.columns(3)
    a.metric("선택 평면 최소 수두", f"{np.min(selected):.4f} m")
    b.metric("선택 평면 최대 수두", f"{np.max(selected):.4f} m")
    budget = products["summary"].get("water_budget", {})
    residual = budget.get("max_abs_residual_m3_per_day")
    c.metric("최대 물수지 잔차", "기록 확인" if residual is None else f"{residual:.4g} m³/day")
    st.caption("물수지는 절대 잔차 10⁻⁶ m³/day 또는 상대 잔차 0.1% 중 큰 허용값으로 검사합니다. 유량이 0에 가까운 시각에는 상대 백분율보다 절대 잔차를 확인하세요. 자세한 기록은 실행 ZIP에 있습니다.")
    # Period-specific well controls must match the plotted output time.
    elapsed = 0.0
    wells = case["wells"]
    for period in case["periods"]:
        elapsed += period["length_days"]
        if times[time_index] <= elapsed + 1e-9:
            wells = period.get("wells", case["wells"])
            break
    wells = case["wells"] if wells is None else wells
    left, right = st.columns(2)
    with left:
        st.markdown("**평면 수두 · 등수두선**")
        st.plotly_chart(map_figure(case, selected, wells, layer), use_container_width=True, key="head_map")
    with right:
        st.markdown("**지층과 선택 층의 수두 표면**")
        display_case = copy.deepcopy(case)
        display_case["wells"] = wells
        st.plotly_chart(model_figure(display_case, selected), use_container_width=True, key="head_3d")
    st.caption("수두 표면은 선택 층의 수리수두이며 CO₂ 포화도나 지하수면 형상이 아닙니다. 3D 축 비율은 자동 조정됩니다.")
    with st.expander("셀별 수두 시간 변화"):
        a, b = st.columns(2)
        row = a.number_input("관찰할 행", 0, case["grid"]["nrow"] - 1, case["grid"]["nrow"] // 2, step=1)
        column = b.number_input("관찰할 열", 0, case["grid"]["ncol"] - 1, case["grid"]["ncol"] // 2, step=1)
        fig = go.Figure(go.Scatter(x=times, y=heads[:, layer, row, column], mode="lines+markers"))
        fig.update_layout(height=260, xaxis_title="경과 시간 (day)", yaxis_title="수두 (m)", margin={"t": 10, "b": 20})
        st.plotly_chart(fig, use_container_width=True, key="head_series")
    with st.expander("엔진 요약 · 가정 · 검증 한계"):
        st.json(products["summary"])
        st.json(products["project_summary"])
    st.caption("도표와 수두 CSV의 x/y는 격자 로컬 좌표입니다. 공통 프로젝트의 원점·CRS·표고 기준은 공통 ZIP의 project.json과 mapping.json에 보존됩니다.")
    st.download_button("공통 프로젝트 실행 ZIP 다운로드", products["project_bundle"], "subsurface_project_run.zip", "application/zip", use_container_width=True)
    a, b = st.columns(2)
    a.download_button("전체 실행 ZIP 다운로드", products["bundle"], "groundwater_run.zip", "application/zip", use_container_width=True)
    if b.button("모든 시각·층의 수두 CSV 준비", use_container_width=True):
        with st.spinner("수두 CSV를 만듭니다…"):
            st.session_state.gw_csv = heads_csv(heads, times, case)
    if "gw_csv" in st.session_state:
        st.download_button("수두 결과 CSV 다운로드", st.session_state.gw_csv, "groundwater_heads.csv", "text/csv")


def native_workbench() -> None:
    """Keep native decks, their units and their execution products separate."""
    st.subheader("네이티브 MF6 프로젝트 실행")
    st.caption("아래 경로는 앱이 실행되는 서버의 경로입니다. mfsim.nam 파일 또는 네이티브 입력 폴더를 지정하세요.")
    st.info("원본 네이티브 단위와 모델 구성을 보존하여 별도 폴더에서 실행합니다. 위의 피압 케이스·CCS 분야 설정으로 변환하지 않습니다. GMS GUI/보조자료의 편집 내용은 네이티브 입력에 동기화하지 않습니다.")
    with st.form("gw_native_form"):
        source = st.text_input("네이티브 mfsim.nam 또는 폴더", key="gw_native_source")
        allowed = st.text_input("네이티브 입력 허용 루트 (선택)", key="gw_native_allowed",
            help="../Component 같은 참조가 있으면 이들을 포함하는 원본 폴더를 지정하세요. 비워 두면 시뮬레이션 폴더만 허용합니다.")
        output = st.text_input("네이티브 실행 결과 폴더", value="build/native-mf6-run", key="gw_native_output",
            help="원본과 분리된 새 폴더를 매번 지정하세요. 기존 폴더는 덮어쓰지 않습니다.")
        timeout = st.number_input("네이티브 실행 제한 시간 (초)", min_value=1, max_value=600, value=120, step=1)
        a, b = st.columns(2)
        inspect_clicked = a.form_submit_button("네이티브 입력 검사")
        run_clicked = b.form_submit_button("네이티브 MF6 실행")
    request = {"source": source.strip(), "allowed_root": allowed.strip(), "output": output.strip(),
        "timeout": timeout, "exe": st.session_state.get("gw_solver_path", "mf6").strip() or "mf6"}
    request_id = case_fingerprint(request)
    if st.session_state.get("gw_native_request") != request_id:
        for key in ("gw_native_report", "gw_native_result", "gw_native_zip"):
            st.session_state.pop(key, None)
        st.session_state.gw_native_request = request_id
    if inspect_clicked or run_clicked:
        for key in ("gw_native_report", "gw_native_result", "gw_native_zip"):
            st.session_state.pop(key, None)
        try:
            if not request["source"]:
                raise ValueError("mfsim.nam 또는 네이티브 입력 폴더를 지정하세요.")
            if Path(request["source"]).suffix.lower() == ".gpr":
                raise ValueError("이 실행 화면은 .gpr 컨테이너를 변환하지 않습니다. 네이티브 mfsim.nam을 지정하세요.")
            report, _, _, inputs, sidecars, _, units = _preflight(request["source"], request["allowed_root"] or None)
            st.session_state.gw_native_report = {
                "native_inputs_resolved": True, "models": report["models"],
                "package_types": sorted({r["kind"] for r in report["references"] if r["kind"].endswith("6")}),
                "native_units": units, "unit_conversion": "none", "input_files": len(inputs),
                "opaque_sidecars": len(sidecars), "gms_sidecar_native_sync": "not performed",
                "physics_validation": "not evaluated"}
            if run_clicked:
                st.session_state.pop("gw_native_result", None)
                st.session_state.pop("gw_native_zip", None)
                if not request["output"]:
                    raise ValueError("새 네이티브 실행 결과 폴더를 지정하세요.")
                with st.spinner("원본을 보존하고 네이티브 MODFLOW 6를 실행합니다…"):
                    result = run_native_simulation(request["source"], request["output"],
                        allowed_root=request["allowed_root"] or None, exe_name=request["exe"],
                        timeout_seconds=float(timeout))
                    from basinlens_ccs.groundwater.native_run import verify_native_run
                    verified = verify_native_run(result.workspace)
                    if verified["status"] != "completed":
                        raise ValueError("완료된 네이티브 실행의 무결성을 확인하지 못했습니다.")
                    st.session_state.gw_native_result = {"workspace": str(result.workspace),
                        "summary": result.summary, "verified_status": verified["status"]}
                    bundle_size = sum(path.stat().st_size for path in result.workspace.rglob("*") if path.is_file())
                    if bundle_size <= 128 * 1024 * 1024:
                        st.session_state.gw_native_zip = zip_directory(result.workspace)
                st.success("네이티브 실행과 파일 무결성 검사를 완료했습니다. 임의 모델의 물리적 정확성은 별도 검증 대상입니다.")
            else:
                st.success("네이티브 입력 경로와 참조 그래프를 확인했습니다. 계산은 실행하지 않았습니다.")
        except (OSError, ValueError, RuntimeError) as exc:
            st.error(f"네이티브 입력/실행 오류: {exc}")
    if "gw_native_report" in st.session_state:
        with st.expander("네이티브 모델 · 패키지 · 원본 단위", expanded=True):
            st.json(st.session_state.gw_native_report)
        st.caption("단위 선언이 없는 항목은 미상으로 남습니다. 수두를 절대 압력으로 해석하거나 미터·일 단위를 자동 적용하지 않습니다.")
    if "gw_native_result" in st.session_state:
        result = st.session_state.gw_native_result
        st.json(result["summary"])
        st.caption("검증한 네이티브 실행 폴더")
        st.code(result["workspace"], language=None)
        if "gw_native_zip" in st.session_state:
            st.download_button("검증한 네이티브 실행 ZIP 다운로드", st.session_state.gw_native_zip,
                "native_mf6_run.zip", "application/zip", key="gw_native_download")
        else:
            st.caption("묶음이 128 MiB를 초과하여 메모리 다운로드를 생략했습니다. 위 서버 폴더에서 전체 파일을 확인하세요.")
        st.caption("이 결과는 위 피압 케이스의 지도·CSV와 별도로 보존됩니다. GUI/보조자료 상태와 계산 입력의 일치, 물리 검증 및 GMS 동등성은 확인되지 않았습니다.")


def _gpr_sha(path: str) -> str:
    project = Path(path)
    if not project.is_file() or project.stat().st_size > MAX_GPR_BYTES:
        raise ValueError(f"GPR 파일은 {MAX_GPR_BYTES}바이트를 초과할 수 없습니다.")
    digest = hashlib.sha256()
    total = 0
    with project.open("rb") as source:
        while chunk := source.read(min(1024 * 1024, MAX_GPR_BYTES - total + 1)):
            total += len(chunk)
            if total > MAX_GPR_BYTES:
                raise ValueError(f"GPR 파일이 해시 검사 중 {MAX_GPR_BYTES}바이트 제한을 초과했습니다.")
            digest.update(chunk)
    return digest.hexdigest()


def gpr_saved_figure(path: str, geometry_path: str, scalar_path: str, axis_index: int,
                     expected_sha: str) -> tuple[go.Figure, dict]:
    """Read saved geometry/scalars bound to one unchanged file; render <=20k cells."""
    geometry = read_gpr_rectilinear(path, geometry_path.rsplit("/", 1)[0])
    if geometry.source["sha256"] != expected_sha:
        raise ValueError("GPR 파일이 목록 검사 이후 변경되었습니다. 자료 목록을 다시 여세요.")
    count = len(geometry.cells)
    field = None
    description = None
    if scalar_path:
        if _gpr_sha(path) != expected_sha:
            raise ValueError("기하와 원시 필드의 원본 파일 해시가 다릅니다.")
        array, description = read_gpr_numeric_array(path, scalar_path, max_bytes=8 * 1024 * 1024)
        if array.ndim == 1 and array.shape == (count,) and axis_index == 0:
            field = array
        elif array.ndim == 2 and array.shape[1] == count and 0 <= axis_index < array.shape[0]:
            field = array[axis_index]
        else:
            raise ValueError(f"지원하지 않는 셀 배열: shape={array.shape}. (셀 수,) 또는 (첫 축, {count}) 배열을 명시적으로 선택하세요.")
        if field.dtype.kind in "iu" and (int(field.min()) < -(2 ** 53) or int(field.max()) > 2 ** 53):
            raise ValueError("3D 표시에서 정확히 표현할 수 없는 큰 정수 필드입니다. 원시값을 반올림하여 표시하지 않습니다.")
        if field.dtype.kind == "f" and field.dtype.itemsize > 8:
            raise ValueError("3D 표시보다 정밀도가 높은 실수 배열은 지원하지 않습니다.")
        if _gpr_sha(path) != expected_sha:
            raise ValueError("원시 필드를 읽는 동안 GPR 파일이 변경되었습니다.")
    selected = np.linspace(0, count - 1, min(count, 20_000), dtype=np.int64)
    centers = (geometry.points[geometry.cells[selected]] / 8).sum(axis=1)
    k, row, col = np.unravel_index(selected, geometry.shape)
    values = np.asarray(field[selected], dtype=float) if field is not None else k.astype(float)
    finite = np.isfinite(values)
    custom = np.column_stack((selected, k, row, col, values))[finite]
    fig = go.Figure(go.Scatter3d(
        x=centers[finite, 0], y=centers[finite, 1], z=centers[finite, 2], mode="markers",
        customdata=custom,
        marker={"size": 4, "color": values[finite], "colorscale": "Viridis", "opacity": 0.85,
                "colorbar": {"title": "저장 원시값" if scalar_path else "층 인덱스"}},
        hovertemplate="셀 %{customdata[0]:.0f} · KIJ (%{customdata[1]:.0f}, %{customdata[2]:.0f}, %{customdata[3]:.0f})<br>X=%{x}<br>Y=%{y}<br>Z=%{z}<br>표시값=%{customdata[4]}<extra>저장 자료</extra>",
    ))
    fig.update_layout(height=500, margin={"l": 0, "r": 0, "t": 10, "b": 0},
        scene={"xaxis_title": "X (저장 좌표, 단위 미상)", "yaxis_title": "Y (저장 좌표, 단위 미상)",
               "zaxis_title": "Z (저장 꼭짓점 좌표, 단위·기준면 미상)", "aspectmode": "data"})
    receipt = geometry.receipt()
    parametric = receipt.pop("parametric_z_axis")
    receipt["parametric_z_axis_preview"] = parametric[:50]
    receipt["parametric_z_axis_count"] = len(parametric)
    receipt.update(saved_data_only=True, new_solver_result=False, scalar_path=scalar_path or None,
        scalar_storage=description, first_axis_index=axis_index if scalar_path else None,
        field_units=None, first_axis_meaning=None, time_units=None, rendered_cells=int(finite.sum()),
        sampled_cells=len(selected), omitted_nonfinite_sample_values=int((~finite).sum()),
        render_limit=20_000, source_sha256=expected_sha,
        scalar_index_mapping="raw flat field index to geometry flat KIJ cell index; field semantics/order not independently verified")
    return fig, receipt


def gpr_workbench() -> None:
    st.subheader("GPR 저장 기하 · 원시 셀 자료 보기")
    st.caption("읽기 전용입니다. 지원되는 비회전·원점 0 직교 육면체 패킷만 해독하며, 저장 자료를 새 계산 결과로 취급하지 않습니다.")
    with st.form("gw_gpr_inventory_form"):
        source = st.text_input("읽기 전용 GPR 파일 (서버 경로)", key="gw_gpr_source")
        opened = st.form_submit_button("GPR 자료 목록 열기")
    if st.session_state.get("gw_gpr_open_source") != source.strip():
        for key in ("gw_gpr_inventory", "gw_gpr_figure", "gw_gpr_receipt"):
            st.session_state.pop(key, None)
    if opened:
        for key in ("gw_gpr_inventory", "gw_gpr_figure", "gw_gpr_receipt"):
            st.session_state.pop(key, None)
        try:
            if not source.strip():
                raise ValueError("GPR 파일 경로를 지정하세요.")
            st.session_state.gw_gpr_inventory = inventory_gpr(source.strip(), max_objects=5000)
            st.session_state.gw_gpr_open_source = source.strip()
        except (OSError, ValueError) as error:
            st.error(f"GPR 읽기 오류: {error}")
    inventory = st.session_state.get("gw_gpr_inventory")
    if inventory is None:
        return
    datasets = [record for record in inventory["objects"] if record["kind"] == "dataset"]
    grids = [record["path"] for record in datasets if record["path"].endswith("/Geometry.xmsgrid")]
    st.caption(f"객체 {inventory['object_count']:,}개 · 데이터셋 {len(datasets):,}개 · 원본 SHA-256 {inventory['sha256']}")
    with st.expander("HDF5 자료 목록 (최대 500행 표시)"):
        st.dataframe(pd.DataFrame(datasets[:500]), use_container_width=True, hide_index=True)
    if not grids:
        st.error("지원되는 Geometry.xmsgrid 데이터셋을 찾지 못했습니다. 다른 패킷이나 격자는 자동 추측하지 않습니다.")
        return
    numeric = []
    for record in datasets:
        try:
            supported = np.dtype(record["dtype"]).kind in "biuf"
        except (TypeError, ValueError):
            supported = False
        if supported and record["path"] not in grids:
            numeric.append(record["path"])
    with st.form("gw_gpr_view_form"):
        geometry_path = st.selectbox("관측된 기하 데이터셋", grids)
        scalar_path = st.selectbox("직접 선택할 원시 셀 필드", ["", *numeric],
            format_func=lambda value: value or "원시 필드 없이 기하만")
        axis_index = st.number_input("저장 배열 첫 축 인덱스 (시간/샘플, 0부터)", 0, 10000, 0, step=1)
        render = st.form_submit_button("선택한 저장 기하·필드 보기")
    if render:
        st.session_state.pop("gw_gpr_figure", None)
        st.session_state.pop("gw_gpr_receipt", None)
        try:
            figure, receipt = gpr_saved_figure(source.strip(), geometry_path, scalar_path,
                int(axis_index), inventory["sha256"])
            st.session_state.gw_gpr_figure = figure
            st.session_state.gw_gpr_receipt = receipt
        except (OSError, ValueError) as error:
            st.error(f"GPR 기하/원시 배열 오류: {error}")
    if "gw_gpr_figure" in st.session_state:
        st.plotly_chart(st.session_state.gw_gpr_figure, use_container_width=True, key="gw_gpr_saved_plot")
        st.json(st.session_state.gw_gpr_receipt)
        st.caption("좌표는 실제 꼭짓점의 평균입니다. parametric Z축을 깊이로 사용하지 않습니다. 필드 평탄 인덱스를 기하 KIJ 셀 인덱스에 그대로 대응하며, 필드 의미·순서의 외부 검증은 수행하지 않습니다.")
        st.caption("좌표·필드·시간의 단위, CRS와 표고 기준면은 미상으로 유지합니다. 저장 메타데이터와 네이티브 모델 단위의 불일치를 추측으로 보정하지 않습니다. 최대 20,000셀을 표시하며 원본은 변경하지 않습니다.")


def main() -> None:
    st.set_page_config(page_title="BasinLens · 지하수 작업대", page_icon="💧", layout="wide")
    if "gw_case" not in st.session_state:
        st.session_state.gw_case = demo_case().to_dict()
        st.session_state.gw_revision = 0
    if "gw_project" not in st.session_state:
        st.session_state.gw_project = project_from_groundwater(GroundwaterCase.from_dict(st.session_state.gw_case)).to_dict()
    case = st.session_state.gw_case
    sidebar(case)
    st.title("지하수 모델 작업대")
    st.caption("BasinLens · 구조화 격자 → 조건 설정 → MODFLOW 6 → 수두 검토")
    project = SubsurfaceProject.from_dict(st.session_state.gw_project)
    st.caption(f"분야: {DOMAIN_LABELS[project.domain]} · 계산 역할: {project.model.role}")
    st.info("기본 편집기는 단상·피압 지하수 유동(GWF) 연구용 모듈입니다. CO₂–염수 다상유동, plume, 용해·반응, 지반변형과 현장 안전성은 계산하지 않습니다. 기본 예제는 합성 자료입니다.")
    if "gw_notice" in st.session_state:
        st.success(st.session_state.pop("gw_notice"))
    grid = case["grid"]
    a, b, c, d = st.columns(4)
    a.metric("프로젝트", case["name"])
    b.metric("전체 셀", f"{grid['nlay'] * grid['nrow'] * grid['ncol']:,}")
    c.metric("모델 영역", f"{grid['ncol'] * grid['delr_m']:g} × {grid['nrow'] * grid['delc_m']:g} m")
    d.metric("모의 기간", f"{sum(p['length_days'] for p in case['periods']):g} day")
    editor(case, st.session_state.gw_revision)
    execute(case)
    st.divider()
    results(case)
    st.divider()
    native_workbench()
    st.divider()
    gpr_workbench()


if __name__ == "__main__":
    main()
