"""Bounded PE resource-directory cross-check, without executing an image.

This independent structural check follows Microsoft's public PE/COFF format:
https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
Only the conventional type/name/language tree is supported. Neither signatures
nor the provenance of a supplied REA receipt are authenticated here.
"""
from __future__ import annotations

import struct


class PEFormatError(ValueError):
    pass


def inspect_resource_tree(stream, file_size):
    """Return actual leaf locations keyed by typed resource identities."""
    def read(offset, length):
        if offset < 0 or length < 0 or offset + length > file_size:
            raise PEFormatError("PE structure points outside the image")
        stream.seek(offset)
        value = stream.read(length)
        if len(value) != length:
            raise PEFormatError("PE image changed or was truncated")
        return value

    def unpack(fmt, offset):
        values = struct.unpack(fmt, read(offset, struct.calcsize(fmt)))
        return values[0] if len(values) == 1 else values

    if read(0, 2) != b"MZ":
        raise PEFormatError("Target has no DOS image signature")
    pe = unpack("<I", 0x3C)
    if read(pe, 4) != b"PE\0\0":
        raise PEFormatError("Target has no PE image signature")
    section_count = unpack("<H", pe + 6)
    optional_size = unpack("<H", pe + 20)
    if not 1 <= section_count <= 96:
        raise PEFormatError("PE image must have 1 to 96 sections")
    optional = pe + 24
    magic = unpack("<H", optional)
    if magic not in (0x10B, 0x20B):
        raise PEFormatError("Only PE32 and PE32+ image headers are supported")
    directory_start = 96 if magic == 0x10B else 112
    if optional_size < directory_start + 24:
        raise PEFormatError("PE optional header has no complete resource data directory")
    if unpack("<I", optional + directory_start - 4) < 3:
        raise PEFormatError("PE image declares no resource data-directory entry")
    resource_rva, resource_size = unpack("<2I", optional + directory_start + 16)
    sections = []
    for index in range(section_count):
        at = optional + optional_size + 40 * index
        virtual_size, virtual_address, raw_size, raw_offset = unpack("<4I", at + 8)
        read(at, 40)
        if raw_offset + raw_size > file_size:
            raise PEFormatError("PE section raw bytes extend outside the image")
        sections.append((virtual_address, raw_size, raw_offset))

    def map_rva(rva, size):
        matches = [raw + rva - start for start, length, raw in sections
                   if rva >= start and rva + size <= start + length]
        if len(matches) != 1:
            raise PEFormatError("Resource RVA has no unique file-backed PE section")
        return matches[0]

    if not resource_rva and not resource_size:
        return {"format": "pe32" if magic == 0x10B else "pe32-plus",
                "directory": None, "resources": {}, "examined_entries": 0}
    if not resource_rva or resource_size < 16:
        raise PEFormatError("Invalid PE resource-directory extent")
    base = map_rva(resource_rva, resource_size)

    def resource_read(relative, length):
        if relative < 0 or relative + length > resource_size:
            raise PEFormatError("Resource structure is outside its data directory")
        return read(base + relative, length)

    def identity(word):
        if not word & 0x80000000:
            return ("id", word)
        at = word & 0x7FFFFFFF
        length = struct.unpack("<H", resource_read(at, 2))[0]
        if length > 16384:
            raise PEFormatError("Resource name exceeds the bounded decoder limit")
        try:
            name = resource_read(at + 2, length * 2).decode("utf-16le", errors="strict")
        except UnicodeDecodeError as error:
            raise PEFormatError("Invalid UTF-16 resource name") from error
        return ("name", name)

    leaves = {}
    examined = 0

    def directory(relative, path=(), locations=(), ancestors=frozenset()):
        nonlocal examined
        if len(path) > 2 or relative in ancestors:
            raise PEFormatError("Unsupported resource depth or cyclic directory")
        header = resource_read(relative, 16)
        named, numbered = struct.unpack_from("<2H", header, 12)
        count = named + numbered
        resource_read(relative + 16, count * 8)
        siblings = set()
        for index in range(count):
            examined += 1
            if examined > 200_000:
                raise PEFormatError("Resource tree exceeds 200000 directory entries")
            at = relative + 16 + index * 8
            name_word, child = struct.unpack("<2I", resource_read(at, 8))
            item = identity(name_word)
            if (index < named) != (item[0] == "name") or item in siblings:
                raise PEFormatError("Resource directory has inconsistent or duplicate identities")
            siblings.add(item)
            item_path = (*path, item)
            item_locations = (*locations, base + at)
            if child & 0x80000000:
                if len(item_path) == 3:
                    raise PEFormatError("Resource tree exceeds type/name/language depth")
                directory(child & 0x7FFFFFFF, item_path, item_locations, ancestors | {relative})
                continue
            if len(item_path) != 3:
                raise PEFormatError("Resource leaf lacks type/name/language identity")
            rva, size, code_page, reserved = struct.unpack("<4I", resource_read(child, 16))
            location = map_rva(rva, size)
            if item_path in leaves or len(leaves) >= 65_536:
                raise PEFormatError("Duplicate resource leaf or excessive resource count")
            leaves[item_path] = {"entry_offsets": item_locations,
                "data_entry_offset": base + child, "rva": rva,
                "offset": location, "bytes": size, "code_page": code_page,
                "reserved": reserved}

    directory(0)
    return {"format": "pe32" if magic == 0x10B else "pe32-plus",
            "directory": {"rva": resource_rva, "offset": base, "bytes": resource_size},
            "resources": leaves, "examined_entries": examined}
