"""Streamlit demonstration interface for BasinLens CCS."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from basinlens_ccs import analyze_sites, sites_from_dataframe  # noqa: E402
from basinlens_ccs.models import InputValidationError  # noqa: E402


st.set_page_config(page_title="BasinLens CCS", page_icon="🌍", layout="wide")

st.title("BasinLens CCS")
st.caption("Transparent, uncertainty-aware screening for geologic CO₂ storage concepts")
st.warning(
    "Research and educational prototype only. The output is not a determination of "
    "site suitability, containment safety, regulatory compliance, or investment value."
)

with st.sidebar:
    st.header("Run settings")
    uploaded = st.file_uploader("Upload site scenarios", type=["csv"])
    sample_count = st.slider(
        "Monte Carlo samples per site",
        min_value=1_000,
        max_value=100_000,
        value=20_000,
        step=1_000,
    )
    seed = st.number_input("Random seed", min_value=0, value=42, step=1)
    st.caption("No upload? The app uses three synthetic demonstration sites.")

try:
    if uploaded is None:
        input_frame = pd.read_csv(PROJECT_ROOT / "examples" / "synthetic_sites.csv")
    else:
        input_frame = pd.read_csv(uploaded)
    sites = sites_from_dataframe(input_frame)
    summary, capacity_results, attention_results = analyze_sites(
        sites,
        sample_count=int(sample_count),
        seed=int(seed),
    )
except (InputValidationError, ValueError) as exc:
    st.error(f"Input validation failed: {exc}")
    st.stop()

display_columns = {
    "site_name": "Site",
    "capacity_q10_mt": "Q10 capacity (Mt)",
    "capacity_q50_mt": "Q50 capacity (Mt)",
    "capacity_q90_mt": "Q90 capacity (Mt)",
    "attention_score": "Attention score",
    "attention_category": "Attention category",
}

st.subheader("Concept screening overview")
st.dataframe(
    summary[list(display_columns)].rename(columns=display_columns).style.format(
        {
            "Q10 capacity (Mt)": "{:.2f}",
            "Q50 capacity (Mt)": "{:.2f}",
            "Q90 capacity (Mt)": "{:.2f}",
            "Attention score": "{:.1f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

site_name_by_id = {site.site_id: site.site_name for site in sites}
selected_id = st.selectbox(
    "Inspect a site",
    options=list(site_name_by_id),
    format_func=site_name_by_id.get,
)
capacity = capacity_results[selected_id]
attention = attention_results[selected_id]

left, middle, right = st.columns(3)
left.metric("Q10 capacity", f"{capacity.q10_mt:,.2f} Mt")
middle.metric("Q50 capacity", f"{capacity.q50_mt:,.2f} Mt")
right.metric("Q90 capacity", f"{capacity.q90_mt:,.2f} Mt")

chart_left, chart_right = st.columns(2)
with chart_left:
    histogram = px.histogram(
        x=capacity.samples_mt,
        nbins=55,
        labels={"x": "Capacity (Mt)", "y": "Simulation count"},
        title="Monte Carlo capacity distribution",
    )
    histogram.add_vline(x=capacity.q50_mt, line_dash="dash", line_color="#D97706")
    st.plotly_chart(histogram, use_container_width=True)

with chart_right:
    sensitivity_frame = pd.DataFrame(
        {
            "Parameter": list(capacity.sensitivity),
            "Rank correlation": list(capacity.sensitivity.values()),
        }
    ).sort_values("Rank correlation")
    sensitivity_chart = px.bar(
        sensitivity_frame,
        x="Rank correlation",
        y="Parameter",
        orientation="h",
        title="Sensitivity to uncertain inputs",
        range_x=[0, 1],
    )
    st.plotly_chart(sensitivity_chart, use_container_width=True)

st.subheader("Illustrative containment-attention indicators")
st.write(
    f"**{attention.category} — {attention.total_score:.1f}/100.** "
    "A higher value only means that this prototype flags more items for investigation."
)
attention_frame = pd.DataFrame(
    {
        "Indicator": [name.replace("_", " ").title() for name in attention.components],
        "Attention": list(attention.components.values()),
    }
)
st.plotly_chart(
    px.bar(
        attention_frame,
        x="Indicator",
        y="Attention",
        range_y=[0, 100],
        title="Transparent heuristic components",
    ),
    use_container_width=True,
)

with st.expander("Methodology and limitations"):
    st.markdown(
        """
The volumetric estimate is **M = A × h × φ × ρCO₂ × E**. Each uncertain
input is sampled from a triangular distribution defined by low, most-likely,
and high values. Q10/Q50/Q90 are ordinary statistical quantiles; they are not
petroleum reserve-probability labels.

The attention indicators use demonstration thresholds documented in
`docs/METHODOLOGY.md`. They do not model pressure, injectivity, geomechanics,
fault transmissibility, plume migration, leakage, geochemistry, monitoring,
economics, or regulation.
        """
    )

st.download_button(
    "Download summary CSV",
    data=summary.to_csv(index=False).encode("utf-8"),
    file_name="basinlens_summary.csv",
    mime="text/csv",
)

