"""Container corruption and path-boundary tests; fixtures contain no vendor data."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "extract_gms_target.py"
SPEC = importlib.util.spec_from_file_location("extract_gms_target", MODULE_PATH)
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


def fixture(entries):
    payload = bytes(range(256)) * 4
    table = bytearray()
    for name, offset, length, xor_flag in entries:
        encoded = name.encode("utf-16le")
        table.extend(struct.pack("<6I", 8, 6, xor_flag, length, offset, len(encoded) // 2))
        table.extend(encoded)
    footer = len(payload) + len(table)
    end = struct.pack("<7I32sI10s", 0, footer, len(entries), 100, footer,
                      len(payload), 0, b"0" * 32, 0, b"ADVINSTSFX")
    return payload + table + end


class ContainerBoundaryTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.exe"
            source.write_bytes(data)
            return extractor.read_container_table(source)

    def test_bounded_entry_and_prefix_decode(self):
        data = fixture([("folder\\FILES.7z", 0, 700, 2)])
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "fixture.exe", Path(directory) / "payload.7z"
            source.write_bytes(data)
            entries, _ = extractor.read_container_table(source)
            self.assertEqual(entries[0]["name"], "folder/FILES.7z")
            extractor.copy_container_payload(source, entries[0], target)
            result = target.read_bytes()
            self.assertEqual(result[:512], bytes(value ^ 255 for value in data[:512]))
            self.assertEqual(result[512:], data[512:700])

    def test_rejects_payload_outside_data_region(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "data bounds"):
            self.parse(fixture([("FILES.7z", 1000, 100, 0)]))

    def test_rejects_overlapping_payloads(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "overlap"):
            self.parse(fixture([("a", 0, 700, 0), ("b", 500, 200, 0)]))

    def test_rejects_unsafe_filename(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "Unsafe"):
            self.parse(fixture([("../FILES.7z", 0, 700, 0)]))

    def test_rejects_duplicate_embedded_names(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "Duplicate"):
            self.parse(fixture([("a", 0, 400, 0), ("a", 500, 200, 0)]))

    def test_rejects_missing_footer(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "footer"):
            self.parse(b"arbitrary non executable test bytes" * 10)


if __name__ == "__main__":
    unittest.main()
