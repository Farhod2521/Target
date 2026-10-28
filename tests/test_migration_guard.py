from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)

from migrations.guard import guard

DJANGO_SCHEMA = [
    "CREATE TABLE django_session (session_key VARCHAR(40) PRIMARY KEY)",
    "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(200))",
    "CREATE INDEX users_email_1a2b3c4d ON users (email)",
    "CREATE TABLE ads (id INTEGER PRIMARY KEY, owner_id INTEGER, name VARCHAR(50), "
    "legacy VARCHAR(10), "
    "CONSTRAINT ads_owner_id_9f8e7d6c_fk_users_id FOREIGN KEY (owner_id) "
    "REFERENCES users (id))",
    "CREATE INDEX ads_owner_id_9f8e7d6c ON ads (owner_id)",
]


def _models() -> MetaData:
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("email", String(200), index=True),
    )
    Table(
        "ads",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("owner_id", Integer, ForeignKey("users.id"), index=True),
        Column("name", String(50), index=True),
    )
    return metadata


def _guarded() -> str:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for statement in DJANGO_SCHEMA:
            conn.execute(text(statement))
        context = MigrationContext.configure(conn)
        script = produce_migrations(context, _models())
        guard(context, None, [script])
    return render_python_code(script.upgrade_ops) + render_python_code(
        script.downgrade_ops
    )


def test_nothing_the_database_holds_is_dropped() -> None:
    code = _guarded()

    assert "django_session" not in code
    assert "legacy" not in code
    assert "drop_index('users_email_1a2b3c4d'" not in code


def test_an_index_or_link_under_django_s_name_is_not_made_again() -> None:
    code = _guarded()

    assert "ix_users_email" not in code
    assert "ix_ads_owner_id" not in code
    assert "create_foreign_key" not in code


def test_what_is_really_missing_is_still_written() -> None:
    code = _guarded()

    assert "create_index(op.f('ix_ads_name'), 'ads', ['name']" in code
    assert "drop_index(op.f('ix_ads_name')" in code
