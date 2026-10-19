"""Create a scoped, open REA ledger without publishing original resource content.

The original PE Evidence and decoder observation stay in the private workspace.
Only numeric command IDs, byte offsets, hashes, and original analytical prose
enter the public ledger. REA 6.7.0 authenticates the source Evidence semantic ID,
canonicalizes its bundle, builds the ledger, and validates its closure digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys


class LedgerError(ValueError):
    pass


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise LedgerError("JSON input must be a regular file at most 32 MiB")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise LedgerError("Duplicate JSON keys are not allowed")
            result[key] = value
        return result

    def invalid(value):
        raise LedgerError(f"Non-finite JSON value: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid(value)
        return number

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                       parse_constant=invalid, parse_float=finite_float)
    if not isinstance(value, dict):
        raise LedgerError("JSON document root must be an object")
    return value


def command_locations(catalogue: dict) -> dict[int, tuple[int, ...]]:
    """Project verified menu structure into numeric command/offset observations."""
    result: dict[int, set[int]] = {}
    menus = catalogue.get("menus")
    if not isinstance(menus, list) or len(menus) > 65_536:
        raise LedgerError("Invalid decoded menus")

    def walk(items, offset, depth=0):
        if not isinstance(items, list) or depth > 64:
            raise LedgerError("Invalid decoded menu structure")
        for item in items:
            if not isinstance(item, dict) or type(item.get("popup")) is not bool:
                raise LedgerError("Invalid decoded menu item")
            command = item.get("command_id")
            if command is not None and (type(command) is not int or not 0 <= command <= 0xFFFFFFFF):
                raise LedgerError("Invalid decoded command ID")
            if not item["popup"] and not item.get("separator", False) and command not in (None, 0):
                result.setdefault(command, set()).add(offset)
            walk(item.get("children", []), offset, depth + 1)

    for menu in menus:
        if not isinstance(menu, dict) or type(menu.get("file_offset")) is not int or menu["file_offset"] < 0:
            raise LedgerError("Invalid menu file offset")
        walk(menu.get("items"), menu["file_offset"])
    if type(catalogue.get("unique_static_command_ids")) is not int or catalogue["unique_static_command_ids"] != len(result):
        raise LedgerError("Decoded command count does not match menu structure")
    return {command: tuple(sorted(offsets)) for command, offsets in sorted(result.items())}


def verify_observations(observations: dict, decoded: dict, evidence_sha256: str):
    """Labels are irrelevant; changed IDs, locations, identities, or claims fail."""
    for key in ("target", "rea_evidence_id", "menus_decoded", "dialogs_inventoried"):
        if observations.get(key) != decoded.get(key):
            raise LedgerError(f"Observation identity/count mismatch: {key}")
    if observations.get("rea_evidence_sha256") != evidence_sha256:
        raise LedgerError("Observation does not bind the exact source Evidence file")
    if observations.get("runtime_observed") is not False or observations.get("gms_parity_established") is not False:
        raise LedgerError("Static observation must not claim runtime observation or parity")
    expected = command_locations(decoded)
    if command_locations(observations) != expected:
        raise LedgerError("Observation commands differ from freshly decoded target bytes")
    if not expected:
        raise LedgerError("No static commands were decoded; no command ledger can be created")
    return expected


def reviewed_obligations(target_sha256: str, evidence_id: str, commands: dict[int, tuple[int, ...]]):
    common = {
        "obligation_version": 1, "application_layer": "application", "required": True,
        "required_case_kinds": ["positive", "negative"],
        "required_original_authority": "runtime", "required_fixture_authority": "live-observation",
        "required_verifier_authority": "integration", "requires_parser_type": False,
        "dependency_obligation_ids": [], "residual_unknown_ids": [],
        "unavailable_authority": [], "disposition": "active", "review_evidence_ids": [evidence_id],
    }
    result = []
    for command, offsets in commands.items():
        result.append({
            **common,
            "obligation_id": f"gms.menu-command.{command}",
            "title": f"Characterize static menu command {command}",
            "family": "static-menu-command-runtime-characterization",
            "target": {"artifact_sha256": target_sha256, "application_node_id": None,
                       "semantic_node_id": None,
                       "location": f"pe-menu-command:{command}/resource-file-offsets:" + ",".join(map(str, offsets))},
            "required_next_evidence": [
                "Observe authorized original runtime availability, enabled state, inputs, outputs and failure behavior.",
                "Determine whether command IDs are reused across contexts and whether cancellation or teardown cases apply.",
                "Define bounded behavioral claims and tolerances before binding independent implementation and comparisons.",
            ],
        })
    # An explicit barrier prevents treating the finite resource enumeration as
    # proof that the entire application and all dynamically generated UI exist.
    result.append({
        **common,
        "obligation_id": "gms.whole-product-scope-reconciliation",
        "title": "Reconcile whole-product scope beyond static menu resources",
        "family": "whole-product-scope-reconciliation",
        "target": {"artifact_sha256": target_sha256, "application_node_id": None,
                   "semantic_node_id": None, "location": "whole-product-scope:unreconciled"},
        "unavailable_authority": [
            "Static menu resources do not enumerate dynamic UI, command handlers, numerical engines, formats, editions or licensed modules.",
            "No complete original runtime behavior inventory or end-to-end GMS reference comparison is available.",
        ],
        "required_next_evidence": [
            "Reconcile documented features, installed and activated modules, native interfaces, runtime workflows and original reference cases.",
        ],
    })
    return result


def write_json(path: Path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def build(args):
    from basinlens_ccs.reconstruction import resource_catalogue

    output, private = args.output.resolve(), args.private_workspace.resolve()
    if output == private or output in private.parents or private in output.parents:
        raise LedgerError("Public output and private workspace must be separate directory trees")
    for path in (args.output, args.private_workspace):
        if path.exists() or path.is_symlink():
            raise LedgerError("Output and private workspace must be new paths")
    original = read_json(args.evidence)
    decoded = resource_catalogue(args.target, args.evidence, include_labels=False)
    if original["subject"]["digest"]["sha256"] != decoded["target"]["sha256"]:
        raise LedgerError("REA subject digest differs from the decoded target identity")
    evidence_sha256 = digest(args.evidence)
    observations = read_json(args.observations)
    commands = verify_observations(observations, decoded, evidence_sha256)
    obligations = reviewed_obligations(decoded["target"]["sha256"], decoded["rea_evidence_id"], commands)
    private.mkdir(parents=True)
    request = {"evidence_path": str(args.evidence.resolve()), "reviewed_obligations": obligations}
    write_json(private / "request.json", request)
    helper = Path(__file__).with_suffix(".mjs")
    process = subprocess.run([args.node, str(helper), str(private / "request.json"),
                              str(args.rea_package.resolve()), str(private)],
                             capture_output=True, text=True, timeout=180)
    (private / "helper.stdout.log").write_text(process.stdout, encoding="utf-8")
    (private / "helper.stderr.log").write_text(process.stderr, encoding="utf-8")
    if process.returncode:
        raise LedgerError("REA ledger creation failed; inspect the private workspace diagnostics")
    receipt = read_json(private / "rea-ledger.json")
    ledger = receipt["normalized_result"]
    if (receipt.get("operation") != "build_reconstruction_obligation_ledger"
            or ledger["summary"]["total"] != len(commands) + 1
            or ledger["summary"]["verified"] != 0
            or ledger["status"] != "unknown"
            or any(item["binding"] is not None for item in ledger["obligations"])
            or any(item["observed_cases"] for item in ledger["obligations"])):
        raise LedgerError("REA result violated the open static-only ledger contract")
    if digest(args.evidence) != evidence_sha256:
        raise LedgerError("Source Evidence changed during ledger construction")
    versions = read_json(private / "versions.json")
    summary = {
        "schema_version": 1, "scope": "static menu command obligations plus whole-product scope barrier",
        "target": decoded["target"], "source_rea_evidence_id": decoded["rea_evidence_id"],
        "source_rea_evidence_sha256": evidence_sha256,
        "source_observations_sha256": digest(args.observations),
        "rea_version": versions["rea"], "node_version": versions["node"],
        "ledger_id": ledger["ledger_id"], "ledger_evidence_id": receipt["evidence_id"],
        "ledger_closure_digest": ledger["closure_digest"], "ledger_status": ledger["status"],
        "ledger_file_sha256": digest(private / "rea-ledger.json"),
        "static_menu_resources_decoded": decoded["menus_decoded"],
        "distinct_static_command_ids": len(commands), "obligations_total": len(commands) + 1,
        "obligations_verified": 0, "runtime_cases_observed": 0, "whole_product_coverage": "unknown",
        "original_resource_labels_or_bytes_published": False,
        "rea_coverage_field_scope": "REA complete means the supplied finite obligation set was projected; it is not complete GMS coverage.",
        "limitations": [
            "Numeric command IDs are static observations and may be unused, context-dependent or edition-specific.",
            "Reviewed means an analyst supplied the obligations; it does not mean runtime behavior was observed.",
            "No command handler, numerical algorithm, native project compatibility or original GMS output parity was verified.",
            "The canonical source Evidence bundle contains original resource metadata and remains private.",
        ],
    }
    output.mkdir(parents=True)
    shutil.copyfile(private / "rea-ledger.json", output / "reconstruction_obligations.json")
    write_json(output / "reconstruction_obligations_summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--rea-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-workspace", type=Path, required=True)
    parser.add_argument("--node", default="node")
    args = parser.parse_args(argv)
    try:
        summary = build(args)
        print(f"REA ledger: {summary['obligations_total']} open obligations; 0 verified; whole-product coverage unknown")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Ledger error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
