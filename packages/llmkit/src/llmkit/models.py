"""What one Claude call costs and what it returned.

Every field here has a column waiting for it in ``LLMCall``. That is not a
coincidence: a call whose cost, latency and prompt version are not written
down is a call nobody can explain when the monthly bill arrives.
"""

from dataclasses import dataclass
from typing import Literal

# Anthropic quotes prices per million tokens. Keeping the same unit avoids
# a division that would round a fraction of a cent away on every call and
# then be wrong by a visible amount over a month.
TOKENS_PER_PRICE_UNIT = 1_000_000
# Tokens times a price per million tokens is a cost in millionths of a
# minor unit - exactly, with nothing to round. That is the figure kept and
# summed; a whole cent is a cut taken only when a number is shown. A short
# call costs well under a cent, and rounding each one down made it nought.
MICROS_PER_MINOR = TOKENS_PER_PRICE_UNIT


@dataclass(frozen=True, slots=True)
class Pricing:
    """What a model costs, in minor units per million tokens.

    Configuration rather than a constant, and passed in by the caller. Two
    reasons: this package has no environment to read, and Anthropic's
    prices change without asking us - a number compiled into a package is
    a number that is quietly wrong from the day it moves.

    Zero is a valid value and means "not configured yet". Cost then records
    as zero, which is visibly wrong in the admin rather than invisibly
    wrong in a total.

    **Four rates, not two.** A cached prompt is billed at three different
    rates at once: what is written into the cache, what is read back out of
    it, and what was never cacheable. The read tokens do not appear in
    ``input_tokens``, so leaving them uncounted makes every bill *look*
    smaller than it is and leaves the monthly ceiling this product enforces
    quietly measuring the wrong number.
    """

    input_per_mtok_minor: int = 0
    output_per_mtok_minor: int = 0
    # Writing a prefix into the cache, and reading one back. Anthropic
    # charges a premium for the first and a fraction for the second; both
    # arrive from the caller for the same reason the other two do.
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
        """Millionths of a minor unit, exact. Money never becomes a float.

        The two cache figures default to nought, which is what every call
        that is not cached reports - so a caller that has never heard of
        caching gets exactly the arithmetic it always got.
        """
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
        """Whole minor units, rounded down - for showing, never for summing.

        Down, because rounding up would let a shown figure drift above what
        Anthropic actually charges, which is the direction that costs trust.
        """
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
    """One answer, plus everything needed to account for it.

    Generic in the parsed value: the caller asked for a schema and gets an
    instance of it back, type-checked, rather than a dict it has to trust.
    """

    value: T
    input_tokens: int
    output_tokens: int
    # Millionths of ``currency``'s minor unit; see :data:`MICROS_PER_MINOR`.
    cost_micros: int
    currency: str
    latency_ms: int
    prompt_name: str
    prompt_version: str
    model: str
    # How many times the model was asked before the answer fit the schema.
    # 1 is normal. 2 means the prompt is drifting and is worth looking at
    # before it becomes a failure.
    attempts: int = 1
    # The two halves of a cached prompt, as the API reported them. They are
    # *not* included in ``input_tokens`` - the API counts them separately -
    # so a ledger that recorded only the input tokens would show a cached
    # call as having read almost nothing.
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    # How many attempts ran out of room rather than being wrong.
    #
    # Its own figure because it has its own fix. A wrong answer is a prompt
    # to correct; a cut-off one is a ceiling to raise, and the two arrive
    # looking identical - a truncated tool call validates as a dozen
    # missing fields. It costs a whole answer's writing each time.
    truncated: int = 0
    # How many requests an answer that could look things up took, and how
    # many look-ups it made. One and nought for every other call. The cost
    # above is already the sum of every round; these say where it went.
    rounds: int = 1
    tool_calls: int = 0

    @property
    def cost_minor(self) -> int:
        """Whole minor units, rounded down. For showing only."""
        return self.cost_micros // MICROS_PER_MINOR


@dataclass(frozen=True, slots=True)
class Spend:
    """What a call cost, whether or not its answer was used.

    Carried by an exception rather than a result. A successful call reports
    the same figures on :class:`LLMResult`; without this a failed one
    reports none, and the ledger records a schema failure - written twice
    and paid for twice - as a call that cost nothing.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_micros: int = 0

    @property
    def cost_minor(self) -> int:
        """Whole minor units, rounded down. For showing only."""
        return self.cost_micros // MICROS_PER_MINOR


# The picture formats Claude reads. GIF is left out: only its first frame
# is looked at, which is a still that should have been sent as one.
ImageType = Literal["image/jpeg", "image/png", "image/webp"]


@dataclass(frozen=True, slots=True)
class Image:
    """One picture sent beside the prompt.

    ``label`` is written as a line of text just before the picture, so the
    prompt can refer to it by name ("Kadr 3", "12.0 s") and the answer can
    point back at it. Without one, a dozen pictures are a dozen pictures
    and nothing tells the model which is which.
    """

    data: bytes
    media_type: ImageType = "image/jpeg"
    label: str = ""
