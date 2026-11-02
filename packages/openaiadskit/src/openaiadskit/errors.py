"""ChatGPT Ads failures as this package reads them, before the domain does.

OpenAI answers a refused request with an HTTP status and, usually, an
``error`` object (``message``, ``type``, ``code``, ``param``). The status is
the part the documentation promises; the object is read when it is there
and never relied on. Deciding what a refusal means for a caller is
:mod:`openaiadskit.translate`'s job.

**Sent or not sent**, the split every package here makes. A failure before
the request reached OpenAI is :class:`OpenAIAdsUnreachable` and always safe
to repeat. A failure after it left is :class:`OpenAIAdsOutcomeUnknown`: a
create may have landed, and only the same ``Idempotency-Key`` makes a
second attempt safe.

No message here carries the API key: it travels in a header no exception
prints.
"""


class OpenAIAdsError(Exception):
    """Base for anything that went wrong while talking to ChatGPT Ads."""


class OpenAIAdsUnreachable(OpenAIAdsError):
    """The request never reached OpenAI. Repeating it is safe."""


class OpenAIAdsOutcomeUnknown(OpenAIAdsError):
    """The request left and no answer came back. A write may have landed."""


class OpenAIAdsAPIError(OpenAIAdsError):
    """OpenAI answered and refused. Everything it said is kept."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        type: str = "",
        code: str = "",
        param: str = "",
        request_id: str = "",
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.type = type
        self.code = code
        # The field OpenAI blamed, when it named one.
        self.param = param
        # What OpenAI's support asks for first. Logged, never shown.
        self.request_id = request_id
        # From ``Retry-After``; only rate-limit refusals carry it.
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "OpenAIAdsAPIError",
    "OpenAIAdsError",
    "OpenAIAdsOutcomeUnknown",
    "OpenAIAdsUnreachable",
]
