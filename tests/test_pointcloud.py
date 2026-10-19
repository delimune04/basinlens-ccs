"""Independently assembled LAS record/header fixtures; no reference GMS output."""
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from basinlens_ccs.subsurface import pointcloud as pc

META = {"crs": "LOCAL:authored-planar", "horizontal_unit": "m", "vertical_unit": "m", "vertical_datum": "authored elevation zero", "provenance": ["Synthetic fixture authored for independent encoded LAS checks; not a measurement"]}
RAW = [(-100, 0, 50), (0, 0, 0), (100, 10, -10), (100, 10, 10), (200, 20, 20), (300, 30, 40)]


def authored_las(fmt=3, *, vlr=True):
    """Literal ASPRS legacy offsets, independently of the production writer."""
    length = (20, 28, 26, 34)[fmt]
    records = []
    for i, (x, y, z) in enumerate(RAW):
        number = i % 3 + 1
        flags = number | (3 << 3) | (64 if i % 2 else 0) | (128 if i == 5 else 0)
        classification = (2 if i in (1, 2, 3) else 5) | (32 if i == 0 else 0) | (64 if i == 2 else 0) | (128 if i == 3 else 0)
        rec = struct.pack('<iiiHBBbBH', x, y, z, 100 + 1000 * i, flags, classification, -45 + i, 255 - i, 500 + i)
        if fmt in (1, 3): rec += struct.pack('<d', 123456.125 + i * .5)
        if fmt in (2, 3): rec += struct.pack('<3H', 65535 - i, i, 1024 + i)
        assert len(rec) == length
        records.append(rec)
    payload = b'\x00\xfeopaque\xff\x80'
    vlr_bytes = struct.pack('<H16sHH32s', 0, b'PRIVATE_TEST', 4711, len(payload), b'opaque authored fixture') + payload if vlr else b''
    padding = b'\xa5\x5a' if vlr else b''
    header = bytearray(227)
    header[:4] = b'LASF'
    struct.pack_into('<HH', header, 4, 41, 1)
    header[24:26] = b'\x01\x02'
    header[26:58] = b'Independent fixture'.ljust(32, b'\x00')
    header[58:90] = b'BasinLens synthetic'.ljust(32, b'\x00')
    struct.pack_into('<HH', header, 90, 292, 2026)
    struct.pack_into('<HII', header, 94, 227, 227 + len(vlr_bytes) + len(padding), int(vlr))
    struct.pack_into('<BHI', header, 104, fmt, length, len(RAW))
    struct.pack_into('<5I', header, 111, 2, 2, 2, 0, 0)
    struct.pack_into('<3d', header, 131, .01, .1, .5)
    struct.pack_into('<3d', header, 155, 1000, 2000, 100)
    struct.pack_into('<6d', header, 179, 1003, 999, 2003, 2000, 125, 95)
    return bytes(header) + vlr_bytes + padding + b''.join(records)


class TestPointCloud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'authored.las'
        self.path.write_bytes(authored_las())
        self.cloud = pc.read_las(self.path, metadata=META)

    def tearDown(self): self.tmp.cleanup()

    def test_known_integer_coordinates_flags_gps_rgb_and_opaque_vlr(self):
        p = pc.points(self.cloud)
        self.assertEqual(p[0]['raw_xyz'], [-100, 0, 50])
        self.assertEqual([p[0][k] for k in ('x', 'y', 'z')], [999, 2000, 125])
        self.assertEqual([p[2][k] for k in ('x', 'y', 'z')], [1001, 2001, 95])
        self.assertEqual(p[5]['intensity'], 5100)
        self.assertEqual(p[5]['return_number'], 3)
        self.assertEqual(p[5]['number_of_returns'], 3)
        self.assertTrue(p[5]['edge_of_flight_line'])
        self.assertTrue(p[5]['scan_direction'])
        self.assertTrue(p[0]['synthetic']); self.assertTrue(p[2]['key_point']); self.assertTrue(p[3]['withheld'])
        self.assertEqual(p[3]['classification'], 2)
        self.assertEqual(p[2]['scan_angle_rank'], -43)
        self.assertEqual(p[2]['user_data'], 253)
        self.assertEqual(p[2]['point_source_id'], 502)
        self.assertEqual(p[4]['gps_time'], 123458.125)
        self.assertEqual(p[4]['rgb'], [65531, 4, 1028])
        self.assertEqual(self.cloud.prefix[227:243], struct.pack('<H', 0) + b'PRIVATE_TEST\x00\x00')
        self.assertEqual(self.cloud.prefix[-2:], b'\xa5\x5a')
        self.assertEqual(pc.inspect_pointcloud(self.cloud)['vlr_count'], 1)

    def test_all_four_formats_las_and_json_exact_roundtrip(self):
        for fmt in range(4):
            with self.subTest(fmt=fmt):
                source = self.root / f'format{fmt}.las'; source.write_bytes(authored_las(fmt))
                cloud = pc.read_las(source, metadata=META)
                out = self.root / f'out{fmt}.las'; pc.write_las(cloud, out)
                self.assertEqual(out.read_bytes(), source.read_bytes())
                p = pc.points(cloud)[0]
                self.assertEqual('gps_time' in p, fmt in (1, 3)); self.assertEqual('rgb' in p, fmt in (2, 3))
                receipt = pc.verify_pointcloud_roundtrip(cloud, self.root / f'rt{fmt}')
                self.assertTrue(receipt['native_json_identities_equal'])
                self.assertEqual(receipt['original_gms_comparison'], 'NOT_OBSERVED')
                loaded = pc.load_pointcloud(self.root / f'rt{fmt}' / 'points.json')
                self.assertEqual(loaded.to_dict(), cloud.to_dict())

    def test_class_bbox_height_return_filter_retains_encoded_attributes_identity(self):
        filtered = pc.filter_points(self.cloud, classifications=[2], bbox=[1000, 2000, 1001, 2001], height=[95, 100], returns=[2, 3], include_withheld=False)
        self.assertEqual(filtered.count, 2)
        self.assertEqual(filtered.identities, self.cloud.identities[1:3])
        self.assertEqual(filtered.records, self.cloud.records[34:102])
        self.assertEqual(struct.unpack_from('<5I', filtered.prefix, 111), (0, 1, 1, 0, 0))
        self.assertEqual(struct.unpack_from('<6d', filtered.prefix, 179), (1001, 1000, 2001, 2000, 100, 95))
        self.assertEqual(filtered.prefix[227:], self.cloud.prefix[227:])
        path = self.root / 'trimmed.las'; pc.write_las(filtered, path)
        self.assertEqual(pc.read_las(path, metadata=META).records, filtered.records)

    def test_empty_filter_has_zero_bounds_counts_and_roundtrip(self):
        empty = pc.filter_points(self.cloud, classifications=[31])
        self.assertEqual(empty.count, 0)
        self.assertEqual(struct.unpack_from('<6d', empty.prefix, 179), (0.,) * 6)
        self.assertEqual(pc.points(empty), [])
        self.assertEqual(pc.render_points(empty)['rendered_count'], 0)
        pc.verify_pointcloud_roundtrip(empty, self.root / 'empty')

    def test_merge_reassembles_disjoint_parts_without_losing_identities(self):
        a = pc.filter_points(self.cloud, classifications=[2]); b = pc.filter_points(self.cloud, classifications=[5])
        merged = pc.merge_pointclouds([a, b])
        self.assertEqual(merged.count, 6)
        self.assertEqual(merged.identities, a.identities + b.identities)
        self.assertEqual(merged.records, a.records + b.records)
        self.assertEqual(struct.unpack_from('<6d', merged.prefix, 179), (1003, 999, 2003, 2000, 125, 95))
        self.assertEqual(merged.metadata["crs"], META["crs"])
        self.assertIn("Merged 2 compatible", merged.metadata["provenance"][-1])
        self.assertIn("Filtered original encoded", merged.metadata["provenance"][-2])
        with self.assertRaisesRegex(pc.PointCloudError, 'duplicate'): pc.merge_pointclouds([a, a])
        changed = b.to_dict(); changed['metadata']['vertical_datum'] = 'other'
        with self.assertRaisesRegex(pc.PointCloudError, 'identical'): pc.merge_pointclouds([a, pc.PointCloud.from_dict(changed)])
        changed = b.to_dict(); prefix = bytearray(bytes.fromhex(changed['prefix_hex'])); prefix[6] = 0; changed['prefix_hex'] = prefix.hex()
        with self.assertRaisesRegex(pc.PointCloudError, 'identical'): pc.merge_pointclouds([a, pc.PointCloud.from_dict(changed)])

    def grid(self, **kw):
        return pc.aggregate_grid(self.cloud, x_origin=1000, y_origin=2000, dx=1, dy=1, nrow=3, ncol=3, crs=META['crs'], horizontal_unit='m', vertical_datum=META['vertical_datum'], **kw)

    def test_grid_edges_known_means_and_unsupported_cells_never_filled(self):
        g = self.grid()
        self.assertEqual(g['values'], [[100., None, None], [None, 100., None], [None, None, 110.]])
        self.assertEqual(g['counts'], [[1, 0, 0], [0, 2, 0], [0, 0, 1]])
        self.assertFalse(g['support'][0][1])
        self.assertEqual(g['point_identities'][1][1], list(self.cloud.identities[2:4]))
        self.assertEqual(g['excluded_identities'], [self.cloud.identities[0], self.cloud.identities[5]])
        self.assertEqual(self.grid(statistic='min')['values'][1][1], 95)
        self.assertEqual(self.grid(statistic='max')['values'][1][1], 105)
        self.assertEqual(self.grid(statistic='count')['values'][1][1], 2)
        self.assertEqual(self.grid(statistic='count')['values'][0][1], None)
        self.assertEqual(self.grid(field='intensity')['values'][1][1], 2600)

    def test_grid_metadata_no_reproject_unknown_or_unbounded_grid(self):
        for kw in [dict(crs='other'), dict(horizontal_unit='unknown'), dict(vertical_datum='other'), dict(dx=0), dict(dx=math.nan), dict(nrow=True), dict(nrow=200000, ncol=2),dict(x_origin=1e9,dx=1e-6),dict(dx=10**500)]:
            params=dict(x_origin=1000,y_origin=2000,dx=1,dy=1,nrow=3,ncol=3,crs=META['crs'],horizontal_unit='m',vertical_datum=META['vertical_datum']); params.update(kw)
            with self.subTest(kw=kw), self.assertRaises(pc.PointCloudError): pc.aggregate_grid(self.cloud, **params)

    def test_decimal_grid_internal_edges_go_upper_right_with_explicit_halfopen_outer_edge(self):
        raw = bytearray(authored_las())
        offset = struct.unpack_from('<I', raw, 96)[0]
        struct.pack_into('<d', raw, 131, .3)
        for i, x in enumerate([-1, 0, 1, 1, 2, 3]):
            struct.pack_into('<i', raw, offset + i * 34, x)
        struct.pack_into('<2d', raw, 179, 1000 + 3 * .3, 1000 - .3)
        path = self.root / 'decimal.las'; path.write_bytes(raw)
        cloud = pc.read_las(path, metadata=META)
        grid = pc.aggregate_grid(cloud,x_origin=1000,y_origin=2000,dx=.3,dy=1,nrow=3,ncol=3,crs=META['crs'],horizontal_unit='m',vertical_datum=META['vertical_datum'])
        self.assertEqual(grid['counts'], [[1,0,0],[0,2,0],[0,0,1]])
        self.assertEqual(len(grid['excluded_identities']), 2)

    def test_strict_json_applies_to_direct_metadata_and_cli_sidecars(self):
        duplicate = b'{"crs":"other","crs":"LOCAL:authored-planar","horizontal_unit":"m","vertical_unit":"m","vertical_datum":"authored elevation zero","provenance":["synthetic"]}'
        with self.assertRaisesRegex(pc.PointCloudError, 'duplicate'):
            pc.PointCloud(self.cloud.prefix,self.cloud.records,self.cloud.identities,duplicate)
        meta = self.root / 'duplicate.json'; meta.write_bytes(duplicate)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pc.main(['import-las',str(self.path),str(self.root/'not-created.json'),'--metadata',str(meta)])
        self.assertFalse((self.root/'not-created.json').exists())
        malformed = self.root/'deep.json'; malformed.write_text('[' * 1500 + '0' + ']' * 1500)
        with self.assertRaises(pc.PointCloudError): pc.load_pointcloud(malformed)

    def test_view_decimation_does_not_change_store_and_preserves_original_indices(self):
        before = self.cloud.to_dict()
        rendered = pc.render_points(self.cloud, max_points=4)
        self.assertEqual([p['index'] for p in rendered['points']], [0, 1, 3, 4])
        self.assertEqual(rendered['stored_count'], 6); self.assertEqual(self.cloud.to_dict(), before)
        with self.assertRaises(pc.PointCloudError): pc.render_points(self.cloud, 20001)

    def test_malformed_header_count_offsets_bounds_records_bits_and_gps(self):
        raw = authored_las()
        offset = struct.unpack_from('<I', raw, 96)[0]
        changes = [(0, b'NOPE'), (24, b'\x01\x04'), (6, b'\x02\x00'), (94, struct.pack('<H', 228)), (96, struct.pack('<I', 1)), (100, struct.pack('<I', 257)), (104, b'\x83'), (105, struct.pack('<H', 35)), (107, struct.pack('<I', 200001)), (111, struct.pack('<I', 3)), (131, struct.pack('<d', 0)), (139, struct.pack('<d', math.nan)), (155, struct.pack('<d', math.inf)), (179, struct.pack('<d', 1004)), (227 + 20, struct.pack('<H', 65535)), (offset + 14, b'\x00'), (offset + 16, struct.pack('<b', 91)), (offset + 20, struct.pack('<d', math.inf))]
        for pos, value in changes:
            malformed = bytearray(raw); malformed[pos:pos+len(value)] = value
            path=self.root/'bad.las';path.write_bytes(malformed)
            with self.subTest(pos=pos), self.assertRaises(pc.PointCloudError):pc.read_las(path, metadata=META)
        for value in (raw[:-1], raw+b'\x00'):
            path=self.root/'bad.las';path.write_bytes(value)
            with self.assertRaises(pc.PointCloudError):pc.read_las(path, metadata=META)

    def test_json_corruption_duplicate_keys_unknown_fields_and_nonfinite_metadata(self):
        d = self.cloud.to_dict()
        mutations=[]
        x=copy.deepcopy(d);x['schema']='future';mutations.append(x)
        x=copy.deepcopy(d);x['unexpected']=1;mutations.append(x)
        x=copy.deepcopy(d);x['identities'][0]=x['identities'][1];mutations.append(x)
        x=copy.deepcopy(d);x['identities'][0]=[];mutations.append(x)
        x=copy.deepcopy(d);x['records_hex']='zz';mutations.append(x)
        x=copy.deepcopy(d);x['metadata']['horizontal_unit']='degree';mutations.append(x)
        for x in mutations:
            with self.assertRaises(pc.PointCloudError):pc.PointCloud.from_dict(x)
        path=self.root/'bad.json';path.write_text('{"schema":"x","schema":"y"}')
        with self.assertRaisesRegex(pc.PointCloudError,'duplicate'):pc.load_pointcloud(path)
        path.write_text('{"x":NaN}')
        with self.assertRaises(pc.PointCloudError):pc.load_pointcloud(path)

    def test_read_byte_budget_regular_file_and_symlink_refusal(self):
        with patch.object(pc,'MAX_BYTES',len(authored_las())-1):
            with self.assertRaises(pc.PointCloudError):pc.read_las(self.path,metadata=META)
        link=self.root/'link.las';link.symlink_to(self.path)
        with self.assertRaises(pc.PointCloudError):pc.read_las(link,metadata=META)
        fifo=self.root/'fifo';os.mkfifo(fifo)
        with self.assertRaises(pc.PointCloudError):pc.read_las(fifo,metadata=META)
        with self.assertRaises(pc.PointCloudError):pc.read_las(self.root,metadata=META)

    def test_fresh_outputs_refused_and_failed_operation_can_recover_elsewhere(self):
        original=self.path.read_bytes()
        with self.assertRaises(pc.PointCloudError):pc.write_las(self.cloud,self.path)
        self.assertEqual(self.path.read_bytes(),original)
        with self.assertRaises(pc.PointCloudError):pc.write_las(self.cloud,self.root/'missing'/'x.las')
        good=self.root/'recovered.las';pc.write_las(self.cloud,good)
        self.assertEqual(good.read_bytes(),original)
        pc.verify_pointcloud_roundtrip(self.cloud,self.root/'run')
        with self.assertRaises(pc.PointCloudError):pc.verify_pointcloud_roundtrip(self.cloud,self.root/'run')

    def test_invalid_filter_inputs_explicit(self):
        for kw in [dict(classifications=[]),dict(classifications=[True]),dict(classifications=[[]]),dict(classifications=[2,2]),dict(bbox=[1,2,0,3]),dict(height=[1,math.nan]),dict(returns=[6]),dict(include_withheld=1)]:
            with self.subTest(kw=kw),self.assertRaises(pc.PointCloudError):pc.filter_points(self.cloud,**kw)

    def test_cli_actual_import_filter_export_merge_rasterize_roundtrip_and_recovery(self):
        meta=self.root/'meta.json';meta.write_text(json.dumps(META))
        cloud=self.root/'cloud.json'
        self.assertEqual(pc.main(['import-las',str(self.path),str(cloud),'--metadata',str(meta)]),0)
        with contextlib.redirect_stdout(io.StringIO()) as capture:self.assertEqual(pc.main(['inspect',str(cloud)]),0)
        self.assertEqual(json.loads(capture.getvalue())['point_count'],6)
        a=self.root/'a.json';b=self.root/'b.json'
        pc.main(['filter',str(cloud),str(a),'--classes','2']);pc.main(['filter',str(cloud),str(b),'--classes','5'])
        merged=self.root/'merged.json';pc.main(['merge',str(merged),str(a),str(b)])
        pc.main(['export',str(merged),str(self.root/'merged.las')])
        grid=self.root/'grid.json';grid.write_text(json.dumps(dict(x_origin=1000,y_origin=2000,dx=1,dy=1,nrow=3,ncol=3,crs=META['crs'],horizontal_unit='m',vertical_datum=META['vertical_datum'])))
        pc.main(['rasterize',str(cloud),str(self.root/'raster.json'),'--grid',str(grid)])
        self.assertEqual(json.loads((self.root/'raster.json').read_text())['counts'][1][1],2)
        with contextlib.redirect_stdout(io.StringIO()):pc.main(['roundtrip',str(cloud),str(self.root/'cli-run')])
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:pc.main(['export',str(cloud),str(self.path)])
        self.assertEqual(error.exception.code,2)
        self.assertEqual(self.path.read_bytes(),authored_las())
        pc.main(['export',str(cloud),str(self.root/'after-error.las')])


if __name__ == '__main__': unittest.main()
