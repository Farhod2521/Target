"""Pure-Python domain layer.

No Django here: no models, no settings, no clock. Everything enters and
leaves as a dataclass from ``core.contracts``, and the current time arrives
as an argument. That is what keeps this layer testable without a database
and readable without knowing the framework.
"""
