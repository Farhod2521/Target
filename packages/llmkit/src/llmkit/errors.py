"""Claude failures, split by what the caller should do about them."""

from llmkit.models import Spend


class LLMError(Exception):
    """Root of everything this package raises."""

    spent: Spend = Spend()


class PromptNotFound(LLMError):
    """A prompt name or version that is not on disk."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(f"no prompt {name!r} at version {version!r}")
        self.name = name
        self.version = version


class StructuredOutputError(LLMError):
    """The answer did not fit the schema, twice."""

    def __init__(
        self,
        message: str,
        *,
        schema: str = "",
        attempts: int = 0,
        spent: Spend | None = None,
    ) -> None:
        super().__init__(message)
        self.schema = schema
        self.attempts = attempts
        if spent is not None:
            self.spent = spent


class ClaudeRefused(LLMError):
    """The model declined to answer (``stop_reason`` ``"refusal"``)."""

    def __init__(
        self,
        message: str,
        *,
        schema: str = "",
        attempts: int = 0,
        spent: Spend | None = None,
    ) -> None:
        super().__init__(message)
        self.schema = schema
        self.attempts = attempts
        if spent is not None:
            self.spent = spent


class BudgetExceeded(LLMError):
    """The caller's spend ceiling is reached, so no call was made."""


class ClaudeAuthError(LLMError):
    """The key is wrong, revoked, or absent. Never retried."""


class ClaudeSpendLimit(LLMError):
    """The organisation's or the workspace's spend limit is reached, or
    the credit is gone. Never retried: nothing will answer until someone
    raises the limit or tops the balance up.
    """


class ClaudeRateLimited(LLMError):
    """Too many requests or too many tokens per minute."""

    def __init__(self, message: str, *, retry_after_seconds: int = 0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ClaudeTemporaryError(LLMError):
    """A 5xx, a timeout, an overloaded model. Retryable."""
