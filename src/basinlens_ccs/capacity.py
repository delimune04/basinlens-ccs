"""Probabilistic volumetric capacity calculations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import InputValidationError, SiteScenario


PARAMETER_LABELS = {
    "area_km2": "Storage area",
    "net_thickness_m": "Net thickness",
    "porosity": "Porosity",
    "co2_density_kg_m3": "CO2 density",
    "storage_efficiency": "Storage efficiency",
}


@dataclass(frozen=True)
class CapacityResult:
    """Monte Carlo samples and summary statistics for one site."""

    site_id: str
    site_name: str
    samples_mt: np.ndarray
    sensitivity: dict[str, float]

    @property
    def q10_mt(self) -> float:
        return float(np.quantile(self.samples_mt, 0.10))

    @property
    def q50_mt(self) -> float:
        return float(np.quantile(self.samples_mt, 0.50))

    @property
    def q90_mt(self) -> float:
        return float(np.quantile(self.samples_mt, 0.90))

    @property
    def mean_mt(self) -> float:
        return float(np.mean(self.samples_mt))

    @property
    def standard_deviation_mt(self) -> float:
        return float(np.std(self.samples_mt, ddof=1))

    def to_record(self) -> dict[str, float | str]:
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "capacity_q10_mt": self.q10_mt,
            "capacity_q50_mt": self.q50_mt,
            "capacity_q90_mt": self.q90_mt,
            "capacity_mean_mt": self.mean_mt,
            "capacity_sd_mt": self.standard_deviation_mt,
        }


def volumetric_capacity_mt(
    area_km2: np.ndarray,
    net_thickness_m: np.ndarray,
    porosity: np.ndarray,
    co2_density_kg_m3: np.ndarray,
    storage_efficiency: np.ndarray,
) -> np.ndarray:
    """Calculate effective storage capacity in million metric tonnes (Mt).

    M = A * h * phi * rho_CO2 * E

    This is a screening-level volumetric estimate. It does not model pressure,
    injectivity, plume migration, geochemistry, leakage, or economics.
    """

    area_m2 = area_km2 * 1_000_000.0
    mass_kg = (
        area_m2
        * net_thickness_m
        * porosity
        * co2_density_kg_m3
        * storage_efficiency
    )
    return mass_kg / 1_000_000_000.0


def _rank_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman-style correlation without requiring SciPy."""

    if np.all(x == x[0]) or np.all(y == y[0]):
        return 0.0
    x_rank = np.argsort(np.argsort(x, kind="mergesort"), kind="mergesort").astype(float)
    y_rank = np.argsort(np.argsort(y, kind="mergesort"), kind="mergesort").astype(float)
    return float(np.corrcoef(x_rank, y_rank)[0, 1])


def simulate_capacity(
    site: SiteScenario,
    *,
    sample_count: int = 20_000,
    seed: int = 42,
) -> CapacityResult:
    """Run a reproducible Monte Carlo capacity simulation for one scenario."""

    if sample_count < 100:
        raise InputValidationError("sample_count must be at least 100")

    rng = np.random.default_rng(seed)
    inputs = {
        "area_km2": site.area_km2.sample(rng, sample_count),
        "net_thickness_m": site.net_thickness_m.sample(rng, sample_count),
        "porosity": site.porosity.sample(rng, sample_count),
        "co2_density_kg_m3": site.co2_density_kg_m3.sample(rng, sample_count),
        "storage_efficiency": site.storage_efficiency.sample(rng, sample_count),
    }
    samples_mt = volumetric_capacity_mt(**inputs)
    sensitivity = {
        PARAMETER_LABELS[name]: _rank_correlation(values, samples_mt)
        for name, values in inputs.items()
    }

    return CapacityResult(
        site_id=site.site_id,
        site_name=site.site_name,
        samples_mt=samples_mt,
        sensitivity=sensitivity,
    )
