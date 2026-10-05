"""Regression coverage for the legacy CSV and direct-Python input contract."""

import contextlib
from dataclasses import replace
from io import BytesIO, StringIO
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from basinlens_ccs.analysis import analyze_sites
from basinlens_ccs.artifacts import verify_run_bundle
from basinlens_ccs.capacity import _rank_correlation
from basinlens_ccs.cli import main
from basinlens_ccs.io import load_sites, read_site_dataframe, sites_from_dataframe
from basinlens_ccs.models import InputValidationError, SiteScenario, TriangularEstimate


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_sites.csv"


def valid_row():
    return read_site_dataframe(EXAMPLE).iloc[0].to_dict()


def valid_site():
    return SiteScenario.from_mapping(valid_row())


class IdentityValidationTests(unittest.TestCase):
    def test_invalid_identity_in_mapping_and_direct_construction(self):
        site = valid_site()
        for name in ("site_id", "site_name"):
            for value in (None, np.nan, pd.NA, "", " \t ", "NaN", " nan ", 123, False):
                with self.subTest(field=name, value=repr(value)):
                    row = valid_row()
                    row[name] = value
                    with self.assertRaisesRegex(InputValidationError, name):
                        SiteScenario.from_mapping(row)
                    with self.assertRaisesRegex(InputValidationError, name):
                        replace(site, **{name: value})

    def test_identities_are_trimmed_without_losing_leading_zeros(self):
        site = replace(valid_site(), site_id=" 001 ", site_name=" Alpha ")
        self.assertEqual((site.site_id, site.site_name), ("001", "Alpha"))

    def test_csv_preserves_numeric_and_na_like_strings(self):
        ids = ["001", "1", "NA", "N/A", "NULL", "1e3"]
        frame = pd.DataFrame([dict(valid_row(), site_id=value) for value in ids])
        raw = frame.to_csv(index=False).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sites.csv"
            path.write_bytes(raw)
            self.assertEqual([site.site_id for site in load_sites(path)], ids)
        uploaded = sites_from_dataframe(read_site_dataframe(BytesIO(raw)))
        self.assertEqual([site.site_id for site in uploaded], ids)

    def test_duplicate_canonical_ids_are_rejected_with_row_number(self):
        frame = pd.DataFrame([
            dict(valid_row(), site_id="DUP"), dict(valid_row(), site_id=" DUP "),
        ], index=["alpha", "beta"])
        with self.assertRaisesRegex(InputValidationError, "row 3: duplicate site_id: DUP"):
            sites_from_dataframe(frame)

    def test_error_row_uses_position_not_dataframe_index(self):
        frame = pd.DataFrame([dict(valid_row(), porosity_mode="bad")], index=["site-A"])
        with self.assertRaisesRegex(InputValidationError, "row 2: porosity_mode.*non-numeric"):
            sites_from_dataframe(frame)

    def test_blank_csv_identity_is_rejected(self):
        for field in ("site_id", "site_name"):
            raw = pd.DataFrame([dict(valid_row(), **{field: ""})]).to_csv(index=False)
            with self.subTest(field=field), self.assertRaisesRegex(InputValidationError, field):
                sites_from_dataframe(read_site_dataframe(StringIO(raw)))


class PhysicalValidationTests(unittest.TestCase):
    def test_direct_fraction_bounds_cannot_be_bypassed(self):
        for name in ("porosity", "storage_efficiency"):
            for estimate in (
                TriangularEstimate(0.1, 0.5, 1.1),
                TriangularEstimate(-0.1, 0.1, 0.2, minimum=-1),
            ):
                with self.subTest(field=name, estimate=estimate):
                    with self.assertRaisesRegex(InputValidationError, name):
                        replace(valid_site(), **{name: estimate})

    def test_direct_nonnegative_bounds_cannot_be_bypassed(self):
        for name in ("area_km2", "net_thickness_m", "co2_density_kg_m3"):
            with self.subTest(field=name), self.assertRaisesRegex(InputValidationError, name):
                replace(valid_site(), **{name: TriangularEstimate(-1, 0, 1, minimum=-1)})

    def test_fraction_endpoints_and_zero_physical_inputs_remain_valid(self):
        site = valid_site()
        for name in ("area_km2", "net_thickness_m", "co2_density_kg_m3", "porosity", "storage_efficiency"):
            zero = TriangularEstimate(0, 0, 0)
            self.assertEqual(getattr(replace(site, **{name: zero}), name), zero)
        for name in ("porosity", "storage_efficiency"):
            one = TriangularEstimate(1, 1, 1)
            self.assertEqual(getattr(replace(site, **{name: one}), name), one)

    def test_direct_estimate_type_error_names_field(self):
        with self.assertRaisesRegex(InputValidationError, "porosity.*TriangularEstimate"):
            replace(valid_site(), porosity=0.2)

    def test_direct_screening_errors_name_field(self):
        for name in ("caprock_thickness_m", "fault_distance_km", "legacy_wells_per_100km2"):
            for value in (-1, np.nan, np.inf, None, "abc", True, 10**1000):
                with self.subTest(field=name, value=value), self.assertRaisesRegex(InputValidationError, name):
                    replace(valid_site(), **{name: value})

    def test_numeric_field_errors_are_not_relabelled(self):
        for name in ("porosity_mode", "fault_distance_km", "area_km2_low"):
            for value in ("bad", None, np.nan, np.inf, True):
                with self.subTest(field=name, value=value), self.assertRaisesRegex(InputValidationError, name):
                    SiteScenario.from_mapping(dict(valid_row(), **{name: value}))

    def test_range_errors_preserve_original_reason(self):
        cases = [
            ({"area_km2_low": 999}, "area_km2 must satisfy low <= mode <= high"),
            ({"porosity_high": 1.1}, "porosity must be <= 1"),
            ({"fault_distance_km": -1}, "fault_distance_km.*non-negative"),
        ]
        for values, message in cases:
            with self.subTest(values=values), self.assertRaisesRegex(InputValidationError, message):
                SiteScenario.from_mapping(dict(valid_row(), **values))

    def test_missing_columns_retain_exact_name(self):
        for name in ("site_id", "porosity_mode", "caprock_thickness_m"):
            row = valid_row()
            del row[name]
            with self.subTest(field=name), self.assertRaisesRegex(InputValidationError, f"missing required column: {name}"):
                SiteScenario.from_mapping(row)

    def test_invalid_estimate_numbers_and_bounds(self):
        for value in (None, "1", np.nan, np.inf, True, 10**1000):
            with self.subTest(value=value), self.assertRaisesRegex(InputValidationError, "porosity_low"):
                TriangularEstimate(value, 1, 1, name="porosity")
        for kwargs in ({"minimum": np.nan}, {"maximum": np.inf}, {"minimum": 2, "maximum": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InputValidationError):
                TriangularEstimate(1, 1, 1, **kwargs)


class AnalysisValidationTests(unittest.TestCase):
    def test_direct_duplicates_rejected_before_simulation(self):
        site = valid_site()
        with patch("basinlens_ccs.analysis.simulate_capacity") as simulate:
            with self.assertRaisesRegex(InputValidationError, "duplicate site_id"):
                analyze_sites([site, site])
            simulate.assert_not_called()

    def test_empty_scenario_list_is_rejected(self):
        with self.assertRaisesRegex(InputValidationError, "no site"):
            analyze_sites([])

    def test_summary_ties_are_sorted_by_id(self):
        site = valid_site()
        for name in ("area_km2", "net_thickness_m", "porosity", "co2_density_kg_m3", "storage_efficiency"):
            value = getattr(site, name).mode
            site = replace(site, **{name: TriangularEstimate(value, value, value)})
        sites = [replace(site, site_id=value) for value in ("B", "A", "C")]
        for permutation in itertools.permutations(sites):
            summary, _, _ = analyze_sites(list(permutation), sample_count=100)
            self.assertEqual(list(summary.site_id), ["A", "B", "C"])

    def test_tied_rank_correlation_matches_hand_calculation(self):
        # x ranks [1.5, 1.5, 3], y ranks [1, 2.5, 2.5]: Pearson r = 0.5.
        x, y = np.array([1, 1, 2]), np.array([1, 2, 2])
        for order in itertools.permutations(range(3)):
            index = list(order)
            self.assertAlmostEqual(_rank_correlation(x[index], y[index]), 0.5)
        self.assertAlmostEqual(_rank_correlation(x, -y), -0.5)

    def test_untied_ranks_and_constant_sentinel(self):
        x = np.array([3, 1, 2])
        self.assertAlmostEqual(_rank_correlation(x, x), 1.0)
        self.assertAlmostEqual(_rank_correlation(x, -x), -1.0)
        self.assertEqual(_rank_correlation(x, np.ones(3)), 0.0)
        self.assertEqual(_rank_correlation(np.ones(3), x), 0.0)


class ValidationBundleTests(unittest.TestCase):
    def test_cli_preserves_ids_in_every_bundle_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "input.csv", root / "run"
            ids = ["001", "1", "NA"]
            pd.DataFrame([dict(valid_row(), site_id=value) for value in ids]).to_csv(source, index=False)
            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(main([str(source), "--output", str(target), "--samples", "100"]), 0)
            self.assertEqual((target / "input.csv").read_bytes(), source.read_bytes())
            manifest = json.loads((target / "run_metadata.json").read_text())
            self.assertEqual(list(manifest["site_seeds"]), ids)
            for name in ("summary.csv", "sensitivity.csv"):
                frame = pd.read_csv(target / name, dtype={"site_id": str}, keep_default_na=False)
                self.assertEqual(set(frame.site_id), set(ids))
            report = (target / "report.md").read_text()
            for value in ids:
                self.assertIn(f"| {value} |", report)
            verify_run_bundle(target)

    def test_invalid_cli_input_keeps_field_and_creates_no_output(self):
        for values in ({"site_id": " "}, {"porosity_high": 1.1}, {"fault_distance_km": "bad"}):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as directory:
                source, target = Path(directory) / "input.csv", Path(directory) / "run"
                pd.DataFrame([dict(valid_row(), **values)]).to_csv(source, index=False)
                stderr = StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    main([str(source), "--output", str(target)])
                self.assertEqual(error.exception.code, 2)
                self.assertIn("row 2", stderr.getvalue())
                self.assertIn(next(iter(values)).split("_high")[0], stderr.getvalue())
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
