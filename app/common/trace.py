import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from metaads import tracing

from app.common.config import settings
from app.common.db import utcnow
from app.common.env import BASE_DIR

logger = logging.getLogger(__name__)
PERSONAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "phone",
        "phone_number",
        "email",
        "email_address",
        "full_name",
        "first_name",
        "last_name",
        "contact_phone",
        "phone_e164",
        "values",
    }
)
VALUE_LIMIT: Final = 20000
CELL_LIMIT: Final = 1000
_DIGIT = re.compile("\\d")
_LETTER = re.compile("[^\\W\\d_]", re.UNICODE)


def shape(value: Any) -> Any:
    if isinstance(value, str):
        return _LETTER.sub("x", _DIGIT.sub("#", value))
    if isinstance(value, Mapping):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [shape(item) for item in value]
    return value


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _by_key(str(key).lower(), item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


def _by_key(key: str, value: Any) -> Any:
    if key in tracing.SECRET_KEYS:
        return tracing.MASK
    if key in PERSONAL_KEYS:
        return shape(value)
    return redact(value)


def enabled() -> bool:
    return bool(settings.launch_trace_enabled)


class Trace:
    def __init__(self, *, subject: str, started: datetime, title: str = "") -> None:
        self.subject = subject
        self.started = started
        self.title = title
        self._lines: list[str] = []
        self._calls = 0

    def step(self, number: int, title: str) -> None:
        self._lines.append(f"\n## {number}. {title}\n\n{self._stamp()}\n")

    def inputs(self, label: str, value: Any) -> None:
        self._block("KIRISH", label, value)

    def decision(self, label: str, value: Any) -> None:
        self._block("QAROR", label, value)

    def db(self, model: str, changes: Mapping[str, tuple[Any, Any]]) -> None:
        if not changes:
            return
        rows = "\n".join(
            (
                f"| `{field}` | `{short(redact({field: before})[field])}` | `{short(redact({field: after})[field])}` |"
                for field, (before, after) in changes.items()
            )
        )
        self._lines.append(
            f"**DB** - `{model}`\n\n| maydon | eski | yangi |\n|---|---|---|\n{rows}\n"
        )

    def table(
        self, label: str, headers: tuple[str, ...], rows: list[tuple[Any, ...]]
    ) -> None:
        if not rows:
            return
        head = "| " + " | ".join(headers) + " |"
        rule = "|" + "|".join("---" for _ in headers) + "|"
        body = "\n".join(
            "| " + " | ".join(str(cell) for cell in row) + " |" for row in rows
        )
        self._lines.append(f"**{label}**\n\n{head}\n{rule}\n{body}\n")

    def meta(self, **call: Any) -> None:
        self._calls += 1
        status = call.get("status", 0)
        error = str(call.get("error", ""))
        head = f"`{call.get('method', '?')} {call.get('url', '?')}`"
        result = error or f"HTTP {status}"
        self._lines.append(
            f"**META** #{self._calls} - {head} - {result} ({float(call.get('ms', 0)):.0f} ms)\n\n_query_\n{fence(redact(call.get('query')))}\n_yuborildi_\n{fence(redact(call.get('body')))}\n_qaytdi_\n{fence(redact(call.get('response')))}\n"
        )

    def note(self, text: str) -> None:
        self._lines.append(f"> {text}\n")

    def heading(self, text: str) -> None:
        self._lines.append(f"\n### {text}\n")

    def substep(self, title: str) -> None:
        self._lines.append(f"\n### {title}\n\n{self._stamp()}\n")

    def embed(self, text: str) -> None:
        self._lines.append(f"{text}\n")

    def flush(self, directory: str) -> Path | None:
        stamp = self.started.strftime("%Y-%m-%d_%H%M%S")
        path = Path(BASE_DIR) / directory / f"{stamp}_{self.subject[:8]}.md"
        body = self._header() + "".join(self._lines)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except OSError:
            logger.exception("trace not written", extra={"path": str(path)})
            return None
        return path

    def _header(self) -> str:
        return f"# {self.title or 'Trace'} - `{self.subject}`\n\nBoshlandi: `{self.started.isoformat()}`\n"

    def _block(self, kind: str, label: str, value: Any) -> None:
        self._lines.append(f"**{kind}** - {label}\n{fence(redact(value))}\n")

    def _stamp(self) -> str:
        now = utcnow()
        elapsed = (now - self.started).total_seconds()
        return f"`{now.strftime('%H:%M:%S.%f')[:-3]}` · +{elapsed:.3f}s"


class NoTrace(Trace):
    def __init__(self) -> None:
        super().__init__(subject="", started=utcnow())

    def step(self, number: int, title: str) -> None: ...

    def inputs(self, label: str, value: Any) -> None: ...

    def decision(self, label: str, value: Any) -> None: ...

    def db(self, model: str, changes: Mapping[str, tuple[Any, Any]]) -> None: ...

    def table(
        self, label: str, headers: tuple[str, ...], rows: list[tuple[Any, ...]]
    ) -> None: ...

    def meta(self, **call: Any) -> None: ...

    def note(self, text: str) -> None: ...

    def heading(self, text: str) -> None: ...

    def substep(self, title: str) -> None: ...

    def embed(self, text: str) -> None: ...

    def flush(self, directory: str) -> Path | None:
        return None


def fence(value: Any) -> str:
    if value is None:
        return "```\n(yo'q)\n```"
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    if len(text) > VALUE_LIMIT:
        text = f"{text[:VALUE_LIMIT]}\n... ({len(text)} belgi)"
    return f"```json\n{text}\n```"


def short(value: Any) -> str:
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str)
    )
    return text if len(text) <= CELL_LIMIT else f"{text[:CELL_LIMIT]}..."
