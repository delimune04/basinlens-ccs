import argparse
import json
from pathlib import Path
import sys

from . import resource_catalogue


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-bound static menu reconstruction; no target execution")
    parser.add_argument("target", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-labels", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output exists; choose a fresh output file")
        result = resource_catalogue(args.target, args.evidence, include_labels=args.include_labels)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        print(f"Static inventory: {result['menus_decoded']} menus; {result['unique_static_command_ids']} distinct command IDs; {len(result['decode_failures'])} decoder limitations")
        return 0
    except (ValueError, OSError) as error:
        print(f"Resource reconstruction error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
