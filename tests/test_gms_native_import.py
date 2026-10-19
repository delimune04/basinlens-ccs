"""Independent native MF6 inputs; no vendor samples or implementation included."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.groundwater.gms_native import (
    NativeImportError, discover_simulations, import_native_simulation, load_with_flopy,
)


def native_graph(folder):
    (folder / "models").mkdir(parents=True)
    (folder / "arrays").mkdir()
    (folder / "mfsim.nam").write_text(
        'BEGIN TIMING\n TDIS6 time.tdis\nEND TIMING\n'
        'BEGIN MODELS\n GWF6 "models/flow model.nam" aquifer\nEND MODELS\n'
        'BEGIN EXCHANGES\nEND EXCHANGES\n'
        'BEGIN SOLUTIONGROUP 1\n IMS6 solve.ims aquifer\nEND SOLUTIONGROUP 1\n'
    )
    (folder / "time.tdis").write_text("BEGIN PERIODDATA\n 10 2 1.0\nEND PERIODDATA\n")
    (folder / "solve.ims").write_text("BEGIN OPTIONS\n COMPLEXITY SIMPLE\nEND OPTIONS\n")
    (folder / "models" / "flow model.nam").write_text(
        'BEGIN PACKAGES\n DIS6 models/grid.dis\n NPF6 "models/conductivity.npf"\nEND PACKAGES\n'
    )
    (folder / "models" / "grid.dis").write_text("BEGIN DIMENSIONS\n NLAY 1\n NROW 1\n NCOL 3\nEND DIMENSIONS\n")
    (folder / "models" / "conductivity.npf").write_text(
        'BEGIN GRIDDATA\n K\n OPEN/CLOSE "arrays/k values.txt" FACTOR 1\nEND GRIDDATA\n'
    )
    (folder / "arrays" / "k values.txt").write_text("2 3 4\n")


class NativeFolderImportTests(unittest.TestCase):
    def test_quoted_paths_use_simulation_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            report = import_native_simulation(root)
            self.assertTrue(report["native_inputs_resolved"], report["issues"])
            self.assertFalse(report["engine_executed"])
            self.assertEqual(len(report["files"]), 7)
            self.assertEqual(report["models"][0]["name"], "aquifer")
            self.assertIn("arrays/k values.txt", {item["path"] for item in report["files"]})

    def test_preserves_unknown_json_and_period_rows_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            options = {"USE_OPEN_CLOSE": True, "CUSTOM_PROPERTY": {"value": 7}}
            (root / "gms_options.json").write_text(json.dumps(options))
            (root / "models" / "settings.json").write_text('{"selected_layer": 2}')
            database = root / "models" / "periods.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE data (LAY INTEGER, ROW INTEGER, COL INTEGER, Q REAL, "
                                   "CELLIDX INTEGER, PERIOD INTEGER, PERIOD_ROW INTEGER, id INTEGER PRIMARY KEY)")
                connection.executemany("INSERT INTO data VALUES (?,?,?,?,?,?,?,?)", [
                    (1, 1, 2, -9.0, 1, 2, 0, 2), (1, 1, 2, -3.0, 1, 1, 0, 1)])
            before = database.read_bytes()
            before_names = {path.name for path in database.parent.iterdir()}
            report = import_native_simulation(root, database_row_limit=1)
            self.assertTrue(report["native_inputs_resolved"], report["issues"])
            sidecars = {item["kind"]: item for item in report["sidecars"]}
            self.assertEqual(sidecars["gms_options.json"]["data"], options)
            table = sidecars["periods.db"]
            self.assertEqual(table["row_count"], 2)
            self.assertTrue(table["rows_truncated"])
            self.assertEqual(table["rows"][0]["PERIOD"], 1)
            self.assertEqual(table["rows"][0]["Q"], -3.0)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual({path.name for path in database.parent.iterdir()}, before_names)

    def test_discovers_observed_gms_layout_without_parsing_gpr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "research.gpr"
            project.write_bytes(b"opaque project container: intentionally not interpreted")
            simulation = root / "research_models" / "MODFLOW 6" / "trial"
            native_graph(simulation)
            self.assertEqual(discover_simulations(project), [simulation / "mfsim.nam"])
            self.assertTrue(import_native_simulation(project)["native_inputs_resolved"])

    def test_outside_reference_is_reported_and_not_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulation = root / "simulation"
            native_graph(simulation)
            (root / "external.ims").write_text("outside")
            main = simulation / "mfsim.nam"
            main.write_text(main.read_text().replace("solve.ims", "../external.ims"))
            report = import_native_simulation(simulation)
            self.assertFalse(report["native_inputs_resolved"])
            self.assertTrue(any("outside" in item["reason"] for item in report["issues"]))
            self.assertNotIn("../external.ims", {item["path"] for item in report["files"]})

    def test_discovers_component_layout_and_preserves_sibling_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "component-project.gpr"
            project.write_bytes(b"opaque")
            components = root / "component-project_data" / "Components"
            simulation = components / "simulation-id"
            native_graph(simulation)
            sibling = components / "timing-id"
            sibling.mkdir()
            (simulation / "time.tdis").rename(sibling / "time.tdis")
            main = simulation / "mfsim.nam"
            main.write_text(main.read_text().replace("time.tdis", "../timing-id/time.tdis"))
            report = import_native_simulation(project)
            self.assertTrue(report["native_inputs_resolved"], report["issues"])
            self.assertEqual(report["allowed_root"], str(root))

    def test_missing_input_blocks_numerical_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            (root / "arrays" / "k values.txt").unlink()
            report = import_native_simulation(root)
            self.assertFalse(report["native_inputs_resolved"])
            with self.assertRaisesRegex(NativeImportError, "Resolve native"):
                load_with_flopy(root)

    def test_malformed_blocks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "mfsim.nam").write_text("BEGIN MODELS\nEND TIMING\n")
            with self.assertRaisesRegex(NativeImportError, "Mismatched END"):
                import_native_simulation(root)

    def test_nul_comment_cannot_hide_an_outside_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "mfsim.nam").write_bytes(b"#\0padding\nBEGIN TIMING\n TDIS6 ../outside.tdis\nEND TIMING\n")
            with self.assertRaisesRegex(NativeImportError, "NUL byte"):
                import_native_simulation(root)

    def test_only_declared_binary_arrays_can_skip_text_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            npf = root / "models" / "conductivity.npf"
            npf.write_text('BEGIN GRIDDATA\n K\n OPEN/CLOSE "arrays/k.bin" (BINARY)\nEND GRIDDATA\n')
            (root / "arrays" / "k.bin").write_bytes(b"\0\xff\x01binary input")
            report = import_native_simulation(root)
            self.assertTrue(report["native_inputs_resolved"], report["issues"])
            entry = next(item for item in report["files"] if item["path"] == "arrays/k.bin")
            self.assertEqual(entry["scan"], "declared_binary_array_leaf")

    def test_nonfinite_json_overflow_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            (root / "gms_options.json").write_text('{"nested": [1e999]}')
            report = import_native_simulation(root)
            self.assertFalse(report["native_inputs_resolved"])
            self.assertIn("Non-finite", report["issues"][0]["reason"])

    def test_live_wal_is_reported_without_opening_source_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            database = root / "models" / "periods.db"
            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE data (PERIOD INTEGER, PERIOD_ROW INTEGER)")
                connection.execute("INSERT INTO data VALUES (1,0)")
                connection.commit()
                report = import_native_simulation(root)
                self.assertFalse(report["native_inputs_resolved"])
                self.assertTrue(any("WAL/journal" in issue["reason"] for issue in report["issues"]))

    def test_virtual_period_table_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            with sqlite3.connect(root / "models" / "periods.db") as connection:
                try:
                    connection.execute("CREATE VIRTUAL TABLE data USING fts5(PERIOD, PERIOD_ROW)")
                except sqlite3.OperationalError:
                    self.skipTest("SQLite FTS5 unavailable")
            report = import_native_simulation(root)
            self.assertFalse(report["native_inputs_resolved"])
            self.assertTrue(any("ordinary" in issue["reason"] for issue in report["issues"]))

    def test_nonfinite_sqlite_value_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            with sqlite3.connect(root / "models" / "periods.db") as connection:
                connection.execute("CREATE TABLE data (Q REAL, PERIOD INTEGER, PERIOD_ROW INTEGER)")
                connection.execute("INSERT INTO data VALUES (?,1,0)", (float("inf"),))
            report = import_native_simulation(root)
            self.assertFalse(report["native_inputs_resolved"])
            self.assertTrue(any("Non-finite SQLite" in issue["reason"] for issue in report["issues"]))

    def test_aggregate_input_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            with patch("basinlens_ccs.groundwater.gms_native.MAX_TOTAL_INPUT_BYTES", 10):
                with self.assertRaisesRegex(NativeImportError, "input budget"):
                    import_native_simulation(root)

    def test_outside_list_output_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_graph(root)
            model = root / "models" / "flow model.nam"
            model.write_text('BEGIN OPTIONS\n LIST ../outside.lst\nEND OPTIONS\n' + model.read_text())
            report = import_native_simulation(root)
            self.assertFalse(report["native_inputs_resolved"])
            self.assertTrue(any(item["kind"] == "LIST" and not item["input"] for item in report["references"]))

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "FloPy is optional")
    def test_public_flopy_load_preserves_numerical_arrays(self):
        import flopy
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            original = flopy.mf6.MFSimulation(sim_name="original", sim_ws=temporary)
            flopy.mf6.ModflowTdis(original, nper=2, perioddata=[(1, 1, 1), (10, 2, 1)])
            flopy.mf6.ModflowIms(original)
            model = flopy.mf6.ModflowGwf(original, modelname="aquifer", model_rel_path="model_folder")
            flopy.mf6.ModflowGwfdis(model, nlay=1, nrow=1, ncol=3, delr=25, delc=30, top=10, botm=0)
            flopy.mf6.ModflowGwfic(model, strt=12)
            flopy.mf6.ModflowGwfnpf(model, k=[[[2, 3, 4]]])
            flopy.mf6.ModflowGwfwel(model, stress_period_data={0: [((0, 0, 1), -3)], 1: [((0, 0, 1), -9)]})
            original.write_simulation(silent=True)
            loaded, report = load_with_flopy(temporary)
            self.assertTrue(report["native_inputs_resolved"])
            np.testing.assert_array_equal(loaded.get_model("aquifer").npf.k.array, [[[2, 3, 4]]])
            self.assertEqual(loaded.get_model("aquifer").wel.stress_period_data.get_data(1)[0]["q"], -9)
            self.assertEqual(loaded.tdis.nper.array, 2)


if __name__ == "__main__":
    unittest.main()
