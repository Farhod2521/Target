class DomainError(Exception):
    """A rule the user broke. The message is shown to them as is."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = str(message)


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

    def __init__(self, problems: dict[str, str], message: str = "") -> None:
        first = next(iter(problems.values()), "")
        super().__init__(message or first or "Kiritilgan ma'lumotni tekshiring.")
        self.problems = dict(problems)
