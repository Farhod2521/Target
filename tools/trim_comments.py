"""Shorten the explanations carried over from the Django project.

python tools/trim_comments.py core packages

Every docstring keeps its first paragraph - the summary - and loses the rest;
``#`` comments go, except the ones tools read (noqa, type: ignore, pragma,
fmt, ...). Left whole: the docstrings of pydantic models, because pydantic
turns them into the JSON schema descriptions sent to the language model.
Code lines are never touched; ``ruff format`` tidies the blank lines after.
"""

import ast
import importlib
import io
import re
import sys
import tokenize
from pathlib import Path

from pydantic import BaseModel

KEEP = re.compile(r"#\s*(noqa|type:|pragma|fmt:|ruff:|pyright:|mypy:|isort:|pylint:)|#!|-\*-")
ROOT = Path(__file__).resolve().parents[1]


def module_name(path: Path) -> str | None:
    parts = path.relative_to(ROOT).with_suffix("").parts
    if parts[0] == "packages":
        if "src" not in parts:
            return None
        parts = parts[parts.index("src") + 1 :]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def pydantic_classes(path: Path) -> set[str]:
    """Qualified names of the pydantic models a module defines."""
    name = module_name(path)
    if name is None:
        return set()
    try:
        module = importlib.import_module(name)
    except Exception:
        return {"*"}
    found: set[str] = set()
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, BaseModel)
            and value.__module__ == module.__name__
        ):
            found.add(value.__qualname__)
    return found


def docstrings(tree: ast.AST, *, models: set[str]) -> list[ast.Expr]:
    found: list[ast.Expr] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{scope}.{child.name}" if scope else child.name
                if not (isinstance(child, ast.ClassDef) and qual in models):
                    first = _doc(child)
                    if first is not None:
                        found.append(first)
                visit(child, qual)

    first = _doc(tree)
    if first is not None:
        found.append(first)
    visit(tree, "")
    return found


def _doc(node: ast.AST) -> ast.Expr | None:
    body = getattr(node, "body", None)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[0]
    return None


def summary(lines: list[str], doc: ast.Expr) -> list[str] | None:
    """The docstring's lines cut to its first paragraph, or None to keep it."""
    raw = lines[doc.lineno - 1 : doc.end_lineno]
    head = raw[0]
    match = re.match(r'^(\s*)([rRbBuU]{0,2})("""|\'\'\')', head)
    if match is None or len(raw) == 1:
        return None
    quote = match.group(3)
    kept = [head]
    started = bool(head[match.end() :].strip())
    for line in raw[1:]:
        if quote in line:
            return None
        if not line.strip():
            if started:
                break
            continue
        kept.append(line)
        started = True
    if len(kept) == len(raw):
        return None
    last = kept[-1].rstrip()
    if last.endswith(quote[0]) or last.endswith("\\"):
        last += " "
    kept[-1] = last + quote
    return kept


def trim(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    lines = source.split("\n")
    tree = ast.parse(source)
    models = pydantic_classes(path)
    if "*" in models:
        models = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    replaced: dict[int, list[str]] = {}
    drop: set[int] = set()
    for doc in docstrings(tree, models=models):
        short = summary(lines, doc)
        if short is None:
            continue
        replaced[doc.lineno - 1] = short
        drop.update(range(doc.lineno, doc.end_lineno))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT or KEEP.search(token.string):
            continue
        row, col = token.start
        index = row - 1
        if not lines[index][:col].strip():
            drop.add(index)
        elif index not in replaced:
            lines[index] = lines[index][:col].rstrip()
    out: list[str] = []
    for index, line in enumerate(lines):
        if index in replaced:
            out.extend(replaced[index])
        elif index not in drop:
            out.append(line)
    text = "\n".join(out)
    if text == source:
        return False
    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    return True


def main(roots: list[str]) -> None:
    sys.path.insert(0, str(ROOT))
    for package in (ROOT / "packages").glob("*/src"):
        sys.path.insert(0, str(package))
    changed = 0
    for root in roots:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            changed += trim(path)
    print(f"{changed} files trimmed")


if __name__ == "__main__":
    main(sys.argv[1:])
