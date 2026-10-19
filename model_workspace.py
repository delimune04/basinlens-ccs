"""Coherent bounded model workspace; run with ``streamlit run model_workspace.py``.

The editable JSON is an explicit, synthetic/assumed SI groundwater workflow.
Only validated applied drafts may be exported or solved. BasinLens .blproj
packages are distinct from the read-only GMS .gpr formats.
"""
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
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from basinlens_ccs.subsurface.model_workflow import (  # noqa: E402
    WorkflowCase, export_workflow, load_workflow_case, preview_grid,
    read_workflow_results, run_workflow, verify_workflow_export,
    verify_workflow_roundtrip,
)
from basinlens_ccs.groundwater.native_run import verify_native_run  # noqa: E402

MAX_CASE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_PLOT_CELLS = 20_000
FIELDS = {
    "head": ("수두", "m", None),
    "hydraulic_conductivity_x": ("수리전도도 Kx", "m/day", "kx_m_day"),
    "hydraulic_conductivity_y": ("수리전도도 Ky", "m/day", "ky_m_day"),
    "hydraulic_conductivity_z": ("수리전도도 Kz", "m/day", "kz_m_day"),
    "specific_storage": ("비저류계수", "1/m", "ss_per_m"),
    "porosity": ("공극률", "1", "porosity"),
}
DEFAULT_VIEW = {"selected_layer": 0, "selected_field": "hydraulic_conductivity_x",
                "chart_mode": "2d", "show_wells": True}
PRODUCT_KEYS = ("mw_export", "mw_result", "mw_roundtrip", "mw_package", "mw_figure")


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _fingerprint(case) -> str:
    return hashlib.sha256(_json_bytes(case.to_dict())).hexdigest()


def workflow_from_upload(payload: bytes) -> WorkflowCase:
    """Use the bounded backend loader, including duplicate/non-finite rejection."""
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_CASE_BYTES:
        raise ValueError("모델 JSON은 1 byte 이상 2 MiB 이하여야 합니다.")
    with tempfile.TemporaryDirectory(prefix="basinlens-workflow-json-") as directory:
        path = Path(directory) / "case.json"
        path.write_bytes(payload)
        return load_workflow_case(path)


def _clear_products() -> None:
    for key in PRODUCT_KEYS:
        st.session_state.pop(key, None)


def _changed_draft() -> None:
    _clear_products()
    st.session_state.mw_dirty = True


def _drop_package_context() -> None:
    old_package = st.session_state.pop("mw_package_keeper", None)
    if old_package is not None:
        old_package.cleanup()
    st.session_state.pop("mw_loaded_package_receipt", None)


def _load_case(case: WorkflowCase, source: str, view_state: dict | None = None) -> None:
    _clear_products()
    _drop_package_context()
    st.session_state.mw_case = case.to_dict()
    st.session_state.mw_source = source
    st.session_state.mw_draft = _json_bytes(case.to_dict()).decode("utf-8")
    st.session_state.mw_dirty = False
    st.session_state.mw_revision = st.session_state.get("mw_revision", 0) + 1
    view = dict(DEFAULT_VIEW if view_state is None else view_state)
    st.session_state.mw_view = view
    for key in ("mw_layer", "mw_field", "mw_chart_mode", "mw_show_wells", "mw_time"):
        st.session_state.pop(key, None)


def _restore_valid() -> None:
    _load_case(WorkflowCase.from_dict(st.session_state.mw_case), st.session_state.mw_source,
               st.session_state.get("mw_view", DEFAULT_VIEW))


def _diagnose(stage: str, error: Exception, output: str | None = None) -> None:
    receipt = {"stage": stage, "exception_type": type(error).__name__, "message": str(error),
               "output_path": output,
               "recovery": "진단을 확인하고 입력/엔진을 수정한 뒤 새 출력 폴더에서 다시 실행하세요.",
               "last_valid_case_preserved": "mw_case" in st.session_state}
    st.session_state.mw_diagnostic = receipt
    st.error(f"모델 작업 오류 · {stage}: {error}")


def _archive(directory: Path) -> bytes:
    """Bounded archive after a backend verifier has established run integrity."""
    entries, total = [], 0
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink():
            raise ValueError("다운로드 묶음에 심볼릭 링크를 포함할 수 없습니다.")
        if path.is_file():
            total += path.stat().st_size
            if total > MAX_DOWNLOAD_BYTES or len(entries) >= 5000:
                raise ValueError("다운로드 묶음은 128 MiB / 5000개 파일 제한을 넘을 수 없습니다.")
            entries.append(path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in entries:
            archive.write(path, path.relative_to(directory).as_posix())
    if buffer.tell() > MAX_DOWNLOAD_BYTES:
        raise ValueError("압축한 다운로드 묶음이 128 MiB 제한을 초과합니다.")
    return buffer.getvalue()


def _cell_table(preview: dict) -> pd.DataFrame:
    return pd.DataFrame(preview["cells"])


def _preview_tables(case: WorkflowCase, cells: pd.DataFrame) -> None:
    data = case.to_dict()
    a, b, c = st.columns(3)
    a.metric("워크플로 모델", data["project"]["name"])
    b.metric("격자 셀", f"{len(cells):,}")
    c.metric("지층", len(data["strata"]))
    spatial = data["project"]
    st.caption(f"길이 m · 시간 day · CRS: {spatial['crs']} · 수직 기준면: {spatial['vertical_datum']}")
    with st.expander("지층 · 물성 · 격자 배치", expanded=False):
        st.write("지층과 물성은 JSON에 선언한 가정/합성 입력입니다. 아래 셀 배치는 계산에 사용할 값입니다.")
        st.dataframe(pd.DataFrame(data["materials"]), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(data["strata"]), use_container_width=True, hide_index=True)
        st.dataframe(cells.head(2000), use_container_width=True, hide_index=True)
        if len(cells) > 2000:
            st.caption("표는 첫 2,000셀입니다. 전체 배치는 검증한 CSV로 받을 수 있습니다.")
        st.download_button("격자·지층·물성 CSV 다운로드", cells.to_csv(index=False).encode(),
                           "workflow_grid.csv", "text/csv", key="mw_grid_csv")
    with st.expander("기간별 경계조건 · 함양 · 우물", expanded=False):
        st.caption("경계는 각 기간에 명시적으로 지정한 셀 조건입니다. 우물 주입은 +, 취수는 −의 m³/day입니다.")
        for index, period in enumerate(data["periods"]):
            st.markdown(f"**기간 {index + 1} · {period['duration_day']:g} day · {period['nsteps']} 단계 · {'정상' if period['steady'] else '비정상'}**")
            rows = []
            for boundary in data["boundaries"]:
                if boundary["period"] == index:
                    k, row, col = boundary["cell"]
                    rows.append({"종류": boundary["kind"], "이름": boundary["label"],
                                 "층": k, "행": row, "열": col, **boundary["values"]})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("미지정한 외부 면은 유량 없음 경계입니다. 공극률은 지질 메타데이터이며 피압 GWF의 저류계수로 사용하지 않습니다.")


def _values(cells: pd.DataFrame, field: str, heads: np.ndarray | None) -> np.ndarray:
    if field == "head":
        if heads is None:
            raise ValueError("수두는 검증한 실제 실행이 완료된 뒤 선택할 수 있습니다.")
        return np.asarray(heads).reshape(-1)
    column = FIELDS[field][2]
    return cells[column].to_numpy(dtype=float)


def _figure(cells: pd.DataFrame, values: np.ndarray, view: dict, case: WorkflowCase,
            period_index: int | None = None) -> go.Figure:
    if len(values) != len(cells) or not np.isfinite(values).all():
        raise ValueError("표시할 결과와 격자 셀 수가 다르거나 비유한 값이 있습니다.")
    frame = cells.copy()
    frame["value"] = values
    if view["chart_mode"] == "2d":
        frame = frame.loc[frame["layer"] == view["selected_layer"]]
    if len(frame) > MAX_PLOT_CELLS:
        step = int(np.ceil(len(frame) / MAX_PLOT_CELLS))
        frame = frame.iloc[::step]
        st.caption(f"시각화는 균등 간격으로 최대 {MAX_PLOT_CELLS:,}셀을 표시합니다. CSV에는 전체 셀이 들어갑니다.")
    label, unit, _ = FIELDS[view["selected_field"]]
    custom = np.column_stack((frame["layer"], frame["row"], frame["column"],
                              frame["stratum_id"], frame["material_id"]))
    marker = {"size": 7, "color": frame["value"], "colorscale": "Viridis",
              "showscale": True, "colorbar": {"title": f"{label} ({unit})"}}
    hover = "층 %{customdata[0]} · 행 %{customdata[1]} · 열 %{customdata[2]}<br>지층 %{customdata[3]} · 물성 %{customdata[4]}<br>값 %{marker.color}<extra></extra>"
    if view["chart_mode"] == "3d":
        z = (frame["top_m"].to_numpy() / 2 + frame["bottom_m"].to_numpy() / 2)
        fig = go.Figure(go.Scatter3d(x=frame["x_m"], y=frame["y_m"], z=z,
                                    mode="markers", marker=marker, customdata=custom,
                                    hovertemplate=hover, name=label))
        fig.update_layout(scene={"xaxis_title": "x (m)", "yaxis_title": "y (m)",
                                 "zaxis_title": "고도 (m)", "aspectmode": "data"})
    else:
        marker["symbol"] = "square"
        fig = go.Figure(go.Scatter(x=frame["x_m"], y=frame["y_m"], mode="markers",
                                  marker=marker, customdata=custom, hovertemplate=hover, name=label))
        fig.update_xaxes(title="x (m)", constrain="domain")
        fig.update_yaxes(title="y (m)", scaleanchor="x", scaleratio=1)
    if view["show_wells"]:
        wells = [b for b in case.to_dict()["boundaries"] if b["kind"] == "WEL"
                 and (period_index is None or b["period"] == period_index)
                 and (view["chart_mode"] == "3d" or b["cell"][0] == view["selected_layer"])]
        if wells:
            index = {(int(row.layer), int(row.row), int(row.column)): row
                     for row in cells.itertuples(index=False)}
            nodes = [index[tuple(w["cell"])] for w in wells]
            hovertext = [f"{w['label']} · 기간 {w['period'] + 1} · {w['values']['rate_m3_day']:g} m³/day" for w in wells]
            kwargs = {"x": [n.x_m for n in nodes], "y": [n.y_m for n in nodes],
                      "mode": "markers", "marker": {"color": "red", "size": 9, "symbol": "cross"},
                      "text": hovertext, "hovertemplate": "%{text}<extra></extra>", "name": "우물 셀"}
            if view["chart_mode"] == "3d":
                kwargs["z"] = [n.top_m / 2 + n.bottom_m / 2 for n in nodes]
                fig.add_trace(go.Scatter3d(**kwargs))
            else:
                fig.add_trace(go.Scatter(**kwargs))
    fig.update_layout(title=f"{label} · {view['chart_mode']} · 좌표는 선언한 m 기준", margin={"t": 50})
    return fig


def _render_plot(case: WorkflowCase, cells: pd.DataFrame, result=None) -> None:
    fields = list(FIELDS)
    saved = st.session_state.get("mw_view", DEFAULT_VIEW)
    if st.session_state.get("mw_field", saved["selected_field"]) not in fields:
        st.session_state.mw_field = fields[0]
    nlay = int(cells["layer"].max()) + 1
    if st.session_state.get("mw_layer", saved["selected_layer"]) >= nlay:
        st.session_state.mw_layer = 0
    a, b, c, d = st.columns(4)
    layer = a.selectbox("모델 표시 층 (0부터)", list(range(nlay)),
                        index=min(saved["selected_layer"], nlay - 1), key="mw_layer")
    field = b.selectbox("모델 표시 항목", fields,
                        index=fields.index(saved["selected_field"]) if saved["selected_field"] in fields else 0,
                        format_func=lambda x: f"{FIELDS[x][0]} ({FIELDS[x][1]})", key="mw_field")
    mode = c.selectbox("모델 표시 방식", ["2d", "3d"],
                       index=["2d", "3d"].index(saved["chart_mode"]), key="mw_chart_mode")
    wells = d.checkbox("모델 우물 표시", value=saved["show_wells"], key="mw_show_wells")
    view = {"selected_layer": layer, "selected_field": field, "chart_mode": mode, "show_wells": wells}
    st.session_state.mw_view = view
    heads, selected_time = None, None
    if result is not None:
        index = st.selectbox("모델 결과 시각 (day)", list(range(len(result.times_day))),
                             format_func=lambda i: f"{result.times_day[i]:g}", key="mw_time")
        heads, selected_time = result.heads_m[index], float(result.times_day[index])
    if field == "head" and heads is None:
        st.info("수두 표시 설정은 보존했습니다. 검증한 실제 실행을 완료하면 수두를 표시합니다.")
        return
    values = _values(cells, field, heads)
    period_index = None
    if selected_time is not None:
        end_times = np.cumsum([p["duration_day"] for p in case.to_dict()["periods"]])
        period_index = min(int(np.searchsorted(end_times, selected_time, side="left")), len(end_times) - 1)
    fig = _figure(cells, values, view, case, period_index)
    st.plotly_chart(fig, use_container_width=True, key="mw_field_plot")
    st.session_state.mw_figure = fig
    if result is not None:
        selected = cells.copy()
        selected.insert(0, "time_day", selected_time)
        selected["head_m"] = np.asarray(heads).reshape(-1)
        csv = selected.to_csv(index=False).encode("utf-8")
        if len(csv) > MAX_DOWNLOAD_BYTES:
            st.warning("선택 시각 CSV가 다운로드 크기 제한을 초과했습니다. 실행 폴더를 사용하세요.")
        else:
            st.session_state.mw_result["heads_csv"] = csv
            st.download_button("선택 시각 모델 수두 CSV 다운로드", csv, "workflow_heads.csv", "text/csv")
        st.dataframe(pd.DataFrame(result.budget), use_container_width=True, hide_index=True)
        st.json(result.summary)
        if (result.summary.get("water_balance_passed") is True
                and result.summary.get("boundary_rates_passed") is True
                and result.summary.get("confined_saturation_support_passed") is True):
            st.success("검증한 실제 실행의 물수지·경계 유량·피압 포화 가정 판정이 통과했습니다. 원본 GMS 동등성은 미검증입니다.")
        else:
            st.error("실행은 완료했지만 물수지·경계 유량·피압 포화 가정 중 통과하지 않은 판정이 있습니다. 결과와 가정을 확인하세요.")


def render_model_workspace() -> None:
    st.subheader("모델 작업공간 · 파일 → 지질·격자 → 해석 → 결과")
    st.info("구조화 격자 기반 단상·피압 지하수 워크플로입니다. BasinLens .blproj는 자체 프로젝트 형식이며 GMS .gpr 쓰기·원본 동등성·CO₂/석유 다상유동은 미구현입니다.")
    examples = sorted((ROOT / "examples/workflow").glob("*.json"))
    labels = [path.name for path in examples]
    if labels:
        selected = st.selectbox("모델 합성 예제", labels, key="mw_example")
        if st.button("모델 합성 예제 불러오기", key="mw_load_example"):
            try:
                _load_case(load_workflow_case(ROOT / "examples/workflow" / selected), f"합성 예제 {selected}")
            except Exception as exc:
                _diagnose("예제 읽기", exc)
    upload = st.file_uploader("모델 JSON / .blproj 파일 (JSON 2 MiB · 패키지 32 MiB)",
                              type=["json", "blproj"], key="mw_upload")
    if st.button("모델 파일 불러오기", key="mw_load_file"):
        pending_keeper = None
        try:
            if upload is None:
                raise ValueError("불러올 모델 파일을 선택하세요.")
            limit = MAX_PACKAGE_BYTES if upload.name.lower().endswith(".blproj") else MAX_CASE_BYTES
            if upload.size > limit:
                raise ValueError("업로드 파일이 해당 형식의 크기 제한을 초과합니다.")
            payload = upload.getvalue()
            if upload.name.lower().endswith(".blproj"):
                if not payload or len(payload) > MAX_PACKAGE_BYTES:
                    raise ValueError(".blproj 패키지는 32 MiB 이하여야 합니다.")
                pending_keeper = tempfile.TemporaryDirectory(prefix="basinlens-workflow-package-")
                source = Path(pending_keeper.name) / "uploaded.blproj"
                source.write_bytes(payload)
                from basinlens_ccs.subsurface.workflow_project import open_workflow_project
                loaded = open_workflow_project(source, Path(pending_keeper.name) / "opened")
                _load_case(loaded.case, "검증한 .blproj 패키지", loaded.view_state)
                st.session_state.mw_package_keeper = pending_keeper
                pending_keeper = None
                st.session_state.mw_loaded_package_receipt = loaded.receipt
            else:
                _load_case(workflow_from_upload(payload), "검증한 JSON 업로드")
        except Exception as exc:
            if pending_keeper is not None:
                pending_keeper.cleanup()
            _diagnose("모델 불러오기", exc)
    if "mw_case" not in st.session_state:
        st.caption("파일 또는 합성 예제를 명시적으로 불러오면 편집·내보내기·해석을 시작할 수 있습니다.")
        _render_diagnostic()
        return
    case = WorkflowCase.from_dict(st.session_state.mw_case)
    st.caption(f"마지막으로 적용한 유효 모델: {st.session_state.mw_source}")
    if "mw_loaded_package_receipt" in st.session_state:
        with st.expander("불러온 프로젝트 패키지 검증 기록", expanded=False):
            st.json(st.session_state.mw_loaded_package_receipt)
    st.text_area("모델 JSON 초안 편집", height=280, max_chars=MAX_CASE_BYTES,
                 key="mw_draft", on_change=_changed_draft)
    draft = None
    try:
        draft = workflow_from_upload(st.session_state.mw_draft.encode("utf-8"))
    except Exception as exc:
        st.error(f"모델 초안 검증 오류: {exc}")
    changed = draft is None or _fingerprint(draft) != _fingerprint(case)
    if changed:
        _clear_products()
    a, b = st.columns(2)
    if a.button("검증한 모델 초안 적용", disabled=draft is None, key="mw_apply_draft"):
        _clear_products()
        _drop_package_context()
        st.session_state.mw_source = "검증해 적용한 편집 초안"
        st.session_state.mw_case = draft.to_dict()
        st.session_state.mw_dirty = False
        case = draft
    b.button("마지막 유효 모델로 초안 복구", on_click=_restore_valid, key="mw_restore_draft")
    executable = draft is not None and _fingerprint(draft) == _fingerprint(case)
    if not executable:
        st.warning("초안을 적용하거나 마지막 유효 모델로 복구한 뒤 저장·내보내기·해석할 수 있습니다.")
    try:
        cells = _cell_table(preview_grid(case))
        _preview_tables(case, cells)
    except Exception as exc:
        _diagnose("격자·지질 미리보기", exc)
        _render_diagnostic()
        return
    output = st.text_input("모델 작업 폴더 (새 폴더)", "build/model-workspace", key="mw_output")
    engine = st.text_input("모델 MODFLOW 6 실행 파일", os.environ.get("MF6_EXE", "mf6"), key="mw_engine")
    timeout = st.number_input("모델 실행 제한 시간 (초)", 1, 1800, 300, key="mw_timeout")
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("모델 프로젝트 저장 · 왕복 검증", disabled=not executable, key="mw_save_project"):
        _clear_products()
        path = str(Path(output).with_suffix(".blproj"))
        try:
            view = dict(st.session_state.get("mw_view", DEFAULT_VIEW))
            for widget, field in (("mw_layer", "selected_layer"), ("mw_field", "selected_field"),
                                  ("mw_chart_mode", "chart_mode"), ("mw_show_wells", "show_wells")):
                view[field] = st.session_state.get(widget, view[field])
            from basinlens_ccs.subsurface.workflow_project import (save_workflow_project,
                                                                  verify_workflow_project_roundtrip)
            Path(path).expanduser().absolute().parent.mkdir(parents=True, exist_ok=True)
            saved = save_workflow_project(case, path, view_state=view)
            receipt = verify_workflow_project_roundtrip(saved)
            st.session_state.mw_package = {"path": str(saved), "receipt": receipt, "bytes": Path(saved).read_bytes(),
                                             "fingerprint": _fingerprint(case)}
        except Exception as exc:
            _diagnose("프로젝트 저장·왕복", exc, path)
    if col2.button("모델 MF6 입력 내보내기", disabled=not executable, key="mw_export_inputs"):
        _clear_products()
        try:
            export_workflow(case, output)
            captured = verify_workflow_export(output)
            if _fingerprint(captured) != _fingerprint(case):
                raise ValueError("내보낸 입력에 캡처한 모델과 현재 적용한 모델이 다릅니다.")
            st.session_state.mw_export = {"path": output, "bundle": _archive(Path(output)),
                                          "fingerprint": _fingerprint(case)}
        except Exception as exc:
            _diagnose("MF6 입력 내보내기", exc, output)
    if col3.button("모델 MF6 실제 실행", disabled=not executable, key="mw_run"):
        _clear_products()
        try:
            run_workflow(case, output, exe_name=engine.strip() or "mf6", timeout_seconds=int(timeout))
            verify_native_run(output)
            result = read_workflow_results(output)
            if _fingerprint(result.case) != _fingerprint(case):
                raise ValueError("실행에 캡처한 모델과 현재 적용한 모델이 다릅니다.")
            st.session_state.mw_result = {"path": output, "captured_result": result,
                                           "fingerprint": _fingerprint(case), "bundle": _archive(Path(output))}
        except Exception as exc:
            _diagnose("MF6 실제 실행", exc, output)
    if col4.button("모델 네이티브 왕복 검증", disabled=not executable, key="mw_native_roundtrip"):
        _clear_products()
        try:
            target = Path(output).expanduser().absolute()
            if target.exists() or target.is_symlink():
                raise FileExistsError("Choose a fresh workflow directory")
            target.mkdir(parents=True, exist_ok=False)
            source = export_workflow(case, target / "source")
            receipt = verify_workflow_roundtrip(source, target / "roundtrip")
            st.session_state.mw_roundtrip = {"receipt": receipt, "fingerprint": _fingerprint(case)}
        except Exception as exc:
            _diagnose("네이티브 왕복", exc, output)
    if "mw_package" in st.session_state:
        products = st.session_state.mw_package
        st.json(products["receipt"])
        st.download_button("검증한 모델 .blproj 다운로드", products["bytes"], "model.blproj", "application/zip")
    if "mw_export" in st.session_state:
        st.success("MF6 입력 파일 생성과 무결성 검증을 완료했습니다. 엔진은 실행하지 않았습니다.")
        st.download_button("검증한 모델 MF6 입력 ZIP 다운로드", st.session_state.mw_export["bundle"],
                           "workflow_mf6_inputs.zip", "application/zip")
    if "mw_roundtrip" in st.session_state:
        st.json(st.session_state.mw_roundtrip["receipt"])
    result = None
    if "mw_result" in st.session_state and executable:
        products = st.session_state.mw_result
        if products["fingerprint"] == _fingerprint(case):
            result = products["captured_result"]
            st.download_button("검증한 모델 실행 ZIP 다운로드", products["bundle"], "workflow_run.zip", "application/zip")
    _render_plot(case, cells, result)
    st.download_button("적용한 모델 JSON 다운로드", _json_bytes(case.to_dict()), "workflow_case.json", "application/json")
    _render_diagnostic()


def _render_diagnostic() -> None:
    if "mw_diagnostic" in st.session_state:
        with st.expander("마지막 실패 진단 · 재개 조건", expanded=False):
            st.json(st.session_state.mw_diagnostic)
            st.download_button("모델 작업 진단 JSON 다운로드", _json_bytes(st.session_state.mw_diagnostic),
                               "workflow_diagnostic.json", "application/json")


if __name__ == "__main__":
    st.set_page_config(page_title="BasinLens · 모델 작업공간", layout="wide")
    render_model_workspace()
