"""Validated input models for a storage-screening scenario."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Any, Mapping

import numpy as np


class InputValidationError(ValueError):
    """Raised when an input scenario is incomplete or physically implausible."""


def _finite_number(value: Any, name: str) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise InputValidationError(f"{name} must be a finite number")
    if not isfinite(value):
        raise InputValidationError(f"{name} must be a finite number")


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() == "nan":
        raise InputValidationError(f"{name} must be a non-empty string, not missing or NaN")
    return value.strip()


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
        for suffix, value in zip(("low", "mode", "high"), values):
            _finite_number(value, f"{self.name}_{suffix}")
        _finite_number(self.minimum, f"{self.name} minimum")
        if self.maximum is not None:
            _finite_number(self.maximum, f"{self.name} maximum")
            if self.minimum > self.maximum:
                raise InputValidationError(f"{self.name} minimum must be <= maximum")
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
        object.__setattr__(self, "site_id", _identity(self.site_id, "site_id"))
        object.__setattr__(self, "site_name", _identity(self.site_name, "site_name"))

        # Scenario bounds are mandatory even if an estimate was built with
        # custom or omitted bounds. Zero remains a valid screening boundary.
        for name in (
            "area_km2", "net_thickness_m", "porosity",
            "co2_density_kg_m3", "storage_efficiency",
        ):
            value = getattr(self, name)
            if not isinstance(value, TriangularEstimate):
                raise InputValidationError(f"{name} must be a TriangularEstimate")
            if value.low < 0:
                raise InputValidationError(f"{name} must be >= 0; got {value.low}")
            if name in ("porosity", "storage_efficiency") and value.high > 1:
                raise InputValidationError(f"{name} must be <= 1; got {value.high}")

        screening_values = {
            "caprock_thickness_m": self.caprock_thickness_m,
            "fault_distance_km": self.fault_distance_km,
            "legacy_wells_per_100km2": self.legacy_wells_per_100km2,
        }
        for name, value in screening_values.items():
            _finite_number(value, name)
            if value < 0:
                raise InputValidationError(f"{name} must be a finite non-negative value")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "SiteScenario":
        """Build a scenario from one row of the documented CSV schema."""

        def required(name: str) -> Any:
            try:
                return row[name]
            except KeyError as exc:
                raise InputValidationError(f"missing required column: {name}") from exc

        def numeric(name: str) -> float:
            raw = required(name)
            if isinstance(raw, (bool, np.bool_)):
                raise InputValidationError(f"{name} must be numeric, not boolean")
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise InputValidationError(f"{name} contains a non-numeric value") from exc
            _finite_number(value, name)
            return value

        def estimate(
            prefix: str,
            *,
            minimum: float = 0.0,
            maximum: float | None = None,
        ) -> TriangularEstimate:
            return TriangularEstimate(
                low=numeric(f"{prefix}_low"),
                mode=numeric(f"{prefix}_mode"),
                high=numeric(f"{prefix}_high"),
                name=prefix,
                minimum=minimum,
                maximum=maximum,
            )

        return cls(
            site_id=_identity(required("site_id"), "site_id"),
            site_name=_identity(required("site_name"), "site_name"),
            area_km2=estimate("area_km2"),
            net_thickness_m=estimate("net_thickness_m"),
            porosity=estimate("porosity", maximum=1.0),
            co2_density_kg_m3=estimate("co2_density_kg_m3"),
            storage_efficiency=estimate("storage_efficiency", maximum=1.0),
            caprock_thickness_m=numeric("caprock_thickness_m"),
            fault_distance_km=numeric("fault_distance_km"),
            legacy_wells_per_100km2=numeric("legacy_wells_per_100km2"),
        )

