"""CSV input helpers."""

from __future__ import annotations

from pathlib import Path
from typing import IO

import pandas as pd

from .models import InputValidationError, SiteScenario


def read_site_dataframe(source: str | Path | IO) -> pd.DataFrame:
    """Read UTF-8 CSV identities literally; numeric fields are validated later."""
    return pd.read_csv(
        source, encoding="utf-8", dtype={"site_id": str, "site_name": str},
        keep_default_na=False,
    )


def sites_from_dataframe(frame: pd.DataFrame) -> list[SiteScenario]:
    """Validate every row of a DataFrame and return site scenarios."""

    if frame.empty:
        raise InputValidationError("input table contains no site rows")

    sites: list[SiteScenario] = []
    seen_ids: set[str] = set()
    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        try:
            site = SiteScenario.from_mapping(row.to_dict())
        except InputValidationError as exc:
            raise InputValidationError(f"row {row_number}: {exc}") from exc
        if site.site_id in seen_ids:
            raise InputValidationError(f"row {row_number}: duplicate site_id: {site.site_id}")
        seen_ids.add(site.site_id)
        sites.append(site)
    return sites


def load_sites(path: str | Path) -> list[SiteScenario]:
    """Read and validate scenarios from a UTF-8 CSV file."""

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"input file does not exist: {source}")
    return sites_from_dataframe(read_site_dataframe(source))

