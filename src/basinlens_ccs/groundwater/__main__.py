"""python -m basinlens_ccs.groundwater: explicit export/run entry points."""
import argparse
import json
import sys
from pathlib import Path

from . import demo_case, export_case, load_case, run_case, verify_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded single-phase confined groundwater model; not a CO2 simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "run", "export"):
        child = sub.add_parser(command)
        if command != "demo":
            child.add_argument("case", type=Path)
        child.add_argument("--output", type=Path, required=True, help="New output directory (existing paths refused)")
        if command != "export":
            child.add_argument("--exe", default="mf6", help="Installed MODFLOW 6 executable; no automatic download")
    verify = sub.add_parser("verify")
    verify.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            metadata = verify_bundle(args.output)
            print(f"Bundle verified: {metadata['status']}")
            return 0
        case = demo_case() if args.command == "demo" else load_case(args.case)
        if args.command == "export":
            print(f"MF6 inputs exported: {export_case(case, args.output)}")
        else:
            result = run_case(case, args.output, exe_name=args.exe)
            print(json.dumps(result.summary, indent=2))
            print(f"Run bundle: {result.workspace}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Groundwater error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
