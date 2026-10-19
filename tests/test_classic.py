"""Independent confined-water limits and operational checks for actual classic engines.

These authored cases are not original GMS comparisons, unconfined/drying tests,
or a complete MODFLOW-2005/NWT interface acceptance suite.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from basinlens_ccs.subsurface.model_workflow import WorkflowCase, load_workflow_case
from basinlens_ccs.subsurface import classic

ROOT = Path(__file__).resolve().parents[1]
FLOPY = importlib.util.find_spec('flopy') is not None
MF2005 = os.environ.get('MF2005_EXE')
MFNWT = os.environ.get('MFNWT_EXE')
BASE = ROOT / 'examples/workflow/layered_background_water.json'


def material(name, kx=10., ky=10., kz=1., ss=.003):
    return dict(id=name, name=name, kx_m_day=kx, ky_m_day=ky, kz_m_day=kz,
                ss_per_m=ss, porosity=.23)


def boundary(kind, cell, **values):
    return dict(kind=kind, period=0, cell=cell, values=values,
                label='authored_' + kind + '_' + '_'.join(map(str, cell)))


def case(name='base', nrow=1, ncol=2, dx=4., dy=7., thickness=11.,
         materials=None, assignments=None, boundaries=None, periods=None, initial=25.):
    data = load_workflow_case(BASE).to_dict()
    data['project'].update(id='classic_test_' + name, name='Authored classic test ' + name,
        provenance=['Independent synthetic software/numerical regression; not GMS or field data'])
    data['grid'].update(nrow=nrow, ncol=ncol, dx_m=dx, dy_m=dy,
        x_origin_m=47., y_origin_m=-83., layer_surfaces_m=[0., -thickness])
    data.update(strata=[dict(id='aquifer', name='Explicit flat unit', layer_indices=[0])],
        materials=materials or [material('rock')],
        assignments=[dict(material_id=mid, stratum_id='aquifer', cells=cells)
                     for mid, cells in (assignments or [('rock', [[0, r, c] for r in range(nrow) for c in range(ncol)])])],
        boundaries=boundaries if boundaries is not None else [boundary('CHD', [0, 0, 0], head_m=20.)],
        initial_head_m=[initial] * (nrow * ncol),
        periods=periods or [dict(duration_day=1.25, nsteps=1, steady=True)])
    return WorkflowCase.from_dict(data)


def series_case():
    conductivity = [1., 2., 4., 8.]
    model = case('series', ncol=4, dx=3., dy=2., thickness=6.,
        materials=[material('rock' + str(i), k, k / 2., .7) for i, k in enumerate(conductivity)],
        assignments=[('rock' + str(i), [[0, 0, i]]) for i in range(4)],
        boundaries=[boundary('CHD', [0, 0, 0], head_m=20.), boundary('CHD', [0, 0, 3], head_m=8.)])
    # Independent half-cell hydraulic resistance: distance=3 m, face area=12 m2.
    conductance = np.array([2*a*b/(a+b)*12./3. for a, b in zip(conductivity, conductivity[1:])])
    flow = 12. / np.sum(1. / conductance)
    heads = np.r_[20., 20. - np.cumsum(flow / conductance)].reshape(1, 1, 4)
    return model, heads, flow


def combination_case():
    model = case('combination', ncol=2, boundaries=[item for col in range(2) for item in (
        boundary('GHB', [0, 0, col], head_m=16.25, conductance_m2_day=2.7),
        boundary('RCH', [0, 0, col], rate_m_day=.035),
        boundary('WEL', [0, 0, col], rate_m3_day=-1.6))])
    # Steady balance: C*(hb-h) + recharge*area + Qwell = 0.
    expected = 16.25 + (.035 * 28. - 1.6) / 2.7
    return model, expected


def storage_case():
    model = case('storage', ncol=2, dx=5., dy=4., thickness=7., materials=[material('rock', ss=.002)],
        boundaries=[boundary('WEL', [0, 0, col], rate_m3_day=1.12) for col in range(2)],
        periods=[dict(duration_day=1., nsteps=4, steady=False), dict(duration_day=.5, nsteps=2, steady=False)])
    # Ss*V=.002*(5*4*7)=.28 m2; each .25-day first-period step adds 1 m.
    return model, np.repeat(np.array([26., 27., 28., 29., 29., 29.]).reshape(6, 1, 1, 1), 2, axis=3)


def coordinate_case():
    model = case('coordinates', nrow=2, ncol=3, dx=3., dy=5., thickness=4.,
        materials=[material('rock', 6., 2., .7)], boundaries=[
            boundary('CHD', [0, 0, 0], head_m=19.), boundary('CHD', [0, 0, 2], head_m=15.),
            boundary('CHD', [0, 1, 0], head_m=11.), boundary('CHD', [0, 1, 2], head_m=7.)])
    # Independent two-unknown system: Gx=40, Gy=4.8, hS+hN=26,
    # (80+2*4.8)*(hS-hN)=80*(17-9). Project row zero is the south row.
    expected = np.array([[[19., 17.-3./7., 15.], [11., 9.+3./7., 7.]]])
    return model, expected


def snapshot(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file() and not p.is_symlink()}


class ClassicInputAndParserTests(unittest.TestCase):
    def test_missing_engine_and_invalid_timeout_leave_no_result_directory(self):
        model = case()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'absent'
            with self.assertRaises(FileNotFoundError):
                classic.run_classic(model, output, engine='mf2005', exe_name=str(Path(temporary) / 'missing'))
            self.assertFalse(output.exists())
            for timeout in (False, 0, 1801, 1.5):
                with self.subTest(timeout=timeout), self.assertRaises(classic.ClassicError):
                    classic.run_classic(model, output, engine='mf2005', exe_name='missing', timeout_seconds=timeout)
                self.assertFalse(output.exists())

    def test_bounded_double_head_parser_rejects_header_time_shape_and_nonfinite(self):
        model = case('head_parser', ncol=1)
        schedule = [(1, 1, 1.25, 1.25)]
        header = struct.Struct('<iidd16siii')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'head.hds'
            valid = header.pack(1, 1, 1.25, 1.25, b'HEAD            ', 1, 1, 1) + struct.pack('<d', 20.)
            path.write_bytes(valid)
            np.testing.assert_array_equal(classic._heads(path, model, schedule), [[[[20.]]]])
            mutations = [valid[:-1], valid + b'extra',
                header.pack(1, 1, 1.20, 1.25, b'HEAD            ', 1, 1, 1) + struct.pack('<d', 20.),
                header.pack(1, 1, 1.25, 1.25, b'HEAD            ', 2, 1, 1) + struct.pack('<d', 20.),
                valid[:-8] + struct.pack('<d', float('nan'))]
            for payload in mutations:
                with self.subTest(size=len(payload)):
                    path.write_bytes(payload)
                    with self.assertRaises(ValueError): classic._heads(path, model, schedule)

    def test_unassigned_implicit_constant_head_term_must_have_exactly_zero_flow(self):
        model = case('implicit_chd', ncol=2, boundaries=[
            boundary('GHB', [0, 0, 0], head_m=20., conductance_m2_day=2.),
            boundary('WEL', [0, 0, 1], rate_m3_day=1.)])
        header = struct.Struct('<ii16siii')
        times = struct.Struct('<iddd')
        def record(label, rates):
            return header.pack(1, 1, label.encode().ljust(16), 2, 1, -1) + times.pack(1, 1.25, 1.25, 1.25) + struct.pack('<2d', *rates)
        legitimate = record('WELLS', [0., 1.]) + record('HEAD DEP BOUNDS', [-1., 0.])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'budget.cbc'
            path.write_bytes(record('CONSTANT HEAD', [0., 0.]) + legitimate)
            parsed = classic._cbc(path, model, [(1, 1, 1.25, 1.25)])
            self.assertEqual(parsed[0]['TOTAL_IN'], 1.)
            self.assertEqual(parsed[0]['TOTAL_OUT'], 1.)
            path.write_bytes(record('CONSTANT HEAD', [.001, 0.]) + legitimate)
            with self.assertRaises(classic.ClassicError):
                classic._cbc(path, model, [(1, 1, 1.25, 1.25)])

    def test_budget_parser_rejects_wrong_dt_period_time_and_finite_sum_overflow(self):
        model = case('budget', ncol=2, boundaries=[
            boundary('GHB', [0, 0, 0], head_m=20., conductance_m2_day=2.),
            boundary('WEL', [0, 0, 1], rate_m3_day=1.)])
        header = struct.Struct('<ii16siii')
        times = struct.Struct('<iddd')
        prefix = header.pack(1, 1, b'WELLS           ', 2, 1, -1)
        schedule = [(1, 1, 1.25, 1.25)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'budget.cbc'
            for dt, pt in ((1., 1.25), (1.25, 1.)):
                path.write_bytes(prefix + times.pack(1, dt, pt, 1.25) + struct.pack('<2d', 0., 1.))
                with self.subTest(dt=dt, pt=pt), self.assertRaisesRegex(classic.ClassicError, 'time|schedule'):
                    classic._cbc(path, model, schedule)
            path.write_bytes(prefix + times.pack(1, 1.25, 1.25, 1.25) + struct.pack('<2d', 1e308, 1e308))
            with self.assertRaisesRegex(classic.ClassicError, 'finite|overflow|aggregate'):
                classic._cbc(path, model, schedule)
            # Method-2 declared list length is bounded before reading/allocating payload.
            path.write_bytes(prefix + times.pack(2, 1.25, 1.25, 1.25) + struct.pack('<i', 3))
            with self.assertRaisesRegex(classic.ClassicError, 'allocation|list'): classic._cbc(path, model, schedule)


@unittest.skipUnless(FLOPY, 'Optional FloPy dependency required')
class ClassicExportAndFailureTests(unittest.TestCase):
    def test_export_exact_reconstruction_identity_and_input_tampering(self):
        model = series_case()[0]
        original = model.to_dict()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for engine in ('mf2005', 'mfnwt'):
                folder = classic.export_classic(model, root / engine, engine=engine)
                recovered, record = classic.verify_classic_export(folder)
                self.assertEqual(recovered, model)
                self.assertEqual(record['engine'], engine)
                self.assertEqual(record['linear_solver'], 'pcg' if engine == 'mf2005' else 'xmd')
                self.assertIn('classic.py', record['compiler_sources'])
                self.assertEqual(record['compiled_period_durations_day'], [1.25])
                before = snapshot(folder)
                classic.verify_classic_export(folder)
                self.assertEqual(snapshot(folder), before)
                settings_path = folder / 'settings.json'
                original_settings = settings_path.read_bytes()
                edited = json.loads(original_settings)
                edited['linear_solver'] = 'gmres'
                settings_path.write_text(json.dumps(edited))
                with self.assertRaises(classic.ClassicError): classic.verify_classic_export(folder)
                settings_path.write_bytes(original_settings)
                (folder / 'flow.dis').write_bytes((folder / 'flow.dis').read_bytes() + b'\n# altered\n')
                with self.assertRaises(classic.ClassicError): classic.verify_classic_export(folder)
                with self.assertRaises(FileExistsError): classic.export_classic(model, folder, engine=engine)
            self.assertEqual(model.to_dict(), original)

    def test_explicit_linear_solver_refuses_unknown_and_engine_mismatched_methods(self):
        with tempfile.TemporaryDirectory() as temporary:
            for engine, methods in (('mf2005', ('gmres', 'xmd', 'auto', False)),
                                    ('mfnwt', ('pcg', 'auto', False))):
                for index, method in enumerate(methods):
                    output = Path(temporary) / (engine + '-' + str(index))
                    with self.subTest(engine=engine, method=method), self.assertRaises(classic.ClassicError):
                        classic.export_classic(case(), output, engine=engine, linear_solver=method)

    def test_unsupported_single_cell_is_refused_before_engine_execution(self):
        model = case('isolated', ncol=1)
        with tempfile.TemporaryDirectory() as temporary:
            for engine in ('mf2005', 'mfnwt'):
                with self.subTest(engine=engine), self.assertRaisesRegex(classic.ClassicError, 'isolated|single|cell'):
                    classic.export_classic(model, Path(temporary) / engine, engine=engine)

    def test_float32_legacy_geometry_collapse_is_refused_without_correcting_case(self):
        data = case('thin').to_dict()
        data['grid']['layer_surfaces_m'] = [100000., 99999.999]
        data['initial_head_m'] = [100001., 100001.]
        data['boundaries'][0]['values']['head_m'] = 100001.
        model = WorkflowCase.from_dict(data)
        before = model.to_dict()
        with tempfile.TemporaryDirectory() as temporary:
            for engine in ('mf2005', 'mfnwt'):
                with self.subTest(engine=engine), self.assertRaisesRegex(classic.ClassicError, 'precision|thickness|geometry|layer'):
                    classic.export_classic(model, Path(temporary) / engine, engine=engine)
        self.assertEqual(model.to_dict(), before)

    def test_native_roundtrip_really_loads_rewrites_and_preserves_source(self):
        model = coordinate_case()[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for engine in ('mf2005', 'mfnwt'):
                source = classic.export_classic(model, root / (engine + '-source'), engine=engine)
                before = snapshot(source)
                receipt = classic.verify_classic_roundtrip(source, root / (engine + '-roundtrip'))
                self.assertEqual(receipt['status'], 'completed')
                self.assertTrue(receipt['source_unchanged'])
                self.assertTrue(receipt['native_token_semantics_equal'])
                self.assertTrue(receipt['case_metadata_preserved'])
                self.assertEqual(receipt['native_runs_requested'], 0)
                self.assertEqual(receipt['native_runs_completed'], 0)
                self.assertIsNone(receipt['numerical_roundtrip_passed'])
                self.assertFalse(receipt['gms_project_roundtrip'])
                self.assertFalse(receipt['gms_parity_established'])
                self.assertEqual(snapshot(source), before)
                recovered, _ = classic.verify_classic_export(root / (engine + '-roundtrip') / 'rewritten')
                self.assertEqual(recovered, model)

    def test_changing_classic_constant_head_support_is_explicitly_refused(self):
        data = storage_case()[0].to_dict()
        data['boundaries'] = [boundary('CHD', [0, 0, 0], head_m=25.)]
        model = WorkflowCase.from_dict(data)
        with tempfile.TemporaryDirectory() as temporary:
            for engine in ('mf2005', 'mfnwt'):
                with self.subTest(engine=engine), self.assertRaisesRegex(classic.ClassicError, 'CHD|support'):
                    classic.export_classic(model, Path(temporary) / engine, engine=engine)

    def test_engine_failure_preserves_input_logs_and_original_diagnostic(self):
        model = case()
        identity = {'engine': 'mf2005', **classic.PINNED['mf2005'], 'path': '/mock/pinned-engine'}
        def fail(command, folder, stdout, stderr, *args, **kwargs):
            Path(stdout).write_text('Deliberately injected solver process failure\n')
            Path(stderr).write_text('Authored operational fault fixture\n')
            (Path(folder) / 'flow.list').write_text('FAILED TO MEET SOLVER CONVERGENCE\n')
            return 7
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'failure'
            with patch.object(classic, '_solver', return_value=(Path('/mock/pinned-engine'), identity)), patch.object(classic, '_execute', side_effect=fail):
                with self.assertRaises(classic.ClassicError):
                    classic.run_classic(model, output, engine='mf2005', exe_name='/mock/pinned-engine')
            record = json.loads((output / 'run.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['error_type'], 'ClassicError')
            self.assertIn('failed', record['error'].lower())
            self.assertTrue((output / 'stdout.log').is_file())
            self.assertTrue((output / 'stderr.log').is_file())
            self.assertTrue((output / 'native/settings.json').is_file())
            for name, item in record['captured_inputs'].items():
                raw = (output / 'native' / name).read_bytes()
                self.assertEqual({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, item)
            with self.assertRaises(classic.ClassicError): classic.read_classic_results(output)

    def test_timeout_and_secondary_inventory_failure_keep_first_exception(self):
        identity = {'engine': 'mf2005', **classic.PINNED['mf2005'], 'path': '/mock/pinned-engine'}
        def timeout(command, folder, stdout, stderr, *args, **kwargs):
            Path(stdout).write_text('Deliberately injected process timeout\n')
            Path(stderr).write_text('Authored timeout fixture\n')
            raise TimeoutError('authored timeout after captured input export')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'timeout'
            with patch.object(classic, '_solver', return_value=(Path('/mock/pinned-engine'), identity)), \
                 patch.object(classic, '_execute', side_effect=timeout), \
                 patch.object(classic, '_run_inventory', side_effect=classic.ClassicError('authored artifact inventory budget failure')):
                with self.assertRaisesRegex(TimeoutError, 'authored timeout'):
                    classic.run_classic(case(), output, engine='mf2005', exe_name='/mock/pinned-engine')
            record = json.loads((output / 'run.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['error_type'], 'TimeoutError')
            self.assertIn('authored timeout', record['error'])
            self.assertIn('inventory', json.dumps(record).lower())
            self.assertTrue((output / 'native/settings.json').is_file())


class IndependentPhysicsMixin:
    engine = None
    executable = None

    def run_case(self, model):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = classic.run_classic(model, Path(temporary.name) / 'run', engine=self.engine,
                                     exe_name=self.executable, timeout_seconds=30)
        result = classic.read_classic_results(folder)
        self.assertTrue(result.summary['water_balance_passed'])
        self.assertTrue(result.summary['boundary_rates_passed'])
        self.assertTrue(result.summary['confined_saturation_support_passed'])
        self.assertFalse(result.summary['gms_parity_established'])
        self.assertFalse(result.summary['co2_or_oil_multiphase_physics'])
        self.assertEqual(result.case, model)
        self.assertEqual(result.summary['linear_solver'], 'pcg' if self.engine == 'mf2005' else 'xmd')
        return folder, result

    def test_independent_heterogeneous_series_resistance(self):
        model, expected, flow = series_case()
        _, result = self.run_case(model)
        np.testing.assert_allclose(result.heads_m, expected[None, ...], rtol=0, atol=2e-8)
        self.assertAlmostEqual(result.budget[0]['CONSTANT HEAD_IN'], flow, places=7)
        self.assertAlmostEqual(result.budget[0]['CONSTANT HEAD_OUT'], flow, places=7)

    def test_independent_ghb_recharge_and_extraction_balance(self):
        model, expected = combination_case()
        _, result = self.run_case(model)
        np.testing.assert_allclose(result.heads_m, np.full((1, 1, 1, 2), expected), rtol=0, atol=2e-7)
        budget = result.budget[0]
        self.assertAlmostEqual(budget['RECHARGE_IN'], 2. * .035 * 28., places=6)
        self.assertAlmostEqual(budget['WELLS_OUT'], 3.2, places=6)
        self.assertAlmostEqual(budget['HEAD DEP BOUNDS_IN'], 1.24, places=6)

    def test_independent_closed_storage_and_explicit_well_shutoff(self):
        model, expected = storage_case()
        _, result = self.run_case(model)
        np.testing.assert_allclose(result.times_day, [.25, .5, .75, 1., 1.25, 1.5], rtol=0, atol=1e-12)
        np.testing.assert_allclose(result.heads_m, expected, rtol=0, atol=2e-6)
        self.assertTrue(all(abs(row['WELLS_IN']) < 1e-10 for row in result.budget[-2:]))
        self.assertTrue(all(abs(row['STORAGE_IN']) + abs(row['STORAGE_OUT']) < 1e-8 for row in result.budget[-2:]))

    def test_independent_asymmetric_physical_row_mapping(self):
        model, expected = coordinate_case()
        _, result = self.run_case(model)
        np.testing.assert_allclose(result.heads_m, expected[None, ...], rtol=0, atol=2e-8)
        self.assertGreater(result.heads_m[0, 0, 0, 1], result.heads_m[0, 0, 1, 1])

    def test_actual_two_run_native_roundtrip_is_numerically_checked(self):
        model = combination_case()[0]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = classic.export_classic(model, root / 'source', engine=self.engine)
        before = snapshot(source)
        receipt = classic.verify_classic_roundtrip(source, root / 'roundtrip', exe_name=self.executable, timeout_seconds=30)
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(receipt['native_runs_requested'], 2)
        self.assertEqual(receipt['native_runs_completed'], 2)
        self.assertTrue(receipt['native_token_semantics_equal'])
        self.assertTrue(receipt['numerical_roundtrip_passed'])
        self.assertLessEqual(receipt['maximum_head_difference_m'], 1e-7)
        self.assertLessEqual(receipt['maximum_budget_column_difference'], 1e-7)
        self.assertTrue(all(all(gates.values()) for gates in receipt['run_validation_gates']))
        self.assertTrue(receipt['source_unchanged'])
        self.assertEqual(snapshot(source), before)
        self.assertFalse(receipt['gms_parity_established'])

    def test_fractional_constant_heads_survive_native_rewrite_without_float32_loss(self):
        west, east = 12.3456789123, 9.8765432199
        model = case('fractional_heads', ncol=3, initial=15., boundaries=[
            boundary('CHD', [0, 0, 0], head_m=west), boundary('CHD', [0, 0, 2], head_m=east)])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        method = 'gmres' if self.engine == 'mfnwt' else 'pcg'
        source = classic.export_classic(model, root / 'source', engine=self.engine, linear_solver=method)
        receipt = classic.verify_classic_roundtrip(source, root / 'roundtrip', exe_name=self.executable, timeout_seconds=30)
        self.assertTrue(receipt['native_token_semantics_equal'])
        self.assertTrue(receipt['numerical_roundtrip_passed'])
        expected = np.array([[[[west, (west + east) / 2., east]]]])
        for name in ('original-run', 'rewritten-run'):
            result = classic.read_classic_results(root / 'roundtrip' / name)
            np.testing.assert_allclose(result.heads_m, expected, rtol=0., atol=2e-9)
            self.assertTrue(result.summary['boundary_rates_passed'])
            self.assertEqual(result.summary['linear_solver'], method)
        self.assertFalse(receipt['gms_parity_established'])

    def test_actual_result_identity_and_artifact_tampering_are_rejected(self):
        folder, result = self.run_case(series_case()[0])
        record_path = folder / 'run.json'
        original = record_path.read_bytes()
        record = json.loads(original)
        record['solver']['sha256'] = '0' * 64
        record_path.write_text(json.dumps(record))
        with self.assertRaises(classic.ClassicError): classic.read_classic_results(folder)
        record_path.write_bytes(original)
        (folder / 'native/flow.hds').write_bytes((folder / 'native/flow.hds').read_bytes() + b'altered')
        with self.assertRaises(classic.ClassicError): classic.read_classic_results(folder)
        self.assertFalse(result.summary['gms_parity_established'])


@unittest.skipUnless(FLOPY and MF2005, 'Actual pinned MF2005_EXE and optional FloPy required')
class ActualModflow2005Tests(IndependentPhysicsMixin, unittest.TestCase):
    engine = 'mf2005'
    executable = MF2005


@unittest.skipUnless(FLOPY and MFNWT, 'Actual pinned MFNWT_EXE and optional FloPy required')
class ActualModflowNwtTests(IndependentPhysicsMixin, unittest.TestCase):
    engine = 'mfnwt'
    executable = MFNWT


if __name__ == '__main__':
    unittest.main()
