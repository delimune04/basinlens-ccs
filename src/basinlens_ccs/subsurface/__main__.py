"""Run ``python -m basinlens_ccs.subsurface --help`` for explicit engine actions."""
import argparse
import json
from pathlib import Path

from . import default_registry, load_project


def main(argv=None):
    parser = argparse.ArgumentParser(description="Subsurface project metadata and capability-gated engines")
    commands = parser.add_subparsers(dest="command", required=True)
    engines = commands.add_parser("engines", help="list implementation and runtime availability")
    engines.add_argument("--exe", default="mf6")
    for command in ("validate", "export", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("project", type=Path)
        if command != "validate":
            sub.add_argument("--output", type=Path, required=True)
        if command == "run":
            sub.add_argument("--exe", default="mf6")
    args = parser.parse_args(argv)
    registry = default_registry()
    try:
        if args.command == "engines":
            report = registry.engines(exe_name=args.exe)
        else:
            project = load_project(args.project)
            if args.command == "validate":
                report = {"project_id": project.project_id, "mapping": registry.validate(project)}
            elif args.command == "export":
                report = registry.export(project, args.output, asset_root=args.project.parent).summary
            else:
                report = registry.run(project, args.output, exe_name=args.exe, asset_root=args.project.parent).summary
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
