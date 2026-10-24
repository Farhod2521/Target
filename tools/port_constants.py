"""Port a Django ``constants.py`` to plain Python: choices become enums with a LABELS map.

python tools/port_constants.py <django constants.py> <target constants.py>
"""

import ast
import sys
from pathlib import Path

CHOICES = {"TextChoices": "Choices", "IntegerChoices": "IntEnum"}
DROP_MODULES = ("django", "apps.", "shared.")


def is_gettext(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("_", "gettext_lazy", "gettext", "pgettext_lazy")
    )


class Strip(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if is_gettext(node) and node.args:
            return node.args[-1]
        if isinstance(node.func, ast.Name) and node.func.id == "format_lazy":
            return node.args[0] if node.args else node
        return node


def drop_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body or [ast.Pass()]


def port(src: str) -> str:
    tree = Strip().visit(ast.parse(src))
    out: list[ast.stmt] = []
    enums: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [a.name for a in node.names]
            if mod.startswith(DROP_MODULES) or any(
                n.startswith(DROP_MODULES) for n in names
            ):
                continue
            out.append(node)
            continue
        if isinstance(node, ast.ClassDef) and node.bases:
            base = node.bases[0]
            base_name = (
                base.attr
                if isinstance(base, ast.Attribute)
                else getattr(base, "id", "")
            )
            if base_name in CHOICES:
                enums.add(CHOICES[base_name])
                members, labels = [], []
                for item in node.body:
                    if isinstance(item, ast.Assign) and isinstance(
                        item.targets[0], ast.Name
                    ):
                        name = item.targets[0].id
                        value = item.value
                        if isinstance(value, ast.Tuple) and len(value.elts) == 2:
                            members.append(
                                ast.Assign(
                                    targets=[ast.Name(name)],
                                    value=value.elts[0],
                                    lineno=0,
                                )
                            )
                            labels.append((name, value.elts[1]))
                        else:
                            members.append(
                                ast.Assign(
                                    targets=[ast.Name(name)], value=value, lineno=0
                                )
                            )
                    elif isinstance(item, (ast.FunctionDef, ast.AnnAssign)):
                        members.append(item)
                node.bases = [ast.Name(CHOICES[base_name])]
                node.body = members or [ast.Pass()]
                out.append(node)
                if labels:
                    keys = [
                        ast.Attribute(value=ast.Name(node.name), attr=n)
                        for n, _ in labels
                    ]
                    out.append(
                        ast.Assign(
                            targets=[ast.Name(f"{_snake(node.name).upper()}_LABELS")],
                            value=ast.Dict(keys=keys, values=[v for _, v in labels]),
                            lineno=0,
                        )
                    )
                continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            node.body = drop_docstring(node.body)
        out.append(node)
    tree.body = drop_docstring(out) if out and isinstance(out[0], ast.Expr) else out
    header = "from app.common.choices import Choices\n" if "Choices" in enums else ""
    if "IntEnum" in enums:
        header += "from enum import IntEnum\n"
    return header + ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def _snake(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name)


if __name__ == "__main__":
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        port(Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8"
    )
    print(target)
