"""Traceable artifacts for the existing conceptual screening engine.

Hashes detect changes relative to a manifest; they do not certify a model or
authenticate the manifest's author. A manifest is written last, after outputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from uuid import uuid4

import numpy as np
import pandas as pd

from .capacity import CapacityResult
from .models import SiteScenario


ARTIFACT_NAMES = ("input.csv", "summary.csv", "sensitivity.csv", "report.md")
UNMODELED = (
    "injectivity and pressure buildup",
    "CO2 plume migration and multiphase flow",
    "caprock integrity, fault reactivation and well integrity",
    "seismic inversion, leakage probability and economics",
)


def _source_hash() -> str:
    """Identify package Python source, independently of the Git checkout state."""
    digest = sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report(summary: pd.DataFrame, *, sample_count: int, seed: int) -> str:
    """Render numerical results without generating an LLM interpretation."""
    lines = [
        "# BasinLens CCS — conceptual screening report",
        "",
        "Assessment level: **concept screening**. Scientific validation status: "
        "**synthetic regression checks only**.",
        "",
        f"Samples per site: {sample_count:,}. Base seed: {seed}.",
        "Inputs use independent triangular distributions. Q10/Q50/Q90 are "
        "statistical quantiles, not exceedance-probability reserve labels.",
        "",
        "| Site ID | Site | Q10 (Mt) | Q50 (Mt) | Q90 (Mt) | Illustrative attention |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {_cell(str(row.site_id))} | {_cell(str(row.site_name))} | "
            f"{row.capacity_q10_mt:.6f} | {row.capacity_q50_mt:.6f} | "
            f"{row.capacity_q90_mt:.6f} | {_cell(row.attention_category)} |"
        )
    lines.extend([
        "", "## Interpretation boundary", "",
        "Capacity estimates and heuristic attention indicators answer different "
        "questions. Table order is not a recommendation to select a site. "
        "Attention categories are demonstration rules, not failure probabilities.",
        "",
        "The current engine does not calculate:", "",
        *(f"- {item}." for item in UNMODELED),
        "", "## Reproduce and inspect", "",
        "The bundle includes the exact input bytes in `input.csv`, numerical "
        "results in `summary.csv`, and rank correlations in `sensitivity.csv`. "
        "The manifest records each site's seed, runtime versions, package-source "
        "fingerprint, and artifact checksums. Input-row order currently affects "
        "seed assignment; retain it when reproducing this engine.",
        "",
        "Parameter provenance and dataset-use permissions are not captured by "
        "the legacy CSV schema and require a separate evidence register.",
        "",
        "Research prototype. Expert review and independent scientific validation "
        "are required before using results in a real project.", "",
    ])
    return "\n".join(lines)


def write_run_bundle(
    output_dir: str | Path,
    *,
    input_bytes: bytes,
    input_label: str,
    sites: list[SiteScenario],
    summary: pd.DataFrame,
    capacities: dict[str, CapacityResult],
    sample_count: int,
    seed: int,
    disclaimer: str,
) -> Path:
    """Create a new bundle; refuse to overwrite any existing output directory.

    If an I/O error interrupts writing, a partial directory may remain. Only a
    completed, checksum-valid manifest identifies a completed bundle.
    """
    from . import __version__

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=False)
    (target / "input.csv").write_bytes(input_bytes)
    summary.to_csv(target / "summary.csv", index=False)
    sensitivity_rows = [
        {"site_id": site.site_id, "parameter": parameter, "rank_correlation": value}
        for site in sites
        for parameter, value in capacities[site.site_id].sensitivity.items()
    ]
    pd.DataFrame(sensitivity_rows).to_csv(target / "sensitivity.csv", index=False)
    (target / "report.md").write_text(
        render_report(summary, sample_count=sample_count, seed=seed), encoding="utf-8"
    )
    artifacts = {}
    for name in ARTIFACT_NAMES:
        data = (target / name).read_bytes()
        artifacts[name] = {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
    manifest = {
        "manifest_schema_version": 1,
        "run_id": str(uuid4()),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "assessment_level": "concept-screening",
        "validation_status": "synthetic-regression-only",
        "engine": "volumetric-independent-triangular",
        "package_version": __version__,
        "package_source_sha256": _source_hash(),
        "input_csv": input_label,
        "site_count": len(sites),
        "samples_per_site": sample_count,
        "random_seed": seed,
        "site_seeds": {site.site_id: seed + offset for offset, site in enumerate(sites)},
        "rng": "numpy.random.default_rng / PCG64",
        "capacity_quantiles": "Q10/Q50/Q90 are statistical quantiles",
        "assumptions": ["independent triangular inputs", "volumetric resource estimate"],
        "unmodeled": list(UNMODELED),
        "environment": {
            "python": sys.version.split()[0], "numpy": np.__version__,
            "pandas": pd.__version__, "os": platform.system(),
            "machine": platform.machine(),
        },
        "artifacts": artifacts,
        "disclaimer": disclaimer,
    }
    metadata = target / "run_metadata.json"
    metadata.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return metadata


def verify_run_bundle(output_dir: str | Path) -> None:
    """Check completion and every expected artifact against its manifest."""
    root = Path(output_dir)
    manifest = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_schema_version") != 1 or manifest.get("status") != "completed":
        raise ValueError("unsupported or incomplete run manifest")
    artifacts = manifest.get("artifacts", {})
    if set(artifacts) != set(ARTIFACT_NAMES):
        raise ValueError("manifest does not list exactly the expected artifacts")
    for name in ARTIFACT_NAMES:
        data = (root / name).read_bytes()
        record = artifacts[name]
        if len(data) != record.get("bytes") or sha256(data).hexdigest() != record.get("sha256"):
            raise ValueError(f"artifact checksum mismatch: {name}")


def verify_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify BasinLens run artifact checksums.")
    parser.add_argument("output_dir")
    args = parser.parse_args(argv)
    try:
        verify_run_bundle(args.output_dir)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.error(str(exc))
    print("Bundle complete; artifact checksums match the manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify_main())
