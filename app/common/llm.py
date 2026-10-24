from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from functools import lru_cache
from typing import Any, Final, Literal

from llmkit import ClaudeClient, LLMResult, Pricing, PromptLibrary

from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from core.agent import PROMPT_DIR

ASKED: Final = "asked"
UNATTENDED: Final = "unattended"
MECHANICAL: Final = "mechanical"
MONTAGE: Final = "montage"
Tier = Literal["asked", "unattended", "mechanical", "montage"]
CHEAP: Final[frozenset[str]] = frozenset({UNATTENDED, MECHANICAL})
CACHE_WRITE_PERCENT: Final = 125
CACHE_READ_PERCENT: Final = 10
CACHE_READ_PERMILLE: Final[dict[str, int]] = {
    "claude-opus-5-5": 50,
    "claude-fable-5-1": 25,
    "claude-mythos-5-1": 25,
}
Account = Literal["main", "montage"]


@lru_cache(maxsize=1)
def prompts() -> PromptLibrary:
    return PromptLibrary(root=PROMPT_DIR)


def model_for(tier: Tier) -> str:
    if tier == MONTAGE and settings.montage_anthropic_model:
        return settings.montage_anthropic_model
    if tier in CHEAP and settings.anthropic_model_unattended:
        return settings.anthropic_model_unattended
    return settings.anthropic_model


def pricing(tier: Tier = ASKED) -> Pricing:
    model = model_for(tier)
    if tier == MONTAGE and settings.montage_anthropic_model:
        inputs = settings.montage_input_price_minor
        outputs = settings.montage_output_price_minor
        if inputs or outputs:
            return _priced(inputs=inputs, outputs=outputs, model=model)
    if tier in CHEAP and settings.anthropic_model_unattended:
        inputs = settings.anthropic_unattended_input_price_minor
        outputs = settings.anthropic_unattended_output_price_minor
        if inputs or outputs:
            return _priced(inputs=inputs, outputs=outputs, model=model)
    return _priced(
        inputs=settings.anthropic_input_price_minor,
        outputs=settings.anthropic_output_price_minor,
        model=model,
    )


def _priced(*, inputs: int, outputs: int, model: str = "") -> Pricing:
    return Pricing(
        input_per_mtok_minor=inputs,
        output_per_mtok_minor=outputs,
        cache_write_per_mtok_minor=(
            settings.anthropic_cache_write_price_minor
            or inputs * CACHE_WRITE_PERCENT // 100
        ),
        cache_read_per_mtok_minor=(
            settings.anthropic_cache_read_price_minor
            or inputs * CACHE_READ_PERMILLE.get(model, CACHE_READ_PERCENT * 10) // 1000
        ),
        currency=settings.anthropic_price_currency,
    )


def key_for(account: Account) -> str:
    if account == "montage" and settings.montage_anthropic_api_key:
        return settings.montage_anthropic_api_key
    return settings.anthropic_api_key


def workspace_for(account: Account) -> str:
    if account == "montage" and settings.montage_anthropic_api_key:
        return settings.montage_anthropic_workspace_id or "montage"
    return ""


@contextmanager
def claude(
    *,
    tier: Tier = ASKED,
    timeout: float | None = None,
    account: Account = "main",
) -> Iterator[ClaudeClient]:
    key = key_for(account)
    caching: Literal["off", "system", "instructions"] = (
        "instructions"
        if account == "montage"
        else "system"
        if settings.anthropic_prompt_cache
        else "off"
    )
    if not key:
        raise LLMUnavailable(
            "ANTHROPIC_API_KEY is empty in this process; Claude is "
            "callable from the worker only"
        )
    client = ClaudeClient(
        api_key=key,
        model=model_for(tier),
        pricing=pricing(tier),
        caching=caching,
        **({"timeout": timeout} if timeout is not None else {}),
    )
    try:
        yield client
    finally:
        client.close()


def both(first: LLMResult[Any], second: LLMResult[Any]) -> LLMResult[Any]:
    return replace(
        second,
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cost_micros=first.cost_micros + second.cost_micros,
        latency_ms=first.latency_ms + second.latency_ms,
        attempts=first.attempts + second.attempts,
        cache_write_tokens=first.cache_write_tokens + second.cache_write_tokens,
        cache_read_tokens=first.cache_read_tokens + second.cache_read_tokens,
    )
