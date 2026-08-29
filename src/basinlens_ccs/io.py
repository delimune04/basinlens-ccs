"""CSV input helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import InputValidationError, SiteScenario


def sites_from_dataframe(frame: pd.DataFrame) -> list[SiteScenario]:
    """Validate every row of a DataFrame and return site scenarios."""

    if frame.empty:
        raise InputValidationError("input table contains no site rows")

    sites: list[SiteScenario] = []
    seen_ids: set[str] = set()
    for index, row in frame.iterrows():
        try:
            site = SiteScenario.from_mapping(row.to_dict())
        except InputValidationError as exc:
            raise InputValidationError(f"row {index + 2}: {exc}") from exc
        if site.site_id in seen_ids:
            raise InputValidationError(f"duplicate site_id: {site.site_id}")
        seen_ids.add(site.site_id)
        sites.append(site)
    return sites


def load_sites(path: str | Path) -> list[SiteScenario]:
    """Read and validate scenarios from a UTF-8 CSV file."""

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"input file does not exist: {source}")
    return sites_from_dataframe(pd.read_csv(source))

