"""The model is told when what it reads is old.

The context is the mirror. Behind a dead connection a campaign last read as
running was called running, because nothing handed to the model said the
read had stopped - on production, 2026-11-12, that was 166 campaigns.
"""

from core.chat.context import (
    AccountDigest,
    BusinessDigest,
    CampaignDigest,
    ChatContext,
    ConnectionDown,
    PageTotals,
    TotalsDigest,
)
from core.chat.day_report import DayBook


def _account(down: ConnectionDown | None) -> AccountDigest:
    return AccountDigest(
        business=BusinessDigest(
            name="Do'kon", category="Savdo", offer="", currency="USD"
        ),
        totals=TotalsDigest(window_days=7, spend="$10"),
        maturity="",
        down=down,
        by_page=(
            PageTotals(
                name="Sahifa",
                spend="$10",
                campaigns=(
                    CampaignDigest(name="Aksiya", status="running", spend="$10"),
                ),
            ),
        ),
    )


def test_a_dead_connection_is_said_before_any_figure() -> None:
    down = ConnectionDown(
        network="Meta (Facebook)",
        status="invalid",
        lost_at="2026-11-11 17:40 UTC",
        last_read="2026-11-11 17:34 UTC",
    )

    said = ChatContext(account=_account(down)).render()

    first = said.splitlines()[0]
    assert first == "## IMPORTANT: the Meta (Facebook) connection is not working"
    assert said.index("IMPORTANT") < said.index("## Business")
    assert "invalid since 2026-11-11 17:40 UTC" in said
    assert "last read from Meta (Facebook) at 2026-11-11 17:34 UTC" in said
    assert "Never say an advert, group or campaign is running" in said
    assert "unread, not zero" in said
    # The row itself is kept: it is what was true at that read.
    assert "Aksiya - running" in said


def test_a_fall_nobody_dated_is_still_said() -> None:
    down = ConnectionDown(network="Meta (Facebook)", status="revoked")

    said = ChatContext(account=_account(down)).render()

    assert "The connection is revoked. Nothing can be read" in said
    assert "was never read from Meta (Facebook)" in said


def test_a_working_connection_adds_nothing() -> None:
    said = ChatContext(account=_account(None)).render()

    assert said.startswith("## Business")
    assert "connection" not in said


def test_a_report_says_where_its_figures_stop() -> None:
    from datetime import date

    from app.modules.notifications.services.compose_daily import status_section

    day = date(2026, 11, 11)
    cut = DayBook(day=day, until=day, day_text="11-noyabr", cut_off="11-noyabr 22:34")
    late = DayBook(day=day, until=day, day_text="11-noyabr", final=False)
    done = DayBook(day=day, until=day, day_text="11-noyabr")

    assert status_section(cut) == [
        "<i>⚠️ Facebook ulanishi uzilgan — raqamlar 11-noyabr 22:34 gacha, "
        "undan keyingisi o'qilmagan</i>"
    ]
    assert status_section(late) == ["<i>⏳ Raqamlar hali yakuniy emas</i>"]
    assert status_section(done) == []
