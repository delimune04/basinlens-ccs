"""Run ``python -m basinlens_ccs.subsurface --help`` for explicit engine actions."""
import argparse
import json
from pathlib import Path

from . import default_registry, load_project, verify_assets


def _load_view_state(path):
    if path is None:
        return None
    from .project_package import _read_file, _json_tree, MAX_VIEW_BYTES
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("view state: duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("view state: nonfinite JSON number")
    payload = _read_file(path, MAX_VIEW_BYTES)
    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _json_tree(result)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("view state: invalid UTF-8 JSON") from exc
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Subsurface project metadata and capability-gated engines")
    commands = parser.add_subparsers(dest="command", required=True)
    engines = commands.add_parser("engines", help="list implementation and runtime availability")
    engines.add_argument("--exe", default="mf6")
    for command in ("validate", "export", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("project", type=Path)
        sub.add_argument("--asset-root", type=Path)
        if command != "validate":
            sub.add_argument("--output", type=Path, required=True)
        if command == "run":
            sub.add_argument("--exe", default="mf6")
    sub = commands.add_parser("package-save", help="save an inert portable .blproj, including registered assets")
    sub.add_argument("project", type=Path)
    sub.add_argument("--output", type=Path, required=True)
    sub.add_argument("--asset-root", type=Path)
    sub.add_argument("--view-state", type=Path)
    for command in ("package-open", "workflow-open"):
        sub = commands.add_parser(command, help="validate and restore into a fresh directory")
        sub.add_argument("package", type=Path)
        sub.add_argument("--output", type=Path, required=True)
    for command in ("package-roundtrip", "workflow-roundtrip"):
        commands.add_parser(command).add_argument("package", type=Path)
    sub = commands.add_parser("workflow-save", help="preserve the spatial water model in a portable project")
    sub.add_argument("case", type=Path)
    sub.add_argument("--output", type=Path, required=True)
    sub.add_argument("--view-state", type=Path)
    args = parser.parse_args(argv)
    registry = default_registry()
    try:
        if args.command.startswith("package-"):
            from .project_package import save_project_package, open_project_package, verify_project_roundtrip
            if args.command == "package-save":
                view = _load_view_state(args.view_state)
                output = save_project_package(load_project(args.project, check_assets=False), args.output,
                    asset_root=args.asset_root or args.project.parent, view_state=view)
                report = {"package": str(output), "engine_executed": False, "native_gpr_writer": False}
            elif args.command == "package-open":
                restored = open_project_package(args.package, args.output)
                report = {"root": str(restored.root), "asset_root": str(restored.asset_root),
                    "project_id": restored.project.project_id, "view_state": restored.view_state,
                    "receipt": restored.receipt, "engine_executed": False}
            else:
                report = verify_project_roundtrip(args.package)
        elif args.command.startswith("workflow-"):
            from .model_workflow import load_workflow_case
            from .workflow_project import save_workflow_project, open_workflow_project, verify_workflow_project_roundtrip
            if args.command == "workflow-save":
                view = _load_view_state(args.view_state)
                output = save_workflow_project(load_workflow_case(args.case), args.output, view_state=view)
                report = {"package": str(output), "engine_executed": False, "gms_parity_established": False}
            elif args.command == "workflow-open":
                restored = open_workflow_project(args.package, args.output)
                report = {"root": str(restored.root), "asset_root": str(restored.asset_root),
                    "project_id": restored.project.project_id, "view_state": restored.view_state,
                    "receipt": restored.receipt, "engine_executed": False}
            else:
                report = verify_workflow_project_roundtrip(args.package)
        elif args.command == "engines":
            report = registry.engines(exe_name=args.exe)
        else:
            project = load_project(args.project, check_assets=False)
            asset_root = args.asset_root or args.project.parent
            if args.command == "validate":
                report = {"project_id": project.project_id, "mapping": registry.validate(project),
                          "assets_verified": verify_assets(project, asset_root)}
            elif args.command == "export":
                report = registry.export(project, args.output, asset_root=asset_root).summary
            else:
                report = registry.run(project, args.output, exe_name=args.exe, asset_root=asset_root).summary
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
