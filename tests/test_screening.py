import unittest

from basinlens_ccs.models import SiteScenario, TriangularEstimate
from basinlens_ccs.screening import calculate_attention


def scenario(caprock, fault_distance, legacy_wells):
    fixed = TriangularEstimate(1, 1, 1)
    fraction = TriangularEstimate(0.1, 0.1, 0.1, maximum=1.0)
    return SiteScenario(
        site_id="TEST",
        site_name="Test",
        area_km2=fixed,
        net_thickness_m=fixed,
        porosity=fraction,
        co2_density_kg_m3=fixed,
        storage_efficiency=fraction,
        caprock_thickness_m=caprock,
        fault_distance_km=fault_distance,
        legacy_wells_per_100km2=legacy_wells,
    )


class AttentionTests(unittest.TestCase):
    def test_good_demo_inputs_have_zero_attention(self):
        result = calculate_attention(scenario(100, 10, 0))
        self.assertEqual(result.total_score, 0.0)
        self.assertEqual(result.category, "Lower attention")

    def test_poor_demo_inputs_have_maximum_attention(self):
        result = calculate_attention(scenario(20, 1, 20))
        self.assertEqual(result.total_score, 100.0)
        self.assertEqual(result.category, "Very high attention")


if __name__ == "__main__":
    unittest.main()

