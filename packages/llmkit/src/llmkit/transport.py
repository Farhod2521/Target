"""Anthropic's failures, translated once for every way of asking."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import anthropic

from llmkit.errors import (
    ClaudeAuthError,
    ClaudeRateLimited,
    ClaudeSpendLimit,
    ClaudeTemporaryError,
    LLMError,
)


def retry_after(error: anthropic.RateLimitError) -> int:
    """Anthropic's own estimate in seconds, or zero when it sends none."""
    response = getattr(error, "response", None)
    value = response.headers.get("retry-after", "") if response is not None else ""
    return int(value) if value.isdigit() else 0


BILLING_STATUS = 402
_SPEND_WORDS = re.compile(r"usage limit|spend limit|credit balance", re.IGNORECASE)


@contextmanager
def translated() -> Iterator[None]:
    """Run a request, and raise this package's errors instead of the SDK's."""
    try:
        yield
    except anthropic.APIStatusError as exc:
        if _spent_out(exc):
            raise ClaudeSpendLimit(str(exc)) from exc
        if isinstance(exc, anthropic.AuthenticationError):
            raise ClaudeAuthError(str(exc)) from exc
        if isinstance(exc, anthropic.RateLimitError):
            raise ClaudeRateLimited(
                str(exc), retry_after_seconds=retry_after(exc)
            ) from exc
        if isinstance(exc, anthropic.InternalServerError | anthropic.OverloadedError):
            raise ClaudeTemporaryError(str(exc)) from exc
        raise LLMError(str(exc)) from exc
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
        raise ClaudeTemporaryError(str(exc)) from exc
    except anthropic.AnthropicError as exc:
        raise LLMError(str(exc)) from exc


def _spent_out(exc: anthropic.APIStatusError) -> bool:
    """A billing error, or a refusal that names a spend limit or the credit."""
    if exc.status_code == BILLING_STATUS:
        return True
    return exc.status_code < 500 and bool(_SPEND_WORDS.search(str(exc)))
