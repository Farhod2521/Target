"""Give every ``<name>_id`` foreign key in a module's models its ``<name>`` relationship.

python tools/add_relationships.py ads agent chat ...

Django code walks ``row.owner`` and ``row.campaign``; the generated models
only had the id columns. Lines go under ``# -- django extras --``; a name the
class already has is left alone.
"""

import re
import sys
from pathlib import Path

from sqlalchemy import ForeignKey

from app import models as _models  # noqa: F401
from app.common.db import Base

ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"
COLUMN = re.compile(r"^    (\w+)_id: Mapped\[(.+?)\] = mapped_column\(", re.M)


def classes_by_table() -> dict[str, str]:
    return {
        mapper.local_table.name: mapper.class_.__name__
        for mapper in Base.registry.mappers
    }


def patch(path: Path, tables: dict[str, str]) -> int:
    text = path.read_text(encoding="utf-8")
    added: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^    (\w+)_id: Mapped\[(.+?)\] = mapped_column\((.*)$", line)
        if not match:
            continue
        name, kind, rest = match.groups()
        target = re.search(r'ForeignKey\("([\w]+)\.', rest)
        if not target or target.group(1) not in tables:
            continue
        if re.search(rf"^    {name}\s*[:=]", text, re.M) or re.search(
            rf"def {name}\(", text
        ):
            continue
        model = tables[target.group(1)]
        optional = " | None" if "None" in kind else ""
        # A row pointing at its own table: without remote_side the relationship
        # reads the rows pointing at this one - the child, not the parent.
        own = re.search(rf"^class {model}\(", text, re.M)
        remote = "remote_side=[id], " if own else ""
        added.append(
            f'    {name}: Mapped["{model}{optional}"] = relationship('
            f'foreign_keys=[{name}_id], {remote}lazy="select")  # noqa: F821'
        )
    if not added:
        return 0
    if "relationship" not in text.split("class ", 1)[0]:
        text = text.replace(
            "from sqlalchemy.orm import Mapped, mapped_column\n",
            "from sqlalchemy.orm import Mapped, mapped_column, relationship\n",
            1,
        )
    block = "\n".join(added) + "\n"
    if "# -- django extras --" in text:
        text = text.replace(
            "    # -- django extras --\n", "    # -- django extras --\n" + block, 1
        )
    else:
        text = text.rstrip("\n") + "\n    # -- django extras --\n" + block
    path.write_text(text, encoding="utf-8")
    return len(added)


def main(names: list[str]) -> None:
    tables = classes_by_table()
    _ = ForeignKey
    for name in names:
        for path in sorted((ROOT / name / "models").glob("*.py")):
            if path.name == "__init__.py":
                continue
            count = patch(path, tables)
            if count:
                print(f"{path.relative_to(ROOT)}: +{count}")


if __name__ == "__main__":
    main(sys.argv[1:])
