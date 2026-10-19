"""Catalogue-scoped evidence accounting, never a full-product percentage."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .comparison import verify_report
from .dataset import (ParityError, fingerprint, read_json, verify_artifact,
                      _object, _text, _relative_file, _sha, _number)


LEVELS = ("documented", "specified", "implemented", "tested", "matched")


def assess_catalogue(path: str | Path):
    """Inspect hashed receipts and replay comparison reports for each feature.

    Stage flags are independent: a documented feature can have no implementation,
    and a source file alone does not prove tested behavior. A `matched` stage only
    means the declared numerical outputs of the captured observed GMS pair agree.
    The inventory is always explicitly incomplete with respect to all of GMS.
    """
    path = Path(path).resolve()
    catalogue = read_json(path)
    _object(catalogue, "catalogue", {"schema_version", "catalogue_id", "scope", "features"})
    if type(catalogue["schema_version"]) is not int or catalogue["schema_version"] != 1:
        raise ParityError("catalogue.schema_version: integer 1 required")
    for key in ("catalogue_id", "scope"):
        _text(catalogue[key], "catalogue." + key)
    if not isinstance(catalogue["features"], list) or not catalogue["features"]:
        raise ParityError("catalogue.features: at least one feature required")
    result = {"coverage_schema_version": 1, "catalogue_id": catalogue["catalogue_id"],
              "scope": catalogue["scope"], "catalogue_sha256": fingerprint(catalogue),
              "denominator": len(catalogue["features"]),
              "denominator_meaning": "Features in this supplied catalogue only; not the full GMS product",
              "complete_gms_inventory": False, "unknown_unlisted_features": True,
              "stage_counts": {level: 0 for level in LEVELS}, "features": []}
    identifiers = set()
    for feature in catalogue["features"]:
        _object(feature, "feature", {"id", "name"})
        for key in ("id", "name"):
            _text(feature[key], "feature." + key)
        if feature["id"] in identifiers:
            raise ParityError("catalogue: duplicate feature ID")
        identifiers.add(feature["id"])
        entry = {"id": feature["id"], "name": feature["name"],
                 "stages": {level: False for level in LEVELS},
                 "errors": [], "matched_reports": [], "synthetic_reports": []}
        documentation = feature.get("documentation", [])
        if not isinstance(documentation, list):
            raise ParityError("feature.documentation: list required")
        for source in documentation:
            _object(source, "documentation", {"url", "locator"})
            _text(source["locator"], "documentation.locator")
            parsed = urlparse(_text(source["url"], "documentation.url"))
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ParityError("documentation.url: HTTP(S) primary-source URL required")
        entry["stages"]["documented"] = bool(documentation)
        for level, field in (("specified", "specifications"), ("implemented", "implementation")):
            records = feature.get(field, [])
            if not isinstance(records, list):
                raise ParityError(f"feature.{field}: list required")
            valid = bool(records)
            for record in records:
                try:
                    verify_artifact(path.parent, record, "feature." + field)
                except ParityError as exc:
                    valid = False
                    entry["errors"].append(str(exc))
            entry["stages"][level] = valid
        implementation_commit = feature.get("implementation_commit")
        if entry["stages"]["implemented"]:
            try:
                _sha(implementation_commit, "feature.implementation_commit", commit=True)
            except ParityError as exc:
                entry["stages"]["implemented"] = False
                entry["errors"].append(str(exc))
        entry["implementation_commit"] = implementation_commit
        test_runs = feature.get("test_runs", [])
        if not isinstance(test_runs, list):
            raise ParityError("feature.test_runs: list required")
        valid_tests = bool(test_runs)
        for test in test_runs:
            try:
                _object(test, "test_run", {"receipt", "command", "result", "implementation_commit"})
                _text(test["command"], "test_run.command")
                _sha(test["implementation_commit"], "test_run.implementation_commit", commit=True)
                if test["implementation_commit"] != implementation_commit:
                    raise ParityError("test_run: stale or unrelated implementation commit")
                if test["result"] != "passed":
                    raise ParityError("test_run: only an actual passed run can support tested")
                verify_artifact(path.parent, test["receipt"], "test_run.receipt")
            except ParityError as exc:
                valid_tests = False
                entry["errors"].append(str(exc))
        entry["stages"]["tested"] = valid_tests and entry["stages"]["implemented"]
        comparisons = feature.get("comparison_reports", [])
        if not isinstance(comparisons, list):
            raise ParityError("feature.comparison_reports: list required")
        contract = feature.get("comparison_contract", {})
        if comparisons:
            _object(contract, "feature.comparison_contract", {"reference_dataset_ids", "required_outputs", "tolerances"})
            for key in ("reference_dataset_ids", "required_outputs"):
                if not isinstance(contract[key], list) or not contract[key]:
                    raise ParityError(f"comparison_contract.{key}: nonempty list required")
                for item in contract[key]:
                    _text(item, "comparison_contract." + key)
            _object(contract["tolerances"], "comparison_contract.tolerances", contract["required_outputs"])
            for name in contract["required_outputs"]:
                tolerance = _object(contract["tolerances"][name], "comparison_contract tolerance", {"atol", "rtol", "unit"})
                _text(tolerance["unit"], "tolerance.unit")
                if any(_number(tolerance[key], "tolerance." + key) < 0 for key in ("atol", "rtol")):
                    raise ParityError("comparison_contract: tolerances must be non-negative")
        matched_cases = set()
        for report_path in comparisons:
            try:
                report = verify_report(_relative_file(path.parent, report_path))
                reference_id = report["evidence"].get("reference", {}).get("dataset_id")
                if reference_id not in contract["reference_dataset_ids"]:
                    raise ParityError("comparison reference does not belong to the feature contract")
                if not set(contract["required_outputs"]) <= set(report["metrics"]):
                    raise ParityError("comparison is missing feature-contract outputs")
                candidate_commit = report["evidence"].get("candidate", {}).get("implementation", {}).get("git_commit")
                if candidate_commit != implementation_commit:
                    raise ParityError("comparison candidate implementation commit is stale or unrelated")
                for name in contract["required_outputs"]:
                    tolerance = contract["tolerances"][name]
                    if tolerance["unit"] != report["metrics"][name]["unit"] or any(report["tolerances"][key] > tolerance[key] for key in ("atol", "rtol")):
                        raise ParityError("comparison tolerance/unit exceeds the feature acceptance contract")
                if report["status"] == "pass" and report["gms_match"] is True:
                    entry["matched_reports"].append(report["report_sha256"])
                    matched_cases.add(reference_id)
                elif report["evidence"].get("reference", {}).get("source", {}).get("kind") == "synthetic":
                    entry["synthetic_reports"].append(report["report_sha256"])
            except (ParityError, KeyError) as exc:
                entry["errors"].append(f"comparison_reports: {exc}")
        entry["stages"]["matched"] = bool(entry["matched_reports"]) and entry["stages"]["implemented"] and set(contract["reference_dataset_ids"]) <= matched_cases
        if comparisons:
            entry["comparison_contract"] = contract
            entry["matched_scope"] = "Declared outputs and reference cases only; not full feature equivalence"
        entry["highest_evidenced_stage"] = next((level for level in reversed(LEVELS) if entry["stages"][level]), "unknown")
        for level in LEVELS:
            result["stage_counts"][level] += int(entry["stages"][level])
        result["features"].append(entry)
    result["coverage_sha256"] = fingerprint(result)
    return result
