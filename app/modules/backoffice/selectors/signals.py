"""What one customer's leads told Meta, a day at a time, for the CRM tab.

A day is the owner's own: the night send closes it at the owner's clock, so
the office reads it the same way. A day still holding pending or refused rows
the provider would take is what the office's button sends.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from adskit import registry
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors import owner_clocks
from app.modules.leads.constants import SIGNAL_REPORT_HOUR, SignalStatus
from app.modules.leads.models import LeadSignal
from app.modules.leads.selectors.reads import reporting_dataset
from app.modules.leads.services.signals import account_token
from core.leads import is_reportable

SHOWN_DAYS = 30
UNSENT = (SignalStatus.PENDING, SignalStatus.FAILED)
STAGES = ("received", "qualified", "unqualified", "converted")


@dataclass
class SignalDay:
    day: date
    stages: dict[str, dict[str, int]] = field(
        default_factory=lambda: {stage: defaultdict(int) for stage in STAGES}
    )
    sent_at: datetime | None = None
    datasets: set[str] = field(default_factory=set)
    errors: set[str] = field(default_factory=set)
    sendable: int = 0

    def total(self, status: str) -> int:
        return sum(counts[status] for counts in self.stages.values())

    @property
    def state(self) -> str:
        if self.sendable:
            return "unsent"
        if self.total(SignalStatus.SENT):
            unsent = self.total(SignalStatus.EXPIRED) + self.total(SignalStatus.FAILED)
            return "partly" if unsent else "sent"
        if self.total(SignalStatus.EXPIRED) or self.total(SignalStatus.FAILED):
            return "lost"
        return "empty"


@dataclass(frozen=True)
class Blocker:
    account: str
    name: str
    reason: str


@dataclass(frozen=True)
class SignalBook:
    days: list[SignalDay]
    sendable: int
    blockers: list[Blocker]
    last_sent_at: datetime | None
    next_night: datetime
    window_days: int


def window_days() -> int:
    return int(registry.get(PROVIDER).conversions.report_window_days())


def signal_book(db: Session, *, owner: User, now: datetime) -> SignalBook:
    clock = owner_clocks(db, owner_ids=[owner.id])[str(owner.id)]
    local = now.astimezone(clock)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    window = window_days()
    rows = db.execute(
        select(
            LeadSignal.ad_account_id,
            LeadSignal.stage,
            LeadSignal.status,
            LeadSignal.occurred_at,
            LeadSignal.sent_at,
            LeadSignal.dataset_id,
            LeadSignal.last_error,
        ).where(
            LeadSignal.owner_id == owner.id,
            LeadSignal.occurred_at >= today - timedelta(days=SHOWN_DAYS),
            LeadSignal.occurred_at < today,
            LeadSignal.status != SignalStatus.WITHDRAWN,
        )
    ).all()
    days: dict[date, SignalDay] = {}
    waiting: set[uuid.UUID] = set()
    for account_id, stage, status, occurred_at, sent_at, dataset, error in rows:
        key = occurred_at.astimezone(clock).date()
        book = days.setdefault(key, SignalDay(day=key))
        if stage in book.stages:
            book.stages[stage][status] += 1
        if sent_at is not None and (book.sent_at is None or sent_at > book.sent_at):
            book.sent_at = sent_at
        if dataset:
            book.datasets.add(dataset)
        if error and status == SignalStatus.FAILED:
            book.errors.add(error)
        if status in UNSENT and is_reportable(
            occurred_at=occurred_at, now=now, window_days=window
        ):
            book.sendable += 1
            waiting.add(account_id)
    last = max((d.sent_at for d in days.values() if d.sent_at), default=None)
    night = today.replace(hour=SIGNAL_REPORT_HOUR, minute=40)
    if night <= local:
        night += timedelta(days=1)
    return SignalBook(
        days=sorted(days.values(), key=lambda d: d.day, reverse=True),
        sendable=sum(d.sendable for d in days.values()),
        blockers=_blockers(db, owner=owner, account_ids=waiting),
        last_sent_at=last,
        next_night=night,
        window_days=window,
    )


def _blockers(
    db: Session, *, owner: User, account_ids: set[uuid.UUID]
) -> list[Blocker]:
    """Why a waiting account would fail again tonight, read now the way the
    send reads it: a token that will not decrypt is as dead as a revoked one."""
    found = []
    for account in db.scalars(
        select(AdAccount).where(AdAccount.id.in_(account_ids)).order_by(AdAccount.name)
    ):
        if not reporting_dataset(db, owner=owner, ad_account=account):
            reason = "no_pixel"
        elif account_token(account) is None:
            reason = "connection"
        else:
            continue
        found.append(
            Blocker(account=account.external_id, name=account.name, reason=reason)
        )
    return found


def book_out(book: SignalBook) -> dict[str, Any]:
    return {
        "sendable": book.sendable,
        "last_sent_at": book.last_sent_at,
        "next_night": book.next_night,
        "window_days": book.window_days,
        "blockers": [
            {"account": b.account, "name": b.name, "reason": b.reason}
            for b in book.blockers
        ],
        "days": [
            {
                "day": d.day,
                "state": d.state,
                "sendable": d.sendable,
                "sent_at": d.sent_at,
                "datasets": sorted(d.datasets),
                "errors": sorted(d.errors)[:3],
                "stages": {
                    stage: {
                        status: d.stages[stage][status]
                        for status in (
                            SignalStatus.SENT,
                            SignalStatus.PENDING,
                            SignalStatus.FAILED,
                            SignalStatus.EXPIRED,
                        )
                    }
                    for stage in STAGES
                },
            }
            for d in book.days
        ],
    }


__all__ = ["SignalBook", "book_out", "signal_book", "window_days"]
