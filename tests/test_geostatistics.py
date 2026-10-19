"""Independent matrices, exact hull checks, seeded moments, and real file operations."""
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
from statistics import NormalDist
import tempfile
import unittest

import numpy as np

from basinlens_ccs.subsurface.scatter import ScatterDataset, save_scatter
from basinlens_ccs.subsurface import geostatistics as gs


def dataset(coords=None, values=None, dim=2, missing=False):
    coords=coords or [[0,0],[2,0]]
    values=values if values is not None else [2,4]
    data=dict(schema='basinlens-scatter-v1',id='authored',dimension=dim,coordinate_unit='m',crs='LOCAL:authored-metre',vertical_datum='authored-zero',vertical_axis='positive_up' if dim==3 else 'not_applicable',quantity='head',value_unit='m',basis='synthetic',provenance=['Authored numerical checks; not measurements'],duplicate_coordinate_policy='reject',points=[dict(id=f'p{i}',coordinates_m=p,value=v,missing_reason='not observed' if v is None else None) for i,(p,v) in enumerate(zip(coords,values))])
    return ScatterDataset.from_dict(data)


def model(dim=2,**changes):
    d=dict(schema=gs.MODEL_SCHEMA,dimension=dim,kind='exponential',partial_sill=1.,nugget=0.,value_unit='m',ranges_m=[1.]*dim,rotation=np.eye(dim).tolist());d.update(changes)
    return gs.CovarianceModel.from_dict(d)


def kriging(d=None,q=None,m=None,**changes):
    settings=dict(method='ordinary',mean=None,radius_m=10,min_neighbors=2,max_neighbors=32,domain_bounds_m=[[-1,4],[-1,4]],allow_extrapolation=False);settings.update(changes)
    return gs.krige(d or dataset(),q if q is not None else [[1,0]],m or model(),**settings)


class CovarianceChecks(unittest.TestCase):
    def test_literal_stationary_covariances_and_process_nugget(self):
        for kind,expected in [('exponential',math.exp(-.5)),('gaussian',math.exp(-.25)),('spherical',.3125)]:
            m=model(kind=kind,partial_sill=2,nugget=.25)
            c=gs.covariance(m,[[0,0],[.5,0]])
            self.assertEqual(c[0,0],2.25)
            self.assertAlmostEqual(c[0,1],2*expected,places=14)
            self.assertTrue(np.array_equal(c,c.T))
        self.assertEqual(gs.covariance(model(kind='spherical'),[[0,0]],[[1,0]])[0,0],0)
        # Cross-covariance at identical location denotes the same process, not an independent noisy observation.
        self.assertEqual(gs.covariance(model(nugget=.25),[[0,0]],[[0,0]])[0,0],1.25)

    def test_rotated_anisotropy_principal_axes_and_3d(self):
        m=model(ranges_m=[2,1],rotation=[[0,-1],[1,0]])
        c=gs.covariance(m,[[0,0]],[[0,2],[2,0]])[0]
        self.assertAlmostEqual(c[0],math.exp(-1));self.assertAlmostEqual(c[1],math.exp(-2))
        c=gs.covariance(model(3,ranges_m=[2,3,4]),[[0,0,0]],[[0,0,4]])[0,0]
        self.assertAlmostEqual(c,math.exp(-1))

    def test_model_bad_units_rotation_sill_and_large_coordinates(self):
        for change in [dict(kind='power'),dict(partial_sill=0),dict(nugget=-1),dict(ranges_m=[1,0]),dict(rotation=[[1,0],[0,-1]]),dict(rotation=[[1,.1],[0,1]]),dict(dimension=True),dict(partial_sill=10**1000)]:
            with self.subTest(change=change),self.assertRaises(gs.GeostatisticsError):model(**change)
        with self.assertRaises(gs.GeostatisticsError):gs.covariance(model(),[[float('nan'),0]])
        with self.assertRaises(gs.GeostatisticsError):gs.CovarianceModel([]).to_dict()


class KrigingChecks(unittest.TestCase):
    def test_ordinary_two_point_hand_matrix_weights_prediction_variance(self):
        result=kriging();record=result.records[0]
        rho=math.exp(-2);cross=math.exp(-1)
        self.assertAlmostEqual(record['prediction'],3,places=14)
        self.assertAlmostEqual(record['variance'],1.5+.5*rho-2*cross,places=14)
        self.assertTrue(record['supported']);self.assertIsNone(record['reason'])
        weights=result.to_dict()['metadata']['diagnostics'][0]['weights']
        np.testing.assert_allclose(weights,[.5,.5],rtol=0,atol=1e-14)

    def test_simple_known_mean_two_point_hand_inverse(self):
        r=kriging(method='simple',mean=10).records[0];rho=math.exp(-2);cross=math.exp(-1);weight=cross/(1+rho)
        self.assertAlmostEqual(r['prediction'],10+weight*((2-10)+(4-10)),places=13)
        self.assertAlmostEqual(r['variance'],1-2*cross**2/(1+rho),places=14)
        with self.assertRaises(gs.GeostatisticsError):kriging(method='simple',mean=None)
        with self.assertRaises(gs.GeostatisticsError):kriging(method='ordinary',mean=1)

    def test_exact_conditioning_process_nugget_and_constant_reproduction(self):
        d=dataset([[0,0],[2,0],[0,2]],[7,7,7]);m=model(nugget=.4)
        r=kriging(d,[[0,0],[.4,.4]],m).records
        self.assertAlmostEqual(r[0]['prediction'],7,places=13);self.assertAlmostEqual(r[0]['variance'],0,places=13)
        self.assertAlmostEqual(r[1]['prediction'],7,places=13)
        self.assertGreater(r[1]['variance'],0)
        self.assertIn('not observed geological uncertainty',kriging().to_dict()['metadata']['variance_scope'])

    def test_3d_actual_tetrahedral_hull_not_its_bounding_box(self):
        d=dataset([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],[5,5,5,5],3)
        r=kriging(d,[[.2,.2,.2],[.7,.7,.7],[0,0,0]],model(3),domain_bounds_m=[[0,1]]*3).records
        self.assertTrue(r[0]['supported']);self.assertAlmostEqual(r[0]['prediction'],5)
        self.assertFalse(r[1]['supported']);self.assertEqual(r[1]['reason'],'outside_observation_affine_convex_hull');self.assertIsNone(r[1]['prediction'])
        self.assertTrue(r[2]['supported'])

    def test_2d_triangle_and_3d_coplanar_affine_support(self):
        d=dataset([[0,0],[1,0],[0,1]],[1,1,1])
        r=kriging(d,[[.2,.2],[.8,.8],[2,0]]).records
        self.assertTrue(r[0]['supported']);self.assertFalse(r[1]['supported']);self.assertFalse(r[2]['supported'])
        d=dataset([[0,0,4],[1,0,4],[0,1,4]],[1,1,1],3)
        r=kriging(d,[[.2,.2,4],[.2,.2,4.01]],model(3),domain_bounds_m=[[-1,2],[-1,2],[3,5]]).records
        self.assertTrue(r[0]['supported']);self.assertFalse(r[1]['supported'])

    def test_thin_2d_and_3d_hulls_keep_short_edge_and_small_face_support(self):
        d=dataset([[0,0],[1,0],[1,1e-6],[0,1e-6]],[1]*4)
        r=kriging(d,[[-1e-6,.5e-6],[.5,.5e-6]],m=model(nugget=.1)).records
        self.assertFalse(r[0]['supported']);self.assertTrue(r[1]['supported'])
        coords=[[x,y,z] for x in (0,1) for y in (0,1e-6) for z in (0,1e-6)]
        d=dataset(coords,[1]*8,3)
        r=kriging(d,[[-.1,.5e-6,.5e-6],[.5,.5e-6,.5e-6]],m=model(3,nugget=.1),domain_bounds_m=[[-1,2]]*3).records
        self.assertFalse(r[0]['supported']);self.assertTrue(r[1]['supported'])

    def test_one_observation_ordinary_hand_variance(self):
        d=dataset([[0,0]],[7]);m=model(partial_sill=2,nugget=.3)
        r=kriging(d,[[1,0]],m,min_neighbors=1,max_neighbors=1,allow_extrapolation=True).records[0]
        self.assertEqual(r['prediction'],7)
        self.assertAlmostEqual(r['variance'],2*(2.3-2*math.exp(-1)),places=14)

    def test_radius_owner_domain_missing_observations_and_explicit_extrapolation(self):
        d=dataset([[0,0],[2,0],[10,0]],[2,4,None])
        r=kriging(d,[[1,0],[3,0],[0,0],[20,0]],radius_m=.1).records
        self.assertEqual(r[0]['reason'],'insufficient_neighbors_in_radius')
        self.assertEqual(r[1]['reason'],'outside_observation_affine_convex_hull')
        self.assertEqual(r[2]['reason'],'insufficient_neighbors_in_radius')
        self.assertEqual(r[3]['reason'],'outside_owner_domain')
        extra=kriging(d,[[3,0]],allow_extrapolation=True).records[0]
        self.assertTrue(extra['supported']);self.assertGreater(extra['variance'],0)
        self.assertEqual(len(kriging(d).to_dict()['metadata']['source_dataset']['points']),3)

    def test_typed_prediction_and_variance_scatter_export_preserves_missing_support(self):
        result=kriging(q=[[1,0],[3,0]])
        prediction=gs.kriging_to_scatter(result,dataset_id='kriged-head')
        variance=gs.kriging_to_scatter(result,dataset_id='kriging-error',field='variance')
        p=prediction.to_dict();v=variance.to_dict()
        self.assertEqual(p['basis'],'interpreted');self.assertEqual(p['quantity'],'head');self.assertEqual(p['value_unit'],'m')
        self.assertEqual(p['points'][0]['value'],3);self.assertEqual(p['points'][1]['value'],None)
        self.assertEqual(p['points'][1]['missing_reason'],'outside_observation_affine_convex_hull')
        self.assertEqual(v['value_unit'],'(m)^2');self.assertEqual(v['quantity'],'kriging_prediction_error_variance')
        self.assertEqual(v['points'][0]['value'],result.records[0]['variance'])
        with self.assertRaises(gs.GeostatisticsError):gs.kriging_to_scatter(kriging(q=[[1,0],[1,0]]),dataset_id='duplicate-query')

    def test_condition_refusal_no_jitter_and_sill_unit_scaling(self):
        d=dataset([[0,0],[1e-6,0]],[1,2])
        with self.assertRaisesRegex(gs.GeostatisticsError,'ill-conditioned'):kriging(d,[[.5e-6,0]],model(ranges_m=[1e9,1e9]))
        small=kriging(m=model(partial_sill=1e-15));large=kriging(m=model(partial_sill=1e10))
        self.assertAlmostEqual(small.records[0]['prediction'],large.records[0]['prediction'])
        self.assertAlmostEqual(small.records[0]['variance']*1e25,large.records[0]['variance'],delta=1e-4)
        with self.assertRaises(gs.GeostatisticsError):kriging(m=model(value_unit='ft'))
        with self.assertRaises(gs.GeostatisticsError):kriging(q=[[0,0]]*257)


class VariogramChecks(unittest.TestCase):
    def test_known_pair_semivariances_bins_empty_and_last_edge(self):
        d=dataset([[0,0],[1,0],[2,0]],[0,2,4])
        r=gs.experimental_variogram(d,[0,1,2,3]);rows=r.records
        self.assertEqual(rows[0]['pair_count'],0);self.assertIsNone(rows[0]['semivariance'])
        self.assertEqual(rows[1]['pair_count'],2);self.assertEqual(rows[1]['semivariance'],2);self.assertEqual(rows[1]['mean_distance_m'],1)
        self.assertEqual(rows[2]['pair_count'],1);self.assertEqual(rows[2]['semivariance'],8)
        r=gs.experimental_variogram(d,[0,1,2]);self.assertEqual(r.records[-1]['pair_count'],3);self.assertEqual(r.records[-1]['semivariance'],4)
        self.assertEqual(r.to_dict()['metadata']['model_fitting'],'not performed')
        with self.assertRaises(gs.GeostatisticsError):gs.experimental_variogram(d,[0,1,1])


class GaussianChecks(unittest.TestCase):
    META=dict(crs='LOCAL:authored-metre',vertical_datum='authored-zero',provenance=['Authored simulation sites, no survey interpretation'])

    def test_seeded_unconditional_moments_match_independent_two_by_two_covariance(self):
        m=model(partial_sill=2,nugget=.2)
        a=gs.gaussian_field([[0,0],[1,0]],m,mean=7,seed=42,realizations=1024,metadata=self.META)
        b=gs.gaussian_field([[0,0],[1,0]],m,mean=7,seed=42,realizations=1024,metadata=self.META)
        self.assertEqual(a.to_dict(),b.to_dict())
        values=np.array([row[5:] for row in a.to_dict()['rows']])
        np.testing.assert_allclose(values.mean(axis=1),[7,7],atol=.2,rtol=0)
        np.testing.assert_allclose(np.cov(values),[[2.2,2*math.exp(-1)],[2*math.exp(-1),2.2]],atol=.25,rtol=0)
        self.assertEqual(a.to_dict()['metadata']['seed'],42)

    def test_conditional_known_mean_formula_and_exact_observed_process_value(self):
        d=dataset([[0,0]],[5]);r=gs.gaussian_field([[0,0],[1,0]],model(),mean=0,seed=42,realizations=512,metadata=self.META,conditioning=d)
        a,b=r.records
        self.assertEqual(a['conditional_mean'],5);self.assertEqual(a['conditional_variance'],0)
        self.assertTrue(all(a[f'r{i:04d}']==5 for i in range(512)))
        self.assertAlmostEqual(b['conditional_mean'],5*math.exp(-1),places=14)
        self.assertAlmostEqual(b['conditional_variance'],1-math.exp(-2),places=14)
        draws=np.array([b[f'r{i:04d}'] for i in range(512)])
        self.assertAlmostEqual(float(draws.mean()),5*math.exp(-1),delta=.15)
        self.assertAlmostEqual(float(draws.var(ddof=1)),1-math.exp(-2),delta=.2)
        fixed=gs.gaussian_field([[0,0]],model(nugget=.2),mean=0,seed=2,realizations=2,metadata=self.META,conditioning=d)
        self.assertEqual([fixed.records[0]['r0000'],fixed.records[0]['r0001']],[5,5])

    def test_conditional_multi_observation_hand_matrix(self):
        d=dataset([[0,0],[2,0]],[2,4]);m=model(partial_sill=2,nugget=.3)
        r=gs.gaussian_field([[1,0]],m,mean=10,seed=1,realizations=2,metadata=self.META,conditioning=d)
        rho=2*math.exp(-2);cross=2*math.exp(-1);weight=cross/(2.3+rho)
        self.assertAlmostEqual(r.records[0]['conditional_mean'],10+weight*((2-10)+(4-10)),places=13)
        self.assertAlmostEqual(r.records[0]['conditional_variance'],2.3-2*cross**2/(2.3+rho),places=13)

    def test_singular_duplicate_budget_metadata_and_seed_refused(self):
        for coords,m,kw in [([[0,0],[0,0]],model(),{}),([[0,0],[1e-6,0]],model(kind='gaussian',ranges_m=[1e9,1e9]),{}),([[0,0]],model(),dict(realizations=0)),([[0,0]]*256,model(),dict(realizations=1024)),([[0,0]],model(),dict(seed=True)),([[0,0]],model(),dict(metadata={**self.META,'crs':'unknown'})),([[0,0]],model(),dict(mean=1e50))]:
            settings=dict(mean=0,seed=1,realizations=2,metadata=self.META);settings.update(kw)
            with self.subTest(coords=len(coords),kw=kw),self.assertRaises(gs.GeostatisticsError):gs.gaussian_field(coords,m,**settings)


class LatinHypercubeChecks(unittest.TestCase):
    MARGINALS=[dict(name='conductivity',unit='m/day',distribution='uniform',parameters=dict(minimum=1,maximum=5)),dict(name='head',unit='m',distribution='normal',parameters=dict(mean=10,standard_deviation=2)),dict(name='porosity',unit='1',distribution='triangular',parameters=dict(minimum=.1,mode=.2,maximum=.4))]

    def test_deterministic_full_probability_stratification_and_units(self):
        r=gs.latin_hypercube(self.MARGINALS,samples=64,seed=42)
        self.assertEqual(r.to_dict(),gs.latin_hypercube(self.MARGINALS,samples=64,seed=42).to_dict())
        rows=r.records;probabilities=[[],[],[]]
        for row in rows:
            probabilities[0].append((row['conductivity']-1)/4)
            probabilities[1].append(NormalDist(10,2).cdf(row['head']))
            x=row['porosity'];cdf=(x-.1)**2/(.3*.1) if x<=.2 else 1-(.4-x)**2/(.3*.2)
            probabilities[2].append(cdf)
        for p in probabilities:self.assertEqual(sorted(int(v*64) for v in p),list(range(64)))
        self.assertEqual([c['unit'] for c in r.to_dict()['columns']],['1','m/day','m','1'])
        self.assertNotEqual([row['conductivity'] for row in rows],[row['conductivity'] for row in gs.latin_hypercube(self.MARGINALS,samples=64,seed=1).records])

    def test_tiny_triangular_range_resolved_and_invalid_marginals(self):
        tiny=[dict(name='tiny',unit='1',distribution='triangular',parameters=dict(minimum=0,mode=1e-200,maximum=2e-200))]
        vals=[row['tiny'] for row in gs.latin_hypercube(tiny,samples=16,seed=42).records]
        self.assertTrue(all(0<v<2e-200 for v in vals));self.assertEqual(len(set(vals)),16)
        for mutate in [lambda d:d[0]['parameters'].update(maximum=1),lambda d:d[0].update(distribution='lognormal'),lambda d:d.append(copy.deepcopy(d[0])),lambda d:d[1]['parameters'].update(standard_deviation=0),lambda d:d[1]['parameters'].update(mean=1e40,standard_deviation=1e-20)]:
            d=copy.deepcopy(self.MARGINALS);mutate(d)
            with self.assertRaises(gs.GeostatisticsError):gs.latin_hypercube(d,samples=16,seed=42)


class FileCliChecks(unittest.TestCase):
    def test_json_and_csv_exact_roundtrip_preserve_metadata_units_support_and_all_draws(self):
        results=[kriging(q=[[1,0],[3,0]]),gs.experimental_variogram(dataset(),[0,1,2]),gs.gaussian_field([[0,0],[1,0]],model(),mean=2,seed=42,realizations=4,metadata=GaussianChecks.META),gs.latin_hypercube(LatinHypercubeChecks.MARGINALS,samples=16,seed=42)]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for index,r in enumerate(results):
                for ext in ('json','csv'):
                    p=root/f'{index}.{ext}';gs.save_result(r,p);self.assertEqual(gs.load_result(p).to_dict(),r.to_dict())
                    with self.assertRaises(gs.GeostatisticsError):gs.save_result(r,p)
                self.assertTrue(gs.verify_result_roundtrip(r)['json_csv_semantic_equal'])
        self.assertEqual(results[0].to_dict()['metadata']['original_gms_comparison'],'NOT_OBSERVED')

    def test_corruption_duplicate_deep_json_table_type_fifo_and_fresh_recovery(self):
        r=kriging();d=r.to_dict()
        for mutate in [lambda d:d.update(extra=1),lambda d:d.update(schema='future'),lambda d:d['metadata'].update(original_gms_comparison='VERIFIED'),lambda d:d['rows'][0].__setitem__(1,True),lambda d:d['columns'][0].update(kind='object')]:
            data=copy.deepcopy(d);mutate(data)
            with self.assertRaises(gs.GeostatisticsError):gs.GeostatisticsResult.from_dict(data)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'bad.json'
            for raw in ('{"x":1,"x":2}','{"x":NaN}','['*1500+'0'+']'*1500):
                p.write_text(raw)
                with self.assertRaises(gs.GeostatisticsError):gs.load_result(p)
            source=root/'result.json';gs.save_result(r,source);link=root/'link.json';link.symlink_to(source)
            with self.assertRaises(gs.GeostatisticsError):gs.load_result(link)
            if hasattr(os,'mkfifo'):
                fifo=root/'fifo.json';os.mkfifo(fifo)
                with self.assertRaises(gs.GeostatisticsError):gs.load_result(fifo)
            csvpath=root/'wrong.csv';gs.save_result(r,csvpath);csvpath.write_text(csvpath.read_text().replace('id,x_m,y_m','id,y_m,x_m'))
            with self.assertRaises(gs.GeostatisticsError):gs.load_result(csvpath)
            with self.assertRaises(gs.GeostatisticsError):gs.save_result(r,root/'missing'/'out.json')
            gs.save_result(r,root/'recovered.json')

    def test_real_cli_krige_variogram_lhs_simulation_roundtrip_and_refusal_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);save_scatter(dataset(),root/'data.json')
            files={'model':model().to_dict(),'queries':[[1,0],[3,0]],'settings':dict(method='ordinary',mean=None,radius_m=10,min_neighbors=2,max_neighbors=32,domain_bounds_m=[[-1,4],[-1,4]],allow_extrapolation=False),'bins':[0,1,2],'sites':[[0,0],[1,0]],'simulation':dict(mean=0,seed=42,realizations=4,metadata=GaussianChecks.META),'marginals':LatinHypercubeChecks.MARGINALS,'lhs':dict(samples=16,seed=42)}
            for name,d in files.items():(root/(name+'.json')).write_text(json.dumps(d))
            def path(name):return str(root/(name+'.json'))
            self.assertEqual(gs.main(['krige',path('data'),path('model'),path('queries'),path('settings'),path('kriged')]),0)
            self.assertEqual(gs.main(['variogram',path('data'),path('bins'),path('variogram')]),0)
            self.assertEqual(gs.main(['simulate',path('model'),path('sites'),path('simulation'),path('simulated'),'--conditioning',path('data')]),0)
            self.assertEqual(gs.main(['lhs',path('marginals'),path('lhs'),path('sampled')]),0)
            self.assertEqual(gs.main(['roundtrip',path('kriged'),path('receipt')]),0)
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):gs.main(['roundtrip',path('kriged'),path('receipt')])
            self.assertEqual(gs.main(['roundtrip',path('kriged'),path('recovered')]),0)
            self.assertEqual(gs.load_result(path('kriged')).records[0]['prediction'],3)


if __name__=='__main__':unittest.main()
