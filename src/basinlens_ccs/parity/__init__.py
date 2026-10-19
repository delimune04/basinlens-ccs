"""Evidence-bound numerical comparisons; no claim of complete GMS equivalence."""

from .comparison import compare_datasets, verify_report
from .coverage import assess_catalogue
from .dataset import ParityError, artifact_record, input_fingerprint, load_dataset

__all__ = ["ParityError", "artifact_record", "input_fingerprint", "load_dataset",
           "compare_datasets", "verify_report", "assess_catalogue"]
