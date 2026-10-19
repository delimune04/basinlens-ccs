"""Independent checks of the static ledger boundary; no solver or target needed."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


_path = Path(__file__).resolve().parents[1] / "tools/build_gms_ledger.py"
_spec = importlib.util.spec_from_file_location("build_gms_ledger", _path)
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)


def catalogue():
    return {
        "target": {"sha256": "a" * 64, "size_bytes": 1000},
        "rea_evidence_id": "ev_" + "b" * 64, "rea_evidence_sha256": "c" * 64,
        "menus_decoded": 2, "dialogs_inventoried": 1, "unique_static_command_ids": 2,
        "runtime_observed": False, "gms_parity_established": False,
        "menus": [
            {"file_offset": 100, "resource": "DO_NOT_PUBLISH_RESOURCE", "items": [
                {"command_id": 0, "popup": False, "label": ""},
                {"command_id": 777, "popup": True, "label": "DO_NOT_PUBLISH_LABEL", "children": [
                    {"command_id": 42, "popup": False}, {"command_id": 19, "popup": False},
                ]},
            ]},
            {"file_offset": 200, "items": [{"command_id": 42, "popup": False}]},
        ],
    }


class ReaLedgerBoundaryTests(unittest.TestCase):
    def test_numeric_projection_ignores_popups_separators_and_deduplicates(self):
        source = catalogue()
        source["menus"][0]["items"].append({"command_id": 90, "popup": False, "separator": True})
        self.assertEqual(ledger.command_locations(source), {19: (100,), 42: (100, 200)})

    def test_changed_command_or_original_claim_is_rejected(self):
        decoded = catalogue()
        changed = copy.deepcopy(decoded)
        changed["menus"][1]["items"][0]["command_id"] = 19
        with self.assertRaisesRegex(ledger.LedgerError, "commands differ"):
            ledger.verify_observations(changed, decoded, "c" * 64)
        changed = copy.deepcopy(decoded)
        changed["runtime_observed"] = True
        with self.assertRaisesRegex(ledger.LedgerError, "must not claim"):
            ledger.verify_observations(changed, decoded, "c" * 64)
        with self.assertRaisesRegex(ledger.LedgerError, "exact source Evidence"):
            ledger.verify_observations(decoded, decoded, "d" * 64)

    def test_public_obligations_do_not_include_original_names_or_owners(self):
        source = catalogue()
        commands = ledger.verify_observations(source, source, "c" * 64)
        obligations = ledger.reviewed_obligations("a" * 64, source["rea_evidence_id"], commands)
        self.assertEqual(len(obligations), 3)
        self.assertEqual([o["obligation_id"] for o in obligations[:2]], ["gms.menu-command.19", "gms.menu-command.42"])
        public = json.dumps(obligations)
        self.assertNotIn("DO_NOT_PUBLISH", public)
        self.assertNotIn('"owner"', public)
        self.assertTrue(all(o["required_original_authority"] == "runtime" for o in obligations))
        self.assertTrue(obligations[-1]["unavailable_authority"])

    def test_malformed_numeric_ids_counts_and_boolean_ids_fail(self):
        for field in (True, -1, 0x100000000, "42"):
            broken = catalogue()
            broken["menus"][1]["items"][0]["command_id"] = field
            with self.assertRaises(ledger.LedgerError):
                ledger.command_locations(broken)
        broken = catalogue()
        broken["unique_static_command_ids"] = 3
        with self.assertRaisesRegex(ledger.LedgerError, "count"):
            ledger.command_locations(broken)

    def test_json_rejects_duplicate_keys_nonfinite_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "input.json"
            p.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ledger.LedgerError, "Duplicate"):
                ledger.read_json(p)
            p.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ledger.LedgerError, "Non-finite"):
                ledger.read_json(p)
            p.write_text('{"a": 1e999}', encoding="utf-8")
            with self.assertRaisesRegex(ledger.LedgerError, "Non-finite"):
                ledger.read_json(p)
            p.write_text('[]', encoding="utf-8")
            with self.assertRaisesRegex(ledger.LedgerError, "root must be an object"):
                ledger.read_json(p)
            linked = p.with_name("linked.json")
            linked.symlink_to(p)
            with self.assertRaisesRegex(ledger.LedgerError, "regular"):
                ledger.read_json(linked)


if __name__ == "__main__":
    unittest.main()
