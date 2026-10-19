"""Run with ``python -m basinlens_ccs.parity``; no GMS execution is implied."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comparison import compare_datasets, verify_report
from .coverage import assess_catalogue
from .dataset import ParityError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare captured numerical evidence; account for catalogue-scoped GMS coverage")
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="Compare a captured reference with candidate results")
    compare.add_argument("reference")
    compare.add_argument("candidate")
    compare.add_argument("--atol", type=float, default=1e-7, help="Absolute tolerance in each output's explicit unit")
    compare.add_argument("--rtol", type=float, default=1e-6)
    compare.add_argument("--output", type=Path, required=True)
    coverage = sub.add_parser("coverage", help="Assess only the supplied feature catalogue")
    coverage.add_argument("catalogue")
    coverage.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify", help="Rehash and replay comparison receipts")
    verify.add_argument("report")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = verify_report(args.report)
            print(json.dumps({"status": report["status"], "report_sha256": report["report_sha256"]}))
        else:
            # Report files are immutable to preserve earlier evidence.
            if args.output.exists():
                raise ParityError(f"Output already exists: {args.output}")
            report = compare_datasets(args.reference, args.candidate, atol=args.atol, rtol=args.rtol) if args.command == "compare" else assess_catalogue(args.catalogue)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=False)
                stream.write("\n")
            print(json.dumps({"status": report.get("status", "assessed"), "output": str(args.output),
                              "full_gms_equivalence": False}))
        return {"pass": 0, "fail": 1, "unverifiable": 2}.get(report.get("status"), 0)
    except (ParityError, OSError) as exc:
        print(f"parity: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
