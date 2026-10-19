#!/usr/bin/env python3
"""Extract a pinned GMS target for private static analysis, without running it.

This original parser follows the footer/table structure observed in the official
GMS 10.9.7 installer. It decodes the installer container and uses the caller's
7-Zip executable; it does not modify GMS, its license handling, or its code.
Only gms10_9.exe and a small provenance record remain in the new output folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
import zlib


INSTALLER_SHA256 = "69fef79023d065d4664e74950e10669c784a7e18fabfaa8ada48b2760f624335"
INSTALLER_BYTES = 1_992_547_136
PAYLOAD_SHA256 = "75779a37e99c48725ff4283d7ac3a14e8ee8f5ebcf7df949ec08628492fa4e15"
ZIP_SHA256 = "3270503412c2eb4f03c7903c5f3753925194717ef91a04f426f8e4c9ca380489"
ZIP_BYTES = 2_022_937_957
TARGET_NAME = "gms10_9.exe"
TARGET_SHA256 = "d69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2"
TARGET_BYTES = 145_479_264
TARGET_CRC32 = 0x42447C5D
FOOTER_MAGIC = b"ADVINSTSFX"
CHUNK = 1024 * 1024


class ExtractionError(ValueError):
    """The pinned installer did not match the inspected container structure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(CHUNK):
            digest.update(data)
    return digest.hexdigest()


def read_exact(stream, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ExtractionError("Unexpected end of installer")
    return data


def read_container_table(installer: Path) -> tuple[list[dict], dict]:
    """Read bounded footer metadata; no extracted payload is interpreted as code."""
    size = installer.stat().st_size
    if size < 74:
        raise ExtractionError("Installer is too small")
    with installer.open("rb") as stream:
        stream.seek(max(0, size - CHUNK))
        tail = stream.read()
        marker_in_tail = tail.rfind(FOOTER_MAGIC)
        if marker_in_tail < 64:
            raise ExtractionError("Advanced Installer footer was not found")
        marker = size - len(tail) + marker_in_tail
        footer_offset = marker - 64
        stream.seek(footer_offset)
        fields = struct.unpack("<7I32sI10s", read_exact(stream, 74))
        zero, claimed_footer, count, version, second_footer, table, data_start, _, _, magic = fields
        if (zero != 0 or version != 100 or magic != FOOTER_MAGIC
                or claimed_footer != footer_offset or second_footer != footer_offset):
            raise ExtractionError("Unsupported footer structure")
        if not (0 < count <= 64 and 0 <= data_start < table < footer_offset):
            raise ExtractionError("Invalid container table bounds")
        stream.seek(table)
        entries: list[dict] = []
        names: set[str] = set()
        for _ in range(count):
            if stream.tell() + 24 > footer_offset:
                raise ExtractionError("File entry exceeds table bounds")
            kind, subtype, xor_flag, length, offset, units = struct.unpack("<6I", read_exact(stream, 24))
            if not (0 < units <= 4096 and stream.tell() + units * 2 <= footer_offset):
                raise ExtractionError("Invalid embedded filename length")
            try:
                name = read_exact(stream, units * 2).decode("utf-16le").rstrip("\0")
            except UnicodeDecodeError as error:
                raise ExtractionError("Invalid embedded filename encoding") from error
            normalized = name.replace("\\", "/")
            parts = normalized.split("/")
            if (not normalized or normalized.startswith("/") or ":" in normalized
                    or any(part in ("", ".", "..") for part in parts) or "\0" in normalized):
                raise ExtractionError("Unsafe embedded filename")
            if normalized in names:
                raise ExtractionError("Duplicate embedded filename")
            names.add(normalized)
            if xor_flag not in (0, 2) or not (data_start <= offset <= table and length <= table - offset):
                raise ExtractionError("Embedded payload exceeds data bounds")
            entries.append({"name": normalized, "offset": offset, "size": length,
                            "xor_prefix_bytes": 512 if xor_flag == 2 else 0,
                            "kind": kind, "subtype": subtype})
        sorted_entries = sorted(entries, key=lambda entry: entry["offset"])
        for previous, following in zip(sorted_entries, sorted_entries[1:]):
            if previous["offset"] + previous["size"] > following["offset"]:
                raise ExtractionError("Embedded payload ranges overlap")
    return entries, {"footer_offset": footer_offset, "table_offset": table, "version": version}


def copy_container_payload(installer: Path, entry: dict, target: Path) -> None:
    with installer.open("rb") as source, target.open("xb") as destination:
        source.seek(entry["offset"])
        remaining, position = entry["size"], 0
        while remaining:
            data = read_exact(source, min(CHUNK, remaining))
            prefix = max(0, min(len(data), entry["xor_prefix_bytes"] - position))
            if prefix:
                data = bytes(value ^ 0xFF for value in data[:prefix]) + data[prefix:]
            destination.write(data)
            remaining -= len(data)
            position += len(data)


def extract_target(installer: Path, output: Path, sevenzip: Path) -> dict:
    installer = installer.resolve(strict=True)
    sevenzip = sevenzip.resolve(strict=True)
    output = output.absolute()
    if output.exists():
        raise ExtractionError("Output directory must not already exist")
    if not output.parent.is_dir():
        raise ExtractionError("Output parent directory must already exist")
    if installer.stat().st_size != INSTALLER_BYTES or sha256_file(installer) != INSTALLER_SHA256:
        raise ExtractionError("Expected the official pinned GMS 10.9.7 installer SHA-256 and size")
    entries, footer = read_container_table(installer)
    payloads = [entry for entry in entries if entry["name"].split("/")[-1] == "FILES.7z"]
    if len(payloads) != 1:
        raise ExtractionError("Expected exactly one FILES.7z payload")
    payload = payloads[0]
    with tempfile.TemporaryDirectory(prefix="gms-static-extract-", dir=output.parent) as temporary:
        work = Path(temporary)
        archive_path = work / "FILES.7z"
        zip_path = work / "64-bit.zip"
        result_dir = work / "result"
        result_dir.mkdir()
        copy_container_payload(installer, payload, archive_path)
        if sha256_file(archive_path) != PAYLOAD_SHA256:
            raise ExtractionError("Decoded FILES.7z hash does not match the inspected installer")
        with zip_path.open("xb") as destination:
            process = subprocess.run(
                [str(sevenzip), "x", "-so", str(archive_path), "64-bit.zip"],
                stdout=destination, stderr=subprocess.PIPE, check=False,
            )
        if process.returncode != 0:
            raise ExtractionError(f"7-Zip extraction failed with exit code {process.returncode}")
        if zip_path.stat().st_size != ZIP_BYTES or sha256_file(zip_path) != ZIP_SHA256:
            raise ExtractionError("Decoded ZIP hash or size does not match the inspected installer")
        target_path = result_dir / TARGET_NAME
        digest, crc, count = hashlib.sha256(), 0, 0
        with zipfile.ZipFile(zip_path) as archive:
            matches = [info for info in archive.infolist() if info.filename == TARGET_NAME]
            if len(matches) != 1:
                raise ExtractionError("Expected exactly one main GMS target")
            info = matches[0]
            if (info.file_size != TARGET_BYTES or info.CRC != TARGET_CRC32
                    or info.compress_type != zipfile.ZIP_DEFLATED or info.flag_bits & 1):
                raise ExtractionError("Unexpected target ZIP metadata")
            with archive.open(info) as source, target_path.open("xb") as destination:
                while data := source.read(CHUNK):
                    count += len(data)
                    if count > TARGET_BYTES:
                        raise ExtractionError("Target exceeded expected size")
                    destination.write(data)
                    digest.update(data)
                    crc = zlib.crc32(data, crc)
        if count != TARGET_BYTES or crc != TARGET_CRC32 or digest.hexdigest() != TARGET_SHA256:
            raise ExtractionError("Target SHA-256, CRC, or size did not match")
        metadata = {
            "schema": "gms-private-extraction-v1", "target_executed": False,
            "installer": {"name": installer.name, "size": INSTALLER_BYTES, "sha256": INSTALLER_SHA256},
            "container": {**footer, "payload": payload["name"], "sha256": PAYLOAD_SHA256},
            "zip": {"name": "64-bit.zip", "size": ZIP_BYTES, "sha256": ZIP_SHA256},
            "target": {"name": TARGET_NAME, "size": count, "sha256": digest.hexdigest(), "crc32": f"{crc:08x}"},
            "scope": "Container extraction only; no GMS functionality or license mechanism was modified.",
        }
        (result_dir / "extraction.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        # Rename within the same filesystem; no incomplete final folder is exposed.
        if output.exists():
            raise ExtractionError("Output appeared during extraction")
        result_dir.rename(output)
        return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path, help="Local official GMS 10.9.7 full x64 installer")
    parser.add_argument("output", type=Path, help="New private output directory")
    parser.add_argument("--sevenzip", type=Path, required=True, help="Explicit path to an installed 7z/7za executable")
    args = parser.parse_args()
    try:
        metadata = extract_target(args.installer, args.output, args.sevenzip)
    except (OSError, ExtractionError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        parser.exit(1, f"Extraction failed: {error}\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
