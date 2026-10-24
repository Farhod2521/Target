"""Claude failures, split by what the caller should do about them.

The split is the same idea as ``metaads.errors``: the class carries the
decision, so a Celery task can retry on one family and give up on another
without knowing a single Anthropic status code.

One family is unusual and worth naming here. :class:`StructuredOutputError`
is *our* failure, not Anthropic's - the model answered, the answer did not
fit the schema we asked for, and the fix is a better prompt rather than a
retry. It is tracked separately in ``LLMCall.status`` for exactly that
reason: it is a prompt regression, and counting it against a prompt version
is how a bad prompt gets caught.

:class:`ClaudeRefused` is the other answer that is neither: the model
declined. Not a prompt that drifted and not a service that failed, and
asking again buys the same refusal at twice the price.
"""

from llmkit.models import Spend


class LLMError(Exception):
    """Root of everything this package raises.

    ``spent`` is what the call cost before it failed. Nought for anything
    that never reached the model; every attempt's tokens for an answer that
    was paid for and then not used. On the root rather than on the two
    classes that fill it in, so a caller that catches the whole family can
    record the cost without first asking which member it caught.
    """

    spent: Spend = Spend()


class PromptNotFound(LLMError):
    """A prompt name or version that is not on disk.

    Almost always a typo or a version that was deleted. Prompts are never
    deleted - old ``LLMCall`` rows point at them - so this means the name
    was wrong.
    """

    def __init__(self, name: str, version: str) -> None:
        super().__init__(f"no prompt {name!r} at version {version!r}")
        self.name = name
        self.version = version


class StructuredOutputError(LLMError):
    """The answer did not fit the schema, twice.

    Asked once, re-asked once with the validation error attached, and still
    wrong. "Approximately right" is not accepted: a targeting spec with a
    missing age bound is worse than no targeting spec, because it reaches
    the provider and spends money.
    """

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
        # How many answers were paid for before giving up. The successful
        # path reports this on ``LLMResult``; without it here the ledger
        # counts a call that was written twice as a call written once, and
        # the one column that says "this prompt keeps needing a second go"
        # undercounts exactly the calls that needed it most.
        self.attempts = attempts
        if spent is not None:
            self.spent = spent


class ClaudeRefused(LLMError):
    """The model declined to answer (``stop_reason`` ``"refusal"``).

    Never re-asked. What arrives with a refusal need not fit the schema, so
    without this class it reads as an empty answer, is logged as a dozen
    missing fields and is asked again - the same refusal, paid for twice.
    """

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
    """The caller's spend ceiling is reached, so no call was made.

    Raised *before* the request. Nothing was spent and nothing is written
    to ``LLMCall`` - the point of the ceiling is that the call does not
    happen.
    """


class ClaudeAuthError(LLMError):
    """The key is wrong, revoked, or absent. Never retried.

    Retrying an authentication failure is how a key ends up rate-limited
    on top of being invalid. An operator has to look.
    """


class ClaudeSpendLimit(LLMError):
    """The organisation's or the workspace's spend limit is reached, or
    the credit is gone. Never retried: nothing will answer until someone
    raises the limit or tops the balance up.
    """


class ClaudeRateLimited(LLMError):
    """Too many requests or too many tokens per minute.

    Retryable, with backoff. ``retry_after_seconds`` is Anthropic's own
    estimate when it sends one, and zero when it does not.
    """

    def __init__(self, message: str, *, retry_after_seconds: int = 0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ClaudeTemporaryError(LLMError):
    """A 5xx, a timeout, an overloaded model. Retryable."""
