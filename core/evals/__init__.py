"""Measuring what the model actually answers, against rules a machine can check.

**Nothing here runs in the product.** It is read by one management command
that a person starts by hand, because the calls cost money and go to the
real provider - see ``apps.audit.management.commands.evaluate_prompts``.

Django-free, like the rest of ``core``: a case is text and a mark is a
boolean, and the graders are the ones the product already trusts - the
figure gate that guards every answer a customer reads, and the word check
that guards advert copy. Grading with a second set of rules would measure
the grader.
"""

from core.evals.cases import Case, load_cases
from core.evals.grade import Mark, Report, grade

__all__ = ["Case", "Mark", "Report", "grade", "load_cases"]
