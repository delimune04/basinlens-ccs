"""Independent labelled-cell coordinate checks against actual exported DIS."""
from dataclasses import replace
import importlib.util
import tempfile
from pathlib import Path
import unittest

import numpy as np

from basinlens_ccs.groundwater import GroundwaterCase, demo_case
from basinlens_ccs.subsurface import default_registry, project_from_groundwater, ProjectValidationError
from basinlens_ccs.subsurface.coordinates import coordinate_contract, native_to_project_xy, project_cell_centres_xy


class ProjectCoordinateTests(unittest.TestCase):
    def project(self):
        data = demo_case().to_dict()
        data["grid"].update(nrow=3, ncol=5, delr_m=7.0, delc_m=20.0)
        data["wells"] = []
        for period in data["periods"]:
            period.pop("wells", None)
        project = project_from_groundwater(GroundwaterCase.from_dict(data), domain="ccs")
        return replace(project, geometry=replace(project.geometry, origin_x_m=350000.0, origin_y_m=4100000.0))

    def test_asymmetric_labelled_rows_use_project_y_direction(self):
        p = self.project()
        x, y = project_cell_centres_xy(p)
        np.testing.assert_array_equal(x[0], [350003.5, 350010.5, 350017.5, 350024.5, 350031.5])
        np.testing.assert_array_equal(y[:, 0], [4100010.0, 4100030.0, 4100050.0])
        native_x, native_y = np.meshgrid([3.5, 10.5, 17.5, 24.5, 31.5], [50.0, 30.0, 10.0])
        mapped_x, mapped_y = native_to_project_xy(p, native_x, native_y)
        np.testing.assert_array_equal(mapped_x, x)
        np.testing.assert_array_equal(mapped_y, y)
        mapping = default_registry().validate(p)
        self.assertEqual(mapping["mapping_schema_version"], 2)
        self.assertIn("reflection", mapping["local_coordinate_transform"])
        self.assertEqual(mapping["native_grid_height_m"], 60.0)

    @unittest.skipUnless(importlib.util.find_spec("flopy"), "Install FloPy for native DIS coordinate checks")
    def test_every_actual_exported_and_reloaded_cell_maps_to_its_project_label(self):
        import flopy
        p = self.project()
        with tempfile.TemporaryDirectory() as temporary:
            result = default_registry().export(p, Path(temporary) / "export")
            sim = flopy.mf6.MFSimulation.load(sim_ws=str(result.workspace / "engine/model"), verbosity_level=0)
            grid = sim.get_model().modelgrid
            x, y = native_to_project_xy(p, grid.xcellcenters, grid.ycellcenters)
            for row in range(3):
                for col in range(5):
                    self.assertEqual(x[row, col], 350000.0 + (col + 0.5) * 7.0)
                    self.assertEqual(y[row, col], 4100000.0 + (row + 0.5) * 20.0)
            self.assertTrue(np.all(np.diff(grid.ycellcenters[:, 0]) < 0))
            self.assertTrue(np.all(np.diff(y[:, 0]) > 0))

    def test_invalid_points_shapes_axes_and_overflow_are_refused(self):
        p = self.project()
        for x, y in [([1, 2], [1]), ([float("nan")], [1]), ([1], [61]), ([36], [1]), ([True], [False]), (["1"], ["2"])]:
            with self.subTest(x=x, y=y), self.assertRaises(ProjectValidationError):
                native_to_project_xy(p, x, y)
        with self.assertRaises(ProjectValidationError):
            coordinate_contract(replace(p, geometry=replace(p.geometry, delc_m=1e308)))
        with self.assertRaises(ProjectValidationError):
            coordinate_contract(replace(p, spatial_reference=replace(p.spatial_reference, local_axes="different axes")))
