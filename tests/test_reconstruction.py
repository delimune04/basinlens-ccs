import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.reconstruction import ResourceError, decode_menu, resource_catalogue
from basinlens_ccs.reconstruction import resources as resource_module


def text(value):
    return (value + "\0").encode("utf-16le")


def standard_menu():
    # Independent Win32 fixture: File popup -> Open(100), Exit(101), then Help(200).
    return (struct.pack("<HHH", 0, 0, 0x10) + text("File") +
            struct.pack("<HH", 0, 100) + text("Open") +
            struct.pack("<HH", 0x80, 101) + text("Exit") +
            struct.pack("<HH", 0x80, 200) + text("Help"))


def pe_fixture(payloads, *, pe32=False):
    """Original minimal PE fixture with independently constructed resource tables.

    Each input is (type identity, name identity, language identity, payload).
    Fixture construction does not use the production PE tree reader.
    """
    root, metadata, leaves = {}, bytearray(), []
    examined = 0
    for kind, name, language, blob in payloads:
        root.setdefault(kind, {}).setdefault(name, {})[language] = blob

    def allocate(size, alignment=4):
        metadata.extend(b"\0" * ((-len(metadata)) % alignment))
        position = len(metadata)
        metadata.extend(b"\0" * size)
        return position

    def directory(tree, path=(), entry_locations=()):
        nonlocal examined
        keys = sorted(tree, key=lambda value: (0, value) if isinstance(value, str) else (1, value))
        named = sum(isinstance(key, str) for key in keys)
        at = allocate(16 + 8 * len(keys))
        struct.pack_into("<IIHHHH", metadata, at, 0, 0, 0, 0, named, len(keys) - named)
        for index, key in enumerate(keys):
            examined += 1
            slot = at + 16 + 8 * index
            if isinstance(key, str):
                encoded = key.encode("utf-16le")
                start = allocate(2 + len(encoded), 2)
                struct.pack_into("<H", metadata, start, len(encoded) // 2)
                metadata[start + 2:start + 2 + len(encoded)] = encoded
                name_word = 0x80000000 | start
            else:
                name_word = key
            locations = (*entry_locations, 512 + slot)
            if isinstance(tree[key], dict):
                child = 0x80000000 | directory(tree[key], (*path, key), locations)
            else:
                child = allocate(16)
                leaves.append(((*path, key), locations, child, tree[key]))
            struct.pack_into("<2I", metadata, slot, name_word, child)
        return at

    assert directory(root) == 0
    records = []
    for identities, entries, data_entry, blob in leaves:
        offset = allocate(len(blob))
        metadata[offset:offset + len(blob)] = blob
        rva = 0x1000 + offset
        struct.pack_into("<4I", metadata, data_entry, rva, len(blob), 0, 0)
        identities = [{"kind": "name", "name": value} if isinstance(value, str)
                      else {"kind": "id", "id": value} for value in identities]
        records.append({"type": identities[0], "name": identities[1], "language": identities[2],
            "entry_locations": [{"offset": entry, "bytes": 8} for entry in entries],
            "data_entry_location": {"offset": 512 + data_entry, "bytes": 16},
            "code_page": 0, "reserved": 0,
            "payload": {"rva": rva, "location": {"offset": 512 + offset, "bytes": len(blob)},
                        "sha256": hashlib.sha256(blob).hexdigest()}})
    raw_size = (len(metadata) + 511) & ~511
    prefix = bytearray(512)
    prefix[:2] = b"MZ"
    struct.pack_into("<I", prefix, 0x3C, 0x80)
    prefix[0x80:0x84] = b"PE\0\0"
    optional_size = 224 if pe32 else 240
    struct.pack_into("<HHIIIHH", prefix, 0x84, 0x14C if pe32 else 0x8664, 1, 0, 0, 0, optional_size, 2)
    optional = 0x98
    struct.pack_into("<H", prefix, optional, 0x10B if pe32 else 0x20B)
    directory_start = 96 if pe32 else 112
    struct.pack_into("<I", prefix, optional + directory_start - 4, 16)
    struct.pack_into("<2I", prefix, optional + directory_start + 16, 0x1000, len(metadata))
    section = optional + optional_size
    prefix[section:section + 8] = b".rsrc\0\0\0"
    struct.pack_into("<4I", prefix, section + 8, len(metadata), 0x1000, raw_size, 512)
    image = bytes(prefix + metadata + b"\0" * (raw_size - len(metadata)))
    evidence = {"operation": "inspect_pe_resources", "evidence_id": "synthetic-decoder-test",
        "normalized_result": {"format": "pe32" if pe32 else "pe32-plus",
            "artifact": {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)},
            "directory": {"rva": 0x1000, "location": {"offset": 512, "bytes": len(metadata)}},
            "coverage": {"status": "complete", "resources": len(records), "examined_entries": examined},
            "resources": records}}
    return image, evidence


def write_fixture(directory, payloads=None, **kwargs):
    image, record = pe_fixture(payloads or [(4, 1, 1033, standard_menu())], **kwargs)
    target, receipt = Path(directory) / "synthetic.exe", Path(directory) / "evidence.json"
    target.write_bytes(image)
    receipt.write_text(json.dumps(record))
    return target, receipt, record


class ResourceDecoderTests(unittest.TestCase):
    def test_standard_nested_commands(self):
        result = decode_menu(standard_menu())
        self.assertEqual(result["item_count"], 4)
        self.assertEqual([x["command_id"] for x in result["items"][0]["children"]], [100, 101])
        self.assertEqual(result["items"][1]["label"], "Help")
        self.assertEqual(result["items"][1]["standard_options"], 0x80)
        self.assertIsNone(result["items"][1]["state"])
        self.assertIsNone(result["items"][1]["type"])

    def test_extended_menu_and_alignment(self):
        header = struct.pack("<HHI", 1, 4, 0)
        popup = struct.pack("<IIIH", 0, 0, 7, 0x81) + text("File")
        popup += b"\0" * ((-len(popup)) % 4) + struct.pack("<I", 900)
        child = struct.pack("<IIIH", 0, 0, 123456, 0x80) + text("Open")
        result = decode_menu(header + popup + child)
        self.assertEqual(result["items"][0]["help_id"], 900)
        self.assertEqual(result["items"][0]["children"][0]["command_id"], 123456)
        self.assertEqual(result["items"][0]["children"][0]["state"], 0)
        self.assertNotIn("standard_options", result["items"][0])

    def test_truncated_unterminated_and_unknown_templates_rejected(self):
        for value in [b"", b"\0", standard_menu()[:-1], standard_menu() + b"garbage",
                      struct.pack("<HH", 2, 0), struct.pack("<HH", 1, 0) + b"x" * 20]:
            with self.subTest(value=value), self.assertRaises(ResourceError):
                decode_menu(value)

    def test_inventory_binding_tamper_and_private_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt, record = write_fixture(temp)
            result = resource_catalogue(target, receipt)
            self.assertEqual(result["unique_static_command_ids"], 3)
            self.assertFalse(result["runtime_observed"])
            self.assertFalse(result["gms_parity_established"])
            self.assertEqual(result["pe_directory_crosscheck"], {"leaf_count": 1, "listed_leaves_verified": 1})
            self.assertNotIn("label", result["menus"][0]["items"][0])
            self.assertEqual(resource_catalogue(target, receipt, include_labels=True)["menus"][0]["items"][0]["label"], "File")
            altered = copy.deepcopy(record)
            altered["normalized_result"]["resources"][0]["payload"]["sha256"] = "0" * 64
            receipt.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ResourceError, "payload identity"):
                resource_catalogue(target, receipt)
            receipt.write_text(json.dumps(record))
            target.write_bytes(target.read_bytes() + b"changed")
            with self.assertRaisesRegex(ResourceError, "subject identity"):
                resource_catalogue(target, receipt)

    def test_pe32_and_named_resource_types_stay_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt, _ = write_fixture(temp, [(4, 1, 1033, standard_menu()), ("4", 1, 1033, b"opaque")], pe32=True)
            result = resource_catalogue(target, receipt)
            self.assertEqual(result["type_counts"], {"id:4": 1, "name:4": 1})
            self.assertEqual(result["menus_decoded"], 1)

    def test_standard_and_extended_separator_ids_are_not_commands(self):
        standard = struct.pack("<4H", 0, 0, 0x880, 77) + text("")
        extended = struct.pack("<HHI", 1, 4, 0) + struct.pack("<IIIH", 0x800, 0, 77, 0x80) + text("")
        for blob in (standard, extended):
            with self.subTest(blob=blob), tempfile.TemporaryDirectory() as temp:
                target, receipt, _ = write_fixture(temp, [(4, 1, 1033, blob)])
                result = resource_catalogue(target, receipt)
                self.assertEqual(result["unique_static_command_ids"], 0)
                self.assertTrue(result["menus"][0]["items"][0]["separator"])

    def test_claimed_identity_range_and_complete_coverage_are_crosschecked(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt, original = write_fixture(temp)
            variants = []
            changed = copy.deepcopy(original)
            changed["normalized_result"]["resources"][0]["name"]["id"] = 2
            variants.append(changed)
            changed = copy.deepcopy(original)
            changed["normalized_result"]["resources"][0]["payload"]["location"]["offset"] += 2
            variants.append(changed)
            changed = copy.deepcopy(original)
            changed["normalized_result"]["resources"].append(copy.deepcopy(changed["normalized_result"]["resources"][0]))
            changed["normalized_result"]["coverage"]["resources"] = 2
            variants.append(changed)
            changed = copy.deepcopy(original)
            changed["normalized_result"]["resources"] = []
            changed["normalized_result"]["coverage"]["resources"] = 0
            variants.append(changed)
            changed = copy.deepcopy(original)
            changed["normalized_result"]["coverage"]["examined_entries"] = 999
            variants.append(changed)
            for changed in variants:
                with self.subTest(changed=changed):
                    receipt.write_text(json.dumps(changed))
                    with self.assertRaises(ResourceError):
                        resource_catalogue(target, receipt)
            changed["normalized_result"]["resources"] = []
            changed["normalized_result"]["coverage"] = {"status": "partial", "resources": 0}
            receipt.write_text(json.dumps(changed))
            result = resource_catalogue(target, receipt)
            self.assertEqual(result["menus_decoded"], 0)
            self.assertEqual(result["pe_directory_crosscheck"]["leaf_count"], 1)

    def test_non_pe_arbitrary_payload_and_duplicate_json_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt, record = write_fixture(temp)
            receipt.write_text(json.dumps(record).replace('"operation":', '"operation":"inspect_pe_resources","operation":', 1))
            with self.assertRaisesRegex(ResourceError, "Duplicate"):
                resource_catalogue(target, receipt)
            blob = b"MZ" + standard_menu()
            target.write_bytes(blob)
            record["normalized_result"]["artifact"] = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
            receipt.write_text(json.dumps(record))
            with self.assertRaises(ResourceError):
                resource_catalogue(target, receipt)

    def test_evidence_and_target_changes_during_decoding_are_refused(self):
        for changed_file in ("evidence", "target"):
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as temp:
                target, receipt, record = write_fixture(temp)
                original_decode = resource_module.decode_menu
                def decode_and_change(blob):
                    if changed_file == "evidence":
                        receipt.write_text("{}")
                    else:
                        target.write_bytes(target.read_bytes() + b"changed")
                    return original_decode(blob)
                with patch.object(resource_module, "decode_menu", side_effect=decode_and_change):
                    with self.assertRaisesRegex(ResourceError, "changed during"):
                        resource_catalogue(target, receipt)

    def test_private_labels_require_explicit_boolean_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt, _ = write_fixture(temp)
            with self.assertRaisesRegex(ResourceError, "explicit boolean"):
                resource_catalogue(target, receipt, include_labels="false")

    def test_invalid_evidence_and_ranges_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            target, receipt = Path(temp) / "synthetic.exe", Path(temp) / "evidence.json"
            target.write_bytes(b"MZ")
            for malformed in [[], {}, {"operation": "another"}, {"operation": "inspect_pe_resources", "normalized_result": []}]:
                receipt.write_text(json.dumps(malformed))
                with self.assertRaises(ResourceError):
                    resource_catalogue(target, receipt)


if __name__ == "__main__":
    unittest.main()
