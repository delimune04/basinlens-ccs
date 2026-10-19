"""Bounded Win32 dialog-template observations, without original text or execution.

Original implementation of Microsoft's DLGTEMPLATE/DLGITEMTEMPLATE and their
extended variants. Returned coordinates are dialog units, never screen pixels.
All strings and control creation bytes are validated/consumed and discarded.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
import struct

from .resources import ResourceError, resource_catalogue

MAX_TEMPLATE_BYTES = 2_000_000
MAX_CONTROLS = 8192
MAX_STRING_UNITS = 16_384
MAX_TOTAL_CONTROLS = 50_000
MAX_TOTAL_DIALOG_BYTES = 32 * 1024 * 1024
DS_SETFONT = 0x40


class DialogError(ResourceError):
    """Malformed or unsupported bounded dialog observation."""


class _Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def skip(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise DialogError("Truncated dialog template")
        self.offset += count

    def read(self, fmt):
        size = struct.calcsize(fmt)
        start = self.offset
        self.skip(size)
        values = struct.unpack_from(fmt, self.data, start)
        return values[0] if len(values) == 1 else values

    def align(self, alignment=4):
        self.skip((-self.offset) % alignment)

    def string(self):
        """Validate bounded UTF-16, discard content, return only empty/nonempty."""
        start = self.offset
        while self.read("<H"):
            if (self.offset - start) // 2 > MAX_STRING_UNITS:
                raise DialogError("Dialog string exceeds 16384 UTF-16 code units")
        try:
            self.data[start:self.offset - 2].decode("utf-16le", errors="strict")
        except UnicodeDecodeError as error:
            raise DialogError("Invalid UTF-16 string in dialog template") from error
        return self.offset - start > 2

    def ordinal_or_string(self):
        first = self.read("<H")
        if first == 0:
            return {"kind": "empty", "ordinal": None}
        if first == 0xFFFF:
            return {"kind": "ordinal", "ordinal": self.read("<H")}
        self.offset -= 2
        self.string()
        return {"kind": "text-omitted", "ordinal": None}


def _rectangle(values):
    return dict(zip(("x", "y", "width", "height"), values))


def decode_dialog(data: bytes) -> dict:
    """Decode one standard or version-1 extended Win32 template.

    Preserve numeric template facts only. Empty strings, text and ordinals have
    distinct storage meanings; a named class is never guessed to be a built-in
    class. The decoder neither instantiates controls nor validates application
    behavior. Unsupported template versions and trailing non-padding bytes fail.
    """
    if not isinstance(data, bytes) or len(data) > MAX_TEMPLATE_BYTES:
        raise DialogError("Dialog template must be bytes, at most 2 MB")
    reader = _Reader(data)
    _, signature = reader.read("<2H")
    reader.offset = 0
    extended = signature == 0xFFFF
    if extended:
        version, _, help_id, ex_style, style, count, *rect = reader.read("<HHIIIH4h")
        if version != 1:
            raise DialogError("Unsupported extended dialog template version")
    else:
        style, ex_style, count, *rect = reader.read("<IIH4h")
        version, help_id = None, None
    if count > MAX_CONTROLS:
        raise DialogError("Dialog exceeds 8192 controls")
    menu = reader.ordinal_or_string()
    window_class = reader.ordinal_or_string()
    title_present = reader.string()
    font = None
    if style & DS_SETFONT:
        point_size = reader.read("<H")
        weight, italic, charset = reader.read("<HBB") if extended else (None, None, None)
        reader.string()  # Original typeface name is intentionally omitted.
        font = {"point_size": point_size, "weight": weight,
                "italic_byte": italic, "charset": charset}
    controls = []
    for index in range(count):
        reader.align()
        control_offset = reader.offset
        if extended:
            control_help, control_ex_style, control_style, *tail = reader.read("<III4hI")
            control_rect, control_id = tail[:4], tail[4]
        else:
            control_style, control_ex_style, *tail = reader.read("<II4hH")
            control_rect, control_id, control_help = tail[:4], tail[4], None
        control_class = reader.ordinal_or_string()
        title = reader.ordinal_or_string()
        creation_size = reader.read("<H")
        # Standard size includes its own WORD; extended extraCount counts only
        # following bytes. A zero WORD represents no creation data in either.
        if creation_size and not extended and creation_size < 2:
            raise DialogError("Standard creation data size cannot be less than its size WORD")
        creation_bytes = creation_size if extended else max(0, creation_size - 2)
        reader.skip(creation_bytes)
        controls.append({
            "index": index, "template_offset": control_offset, "control_id": control_id,
            "help_id": control_help, "style": control_style, "extended_style": control_ex_style,
            "rect_dlu": _rectangle(control_rect), "window_class": control_class,
            "built_in_class_ordinal": (control_class["ordinal"] if control_class["kind"] == "ordinal"
                                       and 0x80 <= control_class["ordinal"] <= 0x85 else None),
            "title": title, "creation_size_word": creation_size,
            "creation_data_bytes": creation_bytes,
        })
    trailing = len(data) - reader.offset
    if trailing > 3 or any(data[reader.offset:]):
        raise DialogError("Unparsed non-padding data after dialog template")
    return {
        "format": "extended" if extended else "standard", "template_version": version,
        "help_id": help_id, "style": style, "extended_style": ex_style,
        "rect_dlu": _rectangle(rect), "coordinate_units": "dialog_units",
        "menu": menu, "window_class": window_class, "title_present": title_present,
        "font": font, "control_count": count, "controls": controls,
        "original_text_included": False, "creation_data_included": False,
        "runtime_observed": False,
    }


def _sha(path, *, expected_bytes=None, limit=512 * 1024 * 1024):
    """Hash a bounded immutable-size input; never chase a growing stream."""
    size = path.stat().st_size
    if size > limit or (expected_bytes is not None and size != expected_bytes):
        raise DialogError("Input size changed during dialog decoding or exceeds its byte limit")
    expected = size if expected_bytes is None else expected_bytes
    result = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        while read_bytes <= expected:
            block = stream.read(min(1024 * 1024, expected + 1 - read_bytes))
            if not block:
                break
            read_bytes += len(block)
            result.update(block)
    if read_bytes != expected:
        raise DialogError("Input size changed during dialog decoding")
    return result.hexdigest()


def dialog_catalogue(target, evidence) -> dict:
    """Observe numeric layouts from verified REA/PE resources, without names.

    The shared inventory verifies the actual PE directory and every listed
    resource digest. This phase rechecks target identity, exact payload digests,
    and source Evidence identity while reading dialogs. Decode failures remain
    explicit, and do not affect unrelated resource observations.
    """
    target, evidence = Path(target), Path(evidence)
    inventory = resource_catalogue(target, evidence, include_labels=False, decode_menus=False)
    if target.is_symlink() or _sha(target, expected_bytes=inventory["target"]["size_bytes"]) != inventory["target"]["sha256"]:
        raise DialogError("Target changed before dialog decoding")
    layouts, failures = [], []
    total_creation_bytes = charged_controls = total_dialog_bytes = 0
    with target.open("rb") as stream:
        for item in inventory["dialogs"]:
            offset, size = item["file_offset"], item["size_bytes"]
            total_dialog_bytes += size
            if total_dialog_bytes > MAX_TOTAL_DIALOG_BYTES:
                raise DialogError("Dialog catalogue exceeds 32 MiB payload budget")
            stream.seek(offset)
            blob = stream.read(size)
            if len(blob) != size or hashlib.sha256(blob).hexdigest() != item["payload_sha256"]:
                raise DialogError("Dialog payload changed during decoding")
            # Charge declared work before parsing, including aliased leaves and
            # templates that later fail. A global cap must not be swallowed as
            # a per-template decode failure and then continue more work.
            if len(blob) >= 4:
                count_offset = 16 if struct.unpack_from("<H", blob, 2)[0] == 0xFFFF else 8
                if len(blob) >= count_offset + 2:
                    charged_controls += struct.unpack_from("<H", blob, count_offset)[0]
                    if charged_controls > MAX_TOTAL_CONTROLS:
                        raise DialogError("Dialog catalogue exceeds 50000 declared total controls")
            # Names and named-language strings are deliberately omitted even
            # though the shared inventory retains them for private analysis.
            provenance = {"file_offset": offset, "size_bytes": size,
                          "payload_sha256": item["payload_sha256"],
                          "resource_id": item["resource"] if type(item["resource"]) is int else None,
                          "language_id": item["language"] if type(item["language"]) is int else None}
            try:
                layout = decode_dialog(blob)
                total_creation_bytes += sum(c["creation_data_bytes"] for c in layout["controls"])
                layouts.append({**provenance, "layout": layout})
            except DialogError as error:
                failures.append({**provenance, "reason": str(error)})
    if target.is_symlink() or _sha(target, expected_bytes=inventory["target"]["size_bytes"]) != inventory["target"]["sha256"]:
        raise DialogError("Target changed during dialog decoding")
    if evidence.is_symlink() or _sha(evidence, limit=16 * 1024 * 1024) != inventory["rea_evidence_sha256"]:
        raise DialogError("REA evidence changed during dialog decoding")
    # Oversized dialog leaves excluded by the shared bounded reader remain
    # explicit limits instead of disappearing from this decoder's accounting.
    excluded = sum(failure.get("type") == 5 for failure in inventory["decode_failures"])
    formats = Counter(item["layout"]["format"] for item in layouts)
    builtins = Counter(str(control["built_in_class_ordinal"])
                       for item in layouts for control in item["layout"]["controls"]
                       if control["built_in_class_ordinal"] is not None)
    raw_coverage = inventory["resource_inventory_coverage"]
    examined = raw_coverage.get("examined_entries")
    coverage = {"status": raw_coverage["status"], "resources": raw_coverage["resources"],
                "examined_entries": examined if type(examined) is int and 0 <= examined <= 200_000 else None}
    source_id = inventory["rea_evidence_id"]
    # The shared decoder accepts arbitrary caller receipt IDs. Only the REA
    # identifier syntax is safe to project publicly; do not copy arbitrary text.
    safe_id = source_id if re.fullmatch(r"ev_[a-f0-9]{64}", source_id) else None
    return {
        "schema_version": 1, "analysis": "static Win32 dialog template numeric layouts",
        "target": inventory["target"], "rea_evidence_id": safe_id,
        "rea_evidence_sha256": inventory["rea_evidence_sha256"],
        "resource_inventory_coverage": coverage,
        "pe_directory_crosscheck": inventory["pe_directory_crosscheck"],
        "dialogs_attempted": len(inventory["dialogs"]), "dialogs_decoded": len(layouts),
        "dialogs_excluded_by_inventory_limits": excluded,
        "format_counts": dict(sorted(formats.items())),
        "control_count": sum(item["layout"]["control_count"] for item in layouts),
        "declared_controls_charged": charged_controls,
        "dialog_payload_bytes_charged": total_dialog_bytes,
        "built_in_class_ordinal_counts": dict(sorted(builtins.items())),
        "opaque_creation_data_bytes_consumed": total_creation_bytes,
        "dialogs": layouts, "decode_failures": failures,
        "original_text_or_names_included": False, "original_creation_bytes_included": False,
        "runtime_observed": False, "gms_parity_established": False,
        "limitations": [
            "Dialog units depend on font metrics; no runtime pixel layout is inferred.",
            "Static templates do not establish dynamic controls, enabled states, handlers or displayed dialogs.",
            "Names, captions, typefaces and creation data content are omitted.",
            "REA receipt bytes and PE structure are cross-checked; receipt authorship is not authenticated here.",
            "Complete listed dialog decoding does not establish complete GUI or product coverage.",
        ],
    }


def main(argv=None):
    """Write scrubbed observations to a fresh caller-selected output file."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Static numeric Win32 dialog observations; no target execution")
    parser.add_argument("target", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise DialogError("Output exists; choose a fresh output file")
        result = dialog_catalogue(args.target, args.evidence)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(f"Static dialogs: {result['dialogs_decoded']} decoded; {result['control_count']} controls; "
              f"{len(result['decode_failures'])} decoding limitations")
        return 0
    except (ValueError, OSError) as error:
        print(f"Dialog reconstruction error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
