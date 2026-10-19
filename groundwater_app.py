"""Original groundwater workbench: ``streamlit run groundwater_app.py``.

The interface drives the open MODFLOW 6 engine through the project's validated
case contract. It does not reproduce a proprietary application's code or assets.
"""

from __future__ import annotations

import copy
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
    export_case,
    load_case,
    run_case,
)

MAX_UPLOAD_BYTES = 2_000_000
MAX_CELLS = 100_000
MAX_CELL_TIMES = 2_000_000


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


def replace_case(candidate: dict[str, Any], message: str) -> None:
    """Commit a validated edit and clear all products derived from older inputs."""
    validated = validate_ui_case(candidate)
    old = st.session_state.get("gw_case")
    if old is None or case_fingerprint(old) != case_fingerprint(validated):
        st.session_state.gw_case = validated
        st.session_state.gw_revision = st.session_state.get("gw_revision", 0) + 1
        for key in ("gw_result", "gw_input_zip", "gw_csv", "gw_failed_run_zip"):
            st.session_state.pop(key, None)
        message += " 이전 입력의 계산 결과는 비웠습니다."
    st.session_state.gw_notice = message


def apply_edit(candidate: dict[str, Any], message: str) -> None:
    try:
        replace_case(candidate, message)
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
        upload = st.file_uploader("프로젝트 JSON 열기", type=["json"], key="gw_upload")
        if st.button("업로드 파일 불러오기", disabled=upload is None, use_container_width=True):
            if upload is not None:
                try:
                    if upload.size > MAX_UPLOAD_BYTES:
                        raise ValueError("프로젝트 JSON은 2 MB 이하여야 합니다.")
                    with tempfile.TemporaryDirectory(prefix="basinlens-gw-import-") as tmp:
                        path = Path(tmp) / "case.json"
                        path.write_bytes(upload.getvalue())
                        candidate = load_case(path).to_dict()
                    apply_edit(candidate, "프로젝트를 불러왔습니다.")
                except (ValueError, UnicodeError, TypeError, KeyError, OSError) as exc:
                    st.error(f"프로젝트를 읽지 못했습니다: {exc}")
        if st.button("합성 예제로 새로 시작", use_container_width=True):
            apply_edit(demo_case().to_dict(), "합성 예제를 열었습니다.")
        st.download_button("프로젝트 JSON 저장", case_bytes(case), "groundwater_case.json", "application/json", use_container_width=True)
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
    a, b = st.columns([3, 1])
    executable = a.text_input("MODFLOW 6 실행 파일", value="mf6", help="서버에 설치된 mf6 또는 실행 파일의 절대 경로를 입력하세요. 설치·다운로드는 자동으로 수행하지 않습니다.")
    b.caption("실제 엔진이 필요합니다.")
    run_clicked = b.button("MODFLOW 6 계산", type="primary", use_container_width=True)
    export_clicked = st.button("엔진 없이 MF6 입력 파일 만들기")
    if export_clicked:
        try:
            with tempfile.TemporaryDirectory(prefix="basinlens-gw-input-") as tmp:
                with st.spinner("검증한 프로젝트를 MF6 입력으로 변환합니다…"):
                    folder = export_case(GroundwaterCase.from_dict(case), Path(tmp) / "input")
                    st.session_state.gw_input_zip = zip_directory(Path(folder))
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
                        result = run_case(GroundwaterCase.from_dict(case), output, exe_name=executable.strip() or "mf6")
                        products = {
                            "fingerprint": case_fingerprint(case), "heads": result.heads,
                            "times": result.times_days, "summary": result.summary,
                            "bundle": zip_directory(output),
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
    if "gw_failed_run_zip" in st.session_state:
        st.download_button("실패한 실행의 진단 파일 다운로드", st.session_state.gw_failed_run_zip, "groundwater_failed_run.zip", "application/zip")


def results(case: dict[str, Any]) -> None:
    products = st.session_state.get("gw_result")
    if products is None:
        st.subheader("모델 미리보기")
        st.plotly_chart(model_figure(case), use_container_width=True, key="model_preview")
        st.info("합성 지층과 기본 우물의 위치입니다. 수두 결과를 보려면 MODFLOW 6 계산을 실행하세요.")
        return
    if products["fingerprint"] != case_fingerprint(case):
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
    a, b = st.columns(2)
    a.download_button("전체 실행 ZIP 다운로드", products["bundle"], "groundwater_run.zip", "application/zip", use_container_width=True)
    if b.button("모든 시각·층의 수두 CSV 준비", use_container_width=True):
        with st.spinner("수두 CSV를 만듭니다…"):
            st.session_state.gw_csv = heads_csv(heads, times, case)
    if "gw_csv" in st.session_state:
        st.download_button("수두 결과 CSV 다운로드", st.session_state.gw_csv, "groundwater_heads.csv", "text/csv")


def main() -> None:
    st.set_page_config(page_title="BasinLens · 지하수 작업대", page_icon="💧", layout="wide")
    if "gw_case" not in st.session_state:
        st.session_state.gw_case = demo_case().to_dict()
        st.session_state.gw_revision = 0
    case = st.session_state.gw_case
    sidebar(case)
    st.title("지하수 모델 작업대")
    st.caption("BasinLens · 구조화 격자 → 조건 설정 → MODFLOW 6 → 수두 검토")
    st.info("단상·피압 지하수 유동(GWF) 연구용 모듈입니다. CO₂–염수 다상유동, plume, 용해·반응, 지반변형과 현장 안전성은 계산하지 않습니다. 기본 예제는 합성 자료입니다.")
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


if __name__ == "__main__":
    main()
