"""Portable project round trips and hostile or interrupted I/O regression cases."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from basinlens_ccs.subsurface import load_project, ProjectValidationError, SubsurfaceProject, DataAsset
from basinlens_ccs.subsurface import project_package as package

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/project_package'


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


class ProjectPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'source-assets'
        shutil.copytree(EXAMPLE / 'assets', self.assets)
        self.project = load_project(EXAMPLE / 'project.json', check_assets=False)
        self.view = json.loads((EXAMPLE / 'view_state.json').read_text())
        self.archive = self.root / 'source.blproj'
        package.save_project_package(self.project, self.archive, asset_root=self.assets, view_state=self.view)

    def members(self):
        with zipfile.ZipFile(self.archive) as archive:
            return {info.filename: archive.read(info) for info in archive.infolist()}

    def rewritten(self, members, name='altered.blproj'):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for key, value in members.items():
                archive.writestr(key, value)
        return path

    def reject(self, source):
        output = self.root / 'rejected'
        with self.assertRaises(ProjectValidationError):
            package.open_project_package(source, output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.rejected.partial-*')))

    def test_relocation_preserves_all_project_semantics_and_asset_bytes(self):
        expected = {asset.relative_path: (self.assets / asset.relative_path).read_bytes() for asset in self.project.assets}
        shutil.rmtree(self.assets)
        loaded = package.open_project_package(self.archive, self.root / 'relocated')
        self.assertEqual(loaded.project.to_dict(), self.project.to_dict())
        self.assertEqual(loaded.view_state, self.view)
        self.assertEqual(loaded.receipt['assets_verified'], {a.asset_id: a.sha256 for a in self.project.assets})
        self.assertEqual(loaded.receipt['original_gms_comparison'], 'not_performed')
        self.assertEqual(loaded.receipt['source_archive_sha256_before'], loaded.receipt['source_archive_sha256_after'])
        for path, data in expected.items():
            self.assertEqual((loaded.asset_root / path).read_bytes(), data)
        # Explicit checks cover the metadata easily lost by geometry-only serializers.
        self.assertEqual(loaded.project.spatial_reference, self.project.spatial_reference)
        self.assertEqual(loaded.project.stratigraphy, self.project.stratigraphy)
        self.assertEqual(loaded.project.observations, self.project.observations)
        self.assertEqual(loaded.project.wells, self.project.wells)
        self.assertEqual(loaded.project.model.options, self.project.model.options)

    def test_roundtrip_really_reopens_repackages_and_compares(self):
        with patch.object(package, 'open_project_package', wraps=package.open_project_package) as opened, patch.object(package, 'save_project_package', wraps=package.save_project_package) as saved:
            receipt = package.verify_project_roundtrip(self.archive)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(saved.call_count, 1)
        self.assertTrue(receipt['roundtrip_verified'])
        self.assertTrue(receipt['asset_bytes_equal'])
        self.assertTrue(receipt['project_semantics_equal'])
        self.assertTrue(receipt['view_state_equal'])
        self.assertTrue(receipt['archive_bytes_equal'])
        self.assertEqual(set(receipt['assets']), {a.asset_id for a in self.project.assets})

    def test_saved_packages_are_deterministic_and_default_view_is_explicit(self):
        other = self.root / 'other.blproj'
        package.save_project_package(self.project, other, asset_root=self.assets, view_state=self.view)
        self.assertEqual(other.read_bytes(), self.archive.read_bytes())
        empty = replace(self.project, assets=(), observations=(), stratigraphy=(),
                        rock_properties=tuple(replace(p, source_asset_ids=()) for p in self.project.rock_properties))
        path = package.save_project_package(empty, self.root / 'empty.blproj')
        loaded = package.open_project_package(path, self.root / 'empty')
        self.assertTrue(loaded.asset_root.is_dir())
        self.assertEqual(loaded.receipt['asset_count'], 0)
        self.assertEqual(loaded.view_state, dict(selected_layer=0, selected_field='head', chart_mode='2d', show_wells=True))
        self.assertTrue(package.verify_project_roundtrip(path)['roundtrip_verified'])

    def test_multiple_registered_assets_can_share_exactly_one_payload(self):
        second = replace(self.project.assets[0], asset_id='second-declared-role')
        project = replace(self.project, assets=(*self.project.assets, second))
        path = package.save_project_package(project, self.root / 'shared.blproj', asset_root=self.assets)
        loaded = package.open_project_package(path, self.root / 'shared')
        self.assertEqual(loaded.receipt['asset_count'], 3)
        self.assertEqual(loaded.receipt['unique_asset_file_count'], 2)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(len(archive.namelist()), 5)

    def test_missing_tampered_and_unknown_members_are_refused(self):
        for index, change in enumerate(('missing', 'tampered', 'unknown')):
            with self.subTest(change=change):
                members = self.members()
                asset = 'assets/' + self.project.assets[0].relative_path
                if change == 'missing':
                    del members[asset]
                elif change == 'tampered':
                    members[asset] += b'changed'
                else:
                    members['unregistered.bin'] = b'unregistered'
                self.reject(self.rewritten(members, f'inventory-{index}.blproj'))

    def test_rehashed_tamper_cannot_disagree_with_registered_asset(self):
        members = self.members()
        asset = 'assets/' + self.project.assets[0].relative_path
        members[asset] = b'replacement'
        manifest = json.loads(members['manifest.json'])
        manifest['files'][asset] = dict(sha256=hashlib.sha256(members[asset]).hexdigest(), size_bytes=len(members[asset]))
        members['manifest.json'] = canonical(manifest)
        self.reject(self.rewritten(members))

    def test_unknown_or_boolean_versions_and_forged_semantic_bindings_refused(self):
        for index, (key, value) in enumerate((('bundle_version', 2), ('bundle_version', True), ('project_schema_version', True), ('semantic_sha256', '0' * 64), ('format', 'gms-project'))):
            with self.subTest(key=key, value=value):
                members = self.members()
                manifest = json.loads(members['manifest.json'])
                manifest[key] = value
                members['manifest.json'] = canonical(manifest)
                self.reject(self.rewritten(members, f'version-{index}.blproj'))

    def test_forged_inventory_cannot_add_unregistered_payloads(self):
        members = self.members()
        members['assets/unknown.bin'] = b'unknown'
        manifest = json.loads(members['manifest.json'])
        manifest['files']['assets/unknown.bin'] = dict(sha256=hashlib.sha256(b'unknown').hexdigest(), size_bytes=7)
        members['manifest.json'] = canonical(manifest)
        self.reject(self.rewritten(members))

    def test_duplicate_json_keys_and_noncanonical_json_refused(self):
        for index, payload in enumerate((b'{"format":"a","format":"b"}\n', b'{"number":NaN}\n', json.dumps(json.loads(self.members()['manifest.json']), indent=2).encode())):
            with self.subTest(index=index):
                members = self.members()
                members['manifest.json'] = payload
                self.reject(self.rewritten(members, f'json-{index}.blproj'))

    def test_complete_rebinding_still_revalidates_typed_asset_references(self):
        members = self.members()
        project = json.loads(members['project.json'])
        project['observations'][0]['source_asset_ids'] = ['not-registered']
        members['project.json'] = canonical(project)
        manifest = json.loads(members['manifest.json'])
        manifest['files']['project.json'] = dict(sha256=hashlib.sha256(members['project.json']).hexdigest(), size_bytes=len(members['project.json']))
        manifest['project_sha256'] = manifest['files']['project.json']['sha256']
        members['manifest.json'] = canonical(manifest)
        self.reject(self.rewritten(members))

    def test_restored_metadata_corruption_blocks_directory_publication(self):
        real_check = package._verify_staged_payloads
        def corrupt_then_check(root, payloads):
            (root / 'project.json').write_bytes(b'corrupted after write')
            return real_check(root, payloads)
        with patch.object(package, '_verify_staged_payloads', side_effect=corrupt_then_check):
            self.reject(self.archive)

    def test_view_state_has_only_bounded_inert_supported_fields(self):
        for index, view in enumerate(({'run_solver': True}, {'selected_layer': True}, {'selected_layer': 3}, {'selected_field': 'unknown'}, {'chart_mode': 'exec'}, {'show_wells': 1}, {'selected_field': []})):
            with self.subTest(view=view), self.assertRaises(ProjectValidationError):
                package.save_project_package(self.project, self.root / f'view-{index}.blproj', asset_root=self.assets, view_state=view)
        self.assertFalse(list(self.root.glob('view-*.blproj')))

    def test_direct_mutable_options_are_revalidated_before_save(self):
        for index, options in enumerate(({1: 'numeric-key'}, {'bad': float('inf')}, {'deep': [[[[object()]]]]})):
            self.project.model.options.clear()
            self.project.model.options.update(options)
            with self.subTest(index=index), self.assertRaises(ProjectValidationError):
                package.save_project_package(self.project, self.root / f'invalid-{index}.blproj', asset_root=self.assets)

    def test_unsafe_nonportable_and_colliding_archive_paths_refused(self):
        cases = [('../escape',), ('/absolute',), ('C:/drive',), ('assets\\escape',), ('assets/./a',),
                 ('assets/NUL.txt',), ('assets/trailing.',), ('assets/trailing ',), ('assets/e\u0301.txt',),
                 ('assets/A.txt', 'assets/a.txt'), ('assets/A/x', 'assets/a/y'), ('assets/a', 'assets/a/nested')]
        for index, names in enumerate(cases):
            with self.subTest(names=names):
                self.reject(self.rewritten({name: b'x' for name in names}, f'path-{index}.blproj'))
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_duplicate_zip_members_are_refused(self):
        path = self.root / 'duplicate.blproj'
        with warnings.catch_warnings(), zipfile.ZipFile(path, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)
            archive.writestr('project.json', b'one')
            archive.writestr('project.json', b'two')
        self.reject(path)

    def test_zip_symlinks_directories_and_unsupported_compression_refused(self):
        for index, (name, mode, compression) in enumerate((('assets/link', stat.S_IFLNK | 0o777, zipfile.ZIP_STORED), ('assets/directory/', stat.S_IFDIR | 0o755, zipfile.ZIP_STORED), ('assets/bzip', stat.S_IFREG | 0o644, zipfile.ZIP_BZIP2))):
            path = self.root / f'kind-{index}.blproj'
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(info, b'payload')
            self.reject(path)

    def test_zip_encryption_flag_and_prefix_trailing_data_are_refused(self):
        payload = bytearray(self.archive.read_bytes())
        central = payload.find(b'PK\x01\x02')
        payload[6] |= 1
        payload[central + 8] |= 1
        for index, raw in enumerate((bytes(payload), b'prefix' + self.archive.read_bytes(), self.archive.read_bytes() + b'trailing')):
            path = self.root / f'container-{index}.blproj'
            path.write_bytes(raw)
            self.reject(path)

    def test_corrupt_deflate_is_reported_as_validation_error(self):
        payload = bytearray(self.archive.read_bytes())
        with zipfile.ZipFile(self.archive) as archive:
            info = archive.infolist()[0]
        length, extra = struct.unpack_from('<HH', payload, info.header_offset + 26)
        start = info.header_offset + 30 + length + extra
        payload[start] = 0xff  # reserved DEFLATE block type, rejected by zlib.
        path = self.root / 'corrupt-deflate.blproj'
        path.write_bytes(payload)
        self.reject(path)

    def test_ingress_budgets_are_enforced_before_extracting(self):
        for setting, bound in (('MAX_ARCHIVE_BYTES', 10), ('MAX_TOTAL_BYTES', 10), ('MAX_ASSET_BYTES', 10), ('MAX_MEMBERS', 1), ('MAX_PROJECT_BYTES', 10), ('MAX_MANIFEST_BYTES', 10), ('MAX_VIEW_BYTES', 10)):
            with self.subTest(setting=setting), patch.object(package, setting, bound):
                self.reject(self.archive)

    def test_asset_missing_mismatch_duplicate_path_conflict_and_no_root_refused(self):
        for index, assets in enumerate((None, self.root / 'absent')):
            with self.subTest(index=index), self.assertRaises(ProjectValidationError):
                package.save_project_package(self.project, self.root / f'missing-{index}.blproj', asset_root=assets)
        (self.assets / self.project.assets[0].relative_path).write_bytes(b'changed')
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(self.project, self.root / 'changed.blproj', asset_root=self.assets)
        conflict = replace(self.project.assets[0], asset_id='conflicting', sha256='0' * 64)
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(replace(self.project, assets=(*self.project.assets, conflict)), self.root / 'conflict.blproj', asset_root=self.assets)

    def test_nonportable_registered_asset_paths_refused_without_read(self):
        asset = DataAsset('new', 'CON.csv', '0' * 64, 'text/csv', 'CC0-1.0', 'synthetic')
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(replace(self.project, assets=(*self.project.assets, asset)), self.root / 'nonportable.blproj', asset_root=self.assets)

    def test_symlink_sources_parents_and_assets_refused(self):
        link = self.root / 'link.blproj'
        link.symlink_to(self.archive)
        self.reject(link)
        parent_link = self.root / 'assets-link'
        parent_link.symlink_to(self.assets, target_is_directory=True)
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(self.project, self.root / 'link-assets.blproj', asset_root=parent_link)
        original = self.assets / self.project.assets[0].relative_path
        saved = self.root / 'original.csv'
        original.rename(saved)
        original.symlink_to(saved)
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(self.project, self.root / 'asset-link.blproj', asset_root=self.assets)

    def test_fifo_archive_and_asset_refused_without_blocking(self):
        if not hasattr(os, 'mkfifo'):
            return  # FIFO creation is unavailable on Windows; no FIFO can be supplied there.
        fifo = self.root / 'pipe.blproj'
        os.mkfifo(fifo)
        asset = self.assets / self.project.assets[0].relative_path
        asset.unlink()
        os.mkfifo(asset)
        script = """
from pathlib import Path
from basinlens_ccs.subsurface import load_project, ProjectValidationError
from basinlens_ccs.subsurface.project_package import open_project_package, save_project_package
import sys
root, fixture = map(Path, sys.argv[1:])
project = load_project(fixture, check_assets=False)
for call in (lambda: open_project_package(root/'pipe.blproj', root/'pipe-open'),
             lambda: save_project_package(project, root/'pipe-save.blproj', asset_root=root/'source-assets')):
    try:
        call()
    except ProjectValidationError:
        continue
    raise AssertionError('FIFO was accepted')
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(EXAMPLE / 'project.json')],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'pipe-open').exists())
        self.assertFalse((self.root / 'pipe-save.blproj').exists())

    def test_alias_registrations_hash_each_restored_payload_once(self):
        aliases = tuple(replace(self.project.assets[0], asset_id=f'alias-{index}') for index in range(100))
        project = replace(self.project, assets=(*self.project.assets, *aliases))
        path = package.save_project_package(project, self.root / 'aliases.blproj', asset_root=self.assets)
        real_read = package._read_file
        with patch.object(package, '_read_file', wraps=real_read) as reader:
            loaded = package.open_project_package(path, self.root / 'aliases')
        self.assertEqual(loaded.receipt['asset_count'], 102)
        # Exactly two source reads and five unique staged members, independent of alias count.
        self.assertEqual(reader.call_count, 7)

    def test_existing_destinations_refused_without_overwriting(self):
        before = self.archive.read_bytes()
        with self.assertRaises(FileExistsError):
            package.save_project_package(self.project, self.archive, asset_root=self.assets)
        self.assertEqual(before, self.archive.read_bytes())
        directory = self.root / 'exists'
        directory.mkdir()
        (directory / 'keep').write_text('untouched')
        with self.assertRaises(FileExistsError):
            package.open_project_package(self.archive, directory)
        self.assertEqual((directory / 'keep').read_text(), 'untouched')

    def test_interrupted_save_cleans_staging_and_can_resume(self):
        target = self.root / 'recover.blproj'
        with patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('simulated full disk')):
            with self.assertRaises(OSError):
                package.save_project_package(self.project, target, asset_root=self.assets)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.recover.blproj.partial-*')))
        package.save_project_package(self.project, target, asset_root=self.assets)
        self.assertTrue(package.verify_project_roundtrip(target)['roundtrip_verified'])

    def test_failed_open_promotion_cleans_staging_and_can_resume(self):
        target = self.root / 'recover-open'
        with patch.object(package, '_promote_directory', side_effect=OSError('simulated rename failure')):
            with self.assertRaises(OSError):
                package.open_project_package(self.archive, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.recover-open.partial-*')))
        self.assertTrue(package.open_project_package(self.archive, target).receipt['inventory_verified'])

    def test_asset_change_during_save_blocks_publication(self):
        target = self.root / 'changing.blproj'
        real_write = zipfile.ZipFile.writestr
        changed = False
        def write_and_change(archive, *args, **kwargs):
            nonlocal changed
            result = real_write(archive, *args, **kwargs)
            if not changed:
                changed = True
                (self.assets / self.project.assets[0].relative_path).write_bytes(b'changed during write')
            return result
        with patch.object(zipfile.ZipFile, 'writestr', new=write_and_change):
            with self.assertRaises(ProjectValidationError):
                package.save_project_package(self.project, target, asset_root=self.assets)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.changing.blproj.partial-*')))

    def test_source_change_during_open_blocks_publication(self):
        real_verify = package._verify_restored_assets
        def verify_and_change(*args, **kwargs):
            result = real_verify(*args, **kwargs)
            self.archive.write_bytes(self.archive.read_bytes() + b'changed during open')
            return result
        with patch.object(package, '_verify_restored_assets', side_effect=verify_and_change):
            self.reject(self.archive)

    def test_wrong_extensions_unrelated_archives_and_nonregular_sources_refused(self):
        wrong = self.root / 'source.gpr'
        wrong.write_bytes(self.archive.read_bytes())
        self.reject(wrong)
        self.reject(self.rewritten({'unrelated.json': b'{}'}))
        with self.assertRaises(ProjectValidationError):
            package.save_project_package(self.project, self.root / 'wrong.zip', asset_root=self.assets)
        directory = self.root / 'directory.blproj'
        directory.mkdir()
        self.reject(directory)


if __name__ == '__main__':
    unittest.main()
