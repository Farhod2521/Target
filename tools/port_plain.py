"""Port a Django-free-ish module mechanically: drop gettext, docstrings and rename imports.

python tools/port_plain.py <django file> <target file>

Good for ``exceptions.py`` and other files that only lean on Django for
translation. Anything touching the ORM still needs a hand port.
"""

import ast
import sys
from pathlib import Path

GETTEXT = {"_", "gettext_lazy", "gettext", "pgettext_lazy", "gettext_noop", "ngettext"}
MODULES = {
    "shared.exceptions": "app.common.exceptions",
    "shared.money": "app.common.money",
    "shared.presets": "app.common.presets",
    "shared.catalogs": "app.common.catalogs",
    "shared.llm": "app.common.llm",
    "shared.phone": "app.common.phone",
    "shared.i18n": "app.common.i18n",
    "shared.throttle": "app.common.throttle",
    "shared.trace": "app.common.trace",
    "apps.montage": "app.modules.content_studio",
}


DJANGO = {
    "django.urls": "app.common.routes",
    "django.utils.http": "urllib.parse",
    "django.utils.formats": "app.common.dates",
    "django.core.cache": "app.common.cache",
    "django.utils.text": "app.common.text",
    "django.utils.html": "html",
}
DJANGO_NAMES = {("django.utils", "timezone"): "app.common"}


def rename(module: str) -> str:
    for old, new in MODULES.items():
        if module == old or module.startswith(old + "."):
            return new + module[len(old) :]
    if module.startswith("apps."):
        return "app.modules." + module[len("apps.") :]
    return module


class Port(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in GETTEXT and node.args:
            return node.args[0]
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "settings"
            and node.attr.isupper()
        ):
            node.attr = node.attr.lower()
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        module = node.module or ""
        if module == "django.conf":
            node.module = "app.common.config"
            return node
        kept = [a for a in node.names if (module, a.name) in DJANGO_NAMES]
        if kept:
            node.module = DJANGO_NAMES[(module, kept[0].name)]
            node.names = kept
            return node
        if module in DJANGO:
            node.module = DJANGO[module]
            return node
        if module.startswith("django"):
            return None
        node.module = rename(module)
        return node

    def _body(self, node: ast.AST) -> ast.AST:
        self.generic_visit(node)
        body = node.body  # type: ignore[attr-defined]
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        node.body = body or [ast.Pass()]  # type: ignore[attr-defined]
        return node

    visit_ClassDef = _body
    visit_FunctionDef = _body
    visit_AsyncFunctionDef = _body


def port(src: str) -> str:
    tree = Port().visit(ast.parse(src))
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
    ):
        tree.body = tree.body[1:]
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


if __name__ == "__main__":
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(port(source.read_text(encoding="utf-8")), encoding="utf-8")
