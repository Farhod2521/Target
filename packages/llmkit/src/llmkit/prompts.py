"""Where prompts live, and how a version is pinned to a call.

Prompts are files on disk, not strings in code. Three reasons, and all
three come up in practice: a prompt is edited far more often than the code
around it, a prompt is read by people who do not read Python, and a prompt
that changed silently makes every earlier result unexplainable.

The root directory is passed in by the caller. This package must not know
that the project keeps its prompts in ``core/agent/prompts/`` - that is
domain knowledge, and the package that talks to Claude has none.
"""

import re
from pathlib import Path

from llmkit.errors import PromptNotFound

# ``{{ answers }}`` rather than ``{answers}``. Prompts contain JSON examples
# full of single braces, and str.format would either break on them or force
# every example to be written doubled - which is exactly the kind of detail
# that makes a prompt file hard to read for the person editing it.
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# A prompt is never edited in place: a new version file is added beside the
# old one. Old LLMCall rows point at the old version, and a result nobody
# can reproduce is a result nobody can debug.
VERSION_PATTERN = re.compile(r"^v(\d+)$")

# What separates the half of a prompt that is the same for everybody from
# the half that describes one account. On a line of its own and written as
# a comment, so a prompt file still reads as one document.
#
# The split exists for the cache: a breakpoint only pays when the text
# before it is identical from one call to the next, and that is a property
# of how the prompt is written, not of how it is sent. A file that does not
# say where its stable half ends has none, which is the safe answer.
ACCOUNT_MARK = "<!-- account -->"


class PromptLibrary:
    """The prompt files under one directory.

    Layout is ``<root>/<name>/<version>.md``. Flat enough to browse, and
    the version is a file rather than a header so that diffing two versions
    is an ordinary diff.
    """

    def __init__(self, *, root: Path) -> None:
        self._root = root

    def get(self, name: str, *, version: str = "") -> tuple[str, str]:
        """The prompt text and the version actually used.

        An empty ``version`` means the highest one, which is what running
        code wants. The resolved version is returned rather than assumed,
        because it is what gets written to ``LLMCall`` - and "latest" in a
        database column ages into meaninglessness.
        """
        resolved = version or self.latest(name)
        path = self._root / name / f"{resolved}.md"

        if not path.is_file():
            raise PromptNotFound(name, resolved)

        return path.read_text(encoding="utf-8"), resolved

    def latest(self, name: str) -> str:
        """The highest version on disk, compared as a number.

        Numeric rather than alphabetical: ``v10`` sorts before ``v9`` as a
        string, and the first time a prompt reaches its tenth version the
        product would silently fall back to the ninth.
        """
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
    """Fill ``{{ name }}`` placeholders, leaving unknown ones untouched.

    Untouched rather than blank: a prompt that silently lost a variable
    still reads as a sentence and produces a plausible, wrong answer. A
    ``{{ answers }}`` left visible in the text is a bug anyone reviewing
    the call will spot immediately.
    """

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
    """The stable instructions and the part that describes one account.

    Empty instructions when the file carries no mark: nothing in it is
    claimed to be stable, so nothing is offered to the cache and the whole
    template comes back as the account half - which is what every prompt
    written before the mark existed is.
    """
    head, mark, tail = template.partition(ACCOUNT_MARK)
    if not mark:
        return "", template.strip()
    return head.strip(), tail.strip()
