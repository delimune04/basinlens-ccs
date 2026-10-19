"""Decode documented Windows menu templates from exact REA resource ranges.

The decoder never executes a target or recovers function bodies. Resource
observations are not claims about enabled commands or observed runtime behavior.
Binary formats: Microsoft's MENUITEMTEMPLATE / MENUEX_TEMPLATE_ITEM contracts.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

from .pe_resources import PEFormatError, inspect_resource_tree


class ResourceError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data, self.offset, self.count = data, offset, 0

    def read(self, fmt):
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise ResourceError("Truncated menu template")
        values = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return values[0] if len(values) == 1 else values

    def string(self):
        start = self.offset
        while self.read("<H"):
            if self.offset - start > 32768:
                raise ResourceError("Menu label exceeds bounded decoder limit")
        try:
            return self.data[start:self.offset - 2].decode("utf-16le", errors="strict")
        except UnicodeDecodeError as error:
            raise ResourceError("Invalid UTF-16 menu label") from error

    def align(self):
        self.offset = (self.offset + 3) & ~3
        if self.offset > len(self.data):
            raise ResourceError("Truncated aligned menu item")


def decode_menu(data: bytes) -> dict:
    """Decode standard/extended Windows menu templates, preserving command IDs."""
    if not isinstance(data, bytes) or len(data) > 2_000_000:
        raise ResourceError("Menu template must be bytes, at most 2 MB")
    reader = Reader(data)
    version, offset = reader.read("<2H")
    if version not in (0, 1):
        raise ResourceError(f"Unsupported menu template version {version}")
    if version == 1 and offset < 4:
        raise ResourceError("Extended menu header must contain its help ID")
    reader.offset = 4 + offset
    if reader.offset >= len(data):
        raise ResourceError("Menu header points outside its payload")

    def group(depth=0):
        if depth > 64:
            raise ResourceError("Menu nesting exceeds 64 levels")
        result = []
        while True:
            reader.count += 1
            if reader.count > 20_000:
                raise ResourceError("Menu exceeds 20000 items")
            if version == 1:
                reader.align()
                kind, state, command, flags = reader.read("<3IH")
                popup = bool(flags & 1)
            else:
                flags = reader.read("<H")
                popup = bool(flags & 0x10)
                # mtOption combines appearance and structural flags. It is not
                # MENUEX dwType/dwState: in particular MF_END (0x80) must never
                # be reported as the numerically identical MFS_HILITE state.
                kind = state = None
                command = None if popup else reader.read("<H")
            text = reader.string()
            item = {"command_id": command, "label": text, "popup": popup,
                    "flags": flags, "type": kind, "state": state,
                    "separator": bool((kind if version == 1 else flags) & 0x800)}
            if version == 0:
                item["standard_options"] = flags
            if popup:
                if version == 1:
                    reader.align()
                    item["help_id"] = reader.read("<I")
                item["children"] = group(depth + 1)
            result.append(item)
            if flags & 0x80:
                break
        return result

    items = group()
    # DWORD terminal alignment can exist. Other bytes remain an explicit limit.
    trailing = len(data) - reader.offset
    if trailing > 3 or any(data[reader.offset:]):
        raise ResourceError("Unparsed non-padding data after menu template")
    result = {"version": version, "items": items, "item_count": reader.count}
    if version == 1:
        result["header_help_id"] = struct.unpack_from("<I", data, 4)[0]
    return result


def _sha(path: Path, *, expected_bytes=None, limit=512 * 1024 * 1024):
    size = path.stat().st_size
    if size > limit or (expected_bytes is not None and size != expected_bytes):
        raise ResourceError("Input size changed during resource verification or exceeds its byte limit")
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
        raise ResourceError("Input size changed during resource verification")
    return result.hexdigest()


def _identity(value):
    if not isinstance(value, dict):
        raise ResourceError("Resource identity must be an object")
    if value.get("kind") == "id" and type(value.get("id")) is int and 0 <= value["id"] <= 0x7FFFFFFF:
        return value["id"]
    if value.get("kind") == "name" and isinstance(value.get("name"), str):
        return value["name"]
    raise ResourceError("Invalid resource identity")


def _typed_identity(value):
    return (value["kind"], _identity(value))


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResourceError(f"Duplicate REA evidence JSON field: {key}")
        result[key] = value
    return result


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ResourceError("Invalid resource SHA-256 digest")
    return value


def _range(value, expected_offset, expected_bytes):
    if (not isinstance(value, dict) or type(value.get("offset")) is not int
            or type(value.get("bytes")) is not int
            or (value["offset"], value["bytes"]) != (expected_offset, expected_bytes)):
        raise ResourceError("REA resource location differs from the actual PE directory")


def _resource_catalogue(target, evidence, *, include_labels=False, decode_menus=True) -> dict:
    """Bind a REA inventory to unchanged target bytes and decode its menus.

    No icons, bitmaps, audio, original resource bytes or recovered native source
    are exported. Optional functional text labels are observations, not copied
    artwork. Keep a caller-owned target and the full original REA receipt.
    """
    if type(include_labels) is not bool:
        raise ResourceError("include_labels must be an explicit boolean")
    if type(decode_menus) is not bool:
        raise ResourceError("decode_menus must be a boolean")
    target, evidence = Path(target), Path(evidence)
    if target.is_symlink() or not target.is_file():
        raise ResourceError("Target must be a regular file, not a symlink")
    if target.stat().st_size > 512 * 1024 * 1024:
        raise ResourceError("Target exceeds 512 MiB analysis limit")
    if evidence.is_symlink() or not evidence.is_file():
        raise ResourceError("REA evidence must be a regular file, not a symlink")
    evidence_size = evidence.stat().st_size
    if evidence_size > 16 * 1024 * 1024:
        raise ResourceError("REA evidence exceeds 16 MiB")
    with evidence.open("rb") as stream:
        evidence_bytes = stream.read(evidence_size + 1)
    if len(evidence_bytes) != evidence_size:
        raise ResourceError("REA evidence changed during bounded reading")
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    try:
        data = json.loads(evidence_bytes.decode("utf-8"), object_pairs_hook=_unique_pairs)
        operation = data["operation"]
        normalized = data["normalized_result"]
        artifact = normalized["artifact"]
        resources = normalized["resources"]
        if operation not in ("inspect_pe_resources", "inspect-pe-resources"):
            raise ResourceError("Evidence is not a REA PE-resource observation")
        if not isinstance(resources, list) or len(resources) > 65_536:
            raise ResourceError("Invalid resource inventory")
        _digest(artifact["sha256"])
        if type(artifact["bytes"]) is not int or artifact["sha256"] != _sha(target) or artifact["bytes"] != target.stat().st_size:
            raise ResourceError("REA subject identity does not match target bytes")
        evidence_id = data["evidence_id"]
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ResourceError("REA evidence ID is required")
    except (json.JSONDecodeError, UnicodeError, KeyError, TypeError) as error:
        raise ResourceError(f"Malformed REA evidence: {error}") from error

    counts = Counter()
    menus, dialogs, failures = [], [], []
    skipped_menus = 0
    commands = set()
    with target.open("rb") as stream:
        actual = inspect_resource_tree(stream, artifact["bytes"])
        if normalized.get("format") != actual["format"]:
            raise ResourceError("REA PE format differs from the actual target header")
        claimed_directory = normalized.get("directory")
        if actual["directory"] is None:
            if claimed_directory is not None or resources:
                raise ResourceError("REA claims resources absent from the actual PE header")
        else:
            if not isinstance(claimed_directory, dict) or claimed_directory.get("rva") != actual["directory"]["rva"]:
                raise ResourceError("REA resource-directory RVA differs from the PE header")
            _range(claimed_directory.get("location"), actual["directory"]["offset"], actual["directory"]["bytes"])
        coverage = normalized.get("coverage")
        if (not isinstance(coverage, dict) or coverage.get("status") not in ("complete", "partial")
                or type(coverage.get("resources")) is not int or coverage["resources"] != len(resources)):
            raise ResourceError("REA resource coverage is missing or inconsistent")
        seen_resources, payload_hashes = set(), {}
        total_hashed = 0
        for resource in resources:
            resource_key = tuple(_typed_identity(resource[key]) for key in ("type", "name", "language"))
            if resource_key in seen_resources:
                raise ResourceError("REA inventory contains a duplicate resource identity")
            seen_resources.add(resource_key)
            if resource_key not in actual["resources"]:
                raise ResourceError("REA resource identity is absent from the actual PE directory")
            leaf = actual["resources"][resource_key]
            kind = resource_key[0][1]
            counts[f"{resource_key[0][0]}:{kind}"] += 1
            name = _identity(resource["name"])
            language = _identity(resource["language"])
            payload = resource["payload"]
            location = payload["location"]
            offset, length = location["offset"], location["bytes"]
            _range(location, leaf["offset"], leaf["bytes"])
            if type(payload.get("rva")) is not int or payload["rva"] != leaf["rva"]:
                raise ResourceError("REA payload RVA differs from its actual PE data entry")
            entries = resource["entry_locations"]
            if not isinstance(entries, list) or len(entries) != 3:
                raise ResourceError("REA resource must record its three directory entries")
            for entry, entry_offset in zip(entries, leaf["entry_offsets"]):
                _range(entry, entry_offset, 8)
            _range(resource["data_entry_location"], leaf["data_entry_offset"], 16)
            for field in ("code_page", "reserved"):
                if type(resource.get(field)) is not int or resource[field] != leaf[field]:
                    raise ResourceError(f"REA resource {field} differs from its actual PE data entry")
            digest = _digest(payload["sha256"])
            span = (offset, length)
            if span not in payload_hashes:
                total_hashed += length
                if total_hashed > 512 * 1024 * 1024:
                    raise ResourceError("Distinct resource payload hashing exceeds the 512 MiB analysis limit")
                stream.seek(offset)
                remaining, hashed = length, hashlib.sha256()
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ResourceError("Resource payload was truncated during verification")
                    hashed.update(block)
                    remaining -= len(block)
                payload_hashes[span] = hashed.hexdigest()
            if payload_hashes[span] != digest:
                raise ResourceError(f"Resource payload identity mismatch: {name}")
            if kind not in (4, 5) or resource_key[0][0] != "id":
                continue
            if kind == 4 and not decode_menus:
                # Inventory-only callers still verify this PE leaf and exact
                # payload above, without allocating/decoding unrelated menus.
                skipped_menus += 1
                continue
            if length > 2_000_000:
                failures.append({"resource": name, "type": kind, "reason": "payload exceeds 2 MB decoder limit"})
                continue
            stream.seek(offset)
            blob = stream.read(length)
            provenance = {"resource": name, "language": language,
                          "payload_sha256": payload["sha256"], "file_offset": offset}
            if kind == 5:
                # Leave dialog payloads opaque: layout decoding is a separate step.
                dialogs.append({**provenance, "size_bytes": length, "layout_decoded": False})
                continue
            try:
                decoded = decode_menu(blob)
                def scrub(items):
                    for item in items:
                        command = item["command_id"]
                        if command is not None and not item["popup"] and not item["separator"] and command != 0:
                            commands.add(command)
                        if not include_labels:
                            item.pop("label", None)
                        scrub(item.get("children", []))
                scrub(decoded["items"])
                menus.append({**provenance, **decoded})
            except ResourceError as error:
                failures.append({**provenance, "type": kind, "reason": str(error)})
        if coverage["status"] == "complete" and seen_resources != set(actual["resources"]):
            raise ResourceError("Complete REA coverage omits actual PE resource leaves")
        if coverage["status"] == "complete" and coverage.get("examined_entries") != actual["examined_entries"]:
            raise ResourceError("Complete REA entry count differs from the actual PE resource tree")
    if _sha(target, expected_bytes=artifact["bytes"]) != artifact["sha256"]:
        raise ResourceError("Target changed during resource decoding")
    if evidence.is_symlink() or _sha(evidence, expected_bytes=evidence_size, limit=16 * 1024 * 1024) != evidence_sha256:
        raise ResourceError("REA evidence changed during resource decoding")
    result = {
        "schema_version": 1, "analysis": "static Windows PE menu observations",
        "target": {"sha256": artifact["sha256"], "size_bytes": artifact["bytes"]},
        "rea_evidence_id": evidence_id, "rea_evidence_sha256": evidence_sha256,
        "resource_inventory_coverage": coverage,
        "pe_directory_crosscheck": {"leaf_count": len(actual["resources"]),
                                    "listed_leaves_verified": len(seen_resources)},
        "type_counts": dict(sorted(counts.items())),
        "menus_decoded": len(menus), "dialogs_inventoried": len(dialogs),
        "unique_static_command_ids": len(commands), "labels_included": include_labels,
        "menus": menus, "dialogs": dialogs, "decode_failures": failures,
        "runtime_observed": False, "gms_parity_established": False,
        "limitations": ["Static resources can be unused, dynamically replaced, disabled or edition-specific",
                        "No command handler, interaction outcome or runtime layout was observed",
                        "Receipt bytes and PE structure are cross-checked; REA receipt authorship is not authenticated",
                        "Resource count is not a feature count; complete product coverage remains unknown"],
    }
    if not decode_menus:
        result["analysis"] = "static Windows PE resource inventory; menu decoding not requested"
        result["menu_decoding"] = {"requested": False, "resources_skipped": skipped_menus}
    return result


def resource_catalogue(target, evidence, *, include_labels=False, decode_menus=True) -> dict:
    """Validate and decode an exact REA inventory; malformed records fail cleanly."""
    try:
        return _resource_catalogue(target, evidence, include_labels=include_labels, decode_menus=decode_menus)
    except ResourceError:
        raise
    except (KeyError, TypeError, AttributeError, struct.error, PEFormatError, RecursionError) as error:
        raise ResourceError(f"Malformed REA resource inventory: {error}") from error
