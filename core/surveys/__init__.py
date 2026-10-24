"""Platform surveys: which questions a customer is asked, given their answers."""

from core.surveys.branching import Rule, asked_positions, rule_problem

__all__ = ["Rule", "asked_positions", "rule_problem"]
