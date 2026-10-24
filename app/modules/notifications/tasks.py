from app.common.db import utcnow
from app.modules.notifications.services import (
    announce_feedback,
    announce_referral,
    announce_withdrawal,
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
