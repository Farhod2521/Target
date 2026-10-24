"""Where prompts live, and how a version is pinned to a call."""

import re
from pathlib import Path

from llmkit.errors import PromptNotFound

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

VERSION_PATTERN = re.compile(r"^v(\d+)$")

ACCOUNT_MARK = "<!-- account -->"


class PromptLibrary:
    """The prompt files under one directory."""

    def __init__(self, *, root: Path) -> None:
        self._root = root

    def get(self, name: str, *, version: str = "") -> tuple[str, str]:
        """The prompt text and the version actually used."""
        resolved = version or self.latest(name)
        path = self._root / name / f"{resolved}.md"

        if not path.is_file():
            raise PromptNotFound(name, resolved)

        return path.read_text(encoding="utf-8"), resolved

    def latest(self, name: str) -> str:
        """The highest version on disk, compared as a number."""
        folder = self._root / name
        if not folder.is_dir():
            raise PromptNotFound(name, "*")

        versions = [
            (int(match.group(1)), match.group(0))
            for path in folder.glob("v*.md")
            if (match := VERSION_PATTERN.match(path.stem))
        ]
        if not versions:
            raise PromptNotFound(name, "*")

        return max(versions)[1]

    def names(self) -> tuple[str, ...]:
        """Every prompt in the library, sorted. For diagnostics and tests."""
        return tuple(
            sorted(folder.name for folder in self._root.iterdir() if folder.is_dir())
        )


def render(template: str, variables: dict[str, object]) -> str:
    """Fill ``{{ name }}`` placeholders, leaving unknown ones untouched."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(variables[key]) if key in variables else match.group(0)

    return PLACEHOLDER.sub(replace, template)


def missing_variables(template: str, variables: dict[str, object]) -> tuple[str, ...]:
    """Placeholders the caller did not supply, in order of appearance."""
    seen: list[str] = []
    for match in PLACEHOLDER.finditer(template):
        key = match.group(1)
        if key not in variables and key not in seen:
            seen.append(key)
    return tuple(seen)


def halves(template: str) -> tuple[str, str]:
    """The stable instructions and the part that describes one account."""
    head, mark, tail = template.partition(ACCOUNT_MARK)
    if not mark:
        return "", template.strip()
    return head.strip(), tail.strip()
