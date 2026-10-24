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
