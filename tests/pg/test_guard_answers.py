"""The answers to the guard's findings against PostgreSQL: a late answer
checked against today's figures first, the question when the finding is
over, the provider's outcome told on the same message, a refused stop, and
the page and ad account pair the group must sit in."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import ButtonPress
from telegramkit.updates import Sender

from app.common.db import utcnow
from app.common.i18n import override
from app.modules.ads.models import AdSet
from app.modules.agent.guard_copy import buttons_of, guard_title
from app.modules.agent.guard_follow_copy import follow_of
from app.modules.agent.models import GuardAlert
from app.modules.agent.services.answer_guard import answer_guard
from app.modules.agent.services.recheck_guard import recheck
from app.modules.agent.services.run_guard import run_guard
from app.modules.audit.constants import ActionStatus
from app.modules.integrations.models import AdAccount, PageAccount, PagePair
from app.modules.notifications.constants import GUARD_CALLBACKS
from app.modules.notifications.keys import press_data
from app.modules.notifications.selectors.inbox_guard import (
    guard_item,
    open_guard_alerts,
)
from app.modules.notifications.services.announce_guard import announce_guard, show_state
from app.modules.notifications.services.guard_press import handle_guard_press
from tests.pg.test_guard import (
    _land,
    _linked_phone,
    _pauses,
    _rows,
    _running,
    _today,
    _warned,
)


def _aged(db: Session, row: GuardAlert, *, minutes: int, now: datetime) -> GuardAlert:
    """The finding as though its figures were read ``minutes`` ago."""
    row.figures = {**row.figures, "at": (now - timedelta(minutes=minutes)).isoformat()}
    db.commit()
    return row


def _recheck(
    db: Session, row: GuardAlert, now: datetime, *, may_wait: bool = True
) -> str:
    return recheck(db, alert_id=str(row.id), now=now, may_wait=may_wait)


def _queued_names(queued: list) -> list[str]:
    return [name.rsplit(".", 1)[1] for name, _args in queued]


# -- the answer within half an hour of its figures ------------------------------------------


def test_a_prompt_answer_is_carried_out_on_its_own_figures(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, _account, now, row = _warned(client, db)
    _aged(db, row, minutes=29, now=now)

    done = answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()

    assert done.state == "asked"
    (log,) = _pauses(db)
    # The campaign's one group: its campaign is what stops.
    assert (log.target_level, log.target_external_id) == ("campaign", "c_1")
    assert "recheck_guard_task" not in _queued_names(queued)


# -- a late answer: the second look ---------------------------------------------------------


def test_a_late_stop_still_true_is_carried_out_after_the_second_look(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, _account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)

    done = answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    assert done.state == "checking"
    assert _pauses(db) == []
    assert "recheck_guard_task" in _queued_names(queued)
    # Pressed again while it looks: refused, nothing asked twice.
    from app.modules.agent.exceptions import GuardChecking

    with pytest.raises(GuardChecking):
        answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.rollback()

    # Today's figures still say 5.1 usual prices: the stop goes out.
    assert _recheck(db, row, now) == "asked"
    (row,) = _rows(db)
    assert (row.pending_state, row.answer) == ("", "pause")
    assert row.answer_log_id == _pauses(db)[0].id


def test_a_late_stop_on_a_price_that_eased_asks_first(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    # Since then: three leads for 900, one and a half usual prices.
    _today(db, owner, account, now, spend=900, leads=3)

    assert _recheck(db, row, now) == "confirm"
    (row,) = _rows(db)
    assert (row.pending_state, row.pending_answer) == ("confirm", "pause")
    assert (row.now_figures["spend_minor"], row.now_figures["results"]) == (900, 3)
    assert row.now_figures["unread"] is False
    assert _pauses(db) == []
    with override("uz"):
        line, shown = follow_of(row)
        assert line.startswith(
            "✅ Hozir yaxshi ishlayapti: bugun $9 sarflandi, 3 ta lid, bittasi $3 (odatda $2)."
        )
        assert "Baribir kampaniyani to'xtataymi?" in line
        assert shown == ("confirm", "cancel")
        item = guard_item(row)
        assert [action.href.rsplit("/", 1)[1] for action in item.actions] == [
            "confirm",
            "cancel",
        ]
        assert [action.label for action in item.actions] == [
            "Ha, to'xtat",
            "Yo'q, qoldir",
        ]

    # «Yes»: the stop goes out now, without another look.
    done = answer_guard(db, user=owner, alert_id=str(row.id), answer="confirm", now=now)
    db.commit()
    assert (done.state, done.answer) == ("asked", "pause")
    assert len(_pauses(db)) == 1


def test_no_to_the_question_changes_nothing(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    _today(db, owner, account, now, spend=900, leads=3)
    _recheck(db, row, now)

    done = answer_guard(db, user=owner, alert_id=str(row.id), answer="cancel", now=now)
    db.commit()
    assert done.state == "cancelled"
    (row,) = _rows(db)
    assert (row.answer, row.pending_state, row.closed_at) == ("leave", "", None)
    assert _pauses(db) == []


def test_a_question_left_half_an_hour_is_looked_at_again(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    _today(db, owner, account, now, spend=900, leads=3)
    _recheck(db, row, now)

    later = now + timedelta(minutes=31)
    done = answer_guard(
        db, user=owner, alert_id=str(row.id), answer="confirm", now=later
    )
    db.commit()
    assert done.state == "checking"
    assert _pauses(db) == []


def test_a_group_no_longer_running_is_left_alone(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, _account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    group = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert group is not None
    group.delivery = "paused"
    db.commit()

    assert _recheck(db, row, now) == "gone"
    (row,) = _rows(db)
    assert (row.result, row.closed_at is not None) == ("gone", True)
    assert _pauses(db) == []


def test_old_figures_are_read_from_meta_before_judging(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.ads.services import mirror
    from app.modules.metrics.services import sync as metrics_sync

    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    account.synced_at = now - timedelta(hours=2)
    db.commit()
    read: list[str] = []

    def mirrored(db_: Session, *, ad_account: AdAccount, whole: bool = True) -> None:
        read.append("mirror")
        ad_account.synced_at = utcnow()

    def today(db_: Session, *, ad_account: AdAccount, people_after=None) -> None:
        read.append("today")

    monkeypatch.setattr(mirror, "sync_ad_account", mirrored)
    monkeypatch.setattr(metrics_sync, "sync_today", today)

    assert _recheck(db, row, now) == "asked"
    assert read == ["mirror", "today"]


def test_figures_meta_would_not_give_are_said_so(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.ads.services import mirror
    from app.modules.ads.exceptions import ConnectionUnusable

    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    account.synced_at = now - timedelta(hours=2)
    db.commit()

    def refused(db_: Session, *, ad_account: AdAccount, whole: bool = True) -> None:
        raise ConnectionUnusable

    monkeypatch.setattr(mirror, "sync_ad_account", refused)

    assert _recheck(db, row, now) == "confirm"
    (row,) = _rows(db)
    assert row.now_figures["unread"] is True
    assert _pauses(db) == []
    with override("uz"):
        line, _shown = follow_of(row)
    assert line.startswith("⚠️ Meta'dan hozirgi raqamlarni o'qib bo'lmadi.")


def test_a_sync_already_running_is_waited_for(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    from app.modules.ads.exceptions import SyncAlreadyRunning
    from app.modules.ads.services import mirror

    owner, account, now, row = _warned(client, db)
    _aged(db, row, minutes=45, now=now)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    account.synced_at = now - timedelta(hours=2)
    db.commit()

    def running(db_: Session, *, ad_account: AdAccount, whole: bool = True) -> None:
        raise SyncAlreadyRunning

    monkeypatch.setattr(mirror, "sync_ad_account", running)

    assert _recheck(db, row, now) == "busy"
    assert _rows(db)[0].pending_state == "checking"
    # Out of tries: asked, told the figures could not be read.
    assert _recheck(db, row, now, may_wait=False) == "confirm"
    assert _rows(db)[0].now_figures["unread"] is True


# -- the pair ---------------------------------------------------------------------------------


def test_a_group_whose_page_left_the_pairs_is_not_changed(
    client: TestClient, db: Session, queued: list
) -> None:
    from app.modules.agent.exceptions import GuardPairGone

    owner, _account, now, row = _warned(client, db)
    # The page was switched off in the cabinet: no pair holds it now.
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    assert page is not None
    page.is_active = False
    db.commit()

    with pytest.raises(GuardPairGone):
        answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.rollback()
    assert _pauses(db) == []


def test_a_group_of_an_account_its_page_is_not_paired_with_is_not_judged(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == owner.id))
    assert page is not None
    other = AdAccount(
        owner_id=owner.id,
        provider=account.provider,
        external_id="act_other",
        connection_id=account.connection_id,
        name="Boshqa",
        currency="USD",
        timezone="Asia/Tashkent",
        is_active=True,
    )
    db.add(other)
    db.flush()
    db.add(PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=other.id))
    db.commit()

    _today(db, owner, account, now, spend=6_060, leads=3)
    assert run_guard(db, owner=owner, now=now) == 0
    assert _rows(db) == [] and _pauses(db) == []


# -- the provider's outcome -----------------------------------------------------------------


def test_a_refused_answer_brings_the_buttons_back(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, _account, now, row = _warned(client, db)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()

    _land(db, status=ActionStatus.FAILED, message="Reklama akkaunti yopilgan.")
    (row,) = _rows(db)
    assert (row.result, row.closed_at) == ("failed", None)
    assert "Reklama akkaunti yopilgan." in row.result_text
    assert [found.id for found in open_guard_alerts(db, owner=owner)] == [row.id]
    with override("uz"):
        line, shown = follow_of(row)
    assert line.startswith("❌ Meta bajarmadi:") and shown is None

    # Pressed again: a new change, not «already answered».
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    assert len(_pauses(db)) == 2


def test_a_stop_the_provider_refused_is_said_and_not_asked_again_today(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    owner, account, now = _running(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    assert row.action == "stop"
    # Not said while it is on its way.
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0

    _land(db, status=ActionStatus.FAILED, message="To'lov usuli yo'q.")
    (row,) = _rows(db)
    assert (row.action, row.result) == ("stop", "failed")
    assert buttons_of(row) == ("pause", "leave")
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    (text,) = phone.texts()
    assert "To'xtata olmadim" in text or "Не удалось остановить" in text
    assert "To'lov usuli yo'q." in text

    # The next passes ask nothing again today, and keep the one row.
    for _ in range(2):
        run_guard(db, owner=owner, now=now)
    assert len(_pauses(db)) == 1
    (row,) = _rows(db)
    assert row.closed_at is None


def test_a_stop_is_said_once_it_landed(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    owner, account, now = _running(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
    _land(db)
    assert "tell_guard_outcome_task" in _queued_names(queued)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    (text,) = phone.texts()
    assert "To'xtatdim" in text or "Остановил" in text


# -- the phone ----------------------------------------------------------------------------


def _press(row: GuardAlert, answer: str, *, message_id: int) -> ButtonPress:
    return ButtonPress(
        chat_id="700",
        sender=Sender(id="700"),
        query_id="q1",
        message_id=message_id,
        data=press_data(action=GUARD_CALLBACKS[answer], pk=row.id),
    )


def _edits(phone) -> list[dict]:
    return [fields for name, fields in phone.calls if name == "edit_message_text"]


def test_a_press_rewrites_the_message_and_the_outcome_follows(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    owner, _account, now, row = _warned(client, db)
    owner.language = "uz"
    db.commit()
    phone = _linked_phone(db, owner, now, monkeypatch)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 1
    (row,) = _rows(db)
    assert row.telegram_message_id == 101

    said = handle_guard_press(
        db, client=phone, press=_press(row, "pause", message_id=101), now=now
    )
    assert said == "guard_pause:asked"
    (edit,) = _edits(phone)
    assert edit["message_id"] == 101
    assert "⏳ Kampaniyani to'xtatish so'rovi Meta'ga yuborildi" in edit["text"]
    assert edit["buttons"] == ()

    _land(db)
    (row,) = _rows(db)
    assert show_state(db, client=phone, row=row)
    last = _edits(phone)[-1]
    assert "✅ Bajarildi: kampaniya to'xtatildi." in last["text"]
    assert last["buttons"] == ()


def test_a_late_press_on_the_phone_asks_with_yes_and_no(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    owner, account, now, row = _warned(client, db)
    owner.language = "uz"
    db.commit()
    phone = _linked_phone(db, owner, now, monkeypatch)
    announce_guard(db, client=phone, now=now, asleep=set())
    (row,) = _rows(db)
    _aged(db, row, minutes=50, now=now)

    said = handle_guard_press(
        db, client=phone, press=_press(row, "pause", message_id=101), now=now
    )
    assert said == "guard_pause:checking"
    assert "🔎 Bu raqamlar 50 daqiqa oldingi." in _edits(phone)[-1]["text"]

    _today(db, owner, account, now, spend=900, leads=3)
    _recheck(db, row, now)
    (row,) = _rows(db)
    show_state(db, client=phone, row=row)
    question = _edits(phone)[-1]
    assert "✅ Hozir yaxshi ishlayapti" in question["text"]
    labels = [button.text for button in question["buttons"]]
    assert labels == ["Ha, to'xtat", "Yo'q, qoldir"]
    yes = question["buttons"][0].data
    assert yes == press_data(action=GUARD_CALLBACKS["confirm"], pk=row.id)

    said = handle_guard_press(
        db, client=phone, press=_press(row, "confirm", message_id=101), now=now
    )
    assert said == "guard_pause:asked"
    assert len(_pauses(db)) == 1


def test_the_title_of_a_refused_stop(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    _land(db, status=ActionStatus.FAILED)
    (row,) = _rows(db)
    with override("uz"):
        assert guard_title(row) == "To'xtata olmadim"


def test_leave_after_a_refusal_ends_the_refusal(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, _account, now, row = _warned(client, db)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    _land(db, status=ActionStatus.FAILED)

    answer_guard(db, user=owner, alert_id=str(row.id), answer="leave", now=now)
    db.commit()
    (row,) = _rows(db)
    assert (row.answer, row.result, row.answer_log_id) == ("leave", "", None)
    assert open_guard_alerts(db, owner=owner) == []
    with override("uz"):
        assert follow_of(row) == ("✓ Qoldirildi. Narx yana oshsa, xabar beraman.", ())


def test_a_refused_stop_stopped_by_hand_says_who_stopped_it(
    client: TestClient, db: Session, queued: list
) -> None:
    owner, account, now = _running(client, db)
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    _land(db, status=ActionStatus.FAILED, message="Vaqtincha xato.")
    (row,) = _rows(db)

    answer_guard(db, user=owner, alert_id=str(row.id), answer="pause", now=now)
    db.commit()
    assert len(_pauses(db)) == 2
    _land(db)
    (row,) = _rows(db)
    assert row.closed_at is not None
    with override("uz"):
        assert guard_title(row) == "To'xtata olmadim"
        assert follow_of(row) == ("✅ Bajarildi: kampaniya to'xtatildi.", ())


def test_a_new_step_forgets_the_last_one_s_outcome(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:
    owner, account, now, row = _warned(client, db)
    phone = _linked_phone(db, owner, now, monkeypatch)
    answer_guard(db, user=owner, alert_id=str(row.id), answer="budget_down", now=now)
    db.commit()
    _land(db)
    (row,) = _rows(db)
    assert (row.result, row.closed_at) == ("applied", None)

    # Ten: the guard's own stop - said once it lands, not before.
    _today(db, owner, account, now, spend=6_060, leads=3)
    run_guard(db, owner=owner, now=now)
    (row,) = _rows(db)
    assert (row.action, row.result, row.answer_log_id) == ("stop", "", None)
    assert announce_guard(db, client=phone, now=now, asleep=set()) == 0
