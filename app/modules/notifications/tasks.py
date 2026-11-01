from typing import Any

from app.common.db import utcnow
from app.modules.notifications.services import (
    announce_feedback,
    announce_password_changed,
    announce_referral,
    announce_support_answered,
    announce_support_reply,
    announce_withdrawal,
    forward_support_question,
    handle_staff_update,
    handle_update,
)
from app.modules.notifications.services.notices import user_of
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_feedback_notice_task(
    owner_id: str,
    feedback_id: str,
    outcome: str,
    kind: str,
    amount_minor: int,
    currency: str,
    reason: str,
) -> bool:
    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return False
        sent = announce_feedback(
            db,
            owner=owner,
            feedback_id=feedback_id,
            outcome=outcome,
            kind=kind,
            amount_minor=amount_minor,
            currency=currency,
            reason=reason,
            now=utcnow(),
        )
        db.commit()
        return sent


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_withdrawal_notice_task(
    owner_id: str,
    withdrawal_id: str,
    outcome: str,
    amount_minor: int,
    currency: str,
    card_last4: str,
    reason: str,
) -> bool:
    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return False
        sent = announce_withdrawal(
            db,
            owner=owner,
            withdrawal_id=withdrawal_id,
            outcome=outcome,
            amount_minor=amount_minor,
            currency=currency,
            card_last4=card_last4,
            reason=reason,
            now=utcnow(),
        )
        db.commit()
        return sent


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_referral_notice_task(referrer_id: str, invited_id: str) -> bool:
    with task_session() as db:
        referrer = user_of(db, referrer_id)
        invited = user_of(db, invited_id)
        if referrer is None or invited is None:
            return False
        sent = announce_referral(db, referrer=referrer, invited=invited, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_password_changed_task(owner_id: str) -> bool:
    """Tell the linked phone a password was just replaced through the bot."""
    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return False
        sent = announce_password_changed(db, owner=owner, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="webhooks", ignore_result=True)
def handle_telegram_update(payload: dict[str, Any]) -> str:
    """One delivery to the customer bot, acted on."""
    with task_session() as db:
        return handle_update(db, payload=payload, now=utcnow())


@celery_app.task(queue="webhooks", ignore_result=True)
def handle_staff_telegram_update(payload: dict[str, Any]) -> str:
    """One delivery to the staff bot, acted on."""
    with task_session() as db:
        return handle_staff_update(db, payload=payload, now=utcnow())


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_support_question_task(message_id: str) -> int:
    with task_session() as db:
        copies = forward_support_question(db, message_id=message_id, now=utcnow())
        db.commit()
        return copies


@celery_app.task(queue="webhooks", ignore_result=True)
def mark_support_answered_task(reply_id: str) -> int:
    with task_session() as db:
        marked = announce_support_answered(db, reply_id=reply_id, now=utcnow())
        db.commit()
        return marked


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_support_reply_task(owner_id: str, subject: str) -> bool:
    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return False
        sent = announce_support_reply(db, owner=owner, subject=subject, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="sync", ignore_result=True)
def deliver_notices_task() -> int:
    """Every quarter hour: what every linked phone is owed."""
    from app.modules.notifications.services.sweep import deliver_notices

    with task_session() as db:
        sent = deliver_notices(db, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="sync", ignore_result=True)
def deliver_trouble_notices_task() -> int:
    """Hourly: the cabinet's troubles, to the owners whose morning it is."""
    from app.modules.notifications.services.sweep import deliver_troubles

    with task_session() as db:
        sent = deliver_troubles(db, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="sync", ignore_result=True)
def deliver_expiry_notices_task() -> int:
    """Once a day: warn the accounts whose subscriptions are running out."""
    from app.modules.notifications.services.sweep import deliver_expiry_notices

    with task_session() as db:
        sent = deliver_expiry_notices(db, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="sync", ignore_result=True)
def deliver_lapse_notices_task() -> int:
    """Every quarter hour: the adverts an ended subscription stopped, and the
    day before they are removed."""
    from app.modules.notifications.services.sweep import deliver_lapse_notices

    with task_session() as db:
        sent = deliver_lapse_notices(db, now=utcnow())
        db.commit()
        return sent


@celery_app.task(queue="sync", ignore_result=True)
def deliver_daily_reports_task() -> str:
    """Every hour: hand the owners whose finished day is ready to their own
    task, so one account whose figures raise does not take the rest down."""
    from app.modules.notifications.services.announce_reports import (
        daily_report_audience,
        unfinished_report_audience,
    )

    with task_session() as db:
        now = utcnow()
        owners = daily_report_audience(db, now=now)
        unfinished = unfinished_report_audience(db, now=now)
    for owner_id in owners:
        deliver_daily_report_task.delay(owner_id)
    for owner_id in unfinished:
        finish_daily_report_task.delay(owner_id)
    return f"queued:{len(owners)}:finished:{len(unfinished)}"


@celery_app.task(queue="sync", ignore_result=True)
def deliver_daily_report_task(owner_id: str) -> str:
    """One account's finished day. The journal holds one list per day."""
    from app.modules.notifications.services.announce_reports import (
        deliver_daily_report_for,
    )

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        sent = deliver_daily_report_for(db, owner=owner, now=utcnow())
        return "sent" if sent else "quiet"


@celery_app.task(queue="sync", ignore_result=True)
def finish_daily_report_task(owner_id: str) -> str:
    """Put the finished figures into a message sent without them."""
    from app.modules.notifications.services.announce_reports import (
        finish_daily_report_for,
    )

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        edited = finish_daily_report_for(db, owner=owner, now=utcnow())
        return "edited" if edited else "quiet"


@celery_app.task(queue="sync", ignore_result=True)
def deliver_weekly_reports_task() -> str:
    """Every hour: the owners whose Monday morning it is, a task each."""
    from app.modules.notifications.services.announce_reports import (
        report_audience,
        unfinished_week_audience,
    )

    with task_session() as db:
        now = utcnow()
        owners = report_audience(db, now=now)
        unfinished = unfinished_week_audience(db, now=now)
    for owner_id in owners:
        deliver_report_task.delay(owner_id)
    for owner_id in unfinished:
        finish_weekly_report_task.delay(owner_id)
    return f"queued:{len(owners)}:finished:{len(unfinished)}"


@celery_app.task(queue="sync", ignore_result=True)
def deliver_report_task(owner_id: str) -> str:
    """One account's completed week."""
    from app.modules.notifications.services.announce_reports import deliver_report_for

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        return "sent" if deliver_report_for(db, owner=owner, now=utcnow()) else "quiet"


@celery_app.task(queue="sync", ignore_result=True)
def finish_weekly_report_task(owner_id: str) -> str:
    """Put the finished figures into the week's message."""
    from app.modules.notifications.services.announce_reports import (
        finish_weekly_report_for,
    )

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        edited = finish_weekly_report_for(db, owner=owner, now=utcnow())
        return "edited" if edited else "quiet"


@celery_app.task(queue="sync", ignore_result=True)
def deliver_frequency_task(owner_id: str) -> str:
    """One owner's new frequency levels, once the agent has written them."""
    from app.modules.notifications.services.announce_frequency import (
        deliver_frequency_for,
    )

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        sent = deliver_frequency_for(db, owner=owner, now=utcnow())
        return "sent" if sent else "quiet"


@celery_app.task(queue="chat", ignore_result=True)
def answer_for_telegram(turn_id: str, chat_id: str, reply_to: int) -> str:
    """Write the answer to one question asked in Telegram, and send it. On
    ``chat``, where the cabinet's own answers stream: a Meta lead callback
    must not wait behind a model."""
    from app.modules.notifications.services.converse import answer_and_send

    with task_session() as db:
        return answer_and_send(
            db, turn_id=turn_id, chat_id=chat_id, reply_to=reply_to, now=utcnow()
        )


@celery_app.task(queue="sync", ignore_result=True)
def deliver_surveys_task() -> str:
    """Every hour: the linked owners inside the asking hours, a task each."""
    from app.modules.notifications.services.announce_survey import survey_audience

    with task_session() as db:
        owners = survey_audience(db, now=utcnow())
    for owner_id in owners:
        deliver_survey_task.delay(owner_id)
    return f"queued:{len(owners)}"


@celery_app.task(queue="webhooks", ignore_result=True)
def deliver_survey_task(owner_id: str) -> str:
    """Start the survey owed today in one account's bot."""
    from app.modules.notifications.services.announce_survey import (
        deliver_survey_for,
    )

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        return deliver_survey_for(db, owner=owner, now=utcnow())


@celery_app.task(queue="webhooks", ignore_result=True)
def resend_survey_task(owner_id: str, token: str) -> str:
    """The question «Keyinroq» put off, asked again once the wait is up."""
    from app.modules.notifications.services.announce_survey import resend_survey_for

    with task_session() as db:
        owner = user_of(db, owner_id)
        if owner is None:
            return "gone"
        return resend_survey_for(db, owner=owner, token=token, now=utcnow())
