"""Transparent, illustrative screening flags for further investigation."""

from __future__ import annotations

from dataclasses import dataclass

from .models import SiteScenario


@dataclass(frozen=True)
class AttentionResult:
    """An attention score, not a geologic risk or certification result."""

    total_score: float
    category: str
    components: dict[str, float]

    def to_record(self) -> dict[str, float | str]:
        return {
            "attention_score": self.total_score,
            "attention_category": self.category,
            **{f"attention_{name}": value for name, value in self.components.items()},
        }


def _descending_penalty(value: float, poor: float, good: float) -> float:
    """Return 100 at/below a poor threshold and 0 at/above a good threshold."""

    if value <= poor:
        return 100.0
    if value >= good:
        return 0.0
    return 100.0 * (good - value) / (good - poor)


def _ascending_penalty(value: float, good: float, poor: float) -> float:
    """Return 0 at/below a good threshold and 100 at/above a poor threshold."""

    if value <= good:
        return 0.0
    if value >= poor:
        return 100.0
    return 100.0 * (value - good) / (poor - good)


def calculate_attention(site: SiteScenario) -> AttentionResult:
    """Calculate a configurable demonstration-only attention score.

    Thresholds are deliberately visible and simple. They are placeholders for
    literature- or project-specific criteria and must not be used for real site
    selection without expert review and additional evidence.
    """

    components = {
        "caprock": _descending_penalty(
            site.caprock_thickness_m, poor=20.0, good=100.0
        ),
        "fault_proximity": _descending_penalty(
            site.fault_distance_km, poor=1.0, good=10.0
        ),
        "legacy_wells": _ascending_penalty(
            site.legacy_wells_per_100km2, good=0.0, poor=20.0
        ),
    }
    weights = {"caprock": 0.45, "fault_proximity": 0.35, "legacy_wells": 0.20}
    total_score = sum(components[name] * weights[name] for name in components)

    if total_score <= 25:
        category = "Lower attention"
    elif total_score <= 50:
        category = "Moderate attention"
    elif total_score <= 75:
        category = "High attention"
    else:
        category = "Very high attention"

    return AttentionResult(
        total_score=round(total_score, 2),
        category=category,
        components={name: round(value, 2) for name, value in components.items()},
    )

