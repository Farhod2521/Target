import re
from typing import Any


def _snake(name: str) -> str:
    """``NoEntitlement`` -> ``no_entitlement``, ``CRMSeatTaken`` -> ``crm_seat_taken``."""
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", spaced).lower()


class DomainError(Exception):
    """A rule the user broke. The message is shown to them as is.

    ``code`` is what a client branches on - send to the plans, to the
    profile, show it beside a field - so every refusal has its own. A
    subclass that names none takes its class name in snake case
    (``TrialLimitReached`` answers ``trial_limit_reached``); one under a
    class that named its code by hand keeps that family's code, because the
    shape of the answer is the family's (``invalid_input`` carries
    ``problems``). A bare ``DomainError("...")`` stays ``domain_error``.
    """

    status_code = 400
    code = "domain_error"
    _code_named = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "code" in cls.__dict__:
            cls._code_named = True
        elif not cls._code_named:
            cls.code = _snake(cls.__name__)

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = str(message)


class ProviderRefused(DomainError):
    """The network said no to something the owner pressed.

    ``refusal`` is the whole dialog, in the shape of ``app.common.contract.Refusal``.
    """

    status_code = 422
    code = "provider_refused"

    def __init__(self, message: str, *, refusal: dict[str, Any]) -> None:
        super().__init__(message)
        self.refusal = refusal


class NotAllowed(DomainError):
    status_code = 403
    code = "not_allowed"


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class ConfigurationError(Exception):
    pass


class LLMUnavailable(ConfigurationError):
    pass


class DecryptionFailed(ConfigurationError):
    pass


class InputRefused(DomainError):
    """A request whose fields were checked and refused, field by field.

    ``problems`` maps a field name to the sentence shown under it; ``""``
    is the request as a whole.
    """

    status_code = 422
    code = "invalid_input"

    def __init__(
        self,
        problems: dict[str, str],
        message: str = "",
        *,
        hints: dict[str, str] | None = None,
    ) -> None:
        first = next(iter(problems.values()), "")
        super().__init__(message or first or "Kiritilgan ma'lumotni tekshiring.")
        self.problems = dict(problems)
        # What a press beside the refusal could fix - ``{"offer_outcome":
        # "profile"}`` when an Instagram address was typed for a site.
        self.hints = dict(hints or {})
