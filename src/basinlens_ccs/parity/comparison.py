"""Deterministic paired comparisons with replayable evidence receipts."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .dataset import (ParityError, NumericalDataError, canonical_bytes, fingerprint, load_dataset,
                      read_json, _number)


def _seal(report):
    report["report_sha256"] = fingerprint(report)
    return report


def _base_report(atol, rtol):
    return {"report_schema_version": 1, "status": "unverifiable",
            "claim_scope": "Numerical agreement for declared outputs and one captured case only",
            "gms_match": False, "full_gms_equivalence": False,
            "numerically_comparable": False,
            "tolerances": {"atol": atol, "rtol": rtol,
                           "rule": "abs(candidate-reference) <= atol + rtol * abs(reference)"},
            "errors": [], "metrics": {}, "evidence": {},
            "provenance_limit": "Checksums detect byte changes; operator run attestations are not independently authenticated"}


def compare_datasets(reference_manifest, candidate_manifest, *, atol=1e-7, rtol=1e-6):
    """Compare captured datasets; invalid/missing evidence cannot earn a pass.

    The numerical gate uses the reference magnitude, including at zero. No
    interpolation, implicit unit conversion, clipping or NaN exclusion occurs.
    Passing synthetic pairs exercise this harness only and never establish GMS
    compatibility. Observed GMS agreement is limited to the exported quantities.
    """
    atol, rtol = _number(atol, "atol"), _number(rtol, "rtol")
    if atol < 0 or rtol < 0:
        raise ParityError("atol and rtol must be non-negative")
    report = _base_report(atol, rtol)
    loaded = {}
    for role, path in (("reference", reference_manifest), ("candidate", candidate_manifest)):
        report["evidence"][role] = {"manifest_path": str(Path(path).resolve())}
        try:
            dataset = load_dataset(path)
        except ParityError as exc:
            report["errors"].append(f"{role}: {exc}")
            if isinstance(exc, NumericalDataError):
                report["status"] = "fail"
            continue
        loaded[role] = dataset
        metadata = dataset["manifest"]
        report["evidence"][role].update({
            "manifest_sha256": dataset["manifest_sha256"],
            "dataset_id": metadata["dataset_id"], "source": metadata["source"],
            "engine": metadata["engine"], "implementation": metadata["implementation"],
            "exact_run_inputs_sha256": metadata["exact_run_inputs_sha256"],
            "comparison_input_sha256": dataset["comparison_input_sha256"],
            "data_sha256": metadata["data"]["sha256"]})
    if report["errors"]:
        return _seal(report)
    reference, candidate = loaded["reference"], loaded["candidate"]
    rm, cm = reference["manifest"], candidate["manifest"]
    for key in ("coordinates", "geometry", "times"):
        if canonical_bytes(rm[key]) != canonical_bytes(cm[key]):
            report["errors"].append(f"{key}: metadata differs; explicit alignment/conversion required")
    if reference["comparison_input_sha256"] != candidate["comparison_input_sha256"]:
        report["errors"].append("comparison_input: normalized physical case fingerprints differ")
    if set(rm["outputs"]) != set(cm["outputs"]):
        report["errors"].append("outputs: declared output names differ or required outputs are missing")
    else:
        for name in sorted(rm["outputs"]):
            for key in ("unit", "quantity", "support", "sign_convention"):
                if rm["outputs"][name][key] != cm["outputs"][name][key]:
                    report["errors"].append(f"outputs.{name}.{key}: mismatch")
            reference_semantics = {key: value for key, value in rm["outputs"][name].items() if key != "key"}
            candidate_semantics = {key: value for key, value in cm["outputs"][name].items() if key != "key"}
            if canonical_bytes(reference_semantics) != canonical_bytes(candidate_semantics):
                report["errors"].append(f"outputs.{name}: semantic metadata differs")
    if report["errors"]:
        report["status"] = "fail"
        return _seal(report)
    report["numerically_comparable"] = True
    all_passed = True
    for name in sorted(rm["outputs"]):
        expected, actual = reference["arrays"][name], candidate["arrays"][name]
        # Long-double intermediate differences avoid float64 subtraction overflow.
        difference = actual.astype(np.longdouble) - expected.astype(np.longdouble)
        absolute = np.abs(difference)
        allowed = np.longdouble(atol) + np.longdouble(rtol) * np.abs(expected.astype(np.longdouble))
        failures = absolute > allowed
        max_abs_ld = np.max(absolute)
        # Scale the RMSE calculation to avoid squaring an extreme finite value.
        rmse_ld = max_abs_ld * np.sqrt(np.mean((absolute / max_abs_ld) ** 2)) if max_abs_ld else np.longdouble(0)
        mae_ld = np.mean(absolute)
        metrics_finite = all(math.isfinite(float(value)) for value in (max_abs_ld, rmse_ld, mae_ld))
        if not metrics_finite:
            report["errors"].append(f"outputs.{name}: comparison metrics exceed finite float64 report range")
            all_passed = False
        count = int(np.count_nonzero(failures))
        passed = count == 0 and metrics_finite
        all_passed &= passed
        maximum_index = list(np.unravel_index(int(np.argmax(absolute)), absolute.shape))
        report["metrics"][name] = {
            "unit": rm["outputs"][name]["unit"], "support": rm["outputs"][name]["support"],
            "quantity": rm["outputs"][name]["quantity"],
            "shape": list(expected.shape), "count": int(expected.size), "passed": passed,
            "failed_values": count,
            "max_absolute_error": float(max_abs_ld) if metrics_finite else None,
            "rmse": float(rmse_ld) if metrics_finite else None,
            "mean_absolute_error": float(mae_ld) if metrics_finite else None,
            "max_error_index": [int(i) for i in maximum_index],
            "reference_at_max_error": float(expected[tuple(maximum_index)]),
            "candidate_at_max_error": float(actual[tuple(maximum_index)]),
            "reference_values_sha256": fingerprint(expected.tolist()),
            "candidate_values_sha256": fingerprint(actual.tolist())}
    report["status"] = "pass" if all_passed else "fail"
    report["gms_match"] = bool(all_passed and reference["observed"] and cm["source"]["kind"] == "candidate" and
                                rm["source"]["system"].strip().upper() == "GMS")
    if rm["source"]["kind"] == "synthetic":
        report["qualification"] = "Synthetic harness check; no original GMS run was observed"
    elif not reference["observed"]:
        report["qualification"] = "Reference has no observed-run provenance; no GMS matching claim"
    else:
        report["qualification"] = "One operator-attested observed run; agreement does not validate other features or physics"
    return _seal(report)


def verify_report(path: str | Path):
    """Verify digest and replay every paired receipt before coverage promotion."""
    report = read_json(path)
    digest = report.get("report_sha256")
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    if not isinstance(digest, str) or digest != fingerprint(unsigned):
        raise ParityError("Comparison report integrity fingerprint mismatch")
    if type(report.get("report_schema_version")) is not int or report["report_schema_version"] != 1:
        raise ParityError("Comparison report schema version unsupported")
    try:
        replayed = compare_datasets(
            report["evidence"]["reference"]["manifest_path"],
            report["evidence"]["candidate"]["manifest_path"],
            atol=report["tolerances"]["atol"], rtol=report["tolerances"]["rtol"])
    except (KeyError, TypeError) as exc:
        raise ParityError("Comparison report lacks replay evidence") from exc
    if canonical_bytes(replayed) != canonical_bytes(report):
        raise ParityError("Comparison evidence changed or report does not match a fresh replay")
    return report
