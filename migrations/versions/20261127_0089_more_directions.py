"""Businesses: the five catalogues nobody could pick, and Moliya on its own.

The catalogue has held eighteen kinds of business since 2026-10-31, and the
list a profile is picked from thirteen: nothing ever wrote the other five
into ``business_categories``. A customer in furniture, farming, software,
children's goods or logistics stood on «Xizmatlar» and was advertised with
its interests.

Rows (additive):

- the five missing directions, after the ones already there, each on the
  catalogue of its own name. A key that is already in the table is left as
  it is;
- «Moliya» moved from the «Xizmatlar» catalogue to ``finance``, and the
  profiles standing on it with it, as an office edit of the direction's
  catalogue does.

The downgrade moves «Moliya» back. The five directions stay: a customer may
stand on one by then.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | Sequence[str] | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, uz, ru, en): the catalogue's own label, and its two translations.
SEEDS = (
    ("agriculture", "Qishloq xo'jaligi", "Сельское хозяйство", "Agriculture"),
    ("furniture", "Mebel", "Мебель", "Furniture"),
    ("it_software", "IT va dasturlar", "IT и программы", "IT and software"),
    ("kids", "Bolalar mahsulotlari", "Детские товары", "Children's products"),
    ("logistics", "Logistika", "Логистика", "Logistics"),
)


def _move(bind: sa.Connection, *, old: str, new: str) -> None:
    bind.execute(
        sa.text(
            "UPDATE businesses SET category = :new, updated_at = now() "
            "WHERE category = :old AND direction_id IN ("
            "SELECT id FROM business_categories "
            "WHERE key = 'finance' AND preset_key = :old)"
        ),
        {"old": old, "new": new},
    )
    bind.execute(
        sa.text(
            "UPDATE business_categories SET preset_key = :new, updated_at = now() "
            "WHERE key = 'finance' AND preset_key = :old"
        ),
        {"old": old, "new": new},
    )


def upgrade() -> None:
    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO business_categories (id, created_at, updated_at, key, "
        "label_uz, label_ru, label_en, preset_key, position, is_active) "
        "SELECT gen_random_uuid(), now(), now(), CAST(:key AS varchar), :uz, :ru, "
        ":en, CAST(:key AS varchar), "
        "(SELECT COALESCE(MAX(position), 0) + 1 FROM business_categories), true "
        "WHERE NOT EXISTS (SELECT 1 FROM business_categories "
        "WHERE key = CAST(:key AS varchar))"
    )
    for key, uz, ru, en in SEEDS:
        bind.execute(insert, {"key": key, "uz": uz, "ru": ru, "en": en})
    _move(bind, old="services", new="finance")


def downgrade() -> None:
    _move(op.get_bind(), old="finance", new="services")
