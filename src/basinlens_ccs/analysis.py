"""High-level orchestration for capacity and attention calculations."""

from __future__ import annotations

import pandas as pd

from .capacity import CapacityResult, simulate_capacity
from .models import InputValidationError, SiteScenario
from .screening import AttentionResult, calculate_attention


def analyze_sites(
    sites: list[SiteScenario],
    *,
    sample_count: int = 20_000,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, CapacityResult], dict[str, AttentionResult]]:
    """Analyze sites and return a compact summary plus detailed results."""

    if not sites:
        raise InputValidationError("input contains no site scenarios")
    seen_ids: set[str] = set()
    for site in sites:
        if site.site_id in seen_ids:
            raise InputValidationError(f"duplicate site_id: {site.site_id}")
        seen_ids.add(site.site_id)

    rows: list[dict[str, float | str]] = []
    capacity_results: dict[str, CapacityResult] = {}
    attention_results: dict[str, AttentionResult] = {}

    for offset, site in enumerate(sites):
        capacity = simulate_capacity(
            site,
            sample_count=sample_count,
            seed=seed + offset,
        )
        attention = calculate_attention(site)
        capacity_results[site.site_id] = capacity
        attention_results[site.site_id] = attention
        rows.append({**capacity.to_record(), **attention.to_record()})

    summary = pd.DataFrame(rows).sort_values(
        ["attention_score", "capacity_q50_mt", "site_id"],
        ascending=[True, False, True],
        ignore_index=True,
    )
    return summary, capacity_results, attention_results

