"""Regression tests for evidence accounting, not a claim of GMS equivalence."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from basinlens_ccs.reconstruction.status import (
    ImplementationState, OriginalComparisonState, StatusError, main,
    markdown_report, validate_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'docs/gms/implementation_status.json'


class ImplementationStatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = deepcopy(json.loads(REGISTRY.read_text()))
        names = {self.registry['catalogue']['path']}
        names.update(item['file']['path'] for item in self.registry['evidence'].values())
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.path = self.root / 'docs/gms/implementation_status.json'
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.registry, ensure_ascii=False, indent=2) + '\n')

    def validate(self):
        self.write()
        return validate_registry(self.path, root=self.root)

    @staticmethod
    def execution_snapshots(data):
        """Both public CI wrappers and standalone selected-runner receipts."""
        if data.get('schema') in {'basinlens-feature-tests-v1', 'basinlens-ci-real-mf6-tests-v1'}:
            return [data]
        return [run['parsed_artifact_records']['tests.json'] for run in data['runs']]

    def partial(self):
        return next(row for row in self.registry['features'] if row['implementation'] == 'PARTIAL')

    def rehash(self, evidence):
        path = self.root / evidence['path']
        evidence.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size)

    def test_pinned_catalogue_has_exact_rows_and_no_whole_product_promotion(self):
        report = self.validate()
        catalogue = json.loads((self.root / self.registry['catalogue']['path']).read_text())
        self.assertEqual([row['id'] for row in report['features']], [row['id'] for row in catalogue['features']])
        self.assertEqual(report['catalogue_entries'], 163)
        self.assertEqual(sum(report['implementation_counts'].values()), 163)
        self.assertEqual(report['whole_product']['barrier'], 'OPEN')
        self.assertFalse(report['whole_product']['complete'])
        self.assertFalse(report['whole_product']['native_gpr_write_implemented'])
        self.assertEqual(report['verified_original_numerical_features'], 0)
        self.assertEqual(report['original_comparison_counts']['VERIFIED'], 0)
        self.assertEqual(set(ImplementationState), {ImplementationState.NONE, ImplementationState.PARTIAL, ImplementationState.SCOPED_COMPLETE})
        self.assertEqual(set(OriginalComparisonState), {OriginalComparisonState.NOT_OBSERVED, OriginalComparisonState.OBSERVED_PARTIAL, OriginalComparisonState.VERIFIED})

    def test_missing_duplicate_unrecognized_and_renamed_rows_fail(self):
        original = deepcopy(self.registry)
        for mutation in ('missing', 'duplicate', 'unrecognized', 'rename'):
            with self.subTest(mutation=mutation):
                self.registry = deepcopy(original)
                if mutation == 'missing':
                    self.registry['features'].pop()
                elif mutation == 'duplicate':
                    self.registry['features'].append(deepcopy(self.registry['features'][0]))
                elif mutation == 'unrecognized':
                    self.registry['features'][0]['id'] = 'invented.complete_product'
                else:
                    self.registry['features'][0]['name'] = 'Unreviewed renamed feature'
                with self.assertRaises(StatusError):
                    self.validate()

    def test_catalogue_source_tamper_is_rejected(self):
        path = self.root / self.registry['catalogue']['path']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(StatusError, 'stale or altered'):
            self.validate()

    def test_stale_and_missing_evidence_are_rejected(self):
        evidence = self.registry['evidence'][self.partial()['implementation_evidence_refs'][0]]['file']
        path = self.root / evidence['path']
        original = path.read_bytes()
        path.write_bytes(original + b'\n# changed implementation\n')
        with self.assertRaisesRegex(StatusError, 'stale or altered'):
            self.validate()
        path.unlink()
        with self.assertRaisesRegex(StatusError, 'Missing evidence'):
            self.validate()

    def test_rehashing_changed_source_cannot_reuse_old_test_pass(self):
        evidence = self.registry['evidence'][self.partial()['implementation_evidence_refs'][0]]['file']
        path = self.root / evidence['path']
        path.write_bytes(path.read_bytes() + b'\n# changed source\n')
        self.rehash(evidence)
        with self.assertRaisesRegex(StatusError, 'exact test/source bytes'):
            self.validate()

    def test_nonexistent_or_unexecuted_test_names_are_rejected(self):
        check = self.partial()['software_checks'][0]
        existing_test_name = check['test_names'][0]
        check['test_names'] = ['test_not_in_the_exact_source']
        with self.assertRaisesRegex(StatusError, 'test names do not exist'):
            self.validate()
        check['test_names'] = [existing_test_name]
        record = self.registry['evidence'][check['execution_record_ref']]['file']
        path = self.root / record['path']
        data = json.loads(path.read_text())
        for receipt in self.execution_snapshots(data):
            receipt['test_ids'] = [name for name in receipt['test_ids'] if not name.endswith('.' + existing_test_name)]
            receipt['tests_run'] = len(receipt['test_ids'])
        path.write_text(json.dumps(data))
        self.rehash(record)
        with self.assertRaisesRegex(StatusError, 'exact test/source bytes'):
            self.validate()

    def test_skipped_failed_and_label_only_execution_receipts_are_rejected(self):
        original = deepcopy(self.registry)
        run_ref = self.partial()['software_checks'][0]['execution_record_ref']
        record = self.registry['evidence'][run_ref]['file']
        path = self.root / record['path']
        original_bytes = path.read_bytes()
        for mutation in ('label', 'failed', 'skipped', 'incomplete'):
            with self.subTest(mutation=mutation):
                self.registry = deepcopy(original)
                record = self.registry['evidence'][run_ref]['file']
                data = json.loads(original_bytes)
                if mutation == 'label':
                    data = {'status': 'passed', 'tests_run': 265}
                else:
                    for receipt in self.execution_snapshots(data):
                        if mutation == 'failed': receipt['failures'] = ['failed case']
                        if mutation == 'skipped': receipt['skipped'] = ['missing solver']
                        if mutation == 'incomplete': receipt['tests_run'] -= 1
                path.write_text(json.dumps(data))
                self.rehash(record)
                with self.assertRaises(StatusError): self.validate()

    def test_saved_file_observation_never_becomes_numerical_verification(self):
        observed = next(row for row in self.registry['features'] if row['original_comparison']['state'] == 'OBSERVED_PARTIAL')
        observed['original_comparison']['state'] = 'VERIFIED'
        observed['original_comparison']['kind'] = 'PAIRED_NUMERICAL'
        observed['original_comparison']['verification_contract'] = {'feature_id': observed['id']}
        with self.assertRaisesRegex(StatusError, 'VERIFIED is unavailable'):
            self.validate()

    def test_arbitrary_code_cannot_be_labeled_original_observation(self):
        row = self.partial()
        row['original_comparison'].update(state='OBSERVED_PARTIAL', kind='SAVED_ORIGINAL_FILE', evidence_refs=row['implementation_evidence_refs'])
        with self.assertRaisesRegex(StatusError, 'matching original observation'):
            self.validate()

    def test_product_barrier_and_unknown_inventory_cannot_be_closed(self):
        original = deepcopy(self.registry)
        for key, value in [('barrier', 'CLOSED'), ('complete', True), ('inventory_complete', True),
                           ('unknown_unlisted_features', False), ('native_gpr_write_implemented', True)]:
            with self.subTest(key=key):
                self.registry = deepcopy(original)
                self.registry['whole_product'][key] = value
                with self.assertRaisesRegex(StatusError, 'scope barrier'):
                    self.validate()

    def test_scoped_complete_requires_explicit_bounded_acceptance(self):
        row = self.partial()
        row['implementation'] = 'SCOPED_COMPLETE'
        with self.assertRaisesRegex(StatusError, 'scoped_completion_contract'):
            self.validate()
        row['scoped_completion_contract'] = {
            'scope': 'Unsupported whole GMS completion', 'accepted_criteria': ['One source file exists'],
            'test_names': row['software_checks'][0]['test_names']}
        with self.assertRaisesRegex(StatusError, 'bounded implemented scope'):
            self.validate()

    def test_source_reconciliation_keeps_unmapped_items_and_remains_open(self):
        report = self.validate()
        items = report['source_reconciliation']['items']
        unmapped = [item for item in items if item['mapping_state'] == 'UNMAPPED_OPEN']
        self.assertGreater(len(unmapped), 0)
        self.assertTrue(any('GWE borehole' in item['locator'] for item in unmapped))
        self.assertTrue(any('TVM' in item['locator'] for item in unmapped))
        self.assertEqual({item['source_ref'] for item in items}, set(report['official_sources']))
        self.registry['source_reconciliation']['status'] = 'COMPLETE'
        with self.assertRaisesRegex(StatusError, 'reconciliation must remain OPEN'):
            self.validate()

    def test_unknown_reconciliation_ids_and_mapped_omissions_fail(self):
        item = self.registry['source_reconciliation']['items'][0]
        item['catalogue_refs'] = ['invented.complete_product']
        with self.assertRaisesRegex(StatusError, 'unrecognized catalogue ID'):
            self.validate()
        item['catalogue_refs'] = []
        with self.assertRaisesRegex(StatusError, 'Mapped source items'):
            self.validate()

    def test_path_escape_symbolic_links_and_duplicate_json_keys_fail(self):
        record = self.registry['evidence'][self.partial()['implementation_evidence_refs'][0]]['file']
        original = record['path']
        record['path'] = '../outside.py'
        with self.assertRaisesRegex(StatusError, 'repository-relative'):
            self.validate()
        record['path'] = original
        path = self.root / original
        real = path.with_suffix('.real')
        path.rename(real)
        path.symlink_to(real)
        with self.assertRaisesRegex(StatusError, 'Symbolic-link'):
            self.validate()
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(StatusError, 'duplicate key'):
            validate_registry(self.path, root=self.root)

    def test_selected_module_runner_records_actual_tests_without_full_ci_claim(self):
        tool_path = ROOT / 'tools/update_gms_status.py'
        spec = importlib.util.spec_from_file_location('status_feature_test_runner', tool_path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        receipt_path = self.root / 'feature-tests.json'
        record = tool.selected_run(['test_capacity'], receipt_path)
        self.assertEqual(record['schema'], 'basinlens-feature-tests-v1')
        self.assertEqual(record['status'], 'passed')
        self.assertIs(record['full_suite'], False)
        self.assertEqual(record['selection']['modules'], ['test_capacity'])
        self.assertIn('test_implementation_status', record['selection']['unselected_modules'])
        self.assertEqual(record['tests_run'], 3)
        self.assertTrue(all(test.startswith('test_capacity.') for test in record['test_ids']))
        from basinlens_ccs.reconstruction.status import _executed_test_snapshots
        self.assertEqual(len(_executed_test_snapshots(receipt_path)), 1)
        record['full_suite'] = True
        receipt_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(StatusError, 'cannot claim full CI'):
            _executed_test_snapshots(receipt_path)
        with self.assertRaises(FileExistsError):
            tool.selected_run(['test_capacity'], receipt_path)

    def test_markdown_and_cli_reproduce_counts_without_completion_percentage(self):
        report = self.validate()
        markdown = markdown_report(report)
        self.assertIn('Whole-product barrier: **OPEN**', markdown)
        self.assertIn('UNMAPPED_OPEN', markdown)
        self.assertIn('interchange.gpr_container', markdown)
        self.assertNotIn('100%', markdown)
        target = self.root / 'status.md'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['report', '--registry', str(self.path), '--root', str(self.root), '--format', 'markdown', '--output', str(target)]), 0)
            self.assertEqual(main(['report', '--registry', str(self.path), '--root', str(self.root), '--format', 'markdown', '--output', str(target)]), 1)
            self.assertEqual(main(['validate', '--registry', str(self.path), '--root', str(self.root), '--format', 'markdown']), 1)
        self.assertEqual(target.read_text(), markdown)


if __name__ == '__main__':
    unittest.main()
