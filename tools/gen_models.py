"""Generate SQLAlchemy models from the Django schema dump (tools/django_schema.json).

python tools/gen_models.py tools/django_schema.json
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_OF = {"montage": "content_studio"}
SKIP_M2M = {"auth_group", "auth_permission"}

SIMPLE = {
    "CharField": "String({n})",
    "SlugField": "String({n})",
    "EmailField": "String({n})",
    "URLField": "String({n})",
    "FileField": "String({n})",
    "TextField": "Text",
    "BooleanField": "Boolean",
    "DateTimeField": "DateTime(timezone=True)",
    "DateField": "Date",
    "IntegerField": "Integer",
    "PositiveIntegerField": "Integer",
    "SmallIntegerField": "SmallInteger",
    "PositiveSmallIntegerField": "SmallInteger",
    "BigIntegerField": "BigInteger",
    "PositiveBigIntegerField": "BigInteger",
    "BigAutoField": "BigInteger",
    "AutoField": "Integer",
    "UUIDField": "Uuid",
    "JSONField": "Json",
    "BinaryField": "LargeBinary",
    "FloatField": "Float",
}
PY = {
    "String": "str",
    "Text": "str",
    "Boolean": "bool",
    "DateTime": "datetime",
    "Date": "date",
    "Integer": "int",
    "SmallInteger": "int",
    "BigInteger": "int",
    "Uuid": "uuid.UUID",
    "Json": "Any",
    "LargeBinary": "bytes",
    "Float": "float",
    "Numeric": "Decimal",
    "ARRAY": "list[Any]",
}
ON_DELETE = {
    "CASCADE": "CASCADE",
    "PROTECT": "RESTRICT",
    "SET_NULL": "SET NULL",
    "RESTRICT": "RESTRICT",
    "DO_NOTHING": None,
}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def module_of(app: str) -> str:
    return MODULE_OF.get(app, app)


def sa_type(f: dict, pk_types: dict) -> str:
    t = f["type"]
    if t in ("ForeignKey", "OneToOneField"):
        return pk_types[f["fk_table"]]
    if t == "DecimalField":
        return f"Numeric({f['max_digits']}, {f['decimal_places']})"
    if t == "ArrayField":
        inner = SIMPLE[f["array_of"]].format(n=f.get("array_len") or "")
        return f"ARRAY({inner.replace('String()', 'Text')})"
    base = SIMPLE[t]
    if "{n}" in base:
        return base.format(n=f["max_length"]) if f.get("max_length") else "Text"
    return base


def py_type(sa: str, nullable: bool) -> str:
    head = sa.split("(")[0]
    p = PY[head]
    return f"{p} | None" if nullable else p


def default_expr(f: dict) -> str | None:
    if "default_callable" in f:
        return {"uuid4": "uuid.uuid4", "dict": "dict", "list": "list"}.get(
            f["default_callable"]
        )
    if "default" in f:
        if f["default"] is None:
            return None
        return repr(f["default"])
    return None


OPS = {"": "=", "exact": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _literal(value: object, columns: dict) -> str | None:
    if isinstance(value, dict) and str(value.get("expr", "")).startswith("F("):
        return columns.get(value["expr"][2:-1])
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def condition_sql(node: object, columns: dict) -> str | None:
    if isinstance(node, list):
        key, value = node
        name, _, lookup = key.partition("__")
        col = columns.get(name)
        if col is None:
            return None
        if lookup == "isnull":
            return f"{col} IS {'NULL' if value else 'NOT NULL'}"
        if lookup == "in" and isinstance(value, list):
            items = [_literal(v, columns) for v in value]
            return None if None in items else f"{col} IN ({', '.join(items)})"
        op = OPS.get(lookup)
        lit = _literal(value, columns)
        return None if op is None or lit is None else f"{col} {op} {lit}"
    if not isinstance(node, dict) or "children" not in node:
        return None
    parts = [condition_sql(child, columns) for child in node["children"]]
    if None in parts or not parts:
        return None
    joined = f" {node['connector']} ".join(
        f"({p})" if len(parts) > 1 else p for p in parts
    )
    return f"NOT ({joined})" if node["negated"] else joined


def render(model: dict, pk_types: dict, skipped: list) -> str:
    columns = {f["name"]: f["column"] for f in model["fields"]}
    attr = {
        f["name"]: (
            f["column"] if f["type"] in ("ForeignKey", "OneToOneField") else f["name"]
        )
        for f in model["fields"]
    }
    lines, imports = [], {"Mapped", "mapped_column"}
    sa_names: set[str] = set()
    need = {
        "uuid": False,
        "datetime": False,
        "date": False,
        "Any": False,
        "Decimal": False,
    }
    for f in model["fields"]:
        typ = sa_type(f, pk_types)
        for name in re.findall(r"[A-Za-z]+(?=\(|\b)", typ):
            if name in SIMPLE.values() or name in (
                "String",
                "Numeric",
                "ARRAY",
                "DateTime",
                "Text",
                "Uuid",
                "Json",
                "Boolean",
                "Date",
                "Integer",
                "SmallInteger",
                "BigInteger",
                "LargeBinary",
                "Float",
            ):
                sa_names.add(name)
        nullable = f["null"]
        pt = py_type(typ, nullable)
        for k in need:
            if k in pt or (k == "uuid" and "uuid.UUID" in pt):
                need[k] = True
        args = [f'"{f["column"]}"'] if attr[f["name"]] != f["column"] else []
        args.append(typ)
        if f["type"] in ("ForeignKey", "OneToOneField"):
            sa_names.add("ForeignKey")
            ref = f'"{f["fk_table"]}.id"'
            od = ON_DELETE.get(f.get("on_delete", ""))
            args[-1] = (
                f"{typ}, ForeignKey({ref}" + (f', ondelete="{od}"' if od else "") + ")"
            )
        if f["pk"]:
            args.append("primary_key=True")
            if f["type"] in ("BigAutoField", "AutoField"):
                args.append("autoincrement=True")
        else:
            args.append(f"nullable={nullable}")
        if f["unique"] and not f["pk"]:
            args.append("unique=True")
        elif f["index"] and not f["pk"]:
            args.append("index=True")
        d = default_expr(f)
        if d is None and f["name"] in ("created_at", "date_joined"):
            d = "utcnow"
        if d is None and f["name"] == "updated_at":
            d = "utcnow, onupdate=utcnow"
        if (
            d is None
            and not nullable
            and f["type"]
            in (
                "CharField",
                "TextField",
                "SlugField",
                "EmailField",
                "URLField",
                "FileField",
            )
        ):
            d = '""'
        if d:
            args.append(f"default={d}")
            if d == "uuid.uuid4":
                need["uuid"] = True
        lines.append(
            f"    {attr[f['name']]}: Mapped[{pt}] = mapped_column({', '.join(args)})"
        )

    table_args = []
    for u in model["unique_together"]:
        sa_names.add("UniqueConstraint")
        table_args.append(f"UniqueConstraint({', '.join(repr(columns[c]) for c in u)})")
    for c in model["constraints"]:
        if c["kind"] == "CheckConstraint":
            check = condition_sql(c["condition"], columns)
            if check is None:
                skipped.append(f"{model['table']}: {c['name']}")
                continue
            sa_names.update({"CheckConstraint", "text"})
            table_args.append(f'CheckConstraint(text("{check}"), name="{c["name"]}")')
            continue
        if c["kind"] != "UniqueConstraint" or not c["fields"]:
            skipped.append(f"{model['table']}: {c['kind']} {c['name']}")
            continue
        cols = ", ".join(repr(columns[x]) for x in c["fields"])
        if c["condition"]:
            where = condition_sql(c["condition"], columns)
            if where is None:
                skipped.append(f"{model['table']}: {c['name']} where {c['condition']}")
                continue
            sa_names.update({"Index", "text"})
            table_args.append(
                f'Index("{c["name"]}", {cols}, unique=True, postgresql_where=text("{where}"))'
            )
        else:
            sa_names.add("UniqueConstraint")
            table_args.append(f'UniqueConstraint({cols}, name="{c["name"]}")')
    for i in model["indexes"]:
        sa_names.update(
            {"Index", "text"}
            if any(x.startswith("-") for x in i["fields"])
            else {"Index"}
        )
        cols = ", ".join(
            f'text("{columns[x[1:]]} DESC")' if x.startswith("-") else repr(columns[x])
            for x in i["fields"]
        )
        table_args.append(f'Index("{i["name"]}", {cols})')

    head = ["from __future__ import annotations", ""]
    std = []
    if need["uuid"]:
        std.append("import uuid")
    if need["datetime"] or need["date"]:
        std.append(
            "from datetime import "
            + ", ".join(x for x in ("date", "datetime") if need[x])
        )
    if need["Decimal"]:
        std.append("from decimal import Decimal")
    if need["Any"]:
        std.append("from typing import Any")
    head += std + ([""] if std else [])
    core_names = sorted(n for n in sa_names if n not in ("Json", "ARRAY"))
    if core_names:
        head.append(f"from sqlalchemy import {', '.join(core_names)}")
    pg = sorted(n for n in sa_names if n == "ARRAY")
    if pg:
        head.append(f"from sqlalchemy.dialects.postgresql import {', '.join(pg)}")
    head.append(f"from sqlalchemy.orm import {', '.join(sorted(imports))}")
    common = (
        ["Base"]
        + (["Json"] if "Json" in sa_names else [])
        + (["utcnow"] if any("utcnow" in x for x in lines) else [])
    )
    head += ["", f"from app.common.db import {', '.join(common)}", "", ""]
    body = [f"class {model['model']}(Base):", f'    __tablename__ = "{model["table"]}"']
    if table_args:
        body.append("    __table_args__ = (")
        body += [f"        {a}," for a in table_args]
        body.append("    )")
    body.append("")
    return "\n".join(head + body + lines) + "\n"


def render_m2m(model: dict, m2m: dict) -> str:
    left = (
        model["table"].rstrip("s") if model["table"].endswith("s") else model["table"]
    )
    return (
        f"{m2m['table']} = Table(\n"
        f'    "{m2m["table"]}",\n'
        "    Base.metadata,\n"
        '    Column("id", BigInteger, primary_key=True, autoincrement=True),\n'
        f'    Column("{left}_id", Uuid, ForeignKey("{model["table"]}.id", ondelete="CASCADE"), nullable=False),\n'
        f'    Column("{m2m["to"].rstrip("s")}_id", Uuid, ForeignKey("{m2m["to"]}.id", ondelete="CASCADE"), nullable=False),\n'
        ")\n"
    )


def main() -> None:
    schema = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pk_types = {}
    for m in schema:
        pk = next(f for f in m["fields"] if f["pk"])
        pk_types[m["table"]] = sa_type({**pk, "type": pk["type"]}, {})
    by_module = defaultdict(list)
    for m in schema:
        by_module[module_of(m["app"])].append(m)
    skipped: list[str] = []
    for module, models in sorted(by_module.items()):
        mdir = ROOT / "app" / "modules" / module / "models"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir.parent / "__init__.py").touch()
        exports = []
        for m in sorted(models, key=lambda x: x["model"]):
            name = snake(m["model"])
            src = render(m, pk_types, skipped)
            extra = [x for x in m["m2m"] if x["to"] not in SKIP_M2M]
            if extra:
                src = src.replace(
                    "from sqlalchemy import ",
                    "from sqlalchemy import Column, Table, ",
                    1,
                )
                if "ForeignKey" not in src.split("\n\n")[0]:
                    src = src.replace(
                        "from sqlalchemy import Column, Table, ",
                        "from sqlalchemy import Column, ForeignKey, Table, ",
                        1,
                    )
                for needed in ("BigInteger", "Uuid"):
                    if needed not in src.split("from sqlalchemy.orm")[0]:
                        src = src.replace(
                            "from sqlalchemy import Column, ",
                            f"from sqlalchemy import {needed}, Column, ",
                            1,
                        )
                src += "\n\n" + "\n\n".join(render_m2m(m, x) for x in extra)
                exports += [x["table"] for x in extra]
            (mdir / f"{name}.py").write_text(src, encoding="utf-8")
            exports.append(m["model"])
        lines = []
        for m in sorted(models, key=lambda x: x["model"]):
            extra = [x["table"] for x in m["m2m"] if x["to"] not in SKIP_M2M]
            names = ", ".join([m["model"], *extra])
            lines.append(
                f"from app.modules.{module}.models.{snake(m['model'])} import {names}"
            )
        lines.append("")
        lines.append("__all__ = [" + ", ".join(f'"{e}"' for e in sorted(exports)) + "]")
        (mdir / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    registry = [
        "from app.modules." + mod + " import models as " + mod + "  # noqa: F401"
        for mod in sorted(by_module)
    ]
    (ROOT / "app" / "models.py").write_text(
        '"""Every table, imported once for the mapper and Alembic."""\n\n'
        + "\n".join(registry)
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(schema)} models in {len(by_module)} modules")
    if skipped:
        print("constraints to write by hand:")
        for s in skipped:
            print("  ", s)


if __name__ == "__main__":
    main()
