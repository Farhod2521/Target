"""What one Claude call costs and what it returned."""

from dataclasses import dataclass
from typing import Literal

TOKENS_PER_PRICE_UNIT = 1_000_000
MICROS_PER_MINOR = TOKENS_PER_PRICE_UNIT


@dataclass(frozen=True, slots=True)
class Pricing:
    """What a model costs, in minor units per million tokens."""

    input_per_mtok_minor: int = 0
    output_per_mtok_minor: int = 0
    cache_write_per_mtok_minor: int = 0
    cache_read_per_mtok_minor: int = 0
    currency: str = ""

    def cost_micros(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> int:
        """Millionths of a minor unit, exact. Money never becomes a float."""
        return (
            input_tokens * self.input_per_mtok_minor
            + output_tokens * self.output_per_mtok_minor
            + cache_write_tokens * self.cache_write_per_mtok_minor
            + cache_read_tokens * self.cache_read_per_mtok_minor
        )

    def cost_minor(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> int:
        """Whole minor units, rounded down - for showing, never for summing."""
        return (
            self.cost_micros(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
            )
            // MICROS_PER_MINOR
        )


@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    """One answer, plus everything needed to account for it."""

    value: T
    input_tokens: int
    output_tokens: int
    cost_micros: int
    currency: str
    latency_ms: int
    prompt_name: str
    prompt_version: str
    model: str
    attempts: int = 1
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    truncated: int = 0
    rounds: int = 1
    tool_calls: int = 0

    @property
    def cost_minor(self) -> int:
        """Whole minor units, rounded down. For showing only."""
        return self.cost_micros // MICROS_PER_MINOR


@dataclass(frozen=True, slots=True)
class Spend:
    """What a call cost, whether or not its answer was used."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_micros: int = 0

    @property
    def cost_minor(self) -> int:
        """Whole minor units, rounded down. For showing only."""
        return self.cost_micros // MICROS_PER_MINOR


ImageType = Literal["image/jpeg", "image/png", "image/webp"]


@dataclass(frozen=True, slots=True)
class Image:
    """One picture sent beside the prompt."""

    data: bytes
    media_type: ImageType = "image/jpeg"
    label: str = ""
