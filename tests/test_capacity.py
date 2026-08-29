import unittest

import numpy as np

from basinlens_ccs.capacity import simulate_capacity, volumetric_capacity_mt
from basinlens_ccs.models import SiteScenario, TriangularEstimate


def fixed(value, *, maximum=None):
    return TriangularEstimate(value, value, value, maximum=maximum)


class CapacityTests(unittest.TestCase):
    def test_known_volumetric_result(self):
        result = volumetric_capacity_mt(
            area_km2=np.array([1.0]),
            net_thickness_m=np.array([10.0]),
            porosity=np.array([0.2]),
            co2_density_kg_m3=np.array([700.0]),
            storage_efficiency=np.array([0.02]),
        )
        self.assertAlmostEqual(float(result[0]), 0.028, places=12)

    def test_fixed_scenario_has_fixed_capacity(self):
        site = SiteScenario(
            site_id="FIXED",
            site_name="Fixed test",
            area_km2=fixed(1.0),
            net_thickness_m=fixed(10.0),
            porosity=fixed(0.2, maximum=1.0),
            co2_density_kg_m3=fixed(700.0),
            storage_efficiency=fixed(0.02, maximum=1.0),
            caprock_thickness_m=100.0,
            fault_distance_km=10.0,
            legacy_wells_per_100km2=0.0,
        )
        result = simulate_capacity(site, sample_count=100, seed=1)
        self.assertTrue(np.allclose(result.samples_mt, 0.028))
        self.assertAlmostEqual(result.q50_mt, 0.028)
        self.assertTrue(all(value == 0.0 for value in result.sensitivity.values()))

    def test_simulation_is_reproducible(self):
        site = SiteScenario(
            site_id="RNG",
            site_name="Random test",
            area_km2=TriangularEstimate(1, 2, 3),
            net_thickness_m=TriangularEstimate(10, 15, 20),
            porosity=TriangularEstimate(0.1, 0.2, 0.3, maximum=1.0),
            co2_density_kg_m3=TriangularEstimate(600, 650, 700),
            storage_efficiency=TriangularEstimate(0.01, 0.02, 0.03, maximum=1.0),
            caprock_thickness_m=100,
            fault_distance_km=10,
            legacy_wells_per_100km2=0,
        )
        first = simulate_capacity(site, sample_count=500, seed=7)
        second = simulate_capacity(site, sample_count=500, seed=7)
        self.assertTrue(np.array_equal(first.samples_mt, second.samples_mt))


if __name__ == "__main__":
    unittest.main()

