"""CRM: one person may work several pairs.

Schema:

- ``crm_members.user_id`` stops being unique. The constraint is found by its
  column, since the database Django made names it its own way;
- ``uniq_crm_member_per_pair``: one row for a person on a pair;
- ``ix_crm_members_user_id``: the plain index the unique one stood in for.

No row changes, and every row satisfies the new index: a person had one row.

The downgrade puts the old rule back, and so fails while anybody works two
pairs; take their extra rows away first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088"
down_revision: str | Sequence[str] | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "crm_members"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(TABLE):
        if constraint["column_names"] == ["user_id"]:
            op.drop_constraint(constraint["name"], TABLE, type_="unique")
    inspector = sa.inspect(op.get_bind())
    plain = False
    for index in inspector.get_indexes(TABLE):
        if index["column_names"] != ["user_id"]:
            continue
        if index.get("unique"):
            op.drop_index(index["name"], table_name=TABLE)
        else:
            plain = True
    if not plain:
        op.create_index("ix_crm_members_user_id", TABLE, ["user_id"])
    op.create_index(
        "uniq_crm_member_per_pair",
        TABLE,
        ["user_id", "page_id", "ad_account_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uniq_crm_member_per_pair", table_name=TABLE)
    op.create_unique_constraint("crm_members_user_id_key", TABLE, ["user_id"])
