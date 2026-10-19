"""Save, relocate and round-trip only synthetic registered project assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from basinlens_ccs.subsurface import load_project
from basinlens_ccs.subsurface.project_package import (
    open_project_package, save_project_package, verify_project_roundtrip,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='fresh output directory')
    args = parser.parse_args()
    root = args.output.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False)
    fixture = Path(__file__).resolve().parent
    project = load_project(fixture / 'project.json', check_assets=False)
    view = json.loads((fixture / 'view_state.json').read_text(encoding='utf-8'))
    package = save_project_package(project, root / 'synthetic.blproj',
                                   asset_root=fixture / 'assets', view_state=view)
    loaded = open_project_package(package, root / 'relocated')
    receipt = {'open': loaded.receipt, 'roundtrip': verify_project_roundtrip(package)}
    (root / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
