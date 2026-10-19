import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from basinlens_ccs.subsurface import project_package as package
from basinlens_ccs.subsurface.workspace_archive import create_workspace_zip


class WorkspaceArchiveTests(unittest.TestCase):
    def test_exact_nested_bytes_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir(); (root / "empty").mkdir()
            (root / "nested/values.bin").write_bytes(bytes(range(256)))
            (root / "metadata.json").write_text('{"units":"m"}\n')
            expected = {"nested/values.bin": bytes(range(256)), "metadata.json": b'{"units":"m"}\n'}
            with zipfile.ZipFile(io.BytesIO(create_workspace_zip(root))) as archive:
                self.assertEqual({name: archive.read(name) for name in archive.namelist()}, expected)
            self.assertEqual({name: (root / name).read_bytes() for name in expected}, expected)

    def test_symlinks_and_special_files_refused_without_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); target = root / "target"; target.write_bytes(b"x")
            link = root / "link"; link.symlink_to(target)
            with self.assertRaises(ValueError): create_workspace_zip(root)
            link.unlink()
            if hasattr(os, "mkfifo"):
                os.mkfifo(root / "pipe")
                with self.assertRaises(ValueError): create_workspace_zip(root)

    def test_byte_entry_and_depth_budgets_before_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "a").mkdir(); (root / "b").mkdir()
            with self.assertRaises(ValueError): create_workspace_zip(root, max_entries=1)
            large = root / "large"
            with large.open("wb") as stream: stream.truncate(1025)
            with patch.object(package, "_read_file", side_effect=AssertionError("must not read")):
                with self.assertRaises(ValueError): create_workspace_zip(root, max_bytes=1024)
            large.unlink()
            nested = root
            for _ in range(33): nested = nested / "d"; nested.mkdir()
            with self.assertRaises(ValueError): create_workspace_zip(root)

    def test_real_growth_during_bounded_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "data"; source.write_bytes(b"a" * 64)
            original = package.os.fdopen
            class GrowingReader:
                changed = False
                def __init__(self, stream): self.stream = stream
                def __enter__(self): self.stream.__enter__(); return self
                def __exit__(self, *args): return self.stream.__exit__(*args)
                def fileno(self): return self.stream.fileno()
                def read(self, size):
                    raw = self.stream.read(size)
                    if raw and not self.changed:
                        self.changed = True
                        with source.open("ab") as target: target.write(b"b" * 128)
                    return raw
            with patch.object(package.os, "fdopen", side_effect=lambda *a, **k: GrowingReader(original(*a, **k))):
                with self.assertRaisesRegex(ValueError, "size budget|changed"):
                    create_workspace_zip(root, max_bytes=128)
            self.assertEqual(source.stat().st_size, 192)

    def test_new_file_between_reads_and_final_inventory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "first").write_bytes(b"original")
            original = package._read_file
            def mutate(path, maximum):
                raw = original(path, maximum)
                (root / "later").write_bytes(b"new")
                return raw
            with patch.object(package, "_read_file", side_effect=mutate):
                with self.assertRaisesRegex(ValueError, "workspace changed"):
                    create_workspace_zip(root)

    def test_invalid_budgets_and_casefold_collisions_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in (True, 0, -1, 128 * 1024 * 1024 + 1):
                with self.assertRaises(ValueError): create_workspace_zip(root, max_bytes=value)
            (root / "A").write_bytes(b"1"); (root / "a").write_bytes(b"2")
            with self.assertRaises(ValueError): create_workspace_zip(root)


if __name__ == "__main__": unittest.main()
