"""Independent geometry, field, I/O, corruption and command-line checks."""
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.groundwater import demo_case
from basinlens_ccs.subsurface import DataAsset, SubsurfaceProject, project_from_groundwater
from basinlens_ccs.subsurface.raster import (
    RasterError, RasterGrid, clip_raster, create_catalog, export_ascii_bundle,
    load_raster, main, merge_rasters, open_ascii_bundle, open_catalog,
    raster_to_scatter, read_ascii, resample_raster, sample_project_property,
    sample_raster, save_raster, verify_roundtrip,
)


def fixture(**changes):
    # Centres: x = 101,103,105; y north-to-south = 203,201.
    # Linear field f(x,y)=2*(x-100)+3*(y-200): north 11,15,19; south 5,9,13.
    data = dict(asset_id="linear", geometry=dict(nrow=2,ncol=3,xllcorner_m=100,yllcorner_m=200,dx_m=2,dy_m=2),
                values=[[11,15,19],[5,9,13]],crs="LOCAL:synthetic-metre",vertical_datum="synthetic-z=0",
                quantity="head",unit="m",provenance=["Authored synthetic linear field f=2(x-100)+3(y-200)"],nodata=-9999)
    data.update(changes)
    return RasterGrid(**data)


def metadata(grid):
    return {k:grid.to_dict()[k] for k in ("asset_id","crs","vertical_datum","coordinate_unit","quantity","unit","provenance")}


class RasterSchemaTests(unittest.TestCase):
    def test_json_deterministic_exact_roundtrip_and_no_overwrite(self):
        g=fixture(values=[[11,None,19],[5,9,13]])
        with tempfile.TemporaryDirectory() as td:
            p=save_raster(g,Path(td)/"one.json")
            self.assertEqual(load_raster(p).to_dict(),g.to_dict())
            q=save_raster(load_raster(p),Path(td)/"two.json")
            self.assertEqual(p.read_bytes(),q.read_bytes())
            with self.assertRaises(RasterError): save_raster(g,p)
            self.assertEqual(load_raster(p).values[0][1],None)

    def test_strict_unknown_keys_numeric_bounds_and_units(self):
        for mutator in (
            lambda d:d.update(extra=1),lambda d:d.update(schema="other"),lambda d:d.update(row_axis="south_to_north"),
            lambda d:d.update(unit="ft"),lambda d:d.update(coordinate_unit="ft"),lambda d:d.update(provenance=[]),
            lambda d:d.update(asset_id="../x"),lambda d:d["geometry"].update(nrow=True),
            lambda d:d["geometry"].update(nrow=10000,ncol=10000),lambda d:d["geometry"].update(dx_m=0),
            lambda d:d["geometry"].update(xllcorner_m=1e20),lambda d:d.update(values=[[1,2],[3,4]]),
            lambda d:d.update(values=[[True,15,19],[5,9,13]]),lambda d:d.update(nodata=float("nan")),
            lambda d:d.update(values=[[float("inf"),15,19],[5,9,13]]),lambda d:d.update(nodata=11),
        ):
            data=fixture().to_dict(); mutator(data)
            with self.subTest(data=data), self.assertRaises(RasterError): RasterGrid.from_dict(data)

    def test_duplicate_nonfinite_json_and_fifo_symlinks_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/"bad.json"
            for raw in ('{"x":1,"x":2}','{"x":NaN}', '{"x":Infinity}', '[]'):
                p.write_text(raw)
                with self.assertRaises(RasterError):load_raster(p)
            if hasattr(os,"mkfifo"):
                fifo=root/"fifo";os.mkfifo(fifo)
                with self.assertRaises(RasterError):load_raster(fifo)
            source=save_raster(fixture(),root/"valid.json")
            (root/"link").symlink_to(source)
            with self.assertRaises(RasterError):load_raster(root/"link")
            (root/"dirlink").symlink_to(root,target_is_directory=True)
            with self.assertRaises(RasterError):load_raster(root/"dirlink"/"valid.json")

    def test_valid_extent_and_independent_area(self):
        self.assertEqual(fixture().extent,[100,200,106,204])
        x0,y0,x1,y1=fixture().extent
        self.assertEqual((x1-x0)*(y1-y0),6*2*2)

    def test_source_path_replacement_during_actual_read_is_rejected(self):
        from basinlens_ccs.subsurface import raster
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=save_raster(fixture(),root/"source.json")
            replacement=root/"replacement.json";replacement.write_text("{}")
            real_fdopen=raster.os.fdopen
            class ReplacingReader:
                def __init__(self,handle):self.handle=handle
                def __enter__(self):return self
                def __exit__(self,*args):return self.handle.__exit__(*args)
                def fileno(self):return self.handle.fileno()
                def read(self,*args):
                    raw=self.handle.read(*args)
                    replacement.replace(source)
                    return raw
            with patch.object(raster.os,"fdopen",side_effect=lambda *a,**kw:ReplacingReader(real_fdopen(*a,**kw))):
                with self.assertRaisesRegex(RasterError,"changed during read"):load_raster(source)

    def test_geometry_nested_mapping_is_immutable_and_returned_dict_independent(self):
        g=fixture()
        with self.assertRaises(TypeError):g.geometry["dx_m"]=9
        d=g.to_dict();d["geometry"]["dx_m"]=9;d["values"][0][0]=90
        self.assertEqual(g.geometry["dx_m"],2)
        self.assertEqual(g.values[0][0],11)

    def test_unknown_quantity_type_and_huge_numbers_raise_typed_error(self):
        for update in ({"quantity":[]},{"nodata":10**1000},{"values":[[10**1000,15,19],[5,9,13]]}):
            with self.assertRaises(RasterError):fixture(**update)

    def test_underresolved_large_origin_refused_and_fractional_utm_grid_self_sampling(self):
        with self.assertRaises(RasterError):
            fixture(geometry=dict(nrow=2,ncol=3,xllcorner_m=1e9,yllcorner_m=1e9,dx_m=1e-6,dy_m=1e-6))
        g=fixture(geometry=dict(nrow=2,ncol=3,xllcorner_m=500000.13,yllcorner_m=4100000.27,dx_m=.1,dy_m=.1),values=[[11,None,19],[5,9,13]])
        self.assertEqual(resample_raster(g,dict(g.geometry),method="bilinear").values,g.values)
        points=[[g.geometry["xllcorner_m"]+.1,g.geometry["yllcorner_m"]+.1]]
        self.assertEqual(sample_raster(g,points,method="nearest"),[None])
        west=g.geometry["xllcorner_m"]+.05
        south=g.geometry["yllcorner_m"]+.05
        import math
        # A representable point immediately west of the first centre stays outside.
        self.assertEqual(sample_raster(g,[[math.nextafter(west,-math.inf),south]],method="bilinear"),[None])


class RasterAsciiTests(unittest.TestCase):
    def test_official_corner_and_center_header_coordinates_row_order(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for header in ("XLLCORNER 100\nYLLCORNER 200", "XLLCENTER 101\nYLLCENTER 201"):
                p=root/"data.asc"
                p.write_text("NCOLS 3\nNROWS 2\n"+header+"\nCELLSIZE 2\n11 15 19 5 -9999 13\n")
                g=read_ascii(p,metadata=metadata(fixture()))
                self.assertEqual(g.extent,[100,200,106,204])
                self.assertEqual(g.values,((11.,15.,19.),(5.,None,13.)))
                self.assertEqual(sample_raster(g,[[101,203],[101,201]],method="nearest"),[11,5])

    def test_ascii_roundtrip_preserves_all_metadata_nodata_and_double_precision(self):
        g=fixture(values=[[11.123456789012345,None,19],[5,9,13]],nodata=-32768)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); export_ascii_bundle(g,root/"bundle")
            self.assertEqual(open_ascii_bundle(root/"bundle").to_dict(),g.to_dict())
            with self.assertRaises(RasterError):export_ascii_bundle(g,root/"bundle")
        receipt=verify_roundtrip(g)
        self.assertTrue(receipt["json_equal"])
        self.assertTrue(receipt["ascii_values_and_metadata_equal"])
        self.assertEqual(receipt["original_gms_comparison"],"NOT_OBSERVED")

    def test_ascii_missing_metadata_and_ambiguous_or_bad_header_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.asc"
            good="NCOLS 3\nNROWS 2\nXLLCORNER 100\nYLLCORNER 200\nCELLSIZE 2\n11 15 19 5 9 13\n"
            for raw in (good.replace("YLLCORNER","YLLCENTER"),good.replace("NCOLS 3","NCOLS 3.5"),
                good.replace("CELLSIZE 2","CELLSIZE -1"),good.replace("11 15","nan 15"),
                good+"1",good.replace("XLLCORNER 100","XLLCORNER 100\nXLLCORNER 101"),
                good.replace("NCOLS 3","NCOLS 10000000"),good.replace("CELLSIZE 2","DX 2\nDY 2")):
                p.write_text(raw)
                with self.subTest(raw=raw),self.assertRaises(RasterError): read_ascii(p,metadata=metadata(fixture()))
            p.write_text(good)
            with self.assertRaises(RasterError):read_ascii(p,metadata={})

    def test_ascii_corruption_extra_inventory_sidecar_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);g=fixture()
            for case in ("bytes","geometry","extra","schema"):
                b=export_ascii_bundle(g,root/case)
                if case=="bytes":(b/"grid.asc").write_text((b/"grid.asc").read_text().replace("11 ","12 "))
                if case in ("geometry","schema"):
                    d=json.loads((b/"metadata.json").read_text())
                    if case=="geometry":d["raster"]["geometry"]["dx_m"]=3
                    else:d["schema"]="v999"
                    (b/"metadata.json").write_text(json.dumps(d))
                if case=="extra":(b/"unregistered").write_text("x")
                with self.subTest(case=case),self.assertRaises(RasterError):open_ascii_bundle(b)

    def test_nonsquare_ascii_rejected_own_json_keeps_geometry(self):
        g=fixture(geometry=dict(nrow=2,ncol=3,xllcorner_m=100,yllcorner_m=200,dx_m=2,dy_m=3))
        with tempfile.TemporaryDirectory() as td:
            p=save_raster(g,Path(td)/"r.json")
            self.assertEqual(load_raster(p).geometry["dy_m"],3)
            with self.assertRaises(RasterError):export_ascii_bundle(g,Path(td)/"ascii")
            self.assertFalse((Path(td)/"ascii").exists())

    def test_injected_write_failure_never_publishes_success_and_can_retry(self):
        from basinlens_ccs.subsurface import raster
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);real_write=raster._write
            def fail_metadata(path,raw):
                if Path(path).name=="metadata.json":raise RasterError("injected sidecar I/O failure")
                return real_write(path,raw)
            with patch.object(raster,"_write",side_effect=fail_metadata):
                with self.assertRaises(RasterError):export_ascii_bundle(fixture(),root/"failed")
            self.assertFalse((root/"failed").exists())
            self.assertEqual(list(root.iterdir()),[])
            export_ascii_bundle(fixture(),root/"recovered")
            self.assertEqual(open_ascii_bundle(root/"recovered").values,fixture().values)


class RasterSpatialTests(unittest.TestCase):
    def test_nearest_physical_ties_halfopen_extent_and_offsets(self):
        g=fixture()
        pts=[[101,203],[101,201],[100,200],[102,202],[106,203],[101,204],[99.9,200],[105.99,200.01]]
        self.assertEqual(sample_raster(g,pts,method="nearest"),[11,5,5,15,None,None,None,13])

    def test_bilinear_matches_independent_linear_field(self):
        g=fixture()
        pts=[[101,201],[105,203],[102,202],[104.25,201.75],[101.3,202.4]]
        got=sample_raster(g,pts,method="bilinear")
        for (x,y),v in zip(pts,got):self.assertAlmostEqual(v,2*(x-100)+3*(y-200),places=12)

    def test_bilinear_nodata_support_and_zero_weight_cells(self):
        g=fixture(values=[[11,None,19],[5,9,13]])
        self.assertEqual(sample_raster(g,[[101,203],[101,201],[102,202],[100.1,201],[105.5,202]],method="bilinear"),[11,5,None,None,None])

    def test_single_row_and_single_column_bilinear_degenerate_axes(self):
        one=fixture(geometry=dict(nrow=1,ncol=3,xllcorner_m=0,yllcorner_m=0,dx_m=2,dy_m=2),values=[[1,3,5]])
        self.assertEqual(sample_raster(one,[[1,1],[2,1],[5,1],[2,1.1]],method="bilinear"),[1,2,5,None])
        one=fixture(geometry=dict(nrow=3,ncol=1,xllcorner_m=0,yllcorner_m=0,dx_m=2,dy_m=2),values=[[5],[3],[1]])
        self.assertEqual(sample_raster(one,[[1,2],[1,5],[1.1,2]],method="bilinear"),[2,5,None])

    def test_resample_halfpixel_linear_and_constant_field(self):
        target=dict(nrow=2,ncol=4,xllcorner_m=101,yllcorner_m=201,dx_m=1,dy_m=1)
        g=resample_raster(fixture(),target,method="bilinear")
        self.assertEqual(g.values,((10.5,12.5,14.5,16.5),(7.5,9.5,11.5,13.5)))
        const=fixture(values=[[7,7,7],[7,7,7]])
        self.assertEqual(resample_raster(const,target,method="bilinear").values,((7,7,7,7),(7,7,7,7)))
        outside=dict(target,xllcorner_m=99)
        self.assertIsNone(resample_raster(const,outside,method="bilinear").values[0][0])

    def test_clip_intersection_preserves_source_samples_and_area(self):
        g=clip_raster(fixture(),[101.5,200,104,202])
        self.assertEqual(g.extent,[100,200,104,202])
        self.assertEqual(g.values,((5,9),))
        self.assertEqual(g.geometry["nrow"]*g.geometry["ncol"]*g.geometry["dx_m"]*g.geometry["dy_m"],8)
        exact=clip_raster(fixture(),[102,202,104,204])
        self.assertEqual(exact.values,((15,),))
        for bounds in ([106,200,108,202],[0,0,1,1],[100,200,100,201],[100,200,99,201]):
            with self.assertRaises(RasterError):clip_raster(fixture(),bounds)

    def test_clip_decimal_exact_boundaries_and_nextafter_neighbours(self):
        import math
        g=fixture(geometry=dict(nrow=1,ncol=5,xllcorner_m=1000,yllcorner_m=0,dx_m=.1,dy_m=.1),values=[[1,2,3,4,5]])
        boundary=1000+3*.1
        self.assertEqual(clip_raster(g,[boundary,0,1000.5,.1]).values,((4,5),))
        self.assertEqual(clip_raster(g,[math.nextafter(boundary,-math.inf),0,1000.5,.1]).values,((3,4,5),))
        self.assertEqual(clip_raster(g,[math.nextafter(boundary,math.inf),0,1000.5,.1]).values,((4,5),))
        self.assertEqual(clip_raster(g,[1000,0,boundary,.1]).values,((1,2,3),))
        self.assertEqual(clip_raster(g,[1000,0,math.nextafter(boundary,math.inf),.1]).values,((1,2,3,4),))
        self.assertEqual(sample_raster(g,[[1e308,1e308],[-1e308,-1e308]],method="nearest"),[None,None])
        self.assertEqual(sample_raster(g,[[1e308,1e308]],method="bilinear"),[None])

    def test_merge_adjacent_tiles_gap_and_overlap_policies(self):
        left=fixture(geometry=dict(nrow=1,ncol=2,xllcorner_m=0,yllcorner_m=0,dx_m=2,dy_m=2),values=[[1,2]])
        right=fixture(asset_id="right",geometry=dict(nrow=1,ncol=2,xllcorner_m=4,yllcorner_m=0,dx_m=2,dy_m=2),values=[[3,4]])
        merged=merge_rasters([left,right],asset_id="merged",conflict_policy="error")
        self.assertEqual(merged.values,((1,2,3,4),))
        self.assertEqual(merged.extent,[0,0,8,2])
        gap=replace(right,geometry={**right.geometry,"xllcorner_m":6})
        self.assertEqual(merge_rasters([left,gap],asset_id="gap",conflict_policy="error").values,((1,2,None,3,4),))
        overlap=replace(right,geometry={**right.geometry,"xllcorner_m":2},values=((9,None),))
        with self.assertRaises(RasterError):merge_rasters([left,overlap],asset_id="x",conflict_policy="error")
        self.assertEqual(merge_rasters([left,overlap],asset_id="x",conflict_policy="first").values,((1,2,None),))
        self.assertEqual(merge_rasters([left,overlap],asset_id="x",conflict_policy="last").values,((1,9,None),))

    def test_merge_vertical_row_alignment_nodata_never_erases(self):
        south=fixture(asset_id="south",geometry=dict(nrow=1,ncol=2,xllcorner_m=0,yllcorner_m=0,dx_m=2,dy_m=2),values=[[1,2]])
        north=fixture(asset_id="north",geometry=dict(nrow=1,ncol=2,xllcorner_m=0,yllcorner_m=2,dx_m=2,dy_m=2),values=[[3,4]])
        self.assertEqual(merge_rasters([south,north],asset_id="x",conflict_policy="error").values,((3,4),(1,2)))
        missing=replace(south,asset_id="missing",values=((None,None),))
        self.assertEqual(merge_rasters([south,missing],asset_id="x",conflict_policy="last").values,((1,2),))

    def test_merge_misalignment_metadata_resolution_and_budgets_rejected(self):
        for bad in (replace(fixture(),geometry={**fixture().geometry,"xllcorner_m":101}),replace(fixture(),crs="other"),
                    replace(fixture(),vertical_datum="other"),replace(fixture(),geometry={**fixture().geometry,"dx_m":1})):
            with self.assertRaises(RasterError):merge_rasters([fixture(),bad],asset_id="x",conflict_policy="error")
        with self.assertRaises(RasterError):merge_rasters([fixture()],asset_id="x",conflict_policy="blend")
        with self.assertRaises(RasterError):sample_raster(fixture(),[[True,0]],method="nearest")

    def test_scatter_retains_valid_centres_and_source_hash(self):
        g=fixture(values=[[11,None,19],[5,9,13]])
        s=raster_to_scatter(g)
        self.assertEqual(len(s["points"]),5)
        self.assertEqual(s["points"][0],dict(row=0,column=0,x_m=101,y_m=203,value=11))
        self.assertEqual(s["points"][-1]["y_m"],201)
        self.assertEqual(s["unit"],"m")
        self.assertEqual(len(s["source_raster_sha256"]),64)

    def test_project_sampling_explicit_south_to_north_and_layers(self):
        project=project_from_groundwater(demo_case())
        d=project.to_dict()
        d["geometry"].update(nlay=2,nrow=2,ncol=3,delr_m=2,delc_m=2,origin_x_m=100,origin_y_m=200,top_m=10,layer_bottoms_m=[0,-10])
        d.update(rock_properties=[],stratigraphy=[],wells=[],observations=[])
        d["spatial_reference"].update(crs=fixture().crs,vertical_datum=fixture().vertical_datum)
        grid=fixture(quantity="hydraulic_conductivity_x",unit="m/day")
        with tempfile.TemporaryDirectory() as td:
            p=save_raster(grid,Path(td)/"grid.json")
            d["assets"]=[dict(asset_id="raster",relative_path="grid.json",sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                media_type="application/json",license="Authored synthetic",source="raster test")]
            pmodel=SubsurfaceProject.from_dict(d)
            field=sample_project_property(grid,pmodel,"hydraulic_conductivity_x",method="nearest",source_asset_id="raster")
            self.assertEqual(field.quantity.value,(5,9,13,11,15,19,5,9,13,11,15,19))
            self.assertEqual(field.support.indices[0],(0,0,0))
            self.assertEqual(field.support.indices[-1],(1,1,2))
            self.assertEqual(field.basis,"interpreted")
            with self.assertRaises(RasterError):sample_project_property(grid,pmodel,"porosity",method="nearest",source_asset_id="raster")
            with self.assertRaises(RasterError):sample_project_property(replace(grid,crs="other"),pmodel,"hydraulic_conductivity_x",method="nearest",source_asset_id="raster")
            with self.assertRaises(RasterError):sample_project_property(replace(grid,values=((11,None,19),(5,9,13))),pmodel,"hydraulic_conductivity_x",method="nearest",source_asset_id="raster")


class RasterCatalogCliTests(unittest.TestCase):
    def test_catalog_exact_id_hash_extent_reopen_and_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(fixture(),root/"a.json")
            q=save_raster(replace(fixture(),asset_id="other"),root/"b.json")
            catalog=create_catalog([p,q],root/"catalog.json")
            self.assertEqual([g.asset_id for g in open_catalog(catalog)],["linear","other"])
            d=json.loads(catalog.read_text());d["assets"][0]["extent_m"][0]=0;catalog.write_text(json.dumps(d))
            with self.assertRaises(RasterError):open_catalog(catalog)
            with self.assertRaises(RasterError):create_catalog([p,p],root/"dupe.json")
            dup=save_raster(fixture(),root/"dup.json")
            with self.assertRaises(RasterError):create_catalog([p,dup],root/"dupe-id.json")
            clean=create_catalog([q],root/"clean.json");q.write_text(q.read_text()+" ")
            with self.assertRaises(RasterError):open_catalog(clean)

    def test_catalog_traversal_symlink_and_unregistered_schema_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(fixture(),root/"a.json")
            catalog=create_catalog([p],root/"catalog.json")
            d=json.loads(catalog.read_text());d["assets"][0]["relative_path"]="../a.json";catalog.write_text(json.dumps(d))
            with self.assertRaises(RasterError):open_catalog(catalog)
            catalog.unlink();create_catalog([p],catalog);p.unlink();(root/"target").write_text("x");p.symlink_to(root/"target")
            with self.assertRaises(RasterError):open_catalog(catalog)

    def test_cli_actual_io_recovery_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(fixture(),root/"input.json")
            self.assertEqual(main(["export-ascii",str(p),str(root/"ascii")]),0)
            self.assertEqual(main(["open-ascii",str(root/"ascii"),str(root/"opened.json")]),0)
            self.assertEqual(load_raster(root/"opened.json").to_dict(),fixture().to_dict())
            self.assertEqual(main(["roundtrip",str(p),str(root/"receipt.json")]),0)
            points=root/"points.json";points.write_text("[[102,202],[106,204]]")
            self.assertEqual(main(["query",str(p),str(points),str(root/"query.json"),"--method","bilinear"]),0)
            self.assertEqual(json.loads((root/"query.json").read_text())["values"],[10,None])
            self.assertEqual(main(["scatter",str(p),str(root/"scatter.json")]),0)
            with self.assertRaises(SystemExit) as context:main(["roundtrip",str(p),str(root/"receipt.json")])
            self.assertEqual(context.exception.code,2)
            self.assertEqual(main(["roundtrip",str(p),str(root/"recovery.json")]),0)


    def test_cli_resample_clip_merge_ascii_import_and_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(fixture(),root/"input.json")
            geom=root/"geom.json";geom.write_text(json.dumps(dict(nrow=2,ncol=4,xllcorner_m=101,yllcorner_m=201,dx_m=1,dy_m=1)))
            self.assertEqual(main(["resample",str(p),str(geom),str(root/"resampled.json"),"--method","bilinear"]),0)
            self.assertEqual(load_raster(root/"resampled.json").values[0][0],10.5)
            self.assertEqual(main(["clip",str(p),str(root/"clipped.json"),"--bbox","102","202","104","204"]),0)
            self.assertEqual(load_raster(root/"clipped.json").values,((15,),))
            self.assertEqual(main(["merge",str(root/"merged.json"),str(p),str(p),"--asset-id","merged","--conflict-policy","error"]),0)
            self.assertEqual(load_raster(root/"merged.json").values,fixture().values)
            self.assertEqual(main(["export-ascii",str(p),str(root/"ascii")]),0)
            m=root/"metadata.json";m.write_text(json.dumps(metadata(fixture())))
            self.assertEqual(main(["import-ascii",str(root/"ascii"/"grid.asc"),str(m),str(root/"imported.json")]),0)
            self.assertEqual(load_raster(root/"imported.json").values,fixture().values)
            self.assertEqual(main(["catalog",str(root/"catalog.json"),str(p),str(root/"merged.json")]),0)
            self.assertEqual(main(["verify-catalog",str(root/"catalog.json")]),0)

    def test_catalog_rejects_boolean_extent_even_when_numeric_equality_would_match(self):
        g=fixture(geometry=dict(nrow=2,ncol=3,xllcorner_m=1,yllcorner_m=200,dx_m=2,dy_m=2))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(g,root/"r.json");c=create_catalog([p],root/"catalog.json")
            d=json.loads(c.read_text());d["assets"][0]["extent_m"][0]=True;c.write_text(json.dumps(d))
            with self.assertRaises(RasterError):open_catalog(c)

    def test_module_entrypoint_real_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=save_raster(fixture(),root/"input.json")
            result=subprocess.run([sys.executable,"-m","basinlens_ccs.subsurface.raster","roundtrip",str(p),str(root/"out.json")],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads((root/"out.json").read_text())["ascii_values_and_metadata_equal"])


if __name__=="__main__":unittest.main()
