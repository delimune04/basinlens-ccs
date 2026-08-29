"""BasinLens CCS prototype package."""

from .analysis import analyze_sites
from .capacity import CapacityResult, simulate_capacity
from .io import load_sites, sites_from_dataframe
from .models import InputValidationError, SiteScenario, TriangularEstimate
from .screening import AttentionResult, calculate_attention

__all__ = [
    "analyze_sites",
    "AttentionResult",
    "calculate_attention",
    "CapacityResult",
    "InputValidationError",
    "load_sites",
    "simulate_capacity",
    "SiteScenario",
    "sites_from_dataframe",
    "TriangularEstimate",
]

__version__ = "0.1.0"

