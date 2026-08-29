"""Validated input models for a storage-screening scenario."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

import numpy as np


class InputValidationError(ValueError):
    """Raised when an input scenario is incomplete or physically implausible."""


@dataclass(frozen=True)
class TriangularEstimate:
    """Low, most-likely, and high values for a triangular distribution."""

    low: float
    mode: float
    high: float
    name: str = "parameter"
    minimum: float = 0.0
    maximum: float | None = None

    def __post_init__(self) -> None:
        values = (self.low, self.mode, self.high)
        if not all(isfinite(value) for value in values):
            raise InputValidationError(f"{self.name} must contain finite numbers")
        if not self.low <= self.mode <= self.high:
            raise InputValidationError(
                f"{self.name} must satisfy low <= mode <= high; got {values}"
            )
        if self.low < self.minimum:
            raise InputValidationError(
                f"{self.name} must be >= {self.minimum}; got {self.low}"
            )
        if self.maximum is not None and self.high > self.maximum:
            raise InputValidationError(
                f"{self.name} must be <= {self.maximum}; got {self.high}"
            )

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Draw samples, supporting fixed values where low == mode == high."""

        if self.low == self.high:
            return np.full(size, self.low, dtype=float)
        return rng.triangular(self.low, self.mode, self.high, size=size)


@dataclass(frozen=True)
class SiteScenario:
    """Inputs for a conceptual saline-aquifer storage screening scenario."""

    site_id: str
    site_name: str
    area_km2: TriangularEstimate
    net_thickness_m: TriangularEstimate
    porosity: TriangularEstimate
    co2_density_kg_m3: TriangularEstimate
    storage_efficiency: TriangularEstimate
    caprock_thickness_m: float
    fault_distance_km: float
    legacy_wells_per_100km2: float

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise InputValidationError("site_id cannot be empty")
        if not self.site_name.strip():
            raise InputValidationError("site_name cannot be empty")

        screening_values = {
            "caprock_thickness_m": self.caprock_thickness_m,
            "fault_distance_km": self.fault_distance_km,
            "legacy_wells_per_100km2": self.legacy_wells_per_100km2,
        }
        for name, value in screening_values.items():
            if not isfinite(value) or value < 0:
                raise InputValidationError(f"{name} must be a finite non-negative value")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "SiteScenario":
        """Build a scenario from one row of the documented CSV schema."""

        def estimate(
            prefix: str,
            *,
            minimum: float = 0.0,
            maximum: float | None = None,
        ) -> TriangularEstimate:
            try:
                return TriangularEstimate(
                    low=float(row[f"{prefix}_low"]),
                    mode=float(row[f"{prefix}_mode"]),
                    high=float(row[f"{prefix}_high"]),
                    name=prefix,
                    minimum=minimum,
                    maximum=maximum,
                )
            except KeyError as exc:
                raise InputValidationError(f"missing required column: {exc.args[0]}") from exc
            except (TypeError, ValueError) as exc:
                raise InputValidationError(f"{prefix} contains a non-numeric value") from exc

        try:
            return cls(
                site_id=str(row["site_id"]),
                site_name=str(row["site_name"]),
                area_km2=estimate("area_km2"),
                net_thickness_m=estimate("net_thickness_m"),
                porosity=estimate("porosity", maximum=1.0),
                co2_density_kg_m3=estimate("co2_density_kg_m3"),
                storage_efficiency=estimate("storage_efficiency", maximum=1.0),
                caprock_thickness_m=float(row["caprock_thickness_m"]),
                fault_distance_km=float(row["fault_distance_km"]),
                legacy_wells_per_100km2=float(row["legacy_wells_per_100km2"]),
            )
        except KeyError as exc:
            raise InputValidationError(f"missing required column: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise InputValidationError("screening fields must be numeric") from exc

