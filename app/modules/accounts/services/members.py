"""CRM manager logins, the cross-site handoff token, and erasing an account."""

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import storage
from app.common.cache import cache
from app.common.db import Base, utcnow
from app.common.deletion import ProtectedRows, delete_rows
from app.common.passwords import make_password
from app.modules.accounts.constants import (
    HANDOFF_TOKEN_BYTES,
    HANDOFF_TOKEN_KEY,
    HANDOFF_TTL_SECONDS,
    PURGE_ORDER,
)
from app.modules.accounts.exceptions import EmailTaken
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

logger = logging.getLogger(__name__)
HOME = "/app/"
APP_ALIASES = {"content_studio": "montage"}


def email_in_use(db: Session, *, email: str) -> bool:
    return (
        db.scalar(
            select(User.id).where(func.lower(User.email) == email.strip().lower())
        )
        is not None
    )


def create_member_login(
    db: Session, *, owner: User, email: str, full_name: str, password: str
) -> User:
    address = email.strip().lower()
    if email_in_use(db, email=address):
        raise EmailTaken
    user = User(
        email=address,
        password=make_password(password),
        full_name=full_name.strip()[:255],
        phone="",
        language=owner.language,
        crm_owner_id=owner.id,
        date_joined=utcnow(),
    )
    try:
        with db.begin_nested():
            db.add(user)
    except IntegrityError as exc:
        raise EmailTaken from exc
    emit(
        db,
        owner_id=owner.id,
        name=EventName.USER_REGISTERED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"crm_member": True},
    )
    return user


def set_member_password(db: Session, *, user: User, password: str) -> User:
    user.password = make_password(password)
    emit(
        db,
        owner_id=user.crm_owner_id or user.id,
        name=EventName.USER_PASSWORD_CHANGED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={},
    )
    db.flush()
    return user


def rename_member_login(db: Session, *, user: User, full_name: str) -> User:
    user.full_name = full_name.strip()[:255]
    db.flush()
    return user


def remove_member_login(db: Session, *, user: User) -> bool:
    try:
        with db.begin_nested():
            purge_owned_rows(db, user=user)
            delete_rows(db, User.__table__, User.id == user.id)
    except ProtectedRows:
        user.is_active = False
        db.flush()
        return False
    db.expunge(user)
    return True


@dataclass(frozen=True, slots=True)
class Handoff:
    owner_id: str
    destination: str


def safe_destination(asked: str) -> str:
    if (
        not asked
        or asked.startswith("//")
        or asked.startswith("/\\")
        or ".." in asked
        or not asked.startswith(HOME)
    ):
        return HOME
    return asked


def issue_handoff(*, owner: User, destination: str) -> str:
    token = secrets.token_urlsafe(HANDOFF_TOKEN_BYTES)
    cache.set(
        HANDOFF_TOKEN_KEY.format(token=token),
        {"owner": str(owner.id), "next": safe_destination(destination)},
        HANDOFF_TTL_SECONDS,
    )
    return token


def redeem_handoff(*, token: str) -> Handoff | None:
    if not token:
        return None
    key = HANDOFF_TOKEN_KEY.format(token=token)
    payload = cache.get(key)
    cache.delete(key)
    if not isinstance(payload, dict):
        return None
    owner_id = str(payload.get("owner", ""))
    if not owner_id:
        return None
    return Handoff(
        owner_id=owner_id, destination=safe_destination(str(payload.get("next", "")))
    )


def model_by_label() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        parts = cls.__module__.split(".")
        if len(parts) < 3 or parts[1] != "modules":
            continue
        app = APP_ALIASES.get(parts[2], parts[2])
        found[f"{app}.{cls.__name__}"] = cls
    return found


@dataclass(frozen=True, slots=True)
class PurgeReport:
    email: str
    deleted: dict[str, int] = field(default_factory=dict)
    files_removed: int = 0
    audiences_erased: int = 0
    meta_unlinked: bool = False
    receipts_kept: int = 0

    @property
    def rows(self) -> int:
        return sum(self.deleted.values())


def purge_owned_rows(db: Session, *, user: User) -> dict[str, int]:
    from app.modules.integrations.models import PageAccount

    shared = select(PageAccount.external_id).where(PageAccount.owner_id != user.id)
    pages = list(
        db.scalars(
            select(PageAccount.external_id).where(
                PageAccount.owner_id == user.id,
                PageAccount.external_id != "",
                PageAccount.external_id.not_in(shared),
            )
        )
    )
    models = model_by_label()
    deleted: dict[str, int] = {}
    for label in PURGE_ORDER:
        model = models.get(label)
        if model is None or not hasattr(model, "owner_id"):
            continue
        rows = db.execute(delete(model).where(model.owner_id == user.id)).rowcount
        if label == "leads.RawLeadEvent" and pages:
            rows += db.execute(
                delete(model).where(
                    model.owner_id.is_(None), model.page_external_id.in_(pages)
                )
            ).rowcount
        if rows:
            deleted[label] = rows
    return deleted


def purge_preview(db: Session, *, owner: User) -> list[dict[str, Any]]:
    models = model_by_label()
    lines = []
    for label in PURGE_ORDER:
        model = models.get(label)
        if model is None or not hasattr(model, "owner_id"):
            continue
        rows = int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.owner_id == owner.id)
            )
            or 0
        )
        if rows:
            lines.append({"label": label, "name": label.split(".")[1], "rows": rows})
    return lines


def _uploads(db: Session, *, user: User) -> list[str]:
    models = model_by_label()
    files: list[str] = []

    def collect(label: str, *columns: str, where: Any = None) -> None:
        model = models.get(label)
        if model is None:
            return
        condition = model.owner_id == user.id if where is None else where(model)
        for row in db.execute(
            select(*(getattr(model, c) for c in columns)).where(condition)
        ):
            files.extend(value for value in row if value)

    collect("ads.LaunchCreative", "media_upload")
    collect("montage.Montage", "source", "prepared", "output")
    collect("montage.BrandKit", "logo", "logo_trimmed", "logo_on_dark", "logo_on_light")
    collect("referrals.Feedback", "file")
    collect("supportchat.SupportAttachment", "file")
    collect("supportchat.SupportMessage", "attachment")
    return files


def purge_user(db: Session, *, user: User, reason: str = "") -> PurgeReport:
    from app.modules.billing.services import keep_receipts
    from app.modules.integrations.services import (
        erase_at_provider,
        unlink_meta_identity,
    )

    email = user.email
    erased = erase_at_provider(db, owner=user)
    unlinked = unlink_meta_identity(db, user=user)
    uploads = _uploads(db, user=user)
    kept = keep_receipts(db, owner=user)
    deleted = purge_owned_rows(db, user=user)
    for login in list(db.scalars(select(User).where(User.crm_owner_id == user.id))):
        purge_owned_rows(db, user=login)
        delete_rows(db, User.__table__, User.id == login.id)
    delete_rows(db, User.__table__, User.id == user.id)
    db.commit()
    removed = 0
    for name in uploads:
        storage.delete(name)
        removed += 1
    report = PurgeReport(
        email=email,
        deleted=deleted,
        files_removed=removed,
        meta_unlinked=unlinked,
        audiences_erased=erased,
        receipts_kept=kept,
    )
    logger.warning(
        "user.purged",
        extra={"email": email, "rows": report.rows, "files": removed, "reason": reason},
    )
    return report
