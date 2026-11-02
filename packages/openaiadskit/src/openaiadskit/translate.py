"""ChatGPT Ads failures in the domain's own words.

The only module that knows OpenAI's statuses. A caller above this package
catches :mod:`adskit.errors` and decides by class, never by an OpenAI
string.

The HTTP status decides: it is the one part of a refusal OpenAI documents
(authentication, access, validation, not found, conflict, too large, rate
limited). ``code`` only names the refusal for logs and stored rows.
"""

from adskit.errors import (
    AuthFailed,
    InvalidRequest,
    NotFound,
    PermissionDenied,
    ProviderError,
    RateLimited,
    TemporaryFailure,
)

from openaiadskit.errors import (
    OpenAIAdsAPIError,
    OpenAIAdsError,
    OpenAIAdsOutcomeUnknown,
)


def translate_error(exc: OpenAIAdsError) -> ProviderError:
    """One ChatGPT Ads failure as the domain's own error."""
    translated = _translated(exc)
    if isinstance(exc, OpenAIAdsAPIError):
        translated.key = f"chatgpt:{_code(exc)[:48]}"
    return translated


def _translated(exc: OpenAIAdsError) -> ProviderError:
    if isinstance(exc, OpenAIAdsOutcomeUnknown):
        return TemporaryFailure(str(exc), code="outcome_unknown")
    if not isinstance(exc, OpenAIAdsAPIError):
        return TemporaryFailure(str(exc), code="unreachable")

    code = _code(exc)
    status = exc.http_status
    if status == 429:
        return RateLimited(
            str(exc), code=code, retry_after_seconds=exc.retry_after_seconds
        )
    if status == 401:
        return AuthFailed(str(exc), code=code)
    if status == 403:
        return PermissionDenied(str(exc), code=code)
    if status == 404:
        return NotFound(str(exc), code=code)
    if status >= 500:
        return TemporaryFailure(str(exc), code=code)
    return InvalidRequest(str(exc), code=code)


def _code(exc: OpenAIAdsAPIError) -> str:
    """The most specific word OpenAI gave, for logs and stored rows."""
    return exc.code or exc.type or str(exc.http_status)


__all__ = ["translate_error"]
