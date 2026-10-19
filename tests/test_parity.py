"""Original synthetic comparisons test the harness, never GMS compatibility."""
from __future__ import annotations

import copy
import csv
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
import shutil
import subprocess
from datetime import datetime, timezone
import tempfile
import unittest

import numpy as np

from basinlens_ccs.parity import (ParityError, artifact_record, assess_catalogue,
                                 compare_datasets, input_fingerprint, load_dataset, verify_report)
from basinlens_ccs.parity.__main__ import main
from basinlens_ccs.parity.dataset import fingerprint, RUN_ATTESTATIONS


GENERATOR = Path(__file__).resolve().parents[1] / "examples/parity/generate_synthetic.py"
spec = importlib.util.spec_from_file_location("synthetic_parity_example", GENERATOR)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
capture_spec = importlib.util.spec_from_file_location("capture_gms_reference", GENERATOR.parents[2] / "tools/capture_gms_reference.py")
capture_module = importlib.util.module_from_spec(capture_spec)
capture_spec.loader.exec_module(capture_module)


def write_json(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = generator.generate(Path(self.temporary.name) / "fixture")
        self.reference = self.root / "reference.json"
        self.candidate = self.root / "candidate.json"

    def update(self, path, callback):
        data = json.loads(path.read_text())
        callback(data)
        write_json(path, data)

    def rewrite_npz(self, **arrays):
        np.savez(self.root / "candidate.npz", **arrays)
        self.update(self.candidate, lambda d: d.update(data=dict(artifact_record(self.root / "candidate.npz"), format="npz")))

    def compare(self, **kwargs):
        return compare_datasets(self.reference, self.candidate, **kwargs)

    def test_synthetic_csv_npz_pass_is_deterministic_and_never_gms(self):
        report = self.compare(atol=0, rtol=0)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["numerically_comparable"])
        self.assertFalse(report["gms_match"])
        self.assertFalse(report["full_gms_equivalence"])
        self.assertEqual(report["metrics"]["head"]["rmse"], 0)
        self.assertEqual(report["metrics"]["head"]["count"], 3)
        self.assertEqual(report, self.compare(atol=0, rtol=0))

    def test_different_array_keys_can_represent_same_quantity(self):
        self.rewrite_npz(h=np.array([[[[12., 11., 10.]]]]))
        self.update(self.candidate, lambda d: d["outputs"]["head"].update(key="h"))
        self.assertEqual(self.compare()["status"], "pass")

    def test_absolute_and_reference_relative_tolerance_and_metrics(self):
        self.rewrite_npz(head=np.array([[[[12.0, 11.0, 10.1]]]]))
        report = self.compare(atol=0, rtol=0.005)
        self.assertEqual(report["status"], "fail")
        metrics = report["metrics"]["head"]
        self.assertEqual(metrics["failed_values"], 1)
        self.assertAlmostEqual(metrics["rmse"], 0.1 / np.sqrt(3))
        self.assertAlmostEqual(metrics["mean_absolute_error"], 0.1 / 3)
        self.assertEqual(metrics["max_error_index"], [0, 0, 0, 2])
        self.assertEqual(self.compare(atol=0.101, rtol=0)["status"], "pass")

    def test_geometry_time_coordinates_units_sign_mismatches_fail(self):
        original = self.candidate.read_bytes()
        changes = [
            lambda d: d["geometry"].update(origin_xy=[1, 0]),
            lambda d: d.update(times=[2]),
            lambda d: d["coordinates"].update(crs="EPSG:32652"),
            lambda d: d["coordinates"].update(vertical_datum="different datum"),
            lambda d: d["outputs"]["head"].update(unit="ft"),
            lambda d: d["outputs"]["head"].update(sign_convention="positive down"),
            lambda d: d["outputs"]["head"].update(quantity="pressure"),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.candidate.write_bytes(original)
                self.update(self.candidate, change)
                report = self.compare()
                self.assertEqual(report["status"], "fail")
                self.assertFalse(report["numerically_comparable"])
                self.assertFalse(report["gms_match"])

    def test_nan_inf_shape_boolean_complex_and_missing_outputs_fail(self):
        bad_arrays = [np.array([[[[12., np.nan, 10.]]]]), np.array([[[[12., np.inf, 10.]]]]),
                      np.array([12., 11., 10.]), np.ones((1, 1, 1, 3), dtype=bool),
                      np.ones((1, 1, 1, 3), dtype=complex)]
        for array in bad_arrays:
            with self.subTest(array=array):
                self.rewrite_npz(head=array)
                self.assertEqual(self.compare()["status"], "fail")
        self.rewrite_npz(unrelated=np.ones((1, 1, 1, 3)))
        self.assertEqual(self.compare()["status"], "fail")

    def test_empty_output_evidence_and_input_fingerprints_cannot_bypass(self):
        original = self.candidate.read_bytes()
        for change in [lambda d: d.update(inputs=[]),
                       lambda d: d.update(exact_run_inputs_sha256="0" * 64),
                       lambda d: d["engine"].update(version=""),
                       lambda d: d["implementation"].update(git_commit="unknown"),
                       lambda d: d.update(times=[]),
                       lambda d: d.update(schema_version=True)]:
            self.candidate.write_bytes(original)
            self.update(self.candidate, change)
            self.assertEqual(self.compare()["status"], "unverifiable")
        self.candidate.write_bytes(original)
        self.update(self.candidate, lambda d: d.update(outputs={}))
        self.assertEqual(self.compare()["status"], "fail")

    def test_tampered_input_and_output_fixtures_refused(self):
        (self.root / "physical_case.json").write_text('{"changed":true}')
        self.assertEqual(self.compare()["status"], "unverifiable")
        self.root = generator.generate(Path(self.temporary.name) / "another")
        self.reference, self.candidate = self.root / "reference.json", self.root / "candidate.json"
        (self.root / "candidate.npz").write_bytes(b"altered output bytes")
        self.assertEqual(self.compare()["status"], "unverifiable")

    def test_native_inputs_can_differ_but_normalized_case_must_agree(self):
        (self.root / "different.deck").write_text("DIFFERENT NATIVE FORMAT\n")
        record = artifact_record(self.root / "different.deck")
        self.update(self.candidate, lambda d: d.update(inputs=[record], exact_run_inputs_sha256=input_fingerprint([record])))
        self.assertEqual(self.compare()["status"], "pass")
        (self.root / "different_case.json").write_text('{"boundary_head_m":999}')
        self.update(self.candidate, lambda d: d.update(comparison_input=artifact_record(self.root / "different_case.json")))
        self.assertEqual(self.compare()["status"], "fail")

    def test_csv_missing_duplicate_out_of_range_nan_and_column_bypass_refused(self):
        source = (self.root / "reference.csv").read_text()
        broken = ["\n".join(source.splitlines()[:-1]) + "\n", source + source.splitlines()[1] + "\n",
                  source.replace("0,0,0,2,10.0", "0,0,0,9,10.0"),
                  source.replace("11.0", "nan"), source.replace("head", "unrelated"),
                  source.replace("0,0,0,1,11.0", "0,0,0,1,11.0,unexpected")]
        for text in broken:
            (self.root / "reference.csv").write_text(text)
            self.update(self.reference, lambda d: d.update(data=dict(artifact_record(self.root / "reference.csv"), format="csv")))
            self.assertEqual(self.compare()["status"], "fail")

    def test_multiple_times_and_face_flux_arrays_compare_without_interpolation(self):
        for role in ("reference", "candidate"):
            np.savez(self.root / (role + ".npz"), head=np.array([[[[12., 11., 10.]]], [[[12., 11., 10.]]]]),
                     qx=np.ones((2, 1, 1, 4)))
            def change(data):
                data.update(times=[1, 2], data=dict(artifact_record(self.root / (role + ".npz")), format="npz"))
                data["outputs"]["qx"] = {"key": "qx", "unit": "m3/day", "quantity": "volumetric_flow_rate", "support": "face_x", "sign_convention": "positive x"}
            self.update(self.root / (role + ".json"), change)
        report = self.compare()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["metrics"]["qx"]["shape"], [2, 1, 1, 4])

    def test_observed_reference_without_actual_receipts_is_unverifiable(self):
        self.update(self.reference, lambda d: d["source"].update(kind="observed", system="GMS", system_version="10.9.7"))
        report = self.compare()
        self.assertEqual(report["status"], "unverifiable")
        self.assertFalse(report["gms_match"])
        for provenance in ({}, {"run_id": "x", "operator": "x", "captured_at": "2026-10-19T00:00:00+00:00",
                              "command_or_workflow": "test", "observation_method": "export", "receipts": []}):
            self.update(self.reference, lambda d: d.update(provenance=provenance))
            self.assertEqual(self.compare()["status"], "unverifiable")

    def test_candidate_run_also_requires_actual_capture_receipts(self):
        self.update(self.candidate, lambda d: d["source"].update(kind="candidate"))
        self.assertEqual(self.compare()["status"], "unverifiable")

    def test_report_replay_detects_changes_and_digest_tamper(self):
        path = self.root / "comparison.json"
        report = self.compare()
        write_json(path, report)
        self.assertEqual(verify_report(path), report)
        forged = copy.deepcopy(report)
        forged["gms_match"] = True
        write_json(path, forged)
        with self.assertRaises(ParityError):
            verify_report(path)
        forged["report_sha256"] = fingerprint({k: v for k, v in forged.items() if k != "report_sha256"})
        write_json(path, forged)
        with self.assertRaisesRegex(ParityError, "replay"):
            verify_report(path)
        write_json(path, report)
        self.rewrite_npz(head=np.array([[[[12., 11., 10.2]]]]))
        with self.assertRaises(ParityError):
            verify_report(path)

    def catalogue(self):
        path = self.root / "catalogue.json"
        write_json(self.root / "comparison.json", self.compare())
        source = self.root / "feature.py"
        source.write_text("# actual original synthetic implementation fixture\n")
        log = self.root / "tests.log"
        log.write_text("synthetic test log fixture; not a real GMS run\n")
        implementation_commit = json.loads(self.candidate.read_text())["implementation"]["git_commit"]
        catalogue = {"schema_version": 1, "catalogue_id": "synthetic-inventory", "scope": "One declared analytic interchange feature only",
                     "features": [{"id": "head", "name": "Synthetic head comparison",
                                   "documentation": [{"url": "https://www.usgs.gov/", "locator": "test schema example; no content claim"}],
                                   "specifications": [artifact_record(self.root / "physical_case.json")],
                                   "implementation": [artifact_record(source)],
                                   "implementation_commit": implementation_commit,
                                   "test_runs": [{"receipt": artifact_record(log), "command": "synthetic fixture command", "result": "passed", "implementation_commit": implementation_commit}],
                                   "comparison_reports": ["comparison.json"],
                                   "comparison_contract": {"reference_dataset_ids": ["synthetic-linear-reference"], "required_outputs": ["head"],
                                                           "tolerances": {"head": {"unit": "m", "atol": 1e-7, "rtol": 1e-6}}}},
                                  {"id": "unknown", "name": "Unobserved feature"}]}
        write_json(path, catalogue)
        return path

    def test_catalogue_denominator_unknown_and_synthetic_never_matched(self):
        result = assess_catalogue(self.catalogue())
        self.assertEqual(result["denominator"], 2)
        self.assertFalse(result["complete_gms_inventory"])
        self.assertTrue(result["unknown_unlisted_features"])
        self.assertEqual(result["stage_counts"], {"documented": 1, "specified": 1, "implemented": 1, "tested": 1, "matched": 0})
        self.assertEqual(result["features"][1]["highest_evidenced_stage"], "unknown")
        self.assertTrue(result["features"][0]["synthetic_reports"])

    def test_catalogue_empty_forged_and_unrelated_comparisons_do_not_promote(self):
        catalogue = self.catalogue()
        self.update(catalogue, lambda d: d["features"][0]["comparison_contract"].update(required_outputs=["co2_saturation"]))
        self.update(catalogue, lambda d: d["features"][0]["comparison_contract"]["tolerances"].update(co2_saturation={"unit": "fraction", "atol": 1e-7, "rtol": 1e-6}))
        self.assertFalse(assess_catalogue(catalogue)["features"][0]["stages"]["matched"])
        self.assertTrue(assess_catalogue(catalogue)["features"][0]["errors"])
        self.update(catalogue, lambda d: d.update(features=[]))
        with self.assertRaises(ParityError):
            assess_catalogue(catalogue)

    def test_tampered_implementation_cannot_be_implemented_or_tested(self):
        catalogue = self.catalogue()
        (self.root / "feature.py").write_text("changed")
        result = assess_catalogue(catalogue)["features"][0]
        self.assertFalse(result["stages"]["implemented"])
        self.assertFalse(result["stages"]["tested"])

    def test_tolerance_validation(self):
        for kwargs in ({"atol": -1}, {"rtol": float("nan")}, {"atol": True}, {"rtol": float("inf")}):
            with self.assertRaises(ParityError):
                self.compare(**kwargs)

    def test_unsafe_artifact_duplicate_json_and_empty_case_refused(self):
        self.update(self.candidate, lambda d: d["data"].update(path="../candidate.npz"))
        self.assertEqual(self.compare()["status"], "unverifiable")
        self.candidate.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ParityError, "Duplicate"):
            load_dataset(self.candidate)
        write_json(self.root / "empty.json", {})
        self.update(self.reference, lambda d: d.update(comparison_input=artifact_record(self.root / "empty.json")))
        self.assertEqual(self.compare()["status"], "unverifiable")

    def test_cli_exit_codes_and_immutable_output(self):
        output = self.root / "cli-report.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["compare", str(self.reference), str(self.candidate), "--output", str(output)]), 0)
            self.assertEqual(main(["verify", str(output)]), 0)
            self.assertEqual(main(["compare", str(self.reference), str(self.candidate), "--output", str(output)]), 2)
            self.rewrite_npz(head=np.array([[[[12., 11., 15.]]]]))
            self.assertEqual(main(["compare", str(self.reference), str(self.candidate), "--output", str(self.root / "failure.json")]), 1)
            self.candidate.unlink()
            self.assertEqual(main(["compare", str(self.reference), str(self.candidate), "--output", str(self.root / "unverifiable.json")]), 2)

    def test_capture_requires_explicit_successful_past_run_attestation(self):
        with self.assertRaises(ParityError):
            capture_module._validate_record({})
        record = {"schema_version": 1, "source_kind": "observed", "system": "GMS", "system_version": "10.9.7",
                  "run_id": "schema-test-only", "operator": "synthetic contract test",
                  "run_started_at": "2020-01-01T01:00:00+00:00", "run_finished_at": "2020-01-01T02:00:00+00:00",
                  "successful": True, "command_or_workflow": "schema validation only; no observed GMS run",
                  "engine": {"name": "schema test", "version": "1", "executable_sha256": "b" * 64},
                  "system_executable_sha256": "c" * 64, "implementation_git_commit": "a" * 40, "attestation": ""}
        with self.assertRaises(ParityError):
            capture_module._validate_record(record)
        record["attestation"] = capture_module.ATTESTATION
        capture_module._validate_record(record)
        record["run_finished_at"] = "2999-01-01T00:00:00+00:00"
        with self.assertRaises(ParityError):
            capture_module._validate_record(record)

    @unittest.skipIf(sys.platform == "win32", "Non-Windows unknown-version contract")
    def test_capture_cannot_guess_windows_version_or_activate_target(self):
        with self.assertRaisesRegex(ParityError, "unknown"):
            capture_module._pe_version(self.root / "nonexistent-gms.exe")

    def test_arbitrary_receipts_cannot_relabel_synthetic_as_observed_gms(self):
        for name in ("run.txt", "capture.txt", "operator.txt"):
            (self.root / name).write_text("NOT A RUN OR STRUCTURED CAPTURE\n")
        receipts = [dict(artifact_record(self.root / name), role=role) for name, role in
                    (("run.txt", "run_log"), ("capture.txt", "capture_record"), ("operator.txt", "operator_run_record"))]
        provenance = {"run_id": "never-run", "operator": "schema-only test", "captured_at": "2020-01-01T00:00:00+00:00",
                      "command_or_workflow": "no GMS run", "observation_method": "no run", "receipts": receipts}
        for path, kind in ((self.reference, "observed"), (self.candidate, "candidate")):
            self.update(path, lambda d: d.update(provenance=provenance))
            self.update(path, lambda d: d["source"].update(kind=kind))
        self.update(self.reference, lambda d: d["source"].update(system="GMS", system_version="10.9.7"))
        report = self.compare()
        self.assertEqual(report["status"], "unverifiable")
        self.assertFalse(report["gms_match"])
        self.assertTrue(any("JSON" in error for error in report["errors"]))

    def candidate_capture(self):
        """Actually run the original analytic generator; no GMS reference is involved."""
        run_directory = self.root / "actual-analytic-run"
        started = datetime.now(timezone.utc).isoformat()
        run = subprocess.run([sys.executable, str(GENERATOR), str(run_directory)],
                             check=True, capture_output=True, text=True)
        finished = datetime.now(timezone.utc).isoformat()
        native = self.root / "native-inputs"
        exports = self.root / "native-exports"
        native.mkdir(); exports.mkdir()
        shutil.copyfile(run_directory / "physical_case.json", native / "physical_case.json")
        shutil.copyfile(run_directory / "candidate.npz", exports / "candidate.npz")
        (self.root / "actual-run.log").write_text("Executed original analytic generator; not GMS\n" + run.stdout)
        data = json.loads((run_directory / "candidate.json").read_text())
        record = {"schema_version": 1, "source_kind": "candidate", "system": data["source"]["system"],
                  "system_version": data["source"]["system_version"], "run_id": "actual-analytic-generator-run",
                  "operator": "automated analytic regression", "run_started_at": started, "run_finished_at": finished,
                  "successful": True, "command_or_workflow": "python examples/parity/generate_synthetic.py",
                  "engine": data["engine"], "implementation_git_commit": data["implementation"]["git_commit"],
                  "system_executable_sha256": artifact_record(sys.executable)["sha256"],
                  "attestation": RUN_ATTESTATIONS["candidate"]}
        record_path = self.root / "analytic-operator-record.json"
        write_json(record_path, record)
        captured = capture_module.capture(executable=sys.executable, engine_executable=GENERATOR,
            inputs=native, exports=exports, run_log=self.root / "actual-run.log", run_record=record_path,
            output=self.root / "captured-analytic")
        capture = json.loads((captured / "capture_record.json").read_text())
        inputs = [r for r in capture["snapshots"] if r["path"].startswith("inputs/")]
        data["source"]["kind"] = "candidate"
        data.update(inputs=inputs, exact_run_inputs_sha256=input_fingerprint(inputs), comparison_input=inputs[0],
                    data=dict(artifact_record(captured / "exports/candidate.npz", root=captured), format="npz"),
                    provenance={"run_id": record["run_id"], "operator": record["operator"],
                                "captured_at": capture["captured_at"], "command_or_workflow": record["command_or_workflow"],
                                "observation_method": capture["capture_method"],
                                "receipts": [dict(artifact_record(captured / path, root=captured), role=role)
                                    for path, role in (("original_run.log", "run_log"), ("capture_record.json", "capture_record"),
                                                       ("operator_run_record.json", "operator_run_record"))]})
        destination = captured / "dataset.json"
        write_json(destination, data)
        return destination

    def test_actual_non_gms_candidate_capture_is_bound_and_comparable(self):
        candidate = self.candidate_capture()
        report = compare_datasets(self.reference, candidate)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertFalse(report["gms_match"])

    def test_rehashed_capture_identity_engine_time_input_output_and_commit_mismatch_refused(self):
        candidate = self.candidate_capture()
        capture_path = candidate.parent / "capture_record.json"
        original_capture = capture_path.read_bytes()
        original_manifest = candidate.read_bytes()
        changes = [lambda d: d.update(run_id="unrelated-run"),
                   lambda d: d.update(system_version="unrelated-version"),
                   lambda d: d["engine"].update(version="unrelated-engine"),
                   lambda d: d.update(implementation_git_commit="a" * 40),
                   lambda d: d.update(captured_at="2010-01-01T00:00:00+00:00"),
                   lambda d: d.update(snapshots=[r for r in d["snapshots"] if not r["path"].startswith("inputs/")]),
                   lambda d: d.update(snapshots=[r for r in d["snapshots"] if not r["path"].startswith("exports/")])]
        for change in changes:
            capture_path.write_bytes(original_capture)
            candidate.write_bytes(original_manifest)
            self.update(capture_path, change)
            self.update(candidate, lambda d: d["provenance"].update(receipts=[
                dict(artifact_record(capture_path, root=candidate.parent), role="capture_record") if r["role"] == "capture_record" else r
                for r in d["provenance"]["receipts"]]))
            report = compare_datasets(self.reference, candidate)
            self.assertEqual(report["status"], "unverifiable", report["errors"])
            self.assertFalse(report["gms_match"])

    def test_output_semantic_extras_cannot_be_silently_ignored(self):
        self.update(self.reference, lambda d: d["outputs"]["head"].update(pressure_reference="absolute"))
        self.update(self.candidate, lambda d: d["outputs"]["head"].update(pressure_reference="gauge"))
        self.assertEqual(self.compare()["status"], "fail")

    def test_coverage_rejects_stale_commit_and_overpermissive_tolerance(self):
        path = self.catalogue()
        self.update(path, lambda d: d["features"][0].update(implementation_commit="a" * 40))
        result = assess_catalogue(path)["features"][0]
        self.assertFalse(result["stages"]["tested"])
        self.assertTrue(any("commit" in error for error in result["errors"]))
        path = self.catalogue()
        write_json(self.root / "comparison.json", self.compare(atol=1e100, rtol=1e100))
        result = assess_catalogue(path)["features"][0]
        self.assertFalse(result["stages"]["matched"])
        self.assertTrue(any("tolerance" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
