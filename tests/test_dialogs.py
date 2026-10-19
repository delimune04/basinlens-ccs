"""Original synthetic packets derived from Microsoft's documented layouts."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.reconstruction.dialogs import DialogError, decode_dialog, dialog_catalogue, main
from basinlens_ccs.reconstruction import dialogs as dialog_module, resources as resource_module
from test_reconstruction import write_fixture, standard_menu


def text(value):
    return (value + "\0").encode("utf-16le")


def aligned(value):
    # Alignment padding is unspecified, so nonzero padding must be consumed.
    return value + b"\xAB" * ((-len(value)) % 4)


def standard_template():
    header = struct.pack("<IIH4h", 0x90C80040, 0x123, 2, -4, -7, 200, 150)
    header += struct.pack("<HH", 0xFFFF, 99) + text("PRIVATE_DIALOG_CLASS") + text("PRIVATE_TITLE")
    header += struct.pack("<H", 9) + text("PRIVATE_TYPEFACE")
    one = struct.pack("<II4hH", 0x50010001, 0x200, -8, 9, 40, 12, 0xFFFF)
    one += struct.pack("<HH", 0xFFFF, 0x80) + text("PRIVATE_CONTROL_\U0001f30d")
    one += struct.pack("<H", 5) + b"XYZ"  # 5 includes the size WORD.
    two = struct.pack("<II4hH", 0x50000000, 0, 1, 2, 3, 4, 42)
    two += text("PRIVATE_CUSTOM_CONTROL") + struct.pack("<HHH", 0xFFFF, 123, 2)
    return aligned(aligned(header) + one) + two


def extended_template():
    header = struct.pack("<HHIIIH4h", 1, 0xFFFF, 991, 0x100, 0x90C80048, 2, -32768, 32767, 123, 456)
    header += struct.pack("<HHH", 0, 0xFFFF, 0x85) + text("PRIVATE_EXTENDED_TITLE")
    header += struct.pack("<HHBB", 10, 700, 255, 204) + text("PRIVATE_EXTENDED_FONT")
    one = struct.pack("<III4hI", 987654, 0x200, 0x50010000, -1, -2, 3, 4, 0xFFFFFFFF)
    one += struct.pack("<HH", 0xFFFF, 0x81) + struct.pack("<HH", 0xFFFF, 222)
    one += struct.pack("<H", 3) + b"XYZ"  # extended size excludes its WORD.
    two = struct.pack("<III4hI", 0, 0, 0, 10, 20, 30, 40, 0x12345678)
    two += text("PRIVATE_EXTENDED_CLASS") + text("") + struct.pack("<H", 0)
    return aligned(aligned(header) + one) + two


def empty_template(*, extended=False):
    if extended:
        return struct.pack("<HHIIIH4h", 1, 0xFFFF, 0, 0, 0, 0, 1, 2, 3, 4) + b"\0" * 6
    return struct.pack("<IIH4h", 0, 0, 0, 1, 2, 3, 4) + b"\0" * 6


class DialogDecoderTests(unittest.TestCase):
    def test_standard_signed_coordinates_font_ordinals_and_creation_size(self):
        value = decode_dialog(standard_template())
        self.assertEqual(value["format"], "standard")
        self.assertIsNone(value["template_version"])
        self.assertEqual(value["rect_dlu"], {"x": -4, "y": -7, "width": 200, "height": 150})
        self.assertEqual(value["menu"], {"kind": "ordinal", "ordinal": 99})
        self.assertEqual(value["font"], {"point_size": 9, "weight": None, "italic_byte": None, "charset": None})
        one, two = value["controls"]
        self.assertEqual(one["control_id"], 65535)
        self.assertEqual(one["style"], 0x50010001)
        self.assertEqual(one["extended_style"], 0x200)
        self.assertEqual(one["creation_data_bytes"], 3)
        self.assertEqual(one["built_in_class_ordinal"], 0x80)
        self.assertEqual(two["creation_size_word"], 2)
        self.assertEqual(two["creation_data_bytes"], 0)
        self.assertEqual(two["title"], {"kind": "ordinal", "ordinal": 123})
        self.assertIsNone(two["built_in_class_ordinal"])

    def test_extended_dword_ids_help_font_bytes_and_extra_count(self):
        value = decode_dialog(extended_template())
        self.assertEqual(value["format"], "extended")
        self.assertEqual(value["template_version"], 1)
        self.assertEqual(value["help_id"], 991)
        self.assertEqual(value["rect_dlu"]["x"], -32768)
        self.assertEqual(value["font"], {"point_size": 10, "weight": 700, "italic_byte": 255, "charset": 204})
        self.assertEqual([x["control_id"] for x in value["controls"]], [0xFFFFFFFF, 0x12345678])
        self.assertEqual(value["controls"][0]["help_id"], 987654)
        self.assertEqual(value["controls"][0]["creation_data_bytes"], 3)
        self.assertEqual(value["controls"][1]["title"]["kind"], "empty")
        self.assertTrue(all(x["template_offset"] % 4 == 0 for x in value["controls"]))

    def test_empty_dialogs_no_font_and_terminal_padding(self):
        for extended in (False, True):
            blob = empty_template(extended=extended)
            for padding in (b"", b"\0", b"\0\0\0"):
                with self.subTest(extended=extended, padding=padding):
                    value = decode_dialog(blob + padding)
                    self.assertEqual(value["controls"], [])
                    self.assertIsNone(value["font"])
            with self.assertRaises(DialogError):
                decode_dialog(blob + b"\0" * 4)
            with self.assertRaises(DialogError):
                decode_dialog(blob + b"X")

    def test_text_and_creation_bytes_are_absent_from_projection(self):
        for blob in (standard_template(), extended_template()):
            encoded = json.dumps(decode_dialog(blob))
            self.assertNotIn("PRIVATE_", encoded)
            self.assertNotIn("XYZ", encoded)
            self.assertNotIn("typeface", encoded)
            self.assertNotIn("\U0001f30d", encoded)

    def test_every_nonpadding_truncation_and_unknown_version_fail(self):
        for original in (standard_template(), extended_template()):
            for end in range(len(original)):
                with self.subTest(size=len(original), end=end), self.assertRaises(DialogError):
                    decode_dialog(original[:end])
        unknown = bytearray(extended_template())
        struct.pack_into("<H", unknown, 0, 2)
        with self.assertRaisesRegex(DialogError, "version"):
            decode_dialog(bytes(unknown))

    def test_utf16_validation_string_and_control_limits(self):
        header = struct.pack("<IIH4h", 0, 0, 0, 0, 0, 0, 0) + b"\0" * 4
        for bad_title in (b"\0\xD8\0\0", b"\0\xDC\0\0", text("X" * 16385)):
            with self.subTest(title_bytes=len(bad_title)), self.assertRaises(DialogError):
                decode_dialog(header + bad_title)
        self.assertTrue(decode_dialog(header + text("\U0001f30d"))["title_present"])
        self.assertTrue(decode_dialog(header + text("X" * 16384))["title_present"])
        oversized_count = bytearray(empty_template())
        struct.pack_into("<H", oversized_count, 8, 8193)
        with self.assertRaisesRegex(DialogError, "8192"):
            decode_dialog(bytes(oversized_count))
        with self.assertRaises(DialogError):
            decode_dialog(b"x" * 2_000_001)
        with self.assertRaises(DialogError):
            decode_dialog(bytearray(empty_template()))

    def test_bad_creation_data_count_and_truncation(self):
        # A single control, no font; the final standard count includes itself.
        header = struct.pack("<IIH4h", 0, 0, 1, 0, 0, 10, 10) + b"\0" * 6
        control = struct.pack("<II4hH", 0, 0, 0, 0, 1, 1, 1) + struct.pack("<HHHH", 0xFFFF, 0x80, 0, 1)
        with self.assertRaisesRegex(DialogError, "size WORD"):
            decode_dialog(aligned(header) + control)
        blob = extended_template()
        # Removing its second item makes the preceding extraCount/alignment
        # insufficient to satisfy the declared number of controls.
        with self.assertRaises(DialogError):
            decode_dialog(blob[:decode_dialog(blob)["controls"][1]["template_offset"]])

    def test_catalogue_pe_binding_no_names_and_explicit_decode_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            target, evidence, original = write_fixture(directory, [
                (5, "PRIVATE_RESOURCE_NAME", 1033, standard_template()),
                (5, 17, 1042, extended_template()), (5, 18, 1042, b"bad")])
            value = dialog_catalogue(target, evidence)
            self.assertEqual(value["dialogs_attempted"], 3)
            self.assertEqual(value["dialogs_decoded"], 2)
            self.assertEqual(value["control_count"], 4)
            self.assertEqual(len(value["decode_failures"]), 1)
            self.assertEqual(value["format_counts"], {"extended": 1, "standard": 1})
            self.assertNotIn("PRIVATE_", json.dumps(value))
            self.assertFalse(value["runtime_observed"])
            # Unexpected source metadata and free-form receipt identifiers must
            # not leak into the numeric-only public projection.
            metadata = copy.deepcopy(original)
            metadata["evidence_id"] = "PRIVATE_RECEIPT_ID"
            metadata["normalized_result"]["coverage"]["private_caption"] = "PRIVATE_VENDOR_CAPTION"
            evidence.write_text(json.dumps(metadata))
            scrubbed = dialog_catalogue(target, evidence)
            self.assertNotIn("PRIVATE_", json.dumps(scrubbed))
            self.assertIsNone(scrubbed["rea_evidence_id"])
            altered = copy.deepcopy(original)
            altered["normalized_result"]["resources"][0]["payload"]["sha256"] = "0" * 64
            evidence.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "payload identity"):
                dialog_catalogue(target, evidence)

    def test_catalogue_detects_target_or_evidence_change_during_decode(self):
        for changed in ("target", "evidence"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                target, evidence, _ = write_fixture(directory, [(5, 1, 1033, empty_template())])
                original_decode = decode_dialog
                def mutate(blob):
                    path = target if changed == "target" else evidence
                    path.write_bytes(path.read_bytes() + b" ")
                    return original_decode(blob)
                with patch.object(dialog_module, "decode_dialog", side_effect=mutate):
                    with self.assertRaisesRegex(DialogError, "changed during"):
                        dialog_catalogue(target, evidence)

    def test_catalogue_global_limits_stop_before_further_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            target, evidence, _ = write_fixture(directory, [
                (5, 1, 1033, standard_template()), (5, 2, 1033, standard_template())])
            with patch.object(dialog_module, "MAX_TOTAL_CONTROLS", 3):
                with patch.object(dialog_module, "decode_dialog", wraps=decode_dialog) as decoder:
                    with self.assertRaisesRegex(DialogError, "declared total controls"):
                        dialog_catalogue(target, evidence)
                    self.assertEqual(decoder.call_count, 1)
            with patch.object(dialog_module, "MAX_TOTAL_DIALOG_BYTES", len(standard_template()) - 1):
                with patch.object(dialog_module, "decode_dialog", wraps=decode_dialog) as decoder:
                    with self.assertRaisesRegex(DialogError, "payload budget"):
                        dialog_catalogue(target, evidence)
                    self.assertEqual(decoder.call_count, 0)

    def test_inventory_only_mode_skips_unrelated_menus_and_still_hashes_them(self):
        with tempfile.TemporaryDirectory() as directory:
            target, evidence, original = write_fixture(directory, [
                (4, 1, 1033, standard_menu()), (4, 2, 1033, standard_menu()),
                (5, 3, 1033, empty_template())])
            # Any menu decode before the dialog budget would fail this test.
            with patch.object(resource_module, "decode_menu", side_effect=AssertionError("Unrelated menu decoded")):
                result = dialog_catalogue(target, evidence)
                self.assertEqual(result["dialogs_decoded"], 1)
                inventory = resource_module.resource_catalogue(target, evidence, decode_menus=False)
                self.assertEqual(inventory["menu_decoding"], {"requested": False, "resources_skipped": 2})
                altered = copy.deepcopy(original)
                altered["normalized_result"]["resources"][0]["payload"]["sha256"] = "0" * 64
                evidence.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, "payload identity"):
                    dialog_catalogue(target, evidence)
            evidence.write_text(json.dumps(original))
            default = resource_module.resource_catalogue(target, evidence)
            explicit = resource_module.resource_catalogue(target, evidence, decode_menus=True)
            self.assertEqual(default, explicit)
            self.assertNotIn("menu_decoding", default)
            self.assertEqual(default["menus_decoded"], 2)
            for invalid in (None, 0, 1, "false"):
                with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "boolean"):
                    resource_module.resource_catalogue(target, evidence, decode_menus=invalid)

    def test_phase_hash_size_bound_rejects_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bin"
            path.write_bytes(b"12345")
            with self.assertRaisesRegex(DialogError, "size changed"):
                dialog_module._sha(path, expected_bytes=4)
            with self.assertRaisesRegex(DialogError, "byte limit"):
                dialog_module._sha(path, limit=4)
            self.assertEqual(dialog_module._sha(path, expected_bytes=5), hashlib.sha256(b"12345").hexdigest())
            with self.assertRaisesRegex(ValueError, "size changed"):
                resource_module._sha(path, expected_bytes=4)
            with self.assertRaisesRegex(ValueError, "byte limit"):
                resource_module._sha(path, limit=4)

    def test_cli_output_is_fresh_and_numeric(self):
        with tempfile.TemporaryDirectory() as directory:
            target, evidence, _ = write_fixture(directory, [(5, 1, 1033, empty_template())])
            output = Path(directory) / "layouts.json"
            args = [str(target), "--evidence", str(evidence), "--output", str(output)]
            self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.read_text())["dialogs_decoded"], 1)
            self.assertEqual(main(args), 2)


if __name__ == "__main__":
    unittest.main()
