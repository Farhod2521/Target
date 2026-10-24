"""Claude, made reliable.

The package solves "talk to Claude without surprises" - structured output,
error translation, cost accounting. It does not solve "what should we ask",
which is domain knowledge and lives in ``core/agent/prompts/``.

It therefore knows nothing about advertising: no targeting, no ad set, no
lead, no CPQL. That ignorance is what lets it move to another project
unchanged.

Claude only. A second LLM SDK is a product decision, not a patch.
"""

from llmkit.client import ClaudeClient
from llmkit.conversation import ToolStream
from llmkit.errors import (
    BudgetExceeded,
    ClaudeAuthError,
    ClaudeRateLimited,
    ClaudeRefused,
    ClaudeSpendLimit,
    ClaudeTemporaryError,
    LLMError,
    PromptNotFound,
    StructuredOutputError,
)
from llmkit.models import MICROS_PER_MINOR, Image, LLMResult, Pricing, Spend
from llmkit.prompts import PromptLibrary, halves, missing_variables, render
from llmkit.streaming import TextStream
from llmkit.tools import Tool, ToolCall, ToolOutput, ToolRunner

__all__ = [
    "MICROS_PER_MINOR",
    "BudgetExceeded",
    "ClaudeAuthError",
    "ClaudeClient",
    "ClaudeRateLimited",
    "ClaudeRefused",
    "ClaudeSpendLimit",
    "ClaudeTemporaryError",
    "Image",
    "LLMError",
    "LLMResult",
    "Pricing",
    "PromptLibrary",
    "PromptNotFound",
    "Spend",
    "StructuredOutputError",
    "TextStream",
    "Tool",
    "ToolCall",
    "ToolOutput",
    "ToolRunner",
    "ToolStream",
    "halves",
    "missing_variables",
    "render",
]
