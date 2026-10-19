"""Authored independent contract, geometry, transport and recovery checks."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.subsurface.geology import (
    GeologyProject, GeologyValidationError, MAX_FILE_BYTES, correlate_horizons,
    edit_interval_material, export_geology_csv, import_geology_csv, load_geology,
    project_section, save_geology, verify_geology_roundtrip,
)

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'geology'


def fixture():
    return json.loads((EXAMPLES / 'synthetic_boreholes.json').read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class GeologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = GeologyProject.from_dict(fixture())

    def tearDown(self):
        self.temp.cleanup()

    def export(self, name='bundle'):
        return export_geology_csv(self.project, self.root / name, asset_root=EXAMPLES)

    def rewrite_manifest(self, bundle, name):
        manifest = json.loads((bundle / 'manifest.json').read_text())
        payload = (bundle / name).read_bytes()
        manifest['files'][name] = {'sha256': hashlib.sha256(payload).hexdigest(), 'size_bytes': len(payload)}
        (bundle / 'manifest.json').write_text(json.dumps(manifest))

    def test_nonuniform_depth_and_explicit_gap_preserved(self):
        loaded = load_geology(EXAMPLES / 'synthetic_boreholes.json')
        value = loaded.project.to_dict()
        self.assertEqual(value['boreholes'][0]['intervals'][0]['bottom_depth_m'], 2.5)
        self.assertEqual(value['boreholes'][0]['intervals'][2]['kind'], 'gap')
        self.assertIsNone(value['boreholes'][0]['intervals'][2]['material_id'])
        self.assertEqual((value['crs'], value['vertical_datum']), ('unknown', 'unknown'))
        self.assertEqual(len(loaded.source_identity['files']), 2)

    def test_json_csv_json_roundtrip_exact_semantics_assets_and_source(self):
        before = sha(EXAMPLES / 'synthetic_boreholes.json')
        receipt = verify_geology_roundtrip(EXAMPLES / 'synthetic_boreholes.json', self.root / 'roundtrip')
        self.assertTrue(receipt['json_csv_json_semantics_equal'])
        self.assertTrue(receipt['all_registered_asset_bytes_equal'])
        self.assertEqual(sha(EXAMPLES / 'synthetic_boreholes.json'), before)
        copied = self.root / 'roundtrip/csv/assets/synthetic_notes.txt'
        self.assertEqual(copied.read_bytes(), (EXAMPLES / 'assets/synthetic_notes.txt').read_bytes())
        self.assertEqual(receipt['original_gms_comparison'], 'not performed')

    def test_csv_export_deterministic_and_relocatable(self):
        first, second = self.export('one'), self.export('two')
        expected = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob('*') if p.is_file()}
        actual = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob('*') if p.is_file()}
        self.assertEqual(expected, actual)
        relocated = self.root / 'relocated'
        first.rename(relocated)
        self.assertEqual(import_geology_csv(relocated).project.to_dict(), self.project.to_dict())

    def test_csv_unicode_quoting_and_numeric_looking_ids_are_literal(self):
        value = fixture()
        value['boreholes'][0]['id'] = '001'
        value['materials'][0]['description'] = '합성 모래, "quoted" description'
        value['materials'][0]['name'] = '모래'
        case = GeologyProject.from_dict(value)
        bundle = export_geology_csv(case, self.root / 'quoted', asset_root=EXAMPLES)
        self.assertEqual(import_geology_csv(bundle).project.to_dict(), case.to_dict())
        self.assertEqual(import_geology_csv(bundle).project.to_dict()['boreholes'][0]['id'], '001')

    def test_json_atomic_write_failure_cleanup_and_recovery(self):
        output = self.root / 'recover.json'
        with patch('basinlens_ccs.subsurface.geology.os.fsync', side_effect=OSError('authored disk failure')):
            with self.assertRaises(OSError): save_geology(self.project, output, asset_root=EXAMPLES)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        save_geology(self.project, output, asset_root=EXAMPLES)
        self.assertEqual(load_geology(output, asset_root=EXAMPLES).project.to_dict(), self.project.to_dict())

    def test_json_save_is_canonical_and_refuses_overwrite(self):
        first = save_geology(self.project, self.root / 'one.json', asset_root=EXAMPLES)
        second = save_geology(self.project, self.root / 'two.json', asset_root=EXAMPLES)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with self.assertRaises(FileExistsError):
            save_geology(self.project, first, asset_root=EXAMPLES)
        self.assertEqual(load_geology(first, asset_root=EXAMPLES).project.to_dict(), self.project.to_dict())

    def test_exact_horizon_contacts_no_interpolation(self):
        result = correlate_horizons(self.project)
        self.assertFalse(result['surfaces_inferred'])
        contacts = result['groups'][0]['contacts']
        self.assertEqual(len(contacts), 2)  # shared top/bottom contacts de-duplicated
        self.assertEqual([(c['borehole_id'], c['z_m']) for c in contacts], [('A', 97.5), ('B', 106.0)])
        self.assertEqual(result['correlation_rule'], 'exact declared horizon identifier only')
        self.assertEqual([r['interval_id'] for r in contacts[0]['references']], ['a1', 'a2'])
        self.assertEqual(len(result['source_project_sha256']), 64)

    def test_polyline_projection_hand_computed_chainage_offsets_and_cutoff(self):
        result = project_section(self.project, [[0, 0], [10, 0], [10, 10]], max_distance_m=4)
        holes = {h['borehole_id']: h for h in result['boreholes']}
        self.assertEqual((holes['A']['chainage_m'], holes['A']['distance_m'], holes['A']['signed_offset_m']), (3, 4, 4))
        self.assertEqual((holes['B']['chainage_m'], holes['B']['distance_m'], holes['B']['signed_offset_m']), (18, 2, -2))
        self.assertEqual((holes['C']['chainage_m'], holes['C']['distance_m'], holes['C']['signed_offset_m']), (0, 3, 0))
        self.assertEqual(holes['D']['segment_index'], 0)  # corner exact tie: first segment
        self.assertEqual(holes['A']['intervals'][1]['bottom_z_m'], 94)
        self.assertFalse(result['geological_interpolation'])
        narrow = project_section(self.project, [[0, 0], [10, 0], [10, 10]], max_distance_m=2)
        self.assertEqual({h['borehole_id'] for h in narrow['boreholes']}, {'B', 'D'})
        self.assertEqual({h['borehole_id'] for h in narrow['excluded']}, {'A', 'C'})

    def test_oblique_section_projection_independent_right_triangle(self):
        # A=(3,4), segment=(0,0)->(6,8): dot projection 5m along a 10m line.
        result = project_section(self.project, [[0, 0], [6, 8]], max_distance_m=0)
        self.assertEqual(len(result['boreholes']), 1)
        self.assertEqual(result['boreholes'][0]['chainage_m'], 5)
        self.assertEqual(result['boreholes'][0]['distance_m'], 0)

    def test_material_edit_preserves_original_and_replays_history(self):
        before = self.project.to_dict()
        first = edit_interval_material(self.project, 'A', 'a2', 'clay', reason='Test interpretation revision', provenance_id='authored')
        edited = edit_interval_material(first, 'A', 'a2', 'sand', reason='Revert interpretation', provenance_id='authored')
        self.assertEqual(self.project.to_dict(), before)
        self.assertEqual(len(edited.to_dict()['history']), 2)
        self.assertEqual(edited.to_dict()['boreholes'], before['boreholes'])
        out = save_geology(edited, self.root / 'edited.json', asset_root=EXAMPLES)
        self.assertEqual(load_geology(out, asset_root=EXAMPLES).project.to_dict(), edited.to_dict())

    def test_history_corruption_and_invalid_edit_refused(self):
        edited = edit_interval_material(self.project, 'A', 'a2', 'clay', reason='Revision', provenance_id='authored').to_dict()
        for field, replacement in [('reason', 'Changed reason'), ('old_material_id', 'clay'), ('source_project_sha256', '0' * 64)]:
            with self.subTest(field=field):
                broken = copy.deepcopy(edited)
                broken['history'][0][field] = replacement
                # A human reason is intentionally not signed; changing it creates a
                # new project identity, while material/source hashes must replay.
                if field == 'reason':
                    self.assertNotEqual(GeologyProject.from_dict(broken)._json, self.project._json)
                else:
                    with self.assertRaises(GeologyValidationError):
                        GeologyProject.from_dict(broken)
        for hole, interval, material in [('A', 'a-gap', 'sand'), ('A', 'a2', 'sand'), ('A', 'missing', 'clay'), ('A', 'a2', 'unknown')]:
            with self.subTest(interval=interval, material=material), self.assertRaises(GeologyValidationError):
                edit_interval_material(self.project, hole, interval, material, reason='Revision', provenance_id='authored')

    def test_overlap_missing_gap_unsorted_and_below_total_refused(self):
        for change in ('overlap', 'unrecorded_gap', 'unsorted', 'short_total', 'missing_remainder'):
            value = fixture()
            rows = value['boreholes'][0]['intervals']
            if change == 'overlap': rows[1]['top_depth_m'] = 2
            elif change == 'unrecorded_gap': del rows[2]
            elif change == 'unsorted': rows[0], rows[1] = rows[1], rows[0]
            elif change == 'short_total': value['boreholes'][0]['total_depth_m'] = 11
            elif change == 'missing_remainder': rows.pop()
            with self.subTest(change=change), self.assertRaises(GeologyValidationError):
                GeologyProject.from_dict(value)
        with self.assertRaises(GeologyValidationError):
            load_geology(EXAMPLES / 'invalid_overlap.json')

    def test_units_unknown_fields_nonfinite_bool_and_depth_contract_refused(self):
        for key, replacement in [('length_unit', 'ft'), ('schema', 'foreign'), ('depth_reference', 'measured_depth'), ('crs', 'EPSG:4326'), ('crs', 'epsg:4326')]:
            value = fixture(); value[key] = replacement
            with self.subTest(key=key), self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)
        for replacement in (float('nan'), float('inf'), True, '10', 10 ** 400):
            value = fixture(); value['boreholes'][0]['x_m'] = replacement
            with self.subTest(number=str(replacement)), self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)
        value = fixture(); value['deviated_path'] = []
        with self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)

    def test_duplicate_ids_unknown_refs_and_false_observation_refused(self):
        for change in ('hole', 'interval', 'material', 'horizon', 'provenance', 'source', 'gap', 'observed'):
            value = fixture()
            if change == 'hole': value['boreholes'][1]['id'] = 'A'
            elif change == 'interval': value['boreholes'][0]['intervals'][1]['id'] = 'a1'
            elif change == 'material': value['boreholes'][0]['intervals'][0]['material_id'] = 'unknown'
            elif change == 'horizon': value['boreholes'][0]['intervals'][0]['bottom_horizon_id'] = 'unknown'
            elif change == 'provenance': value['boreholes'][0]['provenance_id'] = 'unknown'
            elif change == 'source': value['provenance'][0]['source_asset_ids'] = [{}]
            elif change == 'gap': value['boreholes'][0]['intervals'][2]['material_id'] = 'sand'
            elif change == 'observed': value['provenance'][0].update(basis='observed', source_asset_ids=[])
            with self.subTest(change=change), self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)

    def test_repeated_or_disagreeing_horizon_refused(self):
        value = fixture(); value['boreholes'][0]['intervals'][3]['bottom_horizon_id'] = 'H1'
        with self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)
        value = fixture(); value['horizons'].append({'id': 'H2', 'name': 'Other', 'provenance_id': 'authored'})
        value['boreholes'][0]['intervals'][1]['top_horizon_id'] = 'H2'
        with self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)

    def test_duplicate_json_keys_nonfinite_and_corrupt_encoding_refused(self):
        for index, payload in enumerate((b'{"schema":1,"schema":2}', b'{"a":NaN}', b'\xff', b'{broken')):
            path = self.root / f'bad-{index}.json'; path.write_bytes(payload)
            with self.subTest(index=index), self.assertRaises(GeologyValidationError): load_geology(path)

    def test_file_and_direct_json_budgets_refused(self):
        path = self.root / 'large.json'
        with path.open('wb') as stream: stream.truncate(MAX_FILE_BYTES + 1)
        with self.assertRaises(GeologyValidationError): load_geology(path)
        with self.assertRaises(GeologyValidationError): GeologyProject(' ' * (MAX_FILE_BYTES + 1)).to_dict()
        value = fixture(); value['boreholes'] *= 201
        with self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)
        value = fixture(); value['name'] = []; value['name'].append(value)
        with self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)

    def test_assets_mismatch_missing_and_unsafe_paths_refused(self):
        value = fixture(); value['assets'][0]['sha256'] = '0' * 64
        with self.assertRaises(GeologyValidationError): save_geology(GeologyProject.from_dict(value), self.root / 'bad.json', asset_root=EXAMPLES)
        with self.assertRaises(GeologyValidationError): save_geology(self.project, self.root / 'bad.json', asset_root=self.root)
        for name in ('../notes.txt', 'assets/../notes', 'assets/CON', 'assets/a\\b', 'assets/a:b', 'assets/a\x7fb', 'assets/e\u0301.txt'):
            value = fixture(); value['assets'][0]['relative_path'] = name
            with self.subTest(name=name), self.assertRaises(GeologyValidationError): GeologyProject.from_dict(value)
        self.assertFalse((self.root / 'bad.json').exists())

    def test_symlink_source_asset_destination_and_fifo_refused(self):
        link = self.root / 'source.json'; link.symlink_to(EXAMPLES / 'synthetic_boreholes.json')
        with self.assertRaises(GeologyValidationError): load_geology(link)
        directory = self.root / 'linked'; directory.symlink_to(EXAMPLES, target_is_directory=True)
        with self.assertRaises(GeologyValidationError): save_geology(self.project, directory / 'new.json', asset_root=EXAMPLES)
        asset_root = self.root / 'asset-root'; (asset_root / 'assets').mkdir(parents=True)
        (asset_root / 'assets/synthetic_notes.txt').symlink_to(EXAMPLES / 'assets/synthetic_notes.txt')
        with self.assertRaises(GeologyValidationError): save_geology(self.project, self.root / 'bad.json', asset_root=asset_root)
        if hasattr(os, 'mkfifo'):
            fifo = self.root / 'input.fifo'; os.mkfifo(fifo)
            with self.assertRaises(GeologyValidationError): load_geology(fifo)

    def test_csv_corrupt_and_unregistered_payload_refused(self):
        first = self.export('corrupt'); (first / 'intervals.csv').write_bytes(b'corrupt')
        with self.assertRaises(GeologyValidationError): import_geology_csv(first)
        second = self.export('extra'); (second / 'extra.txt').write_bytes(b'not registered')
        with self.assertRaises(GeologyValidationError): import_geology_csv(second)
        third = self.export('missing'); (third / 'horizons.csv').unlink()
        with self.assertRaises(GeologyValidationError): import_geology_csv(third)

    def test_csv_header_foreign_hole_and_semantic_corruption_refused(self):
        for change in ('header', 'foreign-hole', 'semantic', 'extra-column'):
            bundle = self.export(change)
            path = bundle / 'intervals.csv'
            text = path.read_text()
            if change == 'header': text = text.replace('borehole_id,id,', 'id,borehole_id,', 1)
            elif change == 'foreign-hole': text = text.replace('A,a1,', 'unknown,a1,', 1)
            elif change == 'semantic': text = text.replace(',2.5,logged,clay,', ',2.5,logged,sand,', 1)
            elif change == 'extra-column': text = text.replace('A,a1,', 'A,extra,a1,', 1)
            path.write_text(text); self.rewrite_manifest(bundle, 'intervals.csv')
            with self.subTest(change=change), self.assertRaises(GeologyValidationError): import_geology_csv(bundle)

    def test_csv_symlink_member_and_directory_refused(self):
        bundle = self.export()
        target = bundle / 'materials.csv'; payload = target.read_bytes(); target.unlink()
        external = self.root / 'external.csv'; external.write_bytes(payload); target.symlink_to(external)
        with self.assertRaises(GeologyValidationError): import_geology_csv(bundle)
        link = self.root / 'bundle-link'; link.symlink_to(bundle, target_is_directory=True)
        with self.assertRaises(GeologyValidationError): import_geology_csv(link)

    def test_atomic_export_failure_cleanup_then_recovery(self):
        output = self.root / 'recover'
        with patch('basinlens_ccs.subsurface.geology.os.rename', side_effect=OSError('authored interruption')):
            with self.assertRaises(OSError): export_geology_csv(self.project, output, asset_root=EXAMPLES)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        export_geology_csv(self.project, output, asset_root=EXAMPLES)
        self.assertEqual(import_geology_csv(output).project.to_dict(), self.project.to_dict())
        with self.assertRaises(FileExistsError): export_geology_csv(self.project, output, asset_root=EXAMPLES)

    def test_atomic_roundtrip_failure_cleanup_then_recovery(self):
        output = self.root / 'roundtrip'
        with patch('basinlens_ccs.subsurface.geology.import_geology_csv', side_effect=GeologyValidationError('authored failure')):
            with self.assertRaises(GeologyValidationError): verify_geology_roundtrip(EXAMPLES / 'synthetic_boreholes.json', output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(verify_geology_roundtrip(EXAMPLES / 'synthetic_boreholes.json', output)['source_unchanged'])

    def test_invalid_section_explicit_distance_and_vertices_refused(self):
        for points, distance in [([[0, 0], [0, 0]], 1), ([[0, 0]], 1), ([[0, 0], [1, 1]], -1),
                                 ([[0, 0], [True, 1]], 1), ([[0, 0], [1, 1]], float('inf'))]:
            with self.subTest(points=points, distance=distance), self.assertRaises(GeologyValidationError):
                project_section(self.project, points, max_distance_m=distance)

    def test_cli_check_roundtrip_sections_contacts_import_and_invalid_recovery(self):
        base = [sys.executable, '-m', 'basinlens_ccs.subsurface.geology']
        source = EXAMPLES / 'synthetic_boreholes.json'
        def run(*arguments, expected=0):
            result = subprocess.run([*base, *map(str, arguments)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, expected, result.stderr)
            return json.loads(result.stdout) if expected == 0 else result.stderr
        self.assertTrue(run('check', source)['valid'])
        run('check', EXAMPLES / 'invalid_overlap.json', expected=2)
        self.assertTrue(run('roundtrip', source, '--output', self.root / 'cli-roundtrip')['source_unchanged'])
        section = run('section', source, '--polyline-json', EXAMPLES / 'section.json', '--max-distance-m', 2, '--output', self.root / 'section.json')
        self.assertEqual(len(section['boreholes']), 2)
        self.assertEqual(len(run('contacts', source, '--output', self.root / 'contacts.json')['groups']), 1)
        run('export-csv', source, '--output', self.root / 'csv')
        run('import-csv', self.root / 'csv', '--output', self.root / 'imported.json')
        self.assertTrue(run('check', self.root / 'imported.json', '--asset-root', self.root / 'csv')['valid'])
        edit = run('edit-material', source, '--borehole-id', 'A', '--interval-id', 'a2', '--material-id', 'clay', '--reason', 'Synthetic revision', '--provenance-id', 'authored', '--output', self.root / 'edit.json')
        self.assertEqual(edit['history_entries'], 1)


if __name__ == '__main__':
    unittest.main()
