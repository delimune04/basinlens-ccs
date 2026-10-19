"""CI-only, explicitly invoked public solver preparation and strict test runner.

The versioned GitHub release itself is not marked immutable. Exact archive and
binary digests pin the accepted content; replacement fails closed. Ordinary
application import/export/run still never downloads a solver.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import time
import traceback
import unittest
import urllib.request
import zipfile

URL = "https://github.com/MODFLOW-ORG/executables/releases/download/29.0/linux.zip"
ASSET_ID = 430362036
ARCHIVE_BYTES = 45_010_855
ARCHIVE_SHA = "ab17192a3531dec61d4f4eab3da10f618e85d1f792d5edc71306a3e06e0e22c3"
BINARY_BYTES = 49_182_760
BINARY_SHA = "479185be33167701696604f7bb55acb4f96476f396e9bb015cbe7da52e278ec4"
BANNER = "mf6: 6.7.0 02/05/2026"
PROJECT = Path(__file__).resolve().parent.parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def solver_path():
    value = os.environ.get("MF6_EXE")
    if not value or not Path(value).is_absolute():
        raise RuntimeError("MF6_EXE must explicitly name an absolute pinned executable")
    return Path(value)


def verify_solver(path):
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != BINARY_BYTES
            or sha(path) != BINARY_SHA):
        raise RuntimeError("Actual MF6 binary differs from the exact study executable")
    version = subprocess.run([str(path), "-v"], capture_output=True, text=True, timeout=10, check=True)
    if version.stdout.strip() != BANNER or version.stderr.strip():
        raise RuntimeError("Pinned binary did not return the expected MF6 version banner")
    return {"sha256": BINARY_SHA, "bytes": BINARY_BYTES, "version": version.stdout.strip(),
            "resolved_path": str(path.resolve()), "version_stdout": version.stdout,
            "version_stderr": version.stderr, "version_returncode": version.returncode}


def prepare(report):
    path = solver_path()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError("The pinned public asset is Linux x86-64 only")
    if path.exists() or path.is_symlink() or path.parent.exists():
        raise FileExistsError("CI solver preparation requires a fresh destination directory")
    path.parent.mkdir(parents=True, exist_ok=False)
    archive = path.parent / "linux.zip"
    start = time.monotonic()
    size = 0
    with urllib.request.urlopen(URL, timeout=30) as source, archive.open("xb") as target:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > ARCHIVE_BYTES or time.monotonic() - start > 120:
                raise RuntimeError("Public solver download exceeded its size/time budget")
            target.write(chunk)
    if size != ARCHIVE_BYTES or sha(archive) != ARCHIVE_SHA:
        raise RuntimeError("Official versioned archive differs from the pinned asset content")
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        selected = [entry for entry in entries if entry.filename == "mf6"]
        if len(entries) > 256 or len(selected) != 1:
            raise RuntimeError("Expected exactly one literal mf6 member in the bounded official archive")
        entry = selected[0]
        if (entry.file_size != BINARY_BYTES or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)):
            raise RuntimeError("Unexpected executable member size/type")
        # Extract only this literal member; never use archive-controlled paths.
        with zipped.open(entry) as source, path.open("xb") as target:
            copied = 0
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > BINARY_BYTES:
                    raise RuntimeError("Executable member exceeds its pinned size")
                target.write(chunk)
    path.chmod(0o755)
    identity = verify_solver(path)
    archive.unlink()
    write_json(report / "solver.json", {"schema": "basinlens-ci-solver-v1",
        "release_url": "https://github.com/MODFLOW-ORG/executables/releases/tag/29.0",
        "release_tag": "29.0", "github_asset_id": ASSET_ID, "download_url": URL,
        "github_release_immutable_flag": False, "archive_bytes": ARCHIVE_BYTES,
        "archive_sha256": ARCHIVE_SHA, "binary": identity,
        "content_policy": "Exact pinned digests; no rolling latest or release-immutability assumption",
        "metadata_caveat": "Release prose lists MF6 6.6.3; actual verified contained binary identifies 6.7.0."})


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def run_tests(report):
    """Dedicated log survives Streamlit's stderr handling; every skip is fatal."""
    summary = {"schema": "basinlens-ci-real-mf6-tests-v1", "status": "failed",
        "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "platform": platform.platform(), "solver": None, "test_ids": [],
        "tests_run": 0, "failures": [], "errors": [], "skipped": [],
        "expected_failures": [], "unexpected_successes": [], "runner_stopped": False,
        "loader_errors_count": 0}
    started = time.monotonic()
    success = False
    with (report / "tests.log").open("w", encoding="utf-8") as log:
        try:
            summary["solver"] = verify_solver(solver_path())
            summary["packages"] = {name: importlib.metadata.version(name) for name in
                ("numpy", "pandas", "flopy", "h5py", "streamlit", "plotly")}
            files = subprocess.check_output(["git", "ls-files", "-z"], cwd=PROJECT).decode().split("\0")
            selected = [p for p in files if p and (p.endswith((".py", ".toml", ".yml", ".json", ".csv")))
                        and (p.startswith(("src/", "tests/", "tools/", "examples/", ".github/workflows/"))
                             or p in ("groundwater_app.py", "model_workspace.py", "app.py", "pyproject.toml"))]
            summary["source_sha256"] = {p: sha(PROJECT / p) for p in selected}
            summary["checkout_commit"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
            summary["github"] = {key: os.environ[key] for key in
                ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                 "ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH") if key in os.environ}
            freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
            (report / "pip-freeze.txt").write_text(freeze, encoding="utf-8")
            # MF6_EXE is verified before discovery imports optional skip guards.
            # Script execution starts sys.path in tools/, whereas `-m unittest`
            # includes the checkout root required by direct groundwater_app imports.
            sys.path.insert(0, str(PROJECT))
            suite = unittest.defaultTestLoader.discover(str(PROJECT / "tests"))
            summary["test_ids"] = list(test_ids(suite))
            summary["loader_errors_count"] = len(unittest.defaultTestLoader.errors)
            for error in unittest.defaultTestLoader.errors:
                log.write(error + "\n")
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            summary.update(tests_run=result.testsRun,
                failures=[test.id() for test, _ in result.failures],
                errors=[test.id() for test, _ in result.errors],
                skipped=[{"test": test.id(), "reason": reason} for test, reason in result.skipped],
                expected_failures=[test.id() for test, _ in result.expectedFailures],
                unexpected_successes=[test.id() for test in result.unexpectedSuccesses],
                runner_stopped=result.shouldStop)
            success = (bool(summary["test_ids"]) and result.testsRun == len(summary["test_ids"])
                       and len(set(summary["test_ids"])) == len(summary["test_ids"])
                       and not summary["loader_errors_count"]
                       and result.wasSuccessful() and not result.skipped
                       and not result.expectedFailures and not result.shouldStop)
            # Recheck after actual execution, not just before it.
            verify_solver(solver_path())
        except BaseException as error:
            success = False
            summary["runner_error_type"] = type(error).__name__
            traceback.print_exc(file=log)
        finally:
            summary["status"] = "passed" if success else "failed"
            summary["duration_seconds"] = time.monotonic() - started
            write_json(report / "tests.json", summary)
    print(json.dumps({key: summary[key] for key in ("status", "tests_run", "duration_seconds")}, allow_nan=False))
    return 0 if success else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "test", "finalize"))
    args = parser.parse_args(argv)
    os.chdir(PROJECT)
    report = Path(os.environ.get("CI_SOLVER_REPORT", "build/ci-real-mf6")).resolve()
    report.mkdir(parents=True, exist_ok=True)
    if args.command == "finalize":
        if not (report / "tests.json").is_file():
            write_json(report / "tests.json", {"schema": "basinlens-ci-real-mf6-tests-v1",
                "status": "not_run", "tests_run": 0,
                "reason": "Strict runner did not start; inspect dependency/solver preparation job steps.",
                "expected_solver_sha256": BINARY_SHA})
        return 0
    if args.command == "test":
        return run_tests(report)
    try:
        prepare(report)
        return 0
    except BaseException as error:
        write_json(report / "preparation_failure.json", {"status": "failed", "error_type": type(error).__name__,
            "message": str(error), "download_url": URL, "archive_sha256": ARCHIVE_SHA,
            "binary_sha256": BINARY_SHA})
        with (report / "preparation.log").open("w", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
