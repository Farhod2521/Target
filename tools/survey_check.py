"""Why a customer's survey does not reach the bot. Read-only.

    docker compose exec -T api python - email@misol.uz < tools/survey_check.py
"""

import sys

from sqlalchemy import func, select

from app import models as _models  # noqa: F401

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.selectors import live_subscription
from app.modules.notifications.bot import is_configured
from app.modules.notifications.constants import (
    SURVEY_FIRST_HOUR,
    SURVEY_LAST_HOUR,
    NoticeKind,
)
from app.modules.notifications.models import TelegramNotice
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.services.survey_state import local_now
from app.modules.surveys.constants import SNOOZE_KEY
from app.modules.surveys.models import Survey, SurveyResponse
from app.modules.surveys.selectors.due import answered_since, due_survey, owed
from app.worker import task_session


def ok(flag: bool) -> str:
    return "OK  " if flag else "XATO"


def main(email: str) -> None:
    now = utcnow()
    with task_session() as db:
        user = db.scalars(
            select(User).where(func.lower(User.email) == email.lower())
        ).first()
        if user is None:
            print("XATO foydalanuvchi topilmadi:", email)
            return
        print(f"Foydalanuvchi: {user.email} id={user.id} til={user.language}")
        print(ok(is_configured()), "bot sozlangan (token, secret, username)")
        print(ok(not user.is_staff), f"staff emas (is_staff={user.is_staff})")
        chat = chat_for(db, owner=user)
        print(ok(chat is not None), "faol Telegram chat ulangan",
              f"chat_id={chat.chat_id}" if chat else "")
        sub = live_subscription(db, owner=user)
        print(ok(sub is not None), "faol tarif",
              f"plan={sub.plan_id} started={sub.started_at:%Y-%m-%d} "
              f"kun={(now - sub.started_at).days}" if sub else "")
        snoozed = bool(cache.get(SNOOZE_KEY.format(user_id=user.id)))
        print(ok(not snoozed), "«Keyinroq» bosilmagan (snooze yo'q)")
        local = local_now(db, owner=user, now=now)
        inside = SURVEY_FIRST_HOUR <= local.hour < SURVEY_LAST_HOUR
        print(ok(inside), f"mahalliy soat {local:%H:%M %Z} "
              f"({SURVEY_FIRST_HOUR}:00-{SURVEY_LAST_HOUR}:00 oralig'ida)")
        morning = local.replace(hour=0, minute=0, second=0, microsecond=0)
        print(ok(not answered_since(db, user=user, since=morning)),
              "bugun boshqa so'rovnomaga javob bermagan")

        print("\nFaol so'rovnomalar va bu foydalanuvchi uchun holati:")
        for s in db.scalars(select(Survey).where(Survey.is_active.is_(True))).all():
            answered = db.scalar(select(SurveyResponse.completed_at).where(
                SurveyResponse.owner_id == user.id,
                SurveyResponse.survey_id == s.id).limit(1))
            print(f"  - {s.id} audience={s.audience} starts={s.starts_at} "
                  f"ends={s.ends_at} ask_after_days={s.ask_after_days} "
                  f"tugatgan={answered}")
        if sub is not None:
            mine = db.scalars(owed(user=user, subscription=sub)).all()
            print(ok(bool(mine)), "unga tegishli so'rovnoma:",
                  [str(s.id) for s in mine])
        due = due_survey(db, user=user, language=user.language)
        print(ok(due is not None), "due_survey natijasi:",
              due.title if due else None,
              f"({len(due.questions)} savol)" if due else "")

        print("\nJurnal (bugungi va oxirgi urinishlar):")
        print(f"  bugungi subject = day:{local.date().isoformat()}")
        for n in db.scalars(select(TelegramNotice).where(
                TelegramNotice.owner_id == user.id,
                TelegramNotice.kind == NoticeKind.SURVEY)
                .order_by(TelegramNotice.created_at.desc()).limit(5)).all():
            print(f"  {n.subject} attempts={n.attempts} sent_at={n.sent_at} "
                  f"message_id={n.message_id}")


if __name__ == "__main__":
    main(sys.argv[1])
