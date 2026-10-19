"""Run the authored geology I/O and finite-polyline section example."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.geology import (
    correlate_horizons, edit_interval_material, load_geology,
    project_section, save_geology, verify_geology_roundtrip,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args(argv)
    source = Path(__file__).parent / 'synthetic_boreholes.json'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    loaded = load_geology(source)
    # Retain an owned incomplete directory on an unexpected example failure.
    arguments.output.mkdir(parents=False, exist_ok=False)
    roundtrip = verify_geology_roundtrip(source, arguments.output / 'roundtrip')
    section = project_section(loaded.project, [[0, 0], [10, 0], [10, 10]], max_distance_m=4)
    contacts = correlate_horizons(loaded.project)
    for filename, value in [('section.json', section), ('contacts.json', contacts)]:
        (arguments.output / filename).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    edited = edit_interval_material(loaded.project, 'A', 'a2', 'clay',
                                    reason='Authored alternative material interpretation',
                                    provenance_id='authored')
    save_geology(edited, arguments.output / 'edited.json', asset_root=loaded.asset_root)
    reloaded = load_geology(arguments.output / 'edited.json', asset_root=loaded.asset_root)
    if reloaded.project.to_dict() != edited.to_dict() or hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise RuntimeError('Example source or edited roundtrip changed')
    result = {'schema': 'basinlens-geology-example-v1', 'synthetic_only': True,
              'json_csv_json_semantics_equal': roundtrip['json_csv_json_semantics_equal'],
              'source_unchanged': True, 'boreholes_in_section': len(section['boreholes']),
              'explicit_contact_count': sum(len(group['contacts']) for group in contacts['groups']),
              'traceable_edit_count': len(edited.to_dict()['history']),
              'original_gms_comparison': 'not performed',
              'crs': 'unknown', 'vertical_datum': 'unknown'}
    (arguments.output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
