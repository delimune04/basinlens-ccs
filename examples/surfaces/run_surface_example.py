"""Authored analytical planes: preserve, query, section and extrude a TIN."""
import argparse
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.surfaces import (
    edit_vertices, extrude_solids, load_surfaces, query_surface, save_surfaces,
    section_surfaces, verify_surface_roundtrip,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir()  # Fresh output is required; no overwrite or implicit retries.
    source = Path(__file__).with_name("tilted_planes.json")
    before = source.read_bytes()
    model = load_surfaces(source)
    receipt = verify_surface_roundtrip(source, args.output / "roundtrip")
    query = query_surface(model, "top", [[1, 0.5], [2, 1], [4.1, 1]])
    solids = extrude_solids(model)
    section = section_surfaces(model, [[-1, 1], [5, 1], [5, 3]])
    edited = edit_vertices(model, horizon_id="top", elevations={"A": 11}, reason="Authored synthetic alternative; no observation claim")
    save_surfaces(edited, args.output / "edited.json")
    for name, value in (("queries.json", query), ("solids.json", solids), ("section.json", section)):
        (args.output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    # Independent calculations, not just a writer reading its own output.
    assert solids["total_volume_m3"] == 8 * (5 + 1) == 48
    assert query["points"][0]["elevation_m"] == 10 + 1 + 2 * 0.5 == 12
    assert not query["points"][2]["supported"]
    assert [piece["distance_m"] for piece in section["pieces"]] == [[1, 3], [3, 5]]
    assert source.read_bytes() == before
    summary = {"source_file_sha256": hashlib.sha256(before).hexdigest(), "model_sha256": model.sha256, "source_unchanged": True, "expected_volume_m3": 48, "actual_volume_m3": solids["total_volume_m3"], "json_csv_roundtrip": receipt, "original_gms_comparison": "NOT_OBSERVED", "scope": "authored analytical TIN horizons and prism geometry; no field or solver validation"}
    (args.output / "example_receipt.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
