"""Execute explicitly selected feature test modules for status bootstrap evidence.

This is a selected-module run. It cannot report full-suite CI or original GMS
comparison. After status evidence is rebound, the required full CI still runs.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def selected_run(modules: list[str], output: Path) -> dict:
    """Run exactly named local modules, recording every outcome and byte binding."""
    if (not modules or len(modules) > 64 or len(modules) != len(set(modules)) or
            any(not re.fullmatch(r'test_[a-z0-9_]+', module) for module in modules)):
        raise ValueError('Provide 1..64 distinct literal test_* module names')
    available = {path.stem for path in (PROJECT / 'tests').glob('test_*.py') if path.is_file() and not path.is_symlink()}
    if not set(modules) <= available:
        raise ValueError('Selected module is missing or is not a regular repository test file')
    output = output.absolute()
    log_path = output.with_suffix('.log')
    if output.exists() or output.is_symlink() or log_path.exists() or log_path.is_symlink():
        raise FileExistsError('Choose new receipt and log paths; existing evidence is never overwritten')
    if not output.parent.is_dir():
        raise FileNotFoundError('Receipt parent directory must already exist')
    record = {'schema': 'basinlens-feature-tests-v1', 'status': 'failed',
        'scope': 'Explicitly selected feature modules only; not complete-suite CI or original GMS comparison.',
        'full_suite': False,
        'selection': {'modules': modules, 'unselected_modules': sorted(available - set(modules)),
                      'method': 'unittest.loadTestsFromNames for the exact named modules'},
        'started_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
        'platform': platform.platform(), 'test_ids': [], 'tests_run': 0, 'failures': [], 'errors': [],
        'skipped': [], 'expected_failures': [], 'unexpected_successes': [], 'runner_stopped': False,
        'loader_errors_count': 0, 'solver': None}
    started = time.monotonic()
    with log_path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        try:
            listed = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=PROJECT).decode().split('\0')
            sources = sorted({name for name in listed if name and (
                name.startswith(('src/', 'tests/', 'tools/', 'examples/', '.github/workflows/')) and name.endswith(('.py', '.json', '.csv', '.yml', '.toml'))
                or name in ('groundwater_app.py', 'model_workspace.py', 'geoscience_workspace.py', 'inference_workspace.py', 'app.py', 'pyproject.toml'))})
            if any((PROJECT / name).is_symlink() or not (PROJECT / name).is_file() for name in sources):
                raise ValueError('Source snapshot requires regular files')
            record['source_sha256'] = {name: sha(PROJECT / name) for name in sources}
            record['checkout_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
            record['packages'] = {}
            for name in ('numpy', 'pandas', 'flopy', 'h5py', 'streamlit', 'plotly'):
                try: record['packages'][name] = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError: record['packages'][name] = None
            if os.environ.get('MF6_EXE'):
                solver = Path(os.environ['MF6_EXE'])
                if not solver.is_absolute() or solver.is_symlink() or not solver.is_file():
                    raise ValueError('MF6_EXE must name an explicit absolute regular executable')
                version = subprocess.run([str(solver), '-v'], capture_output=True, text=True, timeout=10, check=True)
                record['solver'] = {'sha256': sha(solver), 'size_bytes': solver.stat().st_size,
                    'version_stdout': version.stdout, 'version_stderr': version.stderr, 'returncode': version.returncode}
            sys.path.insert(0, str(PROJECT))
            sys.path.insert(0, str(PROJECT / 'src'))
            sys.path.insert(0, str(PROJECT / 'tests'))
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(modules)
            record['test_ids'] = list(test_ids(suite))
            record['loader_errors_count'] = len(loader.errors)
            if len(record['test_ids']) > 2000:
                raise ValueError('Selected feature test count exceeds the 2000-case budget')
            for error in loader.errors: log.write(error + '\n')
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            record.update(tests_run=result.testsRun,
                failures=[test.id() for test, _ in result.failures], errors=[test.id() for test, _ in result.errors],
                skipped=[{'test': test.id(), 'reason': reason} for test, reason in result.skipped],
                expected_failures=[test.id() for test, _ in result.expectedFailures],
                unexpected_successes=[test.id() for test in result.unexpectedSuccesses], runner_stopped=result.shouldStop)
            after = {name: sha(PROJECT / name) for name in sources}
            if after != record['source_sha256']:
                raise ValueError('Source files changed during the selected feature run')
            if record['solver'] is not None and sha(solver) != record['solver']['sha256']:
                raise ValueError('Solver bytes changed during the selected feature run')
            passed = (bool(record['test_ids']) and len(set(record['test_ids'])) == len(record['test_ids']) and
                result.testsRun == len(record['test_ids']) and result.wasSuccessful() and not loader.errors and
                not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses and not result.shouldStop)
            record['status'] = 'passed' if passed else 'failed'
        except Exception as exc:
            record['runner_error_type'] = type(exc).__name__
            traceback.print_exc(file=log)
        finally:
            record['duration_seconds'] = time.monotonic() - started
    record['log'] = {'file_name': log_path.name, 'size_bytes': log_path.stat().st_size, 'sha256': sha(log_path)}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run',))
    parser.add_argument('--test-module', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record = selected_run(args.test_module, args.output)
        print(json.dumps({key: record[key] for key in ('schema', 'status', 'full_suite', 'tests_run', 'duration_seconds')}))
        return 0 if record['status'] == 'passed' else 1
    except (OSError, ValueError) as exc:
        print(f'Feature test run refused: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
