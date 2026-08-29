import unittest

import pandas as pd

from basinlens_ccs.io import sites_from_dataframe
from basinlens_ccs.models import InputValidationError


class InputTests(unittest.TestCase):
    def test_duplicate_site_ids_are_rejected(self):
        row = {
            "site_id": "DUP",
            "site_name": "Duplicate",
            "area_km2_low": 1,
            "area_km2_mode": 2,
            "area_km2_high": 3,
            "net_thickness_m_low": 10,
            "net_thickness_m_mode": 15,
            "net_thickness_m_high": 20,
            "porosity_low": 0.1,
            "porosity_mode": 0.2,
            "porosity_high": 0.3,
            "co2_density_kg_m3_low": 600,
            "co2_density_kg_m3_mode": 650,
            "co2_density_kg_m3_high": 700,
            "storage_efficiency_low": 0.01,
            "storage_efficiency_mode": 0.02,
            "storage_efficiency_high": 0.03,
            "caprock_thickness_m": 100,
            "fault_distance_km": 10,
            "legacy_wells_per_100km2": 0,
        }
        with self.assertRaises(InputValidationError):
            sites_from_dataframe(pd.DataFrame([row, row]))


if __name__ == "__main__":
    unittest.main()

