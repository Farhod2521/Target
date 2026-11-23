"""Boards: the automatic rules, each with a row of its own.

Schema (additive): ``board_rules``: one rule of one board. ``system`` rows
name a rule the code runs and hold what the superuser may change of it
(whether it runs, the columns it reads, the column it sends to, how long it
waits, the reason a card's history keeps); ``stay`` and ``due`` rows are
rules the superuser writes.

Rows: every rule the code runs, with the values the code had fixed until
now, so nothing moves differently after the deploy. From this version the
moves that wrote no reason (a payment, a bill opened or left unpaid, a
discount's steps, a wait over, the client's silence, a term's end) write
the rule's reason into the card's history.

The downgrade drops the table; the code's own values are what is left.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0080"
down_revision: str | Sequence[str] | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (board, code, from columns, to column, amount, unit, reason), in the
# order the settings show them.
SEEDS = (
    ("sales", "sales.lead_opened", [], "unworked", 0, "", ""),
    ("sales", "sales.start_expired", [], "unworked", 0, "", ""),
    ("sales", "sales.sold", [], "sold", 0, "", "Mijoz tarif uchun to'ladi."),
    ("sales", "sales.given", [], "sold", 0, "", ""),
    (
        "sales",
        "sales.start_bought",
        [],
        "",
        0,
        "",
        "Mijoz Start sotib oldi, chegirma soati boshlandi.",
    ),
    (
        "sales",
        "sales.offer_step",
        ["discount_20"],
        "discount_10",
        0,
        "",
        "20% chegirma muddati tugadi, 10% boshlandi.",
    ),
    (
        "sales",
        "sales.offer_ended",
        ["discount_10", "discount_20"],
        "",
        0,
        "",
        "Chegirma muddati tugadi, mijoz to'lamadi.",
    ),
    (
        "sales",
        "sales.bill_opened",
        ["callback", "contacted", "new_lead", "no_contact", "no_discount"],
        "awaiting",
        0,
        "",
        "Mijoz to'lov hisobini ochdi, to'lov kutilmoqda.",
    ),
    (
        "sales",
        "sales.bill_unpaid",
        ["awaiting"],
        "callback",
        0,
        "",
        "Mijoz ochgan hisobni to'lamadi, qo'ng'iroq qilish kerak.",
    ),
    ("support", "support.setup_late", [], "new", 60, "minutes", ""),
    ("support", "support.from_sales", [], "new", 0, "", ""),
    ("support", "support.meta_error", [], "new", 30, "minutes", ""),
    ("support", "support.survey", [], "new", 0, "", ""),
    ("support", "support.idle_no_launch", [], "new", 3, "days", ""),
    ("support", "support.idle_no_spend", [], "new", 24, "hours", ""),
    ("support", "support.reopened", [], "new", 0, "", ""),
    (
        "support",
        "support.due_back",
        ["unreachable", "waiting"],
        "in_progress",
        0,
        "",
        "Belgilangan vaqt keldi, zayavka xodimiga qaytdi.",
    ),
    (
        "support",
        "support.client_replied",
        ["unreachable", "waiting"],
        "in_progress",
        0,
        "",
        "Mijoz chatga yozdi, zayavka xodimiga qaytdi.",
    ),
    ("support", "support.confirmed", ["confirming"], "", 0, "", ""),
    (
        "support",
        "support.unanswered",
        ["confirming"],
        "closed",
        24,
        "hours",
        "Mijoz tasdiq savoliga javob bermadi, zayavka yopildi.",
    ),
    ("support", "support.dev_fixed", ["developer"], "resolved", 0, "", ""),
    ("renewal", "renewal.opened", [], "ending", 3, "days", ""),
    (
        "renewal",
        "renewal.ended",
        ["ending"],
        "ended",
        0,
        "",
        "Obuna muddati tugadi, mijoz hali uzaytirmadi.",
    ),
    ("renewal", "renewal.term_moved", [], "", 0, "", ""),
    (
        "renewal",
        "renewal.bill_opened",
        ["callback", "contacted", "ended", "ending", "no_contact"],
        "awaiting",
        0,
        "",
        "Mijoz uzaytirish hisobini ochdi, to'lov kutilmoqda.",
    ),
    (
        "renewal",
        "renewal.bill_unpaid",
        ["awaiting"],
        "callback",
        0,
        "",
        "Mijoz ochgan hisobni to'lamadi, qo'ng'iroq qilish kerak.",
    ),
    ("renewal", "renewal.renewed", [], "renewed", 0, "", ""),
    (
        "renewal",
        "renewal.silent",
        ["ended", "no_contact"],
        "declined",
        30,
        "days",
        "Muddat tugaganidan beri mijoz bilan bog'lanib bo'lmadi.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "board_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board", sa.String(16), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "from_columns",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("to_column", sa.String(24), nullable=False, server_default=""),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(16), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("uniq_board_rule_code", "board_rules", ["code"], unique=True)
    op.create_index("board_rules_board_idx", "board_rules", ["board", "position"])
    op.create_index("ix_board_rules_created_by_id", "board_rules", ["created_by_id"])
    op.create_index("ix_board_rules_updated_by_id", "board_rules", ["updated_by_id"])
    insert = sa.text(
        "INSERT INTO board_rules (id, created_at, updated_at, board, code, kind, "
        "from_columns, to_column, amount, unit, reason, position, is_default) "
        "VALUES (gen_random_uuid(), now(), now(), :board, :code, 'system', "
        "CAST(:from_columns AS jsonb), :to_column, :amount, :unit, :reason, "
        ":position, true)"
    )
    bind = op.get_bind()
    for position, seed in enumerate(SEEDS, start=1):
        board, code, from_columns, to_column, amount, unit, reason = seed
        bind.execute(
            insert,
            {
                "board": board,
                "code": code,
                "from_columns": json.dumps(from_columns),
                "to_column": to_column,
                "amount": amount,
                "unit": unit,
                "reason": reason,
                "position": position,
            },
        )


def downgrade() -> None:
    op.drop_table("board_rules")
