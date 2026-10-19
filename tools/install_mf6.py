"""Optional installer. No solver download occurs during import/export/run.

Uses the USGS MODFLOW-ORG executable release distribution through FloPy.
The binary and FloPy download metadata must not be committed to this repository.
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Explicit opt-in download of a MODFLOW 6 executable via FloPy")
    parser.add_argument("--accept-download", action="store_true", help="Authorize contacting GitHub and downloading the platform archive")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--release-id", default="latest", help="MODFLOW-ORG/executables release ID; pin for repeat installation")
    args = parser.parse_args()
    if not args.accept_download:
        parser.error("Downloading requires --accept-download; export/run do not download executables")
    try:
        from flopy.utils import get_modflow
    except ImportError:
        parser.error("Install FloPy first: python -m pip install flopy")
    args.destination.mkdir(parents=True, exist_ok=True)
    if any(args.destination.glob("mf6*")):
        parser.error("Destination already contains mf6; use a fresh directory to preserve the existing binary")
    get_modflow(args.destination, release_id=args.release_id, subset="mf6")


if __name__ == "__main__":
    main()
