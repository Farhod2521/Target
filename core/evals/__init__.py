"""Measuring what the model actually answers, against rules a machine can check."""

from core.evals.cases import Case, load_cases
from core.evals.grade import Mark, Report, grade

__all__ = ["Case", "Mark", "Report", "grade", "load_cases"]
