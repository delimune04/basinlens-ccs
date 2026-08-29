import unittest

from basinlens_ccs.models import InputValidationError, SiteScenario, TriangularEstimate


class TriangularEstimateTests(unittest.TestCase):
    def test_rejects_reversed_range(self):
        with self.assertRaises(InputValidationError):
            TriangularEstimate(2.0, 1.0, 3.0, name="bad")

    def test_rejects_fraction_above_one(self):
        with self.assertRaises(InputValidationError):
            TriangularEstimate(0.1, 0.5, 1.1, name="fraction", maximum=1.0)


class SiteScenarioTests(unittest.TestCase):
    def test_rejects_negative_fault_distance(self):
        fixed = TriangularEstimate(1.0, 1.0, 1.0)
        fraction = TriangularEstimate(0.1, 0.1, 0.1, maximum=1.0)
        with self.assertRaises(InputValidationError):
            SiteScenario(
                site_id="X",
                site_name="Test",
                area_km2=fixed,
                net_thickness_m=fixed,
                porosity=fraction,
                co2_density_kg_m3=fixed,
                storage_efficiency=fraction,
                caprock_thickness_m=100,
                fault_distance_km=-1,
                legacy_wells_per_100km2=0,
            )


if __name__ == "__main__":
    unittest.main()

