"""Bounded inert ZIP downloads of an unchanged, trusted workspace directory."""
from __future__ import annotations

import io
from pathlib import Path
import stat
import zipfile

from . import project_package as package

MAX_BYTES = 128 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_FILES = 5_000
MAX_DEPTH = 32


def create_workspace_zip(directory, *, max_bytes=MAX_BYTES, max_entries=MAX_ENTRIES):
    """Return bytes only after bounded reads and a complete source recheck.

    Parent directories must be trusted against concurrent hostile replacement,
    as for project packages. This checks file consistency, not model validity.
    Empty directories are inspected but are not emitted, matching the old UI.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError("ZIP byte budget must be an integer in 1..128 MiB")
    if type(max_entries) is not int or not 1 <= max_entries <= MAX_ENTRIES:
        raise ValueError("ZIP entry budget must be an integer in 1..10000")
    root = package._path_no_links(directory, directory=True)

    def inventory():
        result, stack, total, files = {}, [root], 0, 0
        while stack:
            folder = package._path_no_links(stack.pop(), directory=True)
            for path in folder.iterdir():
                name = path.relative_to(root).as_posix()
                package._safe_name(name)
                if len(path.relative_to(root).parts) > MAX_DEPTH or len(result) >= max_entries:
                    raise ValueError("ZIP workspace entry/depth budget exceeded")
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    files += 1
                    total += info.st_size
                    if files > MAX_FILES or total > max_bytes:
                        raise ValueError("ZIP workspace file/byte budget exceeded")
                else:
                    raise ValueError("ZIP accepts regular files and directories only")
                result[name] = (stat.S_ISREG(info.st_mode), package._identity(info))
        package._check_names([name for name, (regular, _) in result.items() if regular])
        return package._identity(root.stat()), result

    before = inventory()
    buffer, total = io.BytesIO(), 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, (regular, identity) in sorted(before[1].items()):
            if not regular:
                continue
            path = root / name
            if package._identity(path.lstat()) != identity:
                raise ValueError("ZIP source changed after inventory")
            raw = package._read_file(path, max_bytes - total)
            total += len(raw)
            if package._identity(path.lstat()) != identity:
                raise ValueError("ZIP source changed during capture")
            archive.writestr(name, raw)
            if buffer.tell() > max_bytes:
                raise ValueError("ZIP compressed byte budget exceeded")
    if buffer.tell() > max_bytes:
        raise ValueError("ZIP compressed byte budget exceeded")
    if inventory() != before:
        raise ValueError("ZIP workspace changed during capture")
    return buffer.getvalue()
