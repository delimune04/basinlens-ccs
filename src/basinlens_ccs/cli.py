"""Command-line interface for reproducible batch screening."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import analyze_sites
from .io import load_sites


DISCLAIMER = (
    "Research and educational prototype only. Results are not a site-suitability, "
    "safety, regulatory, engineering, or investment determination."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="basinlens",
        description="Run uncertainty-aware conceptual CO2 storage screening.",
    )
    parser.add_argument("input_csv", help="Path to a CSV using the documented schema")
    parser.add_argument(
        "--output",
        default="outputs",
        help="Directory for summary.csv and run_metadata.json (default: outputs)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=20_000,
        help="Monte Carlo samples per site (default: 20000)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sites = load_sites(args.input_csv)
    summary, _, _ = analyze_sites(
        sites,
        sample_count=args.samples,
        seed=args.seed,
    )

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    metadata_path = output_dir / "run_metadata.json"
    summary.to_csv(summary_path, index=False)
    metadata_path.write_text(
        json.dumps(
            {
                "input_csv": str(Path(args.input_csv)),
                "site_count": len(sites),
                "samples_per_site": args.samples,
                "random_seed": args.seed,
                "capacity_quantiles": "Q10/Q50/Q90 are statistical quantiles",
                "disclaimer": DISCLAIMER,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(summary.to_string(index=False))
    print(f"\nSaved {summary_path} and {metadata_path}")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

