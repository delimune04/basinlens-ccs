"""Read native MODFLOW 6 folders and GMS MF6 sidecars without running GMS.

This independent importer works with the native file graph exported by GMS;
it does not parse .gpr containers or reproduce GMS's native DMI protocol.
Numerical model loading is delegated to the public FloPy implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import sqlite3
import shutil
import tempfile
from typing import Any


MAX_FILES = 4096
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_DB_BYTES = 256 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 512 * 1024 * 1024


class NativeImportError(ValueError):
    """A native folder cannot be read within the explicit import boundary."""


def _inside(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def _words(line: str) -> list[str]:
    if line.lstrip().startswith("//"):
        return []
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#!"
    lexer.escape = ""  # Preserve Windows path separators in native input files.
    try:
        return list(lexer)
    except ValueError as error:
        raise NativeImportError(f"Malformed quoted native input: {error}") from error


def _parse_records(path: Path) -> list[tuple[str, list[str]]]:
    """Return (block, tokens); values remain native text instead of guessed units."""
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise NativeImportError(f"Text input exceeds the complete reference-scan limit: {path.name}")
    data = path.read_bytes()
    if b"\0" in data:
        raise NativeImportError(f"NUL byte in structural/native text input: {path.name}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise NativeImportError(f"Structural/native input is not UTF-8 text: {path.name}") from error
    block = ""
    records: list[tuple[str, list[str]]] = []
    for number, line in enumerate(text.splitlines(), 1):
        words = _words(line)
        if not words:
            continue
        keyword = words[0].upper()
        if keyword == "BEGIN":
            if len(words) < 2 or block:
                raise NativeImportError(f"Invalid BEGIN block in {path.name}:{number}")
            block = words[1].upper()
        elif keyword == "END":
            if len(words) < 2 or words[1].upper() != block:
                raise NativeImportError(f"Mismatched END block in {path.name}:{number}")
            block = ""
        else:
            records.append((block, words))
    if block:
        raise NativeImportError(f"Unclosed {block} block in {path.name}")
    return records


def _references(records: list[tuple[str, list[str]]]) -> list[dict]:
    references = []
    graph_blocks = {"TIMING", "MODELS", "EXCHANGES", "PACKAGES", "SOLUTIONGROUP"}
    for block, words in records:
        upper = [word.upper() for word in words]
        if block == "OPTIONS" and upper[0] == "LIST" and len(words) >= 2:
            references.append({"kind": "LIST", "path": words[1], "block": block,
                               "names": [], "input": False})
        if block in graph_blocks and len(words) >= 2 and upper[0].endswith("6"):
            references.append({"kind": upper[0], "path": words[1], "block": block,
                               "names": words[2:], "input": True})
        for index, token in enumerate(upper[:-1]):
            if token in {"FILEIN", "OPEN/CLOSE", "FILEOUT"}:
                references.append({"kind": token, "path": words[index + 1], "block": block,
                                   "names": [], "input": token != "FILEOUT",
                                   "binary": token == "OPEN/CLOSE" and any(
                                       word.strip("()") == "BINARY" for word in upper[index + 2:])})
    return references


def _resolve_reference(name: str, workspace: Path, allowed: Path) -> tuple[Path | None, str | None]:
    # Native MF6 relative paths are relative to the simulation working folder,
    # including package paths written in a model name file in a subdirectory.
    normalized = name.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//"):
        return None, "Windows absolute path requires an explicitly relocated native export"
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve()
    if not _inside(candidate, allowed):
        return None, "Reference is outside the allowed project directory"
    return candidate, None


def _json_sidecar(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise NativeImportError(f"JSON sidecar exceeds {MAX_JSON_BYTES} bytes: {path.name}")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise NativeImportError(f"Duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result
    def reject_nonfinite(value):
        raise NativeImportError(f"Non-finite JSON number in {path.name}: {value}")
    data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_nonfinite)
    if not isinstance(data, dict):
        raise NativeImportError(f"Expected a JSON object in {path.name}")
    def validate_numbers(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise NativeImportError(f"Non-finite JSON number in {path.name}")
        if isinstance(value, dict):
            for item in value.values():
                validate_numbers(item)
        elif isinstance(value, list):
            for item in value:
                validate_numbers(item)
    validate_numbers(data)
    return {"data": data, "sha256": _hash(path)}


def _period_database(path: Path, row_limit: int) -> dict:
    """Read observed table fields without executing database-provided SQL."""
    if path.stat().st_size > MAX_DB_BYTES:
        raise NativeImportError(f"Stress-period database exceeds {MAX_DB_BYTES} bytes")
    operations = 0
    def stop_expensive_query():
        nonlocal operations
        operations += 1
        return int(operations > 20_000)
    def reject_live_journals():
        for suffix in ("-wal", "-journal"):
            journal = path.with_name(path.name + suffix)
            if journal.exists() and journal.stat().st_size:
                raise NativeImportError("Close/checkpoint the stress-period database before importing live WAL/journal state")
    reject_live_journals()
    before = path.stat()
    # SQLite opens only a private immutable snapshot. It cannot create or update
    # source-directory WAL/SHM files, even when a journal mode is stored in the DB.
    temporary = tempfile.TemporaryDirectory(prefix="basinlens-periods-")
    snapshot = Path(temporary.name) / "periods.db"
    try:
        shutil.copyfile(path, snapshot)
        after = path.stat()
        reject_live_journals()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise NativeImportError("Stress-period database changed while taking its read-only snapshot")
        snapshot_sha256 = _hash(snapshot)
        return _read_period_snapshot(snapshot, row_limit, snapshot_sha256, stop_expensive_query)
    finally:
        temporary.cleanup()


def _read_period_snapshot(snapshot: Path, row_limit: int, snapshot_sha256: str, progress_callback) -> dict:
    uri = snapshot.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(progress_callback, 1000)
        actual_table = connection.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = ?", ("data",)
        ).fetchone()
        ordinary = next((row for row in connection.execute("PRAGMA table_list")
                         if row[0] == "main" and row[1] == "data"), None)
        if (not actual_table or actual_table[0] != "table" or ordinary is None or ordinary[2] != "table"
                or re.match(r"\s*CREATE\s+VIRTUAL\s+TABLE", actual_table[1] or "", re.IGNORECASE)):
            raise NativeImportError("Expected an ordinary 'data' table in periods.db")
        schema = connection.execute('PRAGMA table_info("data")').fetchall()
        columns = [row[1] for row in schema]
        if not {"PERIOD", "PERIOD_ROW"}.issubset(columns):
            raise NativeImportError("periods.db lacks PERIOD/PERIOD_ROW columns")
        count = connection.execute('SELECT COUNT(*) FROM "data"').fetchone()[0]
        periods = connection.execute(
            'SELECT "PERIOD", COUNT(*) FROM "data" GROUP BY "PERIOD" ORDER BY "PERIOD" LIMIT 10001'
        ).fetchall()
        if len(periods) > 10000:
            raise NativeImportError("periods.db has too many distinct stress periods")
        if any(type(period) is not int or period < 1 for period, _ in periods):
            raise NativeImportError("periods.db PERIOD values must be one-based integers")
        ordering = '"PERIOD", "PERIOD_ROW"' + (', "id"' if "id" in columns else "")
        rows = connection.execute(f'SELECT * FROM "data" ORDER BY {ordering} LIMIT ?', (row_limit,)).fetchall()
    def json_value(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise NativeImportError("Non-finite SQLite value in periods.db")
        return {"binary_hex": value.hex()} if isinstance(value, bytes) else value
    row_position = columns.index("PERIOD_ROW")
    if any(type(row[row_position]) is not int or row[row_position] < 0 for row in rows):
        raise NativeImportError("periods.db PERIOD_ROW values must be zero-based nonnegative integers")
    return {"sha256": snapshot_sha256, "columns": columns,
            "column_types": {row[1]: row[2] for row in schema}, "row_count": count,
            "period_counts": [{"period": period, "rows": number} for period, number in periods],
            "rows": [{name: json_value(value) for name, value in zip(columns, row)} for row in rows],
            "rows_truncated": count > len(rows),
            "index_convention": "PERIOD is one-based; PERIOD_ROW is zero-based. Native cell IDs are one-based; CELLIDX is a zero-based cache.",
            "native_sync": "Not established; sidecar rows are retained separately from exported solver files."}


def discover_simulations(source: str | Path) -> list[Path]:
    """Discover a direct native simulation or GMS's observed saved-model layout."""
    source = Path(source).resolve(strict=True)
    if source.is_file():
        if source.name.lower() == "mfsim.nam":
            return [source]
        if source.suffix.lower() != ".gpr":
            raise NativeImportError("Expected mfsim.nam, a .gpr path, or a project directory")
        search_roots = [source.parent / (source.stem + "_models") / "MODFLOW 6",
                        source.parent / (source.stem + "_data") / "Components"]
    elif (source / "mfsim.nam").is_file():
        return [source / "mfsim.nam"]
    else:
        search_roots = [source]
    results = []
    examined = 0
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for parent, directories, names in os.walk(search_root, followlinks=False):
            directories[:] = [name for name in directories if not Path(parent, name).is_symlink()]
            examined += len(directories) + len(names)
            if examined > 100_000:
                raise NativeImportError("Project discovery exceeds the directory inventory limit")
            for name in names:
                if name.lower() == "mfsim.nam":
                    candidate = Path(parent, name).resolve()
                    if _inside(candidate, search_root.resolve()):
                        results.append(candidate)
            if len(results) > 100:
                raise NativeImportError("More than 100 native simulations found")
    return sorted(set(results))


def import_native_simulation(source: str | Path, *, allowed_root: str | Path | None = None,
                             database_row_limit: int = 1000) -> dict:
    """Import a file graph, opaque GUI JSON, and bounded SQLite period records.

    The source data is read only. Unknown settings are preserved. No engine is
    started and no input is converted into a narrower application model.
    """
    if type(database_row_limit) is not int or not 0 <= database_row_limit <= 10000:
        raise NativeImportError("database_row_limit must be an integer from 0 to 10000")
    simulations = discover_simulations(source)
    if len(simulations) != 1:
        raise NativeImportError(f"Select one mfsim.nam; found {len(simulations)} simulations")
    main = simulations[0]
    workspace = main.parent
    supplied = Path(source).resolve(strict=True)
    default_root = supplied if supplied.is_dir() else (supplied.parent if supplied.suffix.lower() == ".gpr" else workspace)
    allowed = Path(allowed_root).resolve(strict=True) if allowed_root is not None else default_root
    if not allowed.is_dir() or not _inside(main, allowed):
        raise NativeImportError("Simulation must be within the allowed project directory")
    files, links, issues, sidecars = {}, [], [], {}
    charged_paths: set[Path] = set()
    total_input_bytes = 0
    def charge(path: Path):
        nonlocal total_input_bytes
        if path not in charged_paths:
            total_input_bytes += path.stat().st_size
            if total_input_bytes > MAX_TOTAL_INPUT_BYTES:
                raise NativeImportError(f"Native import exceeds the total {MAX_TOTAL_INPUT_BYTES}-byte input budget")
            charged_paths.add(path)
    queued = [main]
    binary_only = {main: False}
    models = []
    while queued:
        path = queued.pop(0)
        if path in files:
            continue
        if len(files) >= MAX_FILES:
            raise NativeImportError("Native input file graph exceeds the file count limit")
        relative = path.relative_to(allowed).as_posix()
        if not path.is_file():
            issues.append({"path": relative, "reason": "Referenced input file is missing"})
            files[path] = {"path": relative, "exists": False}
            continue
        charge(path)
        if path.stat().st_size > MAX_FILE_BYTES:
            issues.append({"path": relative, "reason": "Input exceeds the file size limit"})
            files[path] = {"path": relative, "exists": True, "loaded": False}
            continue
        records = [] if binary_only[path] else _parse_records(path)
        files[path] = {"path": relative, "exists": True, "loaded": True,
                       "bytes": path.stat().st_size, "sha256": _hash(path),
                       "scan": "declared_binary_array_leaf" if binary_only[path] else "complete_text",
                       "blocks": sorted({block for block, _ in records if block})}
        if path == main:
            models = [{"type": words[0].upper(), "name_file": words[1], "name": words[2]}
                      for block, words in records if block == "MODELS" and len(words) >= 3]
        for reference in _references(records):
            target, problem = _resolve_reference(reference["path"], workspace, allowed)
            link = {**reference, "from": relative,
                    "resolved": target.relative_to(allowed).as_posix() if target else None}
            links.append(link)
            if problem:
                issues.append({"path": reference["path"], "reason": problem})
            elif reference["input"]:
                binary_only[target] = binary_only.get(target, True) and reference.get("binary", False)
                if target in files and files[target].get("scan") == "declared_binary_array_leaf" and not binary_only[target]:
                    issues.append({"path": link["resolved"], "reason": "Structural reference also targets a declared binary array"})
                elif target not in files and target not in queued:
                    queued.append(target)
        for name in ("gms_options.json", "settings.json", "periods.db"):
            sidecar = (path.parent / name).resolve()
            if sidecar in sidecars or not sidecar.is_file():
                continue
            if not _inside(sidecar, allowed):
                issues.append({"path": name, "reason": "Sidecar is outside the allowed project directory"})
                continue
            charge(sidecar)
            try:
                data = _period_database(sidecar, database_row_limit) if name == "periods.db" else _json_sidecar(sidecar)
                sidecars[sidecar] = {"path": sidecar.relative_to(allowed).as_posix(), "kind": name, **data}
            except (OSError, ValueError, sqlite3.DatabaseError) as error:
                issues.append({"path": sidecar.relative_to(allowed).as_posix(), "reason": str(error)})
    return {"schema": "basinlens-gms-mf6-import-v1", "engine_executed": False,
            "workspace": str(workspace), "allowed_root": str(allowed),
            "simulation": main.relative_to(allowed).as_posix(), "models": models,
            "files": list(files.values()), "references": links, "sidecars": list(sidecars.values()),
            "total_input_bytes": total_input_bytes, "total_input_byte_limit": MAX_TOTAL_INPUT_BYTES,
            "issues": issues, "native_inputs_resolved": not issues,
            "scope": "Native MF6 export and sidecar import; .gpr contents, GUI parity and native DMI compatibility are unverified."}


def load_with_flopy(source: str | Path, *, allowed_root: str | Path | None = None):
    """Return (public FloPy MFSimulation, import report); no solver is run."""
    report = import_native_simulation(source, allowed_root=allowed_root)
    if not report["native_inputs_resolved"]:
        raise NativeImportError("Resolve native file/sidecar issues before loading with FloPy")
    try:
        import flopy
    except ImportError as error:
        raise NativeImportError("Install the groundwater extra to load numerical data with FloPy") from error
    simulation = flopy.mf6.MFSimulation.load(sim_ws=report["workspace"], verbosity_level=0,
                                          verify_data=True, strict=True)
    return simulation, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--allowed-root", type=Path)
    parser.add_argument("--database-rows", type=int, default=1000)
    args = parser.parse_args()
    try:
        report = import_native_simulation(args.source, allowed_root=args.allowed_root,
                                          database_row_limit=args.database_rows)
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"Native import failed: {error}\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
