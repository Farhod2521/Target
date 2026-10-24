"""Custom audiences: create, build from a rule or a seed, fill, empty, delete."""

import logging
import uuid
from collections.abc import Sequence

from adskit import AudienceMemberDTO, ExternalRef
from adskit.errors import ProviderError
from metaads.writing import is_dry_run_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.integrations.constants import SourceKind
from app.modules.integrations.exceptions import (
    AudienceNotFillable,
    AudienceRuleRefused,
    AudienceSeedUnusable,
    AudienceSourceUnusable,
    AudienceTermsRequired,
    BusinessCountryMissing,
    LookalikeRefused,
    NobodyToUpload,
    RehearsalCannotErase,
    UnknownAudienceSeed,
    UnknownAudienceSource,
)
from app.modules.integrations.models import AdAccount, CustomAudience
from app.modules.integrations.selectors import (
    SeedOption,
    SourceOption,
    customer_records,
    records_for,
    seed_for,
    source_for,
)
from app.modules.integrations.services.access import (
    account_and_token,
    account_ref,
    audience_ref,
    close_log,
    open_log,
    port_for,
    recording,
    rule_words,
    token_for,
)
from app.modules.integrations.services.sync import (
    request_audience_sync,
    upsert_audience,
)
from core.audiences import (
    AudienceRuleError,
    build_lookalike,
    build_rule,
    hashed_members,
)

logger = logging.getLogger(__name__)
SOURCE_LEVELS = {
    SourceKind.PIXEL: "pixel",
    SourceKind.PAGE: "page",
    SourceKind.LEAD_FORM: "form",
}


def _require_subscription(db: Session, owner: User) -> None:
    from app.modules.billing.services import require_live_subscription

    require_live_subscription(db, owner=owner)


def _finish(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    external_id: str,
    values: dict[str, object],
    log: ActionLog,
    dry_run: bool,
    payload: dict[str, object],
) -> CustomAudience:
    audience = upsert_audience(
        db,
        provider=account.provider,
        external_id=external_id,
        values={"owner_id": owner.id, "ad_account_id": account.id, **values},
    )
    close_log(
        log=log,
        external_id=external_id,
        result={"external_id": external_id, "name": values.get("name", "")},
        dry_run=dry_run,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.AUDIENCE_CREATED,
        aggregate_type="custom_audience",
        aggregate_id=audience.id,
        payload={
            "provider": account.provider,
            "external_id": external_id,
            **payload,
            "dry_run": dry_run,
            "action_log_id": str(log.id),
        },
        occurred_at=utcnow(),
    )
    request_audience_sync(db, account=account)
    db.commit()
    return audience


def create_audience(
    db: Session, *, owner: User, name: str, description: str = ""
) -> CustomAudience:
    _require_subscription(db, owner)
    account, token = account_and_token(db, owner=owner)
    if account.custom_audience_terms_accepted is False:
        raise AudienceTermsRequired
    dry_run = settings.ads_dry_run
    log = open_log(
        db,
        owner=owner,
        action=ActionType.CREATE_AUDIENCE,
        provider=account.provider,
        external_id="",
        requested={"name": name, "description": description},
        previous={},
        dry_run=dry_run,
    )
    with recording(db, log=log):
        result = port_for(provider=account.provider).create_audience(
            account=account_ref(account),
            name=name,
            description=description,
            token=token,
            dry_run=dry_run,
        )
    return _finish(
        db,
        owner=owner,
        account=account,
        external_id=result.ref.id,
        values={
            "name": name,
            "description": description,
            "accepts_members": True,
            "is_ready": False,
            "synced_at": None,
        },
        log=log,
        dry_run=dry_run,
        payload={"name": name},
    )


def create_lookalike_audience(
    db: Session,
    *,
    owner: User,
    name: str,
    origin_external_id: str,
    breadth: str,
    description: str = "",
) -> CustomAudience:
    from app.modules.businesses.selectors import business_for

    _require_subscription(db, owner)
    account, token = account_and_token(db, owner=owner)
    seed = _usable_seed(db, owner=owner, external_id=origin_external_id)
    business = business_for(db, owner)
    if business is None or not business.country_code:
        raise BusinessCountryMissing
    port = port_for(provider=account.provider)
    try:
        spec = build_lookalike(
            origin=audience_ref(
                provider=account.provider, external_id=seed.external_id
            ),
            breadth=breadth,
            country=business.country_code,
        )
    except AudienceRuleError as exc:
        raise LookalikeRefused(rule_words(exc)) from exc
    dry_run = settings.ads_dry_run
    log = open_log(
        db,
        owner=owner,
        action=ActionType.CREATE_AUDIENCE,
        provider=account.provider,
        external_id="",
        requested={
            "name": name,
            "origin": seed.external_id,
            "breadth": breadth,
            "country": spec.country,
        },
        previous={},
        dry_run=dry_run,
    )
    with recording(db, log=log):
        result = port.create_lookalike_audience(
            account=account_ref(account),
            name=name,
            description=description,
            spec=spec,
            token=token,
            dry_run=dry_run,
        )
    return _finish(
        db,
        owner=owner,
        account=account,
        external_id=result.ref.id,
        values={
            "name": name,
            "description": description,
            "accepts_members": False,
            "can_seed": False,
            "is_ready": False,
            "origin_external_id": seed.external_id,
            "origin_label": seed.label,
            "breadth": breadth,
            "ratio_raw": str(result.applied.get("ratio_raw", "")),
            "country_code": spec.country,
            "synced_at": None,
        },
        log=log,
        dry_run=dry_run,
        payload={
            "name": name,
            "origin": seed.external_id,
            "breadth": breadth,
            "country": spec.country,
        },
    )


def _usable_seed(db: Session, *, owner: User, external_id: str) -> SeedOption:
    option = seed_for(db, owner=owner, external_id=external_id)
    if option is None:
        raise UnknownAudienceSeed
    if not option.is_usable:
        raise AudienceSeedUnusable(option.blocked_reason)
    return option


def create_rule_audience(
    db: Session,
    *,
    owner: User,
    name: str,
    kind: str,
    external_id: str,
    action: str,
    retention_days: int,
    description: str = "",
) -> CustomAudience:
    _require_subscription(db, owner)
    account, token = account_and_token(db, owner=owner)
    option = _usable_source(db, owner=owner, account=account, kind=kind, id=external_id)
    port = port_for(provider=account.provider)
    try:
        rule = build_rule(
            kind=kind,  # type: ignore[arg-type]
            action=action,  # type: ignore[arg-type]
            source=ExternalRef(
                provider=account.provider,
                level=SOURCE_LEVELS[SourceKind(kind)],  # type: ignore[arg-type]
                id=external_id,
            ),
            retention_days=retention_days,
            support=port.supported_rules(),
        )
    except AudienceRuleError as exc:
        raise AudienceRuleRefused(rule_words(exc)) from exc
    dry_run = settings.ads_dry_run
    log = open_log(
        db,
        owner=owner,
        action=ActionType.CREATE_AUDIENCE,
        provider=account.provider,
        external_id="",
        requested={
            "name": name,
            "kind": kind,
            "action": action,
            "source": external_id,
            "retention_days": retention_days,
        },
        previous={},
        dry_run=dry_run,
    )
    with recording(db, log=log):
        result = port.create_rule_audience(
            account=account_ref(account),
            name=name,
            description=description,
            rule=rule,
            token=token,
            dry_run=dry_run,
        )
    return _finish(
        db,
        owner=owner,
        account=account,
        external_id=result.ref.id,
        values={
            "name": name,
            "description": description,
            "accepts_members": False,
            "is_ready": False,
            "source_kind": option.kind,
            "source_action": action,
            "source_external_id": option.external_id,
            "source_label": option.label,
            "event_raw": str(result.applied.get("event_raw", "")),
            "excluded_event_raw": str(result.applied.get("excluded_event_raw", "")),
            "retention_days": retention_days,
            "synced_at": None,
        },
        log=log,
        dry_run=dry_run,
        payload={
            "name": name,
            "kind": option.kind,
            "action": action,
            "retention_days": retention_days,
        },
    )


def _usable_source(
    db: Session, *, owner: User, account: AdAccount, kind: str, id: str
) -> SourceOption:
    option = source_for(db, owner=owner, account=account, kind=kind, external_id=id)
    if option is None:
        raise UnknownAudienceSource
    if not option.is_usable:
        raise AudienceSourceUnusable(option.blocked_reason)
    return option


def delete_audience(db: Session, *, owner: User, audience: CustomAudience) -> None:
    _require_subscription(db, owner)
    dry_run = settings.ads_dry_run
    log = open_log(
        db,
        owner=owner,
        action=ActionType.DELETE_AUDIENCE,
        provider=audience.provider,
        external_id=audience.external_id,
        requested={},
        previous={"name": audience.name, "members_sent": audience.members_sent},
        dry_run=dry_run,
    )
    with recording(db, log=log):
        port_for(provider=audience.provider).delete_audience(
            ref=audience_ref(
                provider=audience.provider, external_id=audience.external_id
            ),
            token=token_for(ad_account=audience.ad_account),
            dry_run=dry_run,
        )
    close_log(log=log, external_id=audience.external_id, result={}, dry_run=dry_run)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.AUDIENCE_DELETED,
        aggregate_type="custom_audience",
        aggregate_id=audience.id,
        payload={
            "provider": audience.provider,
            "external_id": audience.external_id,
            "dry_run": dry_run,
            "action_log_id": str(log.id),
        },
        occurred_at=utcnow(),
    )
    db.delete(audience)
    db.commit()


def erase_at_provider(db: Session, *, owner: User) -> int:
    removed = 0
    for audience in list(
        db.scalars(select(CustomAudience).where(CustomAudience.owner_id == owner.id))
    ):
        try:
            delete_audience(db, owner=owner, audience=audience)
        except (ProviderError, DomainError):
            logger.exception(
                "purge: could not remove audience %s", audience.external_id
            )
            continue
        removed += 1
    return removed


def fill_audience(
    db: Session, *, owner: User, audience: CustomAudience
) -> CustomAudience:
    _require_subscription(db, owner)
    if not audience.accepts_members:
        raise AudienceNotFillable
    records, region = customer_records(db, owner=owner)
    members = hashed_members(records=records, region=region)
    if not members:
        raise NobodyToUpload
    dry_run = settings.ads_dry_run
    log = open_log(
        db,
        owner=owner,
        action=ActionType.FILL_AUDIENCE,
        provider=audience.provider,
        external_id=audience.external_id,
        requested={"source": "leads", "rows": len(members)},
        previous={
            "members_sent": audience.members_sent,
            "members_invalid": audience.members_invalid,
        },
        dry_run=dry_run,
    )
    with recording(db, log=log):
        upload = port_for(provider=audience.provider).add_members(
            ref=audience_ref(
                provider=audience.provider, external_id=audience.external_id
            ),
            members=members,
            token=token_for(ad_account=audience.ad_account),
            dry_run=dry_run,
        )
    now = utcnow()
    audience.members_sent = upload.received
    audience.members_invalid = upload.invalid
    audience.last_filled_at = now
    close_log(
        log=log,
        external_id=audience.external_id,
        result={"received": upload.received, "invalid": upload.invalid},
        dry_run=dry_run,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.AUDIENCE_FILLED,
        aggregate_type="custom_audience",
        aggregate_id=audience.id,
        payload={
            "provider": audience.provider,
            "external_id": audience.external_id,
            "received": upload.received,
            "invalid": upload.invalid,
            "dry_run": dry_run,
            "action_log_id": str(log.id),
        },
        occurred_at=now,
    )
    request_audience_sync(db, account=audience.ad_account)
    db.commit()
    if upload.invalid:
        logger.warning(
            "audience %s: provider refused %s of %s rows",
            audience.external_id,
            upload.invalid,
            upload.received,
        )
    return audience


def forget_leads(db: Session, *, owner: User, lead_ids: Sequence[uuid.UUID]) -> int:
    audiences = list(
        db.scalars(
            select(CustomAudience).where(
                CustomAudience.owner_id == owner.id,
                CustomAudience.last_filled_at.is_not(None),
            )
        )
    )
    if not audiences:
        return 0
    records, region = records_for(db, owner=owner, lead_ids=lead_ids)
    members = hashed_members(records=records, region=region)
    if not members:
        return 0
    dry_run = settings.ads_dry_run
    if dry_run and any(not is_dry_run_id(a.external_id) for a in audiences):
        raise RehearsalCannotErase
    for audience in audiences:
        _withdraw(db, owner=owner, audience=audience, members=members, dry_run=dry_run)
    return len(audiences)


def _withdraw(
    db: Session,
    *,
    owner: User,
    audience: CustomAudience,
    members: Sequence[AudienceMemberDTO],
    dry_run: bool,
) -> None:
    log = open_log(
        db,
        owner=owner,
        action=ActionType.FORGET_MEMBERS,
        provider=audience.provider,
        external_id=audience.external_id,
        requested={"rows": len(members)},
        previous={},
        dry_run=dry_run,
    )
    with recording(db, log=log):
        answer = port_for(provider=audience.provider).remove_members(
            ref=audience_ref(
                provider=audience.provider, external_id=audience.external_id
            ),
            members=members,
            token=token_for(ad_account=audience.ad_account),
            dry_run=dry_run,
        )
    close_log(
        log=log,
        external_id=audience.external_id,
        result={"received": answer.received, "invalid": answer.invalid},
        dry_run=dry_run,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.AUDIENCE_MEMBERS_REMOVED,
        aggregate_type="custom_audience",
        aggregate_id=audience.id,
        payload={
            "provider": audience.provider,
            "external_id": audience.external_id,
            "received": answer.received,
            "invalid": answer.invalid,
            "dry_run": dry_run,
            "action_log_id": str(log.id),
        },
        occurred_at=utcnow(),
    )
    db.commit()
