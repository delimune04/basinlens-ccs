"""CLI relocation and failed-input recovery, using exact registered synthetic assets."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from basinlens_ccs.subsurface.__main__ import main

FIXTURE = Path(__file__).resolve().parents[1] / "examples/project_package"


class PackageCliTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([str(arg) for arg in args]), 0)
        return json.loads(output.getvalue())

    def test_explicit_asset_root_save_relocate_and_repack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "model.blproj"
            self.call("package-save", FIXTURE / "project.json", "--asset-root", FIXTURE / "assets",
                      "--view-state", FIXTURE / "view_state.json", "--output", package)
            opened = self.call("package-open", package, "--output", root / "relocated")
            self.assertEqual(opened["view_state"]["selected_layer"], 2)
            self.assertEqual((root / "relocated/assets/geology/layers.csv").read_bytes(),
                             (FIXTURE / "assets/geology/layers.csv").read_bytes())
            verified = self.call("package-roundtrip", package)
            self.assertTrue(verified["roundtrip_verified"])
            self.assertTrue(verified["archive_bytes_equal"])
            self.assertFalse(opened["engine_executed"])
            validated = self.call("validate", root / "relocated/project.json", "--asset-root",
                                  root / "relocated/assets")
            self.assertEqual(set(validated["assets_verified"]), {"synthetic-properties", "synthetic-head"})

    def test_duplicate_oversize_nonfinite_views_fail_without_output_then_recover(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            view, package = root / "view.json", root / "model.blproj"
            for raw in (b'{"selected_layer":0,"selected_layer":2}', b" " * 4097,
                        b'{"selected_layer":NaN}', b"\xff"):
                view.write_bytes(raw)
                with self.subTest(raw=raw[:40]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    main(["package-save", str(FIXTURE / "project.json"), "--asset-root", str(FIXTURE / "assets"),
                          "--view-state", str(view), "--output", str(package)])
                self.assertEqual(raised.exception.code, 2)
                self.assertFalse(package.exists())
            self.call("package-save", FIXTURE / "project.json", "--asset-root", FIXTURE / "assets",
                      "--output", package)
            self.assertTrue(package.is_file())
