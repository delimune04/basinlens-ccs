#!/usr/bin/env python3
"""Record a local GMS executable's identity and actual REA static evidence.

No target execution, downloads, patching, activation or network uploads. Outputs
can contain proprietary resource bytes: keep the output private, outside git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="Local installed GMS .exe (not its installer)")
    parser.add_argument("--output", type=Path, required=True, help="New private output directory")
    parser.add_argument("--rea", default="rea", help="Installed REA executable or scripts/rea.mjs")
    parser.add_argument("--node", default="node", help="Node executable when --rea is a .mjs/.js file")
    parser.add_argument("--native-provider", choices=["ghidra", "hopper", "ida"],
                        help="Also attempt configured static decompilation; never launches GMS")
    args = parser.parse_args()
    target = args.target.expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        parser.error("target must be a regular local file, not a symlink")
    size = target.stat().st_size
    if not 0 < size <= 512 * 1024 * 1024:
        parser.error("REA PE resource input must be at most 512 MiB; select the installed executable")
    with target.open("rb") as stream:
        if stream.read(2) != b"MZ":
            parser.error("target is not a PE executable (missing MZ header)")
    rea = shutil.which(args.rea) or (str(Path(args.rea).absolute()) if Path(args.rea).is_file() else None)
    if rea is None:
        parser.error("REA is not installed; install the official rea-agents package first")
    command = [args.node, rea] if Path(rea).suffix in (".mjs", ".js") else [rea]
    output = args.output.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=False)
    try:
        output.chmod(0o700)
    except OSError:
        pass
    operations = [
        ("version", ["--version"], 30),
        ("pe_resources", ["inspect-pe-resources", str(target), "--max-file-bytes", str(size), "--json"], 120),
        ("managed_identity", ["inspect-managed-artifact", str(target), "--json"], 120),
    ]
    if shutil.which("objdump"):
        operations.append(("file_headers", ["inspect-with-objdump", str(target), "file_headers", "--json"], 120))
    if args.native_provider:
        operations.append(("native_analysis", ["analyze", str(target), "--provider", args.native_provider, "--json"], 600))
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target_name": target.name, "target_size_bytes": size, "target_sha256": digest(target),
        "host_platform": sys.platform, "python": sys.version.split()[0],
        "target_executed": False, "uploaded": False, "operations": [],
        "interpretation": "Static evidence only. Does not establish behavioral or numerical equivalence to GMS.",
    }
    for name, arguments, timeout in operations:
        print(f"REA: {name}", flush=True)
        try:
            result = subprocess.run(command + arguments, capture_output=True, timeout=timeout, check=False)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, code = error.stdout or b"", error.stderr or b"", None
        except OSError as error:
            stdout, stderr, code = b"", str(error).encode(), None
        stdout_path, stderr_path = output / f"{name}.json", output / f"{name}.stderr.txt"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        manifest["operations"].append({
            "operation": name, "arguments": arguments, "returncode": code,
            "stdout": stdout_path.name, "stdout_sha256": digest(stdout_path),
            "stderr": stderr_path.name, "stderr_sha256": digest(stderr_path),
        })
    manifest["target_unchanged"] = digest(target) == manifest["target_sha256"]
    (output / "inspection.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    succeeded = next(o for o in manifest["operations"] if o["operation"] == "pe_resources")["returncode"] == 0
    print(f"Evidence recorded in {output}. PE resources {'completed' if succeeded else 'failed'}; inspect all operation statuses.")
    return 0 if succeeded and manifest["target_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
