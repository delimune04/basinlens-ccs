"""Authored mesh generation/refinement/extrusion and optional actual DISV run.

Use a fresh output directory. Original GMS comparison is explicitly absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from basinlens_ccs.subsurface.mesh import (PlanarMesh, extrude_mesh, read_mesh,
    refine_quadtree, render_data, structured_mesh, to_disv, topology,
    verify_mesh_roundtrip, write_mesh)


def dump(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--exe", help="Explicit authorized local MF6 executable; omitted means geometry only")
    args = parser.parse_args(argv)
    output = Path(args.output).absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("Output may not traverse symbolic links")
    output.mkdir(parents=True, exist_ok=False)
    base = structured_mesh([350000, 350002, 350005, 350009], [4100000, 4100003, 4100007],
                           crs="LOCAL:authored synthetic meter coordinates; no geodetic registration", material_id="synthetic-sand")
    mesh = refine_quadtree(base, levels=2, points_m=[[350001, 4100001]])
    source = write_mesh(mesh, output / "source.mesh.json")
    receipt = verify_mesh_roundtrip(source)
    moved = output / "relocated"; moved.mkdir()
    write_mesh(read_mesh(source), moved / "mesh.json")
    loaded = read_mesh(moved / "mesh.json")
    if loaded.to_dict() != mesh.to_dict():
        raise RuntimeError("Relocation changed the authored mesh")
    report = topology(loaded)
    if report["area_m2"] != 63:
        raise RuntimeError("Nonuniform source frame area changed during refinement")
    solid = extrude_mesh(loaded, [10, 6, -1], vertical_datum="LOCAL:authored synthetic zero elevation",
                         material_ids=["synthetic-upper" if layer == 0 else "synthetic-lower"
                                       for layer in range(2) for _ in loaded.to_dict()["cells"]])
    if solid["total_volume_m3"] != 693:
        raise RuntimeError("Explicit flat prism volume disagrees with hand calculation 9*7*11")
    dump(output / "roundtrip.json", receipt)
    dump(output / "render.json", render_data(loaded))
    dump(output / "prisms.json", solid)
    dump(output / "disv_geometry.json", to_disv(loaded, [10, 0]))
    summary = {"schema": "basinlens-mesh-example-v1", "source_kind": "authored_synthetic",
               "original_gms_comparison": "NOT_OBSERVED", "topology": report,
               "prism_volume_m3": solid["total_volume_m3"], "solver_executed": False}
    if args.exe:
        import flopy
        import numpy as np
        from basinlens_ccs.groundwater.native_run import run_native_simulation, verify_native_run
        native = output / "native_input"
        sim = flopy.mf6.MFSimulation(sim_name="authored-disv", sim_ws=str(native))
        sim.simulation_data.float_precision = 17
        sim.simulation_data.float_characters = 26
        flopy.mf6.ModflowTdis(sim, time_units="DAYS", perioddata=[(1, 1, 1)])
        flopy.mf6.ModflowIms(sim, outer_dvclose=1e-10, inner_dvclose=1e-11, rcloserecord=1e-9)
        model = flopy.mf6.ModflowGwf(sim, modelname="mesh", save_flows=True)
        native_geometry = to_disv(loaded, [10, 0])
        flopy.mf6.ModflowGwfdisv(model, **native_geometry)
        flopy.mf6.ModflowGwfic(model, strt=2)
        flopy.mf6.ModflowGwfnpf(model, icelltype=0, k=1)
        boundary = [cell["id"] for cell in loaded.to_dict()["cells"]
                    if any(set(edge).issubset(cell["vertices"]) for edge in report["boundary_edges"])]
        flopy.mf6.ModflowGwfchd(model, stress_period_data=[((0, i), 3) for i in boundary])
        flopy.mf6.ModflowGwfoc(model, head_filerecord="mesh.hds", budget_filerecord="mesh.cbc",
                             saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
        sim.write_simulation(silent=True)
        reloaded = flopy.mf6.MFSimulation.load(sim_ws=str(native), verbosity_level=0).get_model().modelgrid
        xy = np.column_stack((reloaded.xcellcenters, reloaded.ycellcenters))
        if (not np.allclose(xy, report["centres_m"], rtol=0, atol=1e-9)
                or not np.allclose(reloaded.verts, np.asarray(native_geometry["vertices"])[:, 1:], rtol=0, atol=1e-9)
                or [list(map(int, ring)) for ring in reloaded.iverts] != [row[4:] for row in native_geometry["cell2d"]]
                or not np.array_equal(reloaded.top, native_geometry["top"])
                or not np.array_equal(reloaded.botm, native_geometry["botm"])):
            raise RuntimeError("Export/reload changed physical vertices, centroids, connectivity or elevations")
        result = run_native_simulation(native, output / "actual_run", exe_name=args.exe)
        metadata = verify_native_run(result.workspace)
        with flopy.utils.HeadFile(str(result.simulation_workspace / "mesh.hds"), precision="double") as reader:
            heads = reader.get_alldata()
        error = float(np.max(np.abs(heads - 3)))
        if error > 1e-9:
            raise RuntimeError(f"Uniform-head analytical check failed: {error}")
        summary.update(solver_executed=True, native_run_status=metadata["status"], maximum_uniform_head_error_m=error,
                       native_source_unchanged=metadata["original_sources_unchanged"])
    dump(output / "summary.json", summary)
    files = {path.relative_to(output).as_posix(): {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(output.rglob("*")) if path.is_file()}
    dump(output / "manifest.json", {"schema": "basinlens-mesh-example-inventory-v1", "files": files})
    print(json.dumps({"output": str(output), "cells": report["cells"], "area_m2": report["area_m2"],
                      "volume_m3": solid["total_volume_m3"], "solver_executed": summary["solver_executed"],
                      "original_gms_comparison": "NOT_OBSERVED"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
