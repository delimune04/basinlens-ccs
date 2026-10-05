"""Command-line interface for reproducible batch screening."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from .analysis import analyze_sites
from .artifacts import write_run_bundle
from .io import read_site_dataframe, sites_from_dataframe


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
        help="New directory for the run bundle; existing paths are refused (default: outputs)",
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.samples < 100 or args.seed < 0:
        parser.error("samples must be >= 100 and seed must be >= 0")
    output_dir = Path(args.output)
    if output_dir.exists():
        parser.error(f"output already exists; choose a new run directory: {output_dir}")
    try:
        # Parse and archive the same bytes, even if the original file changes later.
        input_bytes = Path(args.input_csv).read_bytes()
        sites = sites_from_dataframe(read_site_dataframe(BytesIO(input_bytes)))
        summary, capacities, _ = analyze_sites(sites, sample_count=args.samples, seed=args.seed)
        metadata_path = write_run_bundle(
            output_dir, input_bytes=input_bytes, input_label=str(Path(args.input_csv)),
            sites=sites, summary=summary, capacities=capacities,
            sample_count=args.samples, seed=args.seed, disclaimer=DISCLAIMER,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(summary.to_string(index=False))
    print(f"\nSaved run bundle at {output_dir} (manifest: {metadata_path.name})")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
