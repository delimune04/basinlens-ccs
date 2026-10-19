"""Catalogue-bound implementation accounting with conservative parity gates.

This registry describes selected documented work, never a whole-product fraction.
File fingerprints bind bytes; they do not authenticate an operator or attest a run.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any
from urllib.parse import urlparse


class StatusError(ValueError):
    """The registry cannot substantiate its declared status."""


class ImplementationState(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    SCOPED_COMPLETE = "SCOPED_COMPLETE"


class OriginalComparisonState(str, Enum):
    NOT_OBSERVED = "NOT_OBSERVED"
    OBSERVED_PARTIAL = "OBSERVED_PARTIAL"
    VERIFIED = "VERIFIED"


class EvidenceKind(str, Enum):
    SOURCE = "SOURCE"
    TEST_FILE = "TEST_FILE"
    EXECUTED_TEST_RECORD = "EXECUTED_TEST_RECORD"
    SAVED_ORIGINAL_FILE = "SAVED_ORIGINAL_FILE"
    OBSERVED_RUNTIME = "OBSERVED_RUNTIME"
    SHIPPED_TUTORIAL_COMPARISON = "SHIPPED_TUTORIAL_COMPARISON"
    PARITY_REPORT = "PARITY_REPORT"


@dataclass(frozen=True)
class FeatureStatus:
    id: str
    name: str
    category: str
    implementation: ImplementationState
    original_comparison: OriginalComparisonState
    implemented_scope: str
    remaining_scope: tuple[str, ...]
    next_operation: str


MAX_JSON_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _object(value: Any, name: str, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise StatusError(f"{name}: exact fields required: {', '.join(sorted(keys))}")
    return value


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 4000 or "\x00" in value:
        raise StatusError(f"{name}: bounded nonempty text required")
    return value


def _list(value: Any, name: str, *, nonempty: bool = False) -> list:
    if type(value) is not list or (nonempty and not value):
        raise StatusError(f"{name}: {'nonempty ' if nonempty else ''}list required")
    return value


def _texts(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    result = [_text(item, name) for item in _list(value, name, nonempty=nonempty)]
    if len(result) != len(set(result)):
        raise StatusError(f"{name}: duplicates refused")
    return result


def _enum(kind: type[Enum], value: Any, name: str):
    try:
        return kind(value)
    except (ValueError, TypeError) as exc:
        raise StatusError(f"{name}: unsupported state") from exc


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise StatusError(f"JSON: duplicate key {key!r}")
        out[key] = value
    return out


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise StatusError(f"Missing or oversized JSON: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(StatusError("Nonfinite JSON refused")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StatusError(f"Invalid JSON: {path.name}") from exc


def _file(root: Path, name: Any) -> Path:
    name = _text(name, "evidence.path")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or ":" in name or "\\" in name or pure.as_posix() != name:
        raise StatusError("Evidence path must be canonical and repository-relative")
    result = root.joinpath(*pure.parts)
    for candidate in (result, *result.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise StatusError("Symbolic-link evidence is refused")
    if not result.is_file() or not result.resolve().is_relative_to(root):
        raise StatusError(f"Missing evidence file: {name}")
    return result


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(root: Path, record: dict, name: str) -> Path:
    _object(record, name, {"path", "sha256", "size_bytes"})
    if type(record["sha256"]) is not str or not _SHA.fullmatch(record["sha256"]):
        raise StatusError(f"{name}: SHA256 required")
    if type(record["size_bytes"]) is not int or record["size_bytes"] <= 0:
        raise StatusError(f"{name}: positive integer size required")
    path = _file(root, record["path"])
    if path.stat().st_size != record["size_bytes"] or _fingerprint(path) != record["sha256"]:
        raise StatusError(f"{name}: stale or altered evidence: {record['path']}")
    return path


def _executed_test_snapshots(path: Path) -> list[dict]:
    """Read bounded strict-runner receipts; labels alone do not prove execution."""
    record = _read_json(path)
    if record.get("schema") in {"basinlens-ci-real-mf6-tests-v1", "basinlens-feature-tests-v1"}:
        candidates = [record]
    elif type(record.get("runs")) is list:
        try:
            candidates = [run["parsed_artifact_records"]["tests.json"] for run in record["runs"]]
        except (KeyError, TypeError) as exc:
            raise StatusError("Execution record has no strict runner snapshots") from exc
    else:
        raise StatusError("Execution record is not a recognized strict test receipt")
    if not candidates:
        raise StatusError("Execution record has no test runs")
    for item in candidates:
        if (type(item) is not dict or item.get("schema") not in {"basinlens-ci-real-mf6-tests-v1", "basinlens-feature-tests-v1"} or
                item.get("status") != "passed" or item.get("runner_stopped") is not False or
                type(item.get("loader_errors_count")) is not int or item["loader_errors_count"] != 0 or
                any(item.get(key) != [] for key in ("errors", "failures", "skipped", "expected_failures", "unexpected_successes"))):
            raise StatusError("Execution record is incomplete, failed, skipped or not a strict pass")
        ids = _texts(item.get("test_ids"), "executed test IDs", nonempty=True)
        if item["schema"] == "basinlens-feature-tests-v1":
            _text(item.get("scope"), "feature execution scope")
            selection = _object(item.get("selection"), "feature test selection", {"modules", "unselected_modules", "method"})
            modules = _texts(selection["modules"], "selected modules", nonempty=True)
            excluded = _texts(selection["unselected_modules"], "unselected modules")
            if (item.get("full_suite") is not False or selection["method"] != "unittest.loadTestsFromNames for the exact named modules" or
                    set(modules) & set(excluded) or any(not re.fullmatch(r"test_[a-z0-9_]+", module) for module in modules + excluded) or
                    any(test_id.split(".")[0] not in modules for test_id in ids) or
                    set(modules) != {test_id.split(".")[0] for test_id in ids}):
                raise StatusError("Selected feature receipt cannot claim full CI or tests outside its explicit module selection")
        if type(item.get("tests_run")) is not int or item["tests_run"] != len(ids):
            raise StatusError("Execution record discovery/count mismatch")
        sources = item.get("source_sha256")
        if type(sources) is not dict or not sources:
            raise StatusError("Execution record has no source bindings")
        for key, value in sources.items():
            _text(key, "executed source path")
            if type(value) is not str or not _SHA.fullmatch(value):
                raise StatusError("Execution record contains an invalid source hash")
    return candidates


def _refs(value: Any, evidence: dict, name: str, *, nonempty: bool = False) -> list[str]:
    refs = _texts(value, name, nonempty=nonempty)
    if not set(refs) <= set(evidence):
        raise StatusError(f"{name}: unknown evidence reference")
    return refs


def _verify_original(root: Path, row: dict, evidence: dict) -> OriginalComparisonState:
    comparison = _object(row["original_comparison"], row["id"] + ".original_comparison", {
        "state", "kind", "scope", "evidence_refs", "verification_contract"})
    state = _enum(OriginalComparisonState, comparison["state"], "original_comparison.state")
    _text(comparison["scope"], "original_comparison.scope")
    refs = _refs(comparison["evidence_refs"], evidence, "original comparison evidence")
    kinds = {evidence[ref]["kind"] for ref in refs}
    if state is OriginalComparisonState.NOT_OBSERVED:
        if refs or comparison["kind"] != "NONE" or comparison["verification_contract"] is not None:
            raise StatusError("NOT_OBSERVED cannot carry positive comparison evidence")
    elif state is OriginalComparisonState.OBSERVED_PARTIAL:
        if comparison["kind"] not in {"SAVED_ORIGINAL_FILE", "OBSERVED_RUNTIME"} or comparison["kind"] not in kinds:
            raise StatusError("OBSERVED_PARTIAL needs the matching original observation evidence kind")
        if comparison["verification_contract"] is not None:
            raise StatusError("Partial observation is not a verified parity contract")
    else:
        # Current paired-output reports do not independently bind a catalogue
        # feature's accepted behavior. Reusing one head case for unrelated
        # features must never promote their status. A future reviewed schema
        # must add independently pinned feature acceptance contracts first.
        raise StatusError("VERIFIED is unavailable in schema v1: a reviewed feature-specific acceptance contract and replay gate are required")
    return state


def validate_registry(registry_path: str | Path, *, root: str | Path | None = None) -> dict:
    """Validate every catalogue row, evidence byte identity and comparison gate.

    Reports catalogue counts only. Successful validation means consistent status
    accounting; it never means a feature or the complete product has passed.
    """
    registry_path = Path(registry_path).resolve()
    root = Path(root).resolve() if root is not None else registry_path.parents[2]
    registry = _object(_read_json(registry_path), "registry", {
        "schema_version", "updated_at", "scope", "catalogue", "whole_product", "official_sources",
        "evidence", "priority_order", "features", "interpretation", "source_reconciliation"})
    if type(registry["schema_version"]) is not int or registry["schema_version"] != 1:
        raise StatusError("registry.schema_version: integer 1 required")
    for key in ("updated_at", "scope", "interpretation"):
        _text(registry[key], key)
    barrier = _object(registry["whole_product"], "whole_product", {
        "barrier", "inventory_complete", "unknown_unlisted_features", "complete", "native_gpr_write_implemented", "reason"})
    if (barrier["barrier"] != "OPEN" or barrier["inventory_complete"] is not False or
            barrier["unknown_unlisted_features"] is not True or barrier["complete"] is not False or
            barrier["native_gpr_write_implemented"] is not False):
        raise StatusError("Whole-product scope barrier must remain OPEN and native GPR writing unimplemented")
    _text(barrier["reason"], "whole_product.reason")
    catalogue_path = _identity(root, registry["catalogue"], "catalogue")
    catalogue = _read_json(catalogue_path)
    original = {}
    for feature in _list(catalogue.get("features"), "catalogue.features", nonempty=True):
        if type(feature) is not dict or not {"id", "name", "category", "documentation"} <= set(feature):
            raise StatusError("Malformed source catalogue feature")
        fid = _text(feature["id"], "catalogue feature ID")
        if fid in original:
            raise StatusError("Duplicate source catalogue ID")
        original[fid] = feature
    sources = registry["official_sources"]
    if type(sources) is not dict or not sources:
        raise StatusError("Official primary source records required")
    for source in sources.values():
        _object(source, "official source", {"url", "title", "accessed_at", "scope", "version_caution"})
        for key in source:
            _text(source[key], "official_source." + key)
        url = urlparse(source["url"])
        if url.scheme != "https" or url.hostname != "aquaveo.com":
            raise StatusError("Official source must be a directly consulted Aquaveo primary page")
    evidence = registry["evidence"]
    if type(evidence) is not dict:
        raise StatusError("Evidence mapping required")
    for eid, item in evidence.items():
        _text(eid, "evidence ID")
        _object(item, "evidence", {"kind", "file", "scope"})
        _enum(EvidenceKind, item["kind"], "evidence.kind")
        _text(item["scope"], "evidence.scope")
        evidence_path = _identity(root, item["file"], "evidence " + eid)
        if item["kind"] == "EXECUTED_TEST_RECORD":
            _executed_test_snapshots(evidence_path)
        if item["kind"] == "TEST_FILE" and not item["file"]["path"].startswith("tests/test_"):
            raise StatusError("Claimed test evidence must be a repository test file")
    reconciliation = _object(registry["source_reconciliation"], "source_reconciliation", {
        "checked_at", "status", "exhaustive", "scope", "items", "next_operation"})
    if reconciliation["status"] != "OPEN" or reconciliation["exhaustive"] is not False:
        raise StatusError("Official-source reconciliation must remain OPEN and nonexhaustive")
    for key in ("checked_at", "scope", "next_operation"):
        _text(reconciliation[key], "source_reconciliation." + key)
    mapped_ids = set()
    reconciled_sources = set()
    for item in _list(reconciliation["items"], "source_reconciliation.items", nonempty=True):
        _object(item, "reconciled item", {"id", "source_ref", "locator", "catalogue_refs", "mapping_state", "reason"})
        for key in ("id", "locator", "reason"):
            _text(item[key], "reconciled item." + key)
        if item["id"] in mapped_ids or item["source_ref"] not in sources:
            raise StatusError("Duplicate source-reconciliation item or unknown primary source")
        mapped_ids.add(item["id"])
        reconciled_sources.add(item["source_ref"])
        refs = _texts(item["catalogue_refs"], "reconciled catalogue refs")
        if not set(refs) <= set(original):
            raise StatusError("Source reconciliation refers to an unrecognized catalogue ID")
        if item["mapping_state"] not in {"MAPPED", "UNMAPPED_OPEN"} or bool(refs) != (item["mapping_state"] == "MAPPED"):
            raise StatusError("Mapped source items need catalogue references; unmapped items remain explicitly OPEN")
    if reconciled_sources != set(sources):
        raise StatusError("Each consulted primary page needs an explicit reconciliation item")
    priorities = _texts(registry["priority_order"], "priority_order", nonempty=True)
    if not set(priorities) <= set(original):
        raise StatusError("Priority list contains an unrecognized catalogue ID")
    entries = []
    identifiers = set()
    for row in _list(registry["features"], "features", nonempty=True):
        _object(row, "feature", {"id", "name", "category", "implementation", "implemented_scope", "remaining_scope",
            "implementation_evidence_refs", "software_checks", "original_comparison", "official_source_refs",
            "required_conditions", "next_operation", "scoped_completion_contract"})
        fid = _text(row["id"], "feature.id")
        if fid in identifiers:
            raise StatusError("Duplicate feature ID")
        if fid not in original:
            raise StatusError("Unrecognized catalogue ID: " + fid)
        identifiers.add(fid)
        if row["name"] != original[fid]["name"] or row["category"] != original[fid]["category"]:
            raise StatusError("Feature name/category differs from the pinned catalogue")
        state = _enum(ImplementationState, row["implementation"], "implementation")
        _text(row["implemented_scope"], "implemented_scope")
        remaining = _texts(row["remaining_scope"], "remaining_scope", nonempty=True)
        _texts(row["required_conditions"], "required_conditions", nonempty=True)
        _text(row["next_operation"], "next_operation")
        source_refs = _texts(row["official_source_refs"], "official_source_refs", nonempty=True)
        if not set(source_refs) <= set(sources):
            raise StatusError("Unknown official source reference")
        refs = _refs(row["implementation_evidence_refs"], evidence, "implementation evidence")
        kinds = {evidence[ref]["kind"] for ref in refs}
        checks = _list(row["software_checks"], "software_checks")
        if state is ImplementationState.NONE and (refs or checks):
            raise StatusError("NONE cannot carry positive implementation/test evidence")
        if state is not ImplementationState.NONE and ("SOURCE" not in kinds or not checks):
            raise StatusError("Implemented scope requires source and claimed software check evidence")
        completion = row["scoped_completion_contract"]
        if state is ImplementationState.SCOPED_COMPLETE:
            _object(completion, "scoped_completion_contract", {"scope", "accepted_criteria", "test_names"})
            if completion["scope"] != row["implemented_scope"]:
                raise StatusError("Scoped completion must name exactly the bounded implemented scope")
            _texts(completion["accepted_criteria"], "accepted_criteria", nonempty=True)
            completion_tests = set(_texts(completion["test_names"], "scoped completion tests", nonempty=True))
            if not completion_tests <= {name for check in checks for name in check.get("test_names", [])}:
                raise StatusError("Scoped completion lacks its accepted software checks")
        elif completion is not None:
            raise StatusError("Only SCOPED_COMPLETE can carry a scoped completion contract")
        for check in checks:
            _object(check, "software_check", {"test_file_ref", "test_names", "execution_record_ref", "scope"})
            _text(check["scope"], "software_check.scope")
            named = _texts(check["test_names"], "software_check.test_names", nonempty=True)
            test_ref, run_ref = check["test_file_ref"], check["execution_record_ref"]
            if test_ref not in evidence or evidence[test_ref]["kind"] != "TEST_FILE" or run_ref not in evidence or evidence[run_ref]["kind"] != "EXECUTED_TEST_RECORD":
                raise StatusError("Software checks require typed test file and execution record references")
            test_path = _file(root, evidence[test_ref]["file"]["path"])
            try:
                names = {node.name for node in ast.walk(ast.parse(test_path.read_text(encoding="utf-8")))
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")}
            except (SyntaxError, UnicodeError) as exc:
                raise StatusError("Claimed test file cannot be parsed") from exc
            if not set(named) <= names:
                raise StatusError("Claimed test names do not exist in the exact test file")
            snapshots = _executed_test_snapshots(_file(root, evidence[run_ref]["file"]["path"]))
            test_name = Path(evidence[test_ref]["file"]["path"]).stem
            execution_supported = False
            for snapshot in snapshots:
                executed = {item.split(".")[-1] for item in snapshot["test_ids"] if item.split(".")[0] == test_name}
                executed_sources = snapshot["source_sha256"]
                bindings = [evidence[test_ref]["file"]] + [evidence[ref]["file"] for ref in refs if evidence[ref]["kind"] == "SOURCE"]
                if set(named) <= executed and all(executed_sources.get(item["path"]) == item["sha256"] for item in bindings):
                    execution_supported = True
            if not execution_supported:
                raise StatusError("Claimed checks lack an executed receipt for these exact test/source bytes")
        comparison = _verify_original(root, row, evidence)
        if comparison is OriginalComparisonState.VERIFIED and state is ImplementationState.NONE:
            raise StatusError("An unimplemented feature cannot have VERIFIED original parity")
        entries.append(FeatureStatus(fid, row["name"], row["category"], state, comparison,
                                     row["implemented_scope"], tuple(remaining), row["next_operation"]))
    if identifiers != set(original):
        raise StatusError("Registry must contain every catalogue entry exactly once; missing: " + ", ".join(sorted(set(original) - identifiers)))
    return {"schema_version": 1, "registry_sha256": _fingerprint(registry_path),
            "catalogue_sha256": registry["catalogue"]["sha256"], "catalogue_entries": len(entries),
            "scope": registry["scope"], "whole_product": barrier,
            "implementation_counts": {state.value: sum(entry.implementation is state for entry in entries) for state in ImplementationState},
            "original_comparison_counts": {state.value: sum(entry.original_comparison is state for entry in entries) for state in OriginalComparisonState},
            "verified_original_numerical_features": sum(entry.original_comparison is OriginalComparisonState.VERIFIED for entry in entries),
            "priority_order": priorities, "features": registry["features"], "official_sources": sources,
            "source_reconciliation": reconciliation,
            "interpretation": registry["interpretation"]}


def markdown_report(report: dict) -> str:
    """Render exact catalogue mappings without a full-product completion rate."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# GMS implementation status", "", report["scope"], "",
             "Whole-product barrier: **OPEN**. Inventory incomplete; unlisted functions remain unknown.",
             "Native GPR writing is unimplemented. No whole-product completion claim follows from catalogue counts.", "",
             "| Implementation state | Catalogue entries |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["implementation_counts"].items()]
    lines += ["", "| Original comparison state | Catalogue entries |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in report["original_comparison_counts"].items()]
    lines += ["", report["interpretation"], "", "## Ordered next work", ""]
    by_id = {row["id"]: row for row in report["features"]}
    lines += [f"{index}. `{fid}`: {by_id[fid]['next_operation']}" for index, fid in enumerate(report["priority_order"], 1)]
    lines += ["", "## Complete mapping of the pinned partial catalogue", "",
              "| ID | Implementation | Original comparison | Implemented scope | Remaining scope | Next operation |", "|---|---|---|---|---|---|"]
    for row in report["features"]:
        lines.append("| " + " | ".join(cell(value) for value in (row["id"], row["implementation"],
            row["original_comparison"]["state"] + " / " + row["original_comparison"]["kind"],
            row["implemented_scope"], "; ".join(row["remaining_scope"]), row["next_operation"])) + " |")
    reconciliation = report["source_reconciliation"]
    lines += ["", "## Official-source reconciliation and open inventory", "", reconciliation["scope"], "",
              "Checked: " + reconciliation["checked_at"] + ". Reconciliation is **OPEN** and nonexhaustive.", "",
              "A catalogue mapping is not an implementation claim. Unmapped observed source items remain explicit open work.", "",
              "| Source | Source item / locator | Mapping | Catalogue IDs |", "|---|---|---|---|"]
    for item in reconciliation["items"]:
        lines.append("| " + " | ".join(cell(value) for value in (item["source_ref"], item["locator"], item["mapping_state"], ", ".join(item["catalogue_refs"]) or "Unmapped / OPEN")) + " |")
    lines += ["", reconciliation["next_operation"], "", "## Primary source index", ""]
    for source in report["official_sources"].values():
        lines.append(f"- [{source['title']}]({source['url']}) (consulted {source['accessed_at']}): {source['scope']} {source['version_caution']}")
    lines += ["", "## Reproduce this status", "", "```bash",
              "python -m basinlens_ccs.reconstruction.status validate",
              "python -m basinlens_ccs.reconstruction.status report --format markdown", "```", "",
              "Validation checks source-catalogue identity, every catalogue ID, evidence bytes, executed test/source bindings, and comparison gates.",
              "The source catalogue and genuine REA obligation ledger are not modified by this registry.",
              "Hashes detect changes; they do not independently authenticate vendor execution or test operators.", "",
              "## Updating evidence after code changes", "",
              "Changing a referenced source or test intentionally invalidates its old test claim, even if its file hash is refreshed.",
              "First run the affected implementation tests with actual required dependencies/solver and retain a strict runner receipt.",
              "A bootstrap receipt uses `basinlens-feature-tests-v1`, preserving explicit selected modules, unselected modules and full_suite=false.",
              "The historical complete-suite schema `basinlens-ci-real-mf6-tests-v1` is also accepted, as standalone tests.json or the retained public-CI wrapper.",
              "It must contain every executed test ID, matching source SHA256 bindings, a passed result and zero skips/errors/failures/discovery issues.",
              "A targeted pre-integration receipt executes affected implementation tests before this accounting suite is run; it lists only the tests it actually ran and is never full CI.",
              "For example: `MF6_EXE=/absolute/path/to/mf6 PYTHONPATH=src python tools/update_gms_status.py run --test-module test_subsurface --output docs/gms/feature_test_record_v3.json`.",
              "Add that receipt as new EXECUTED_TEST_RECORD evidence; update the changed SOURCE/TEST_FILE identities and the affected rows' execution_record_ref.",
              "Then validate this registry and run the full regression suite. Preserve older records as historical evidence rather than relabeling them as a newer run.",
              "New exchange-package or geological-workflow modules remain pending here until their implementation and execution records are integrated.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "report"))
    parser.add_argument("--registry", type=Path, default=Path("docs/gms/implementation_status.json"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="New output file only; existing paths are refused")
    args = parser.parse_args(argv)
    try:
        report = validate_registry(args.registry, root=args.root)
        if args.command == "validate":
            report = {key: value for key, value in report.items() if key not in {"features", "official_sources"}}
            reconciled = report["source_reconciliation"]
            report["source_reconciliation"] = {"status": reconciled["status"], "exhaustive": reconciled["exhaustive"],
                "checked_at": reconciled["checked_at"], "items": len(reconciled["items"]),
                "unmapped_open": sum(item["mapping_state"] == "UNMAPPED_OPEN" for item in reconciled["items"])}
        if args.command == "validate" and args.format == "markdown":
            raise StatusError("Use report --format markdown for the full mapping")
        text = markdown_report(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            sys.stdout.write(text)
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        return 0
    except (StatusError, OSError, KeyError, TypeError) as exc:
        print(f"Status validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
