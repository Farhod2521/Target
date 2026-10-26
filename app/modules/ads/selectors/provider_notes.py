"""What the provider says is wrong, gathered into one list a person reads."""

from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any, cast

from adskit import ExternalRef, Level, ProviderName
from sqlalchemy import ColumnElement, false, select
from sqlalchemy.orm import Session, selectinload

from app.modules.accounts.models import User
from app.modules.ads.constants import NOT_RUNNING
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.recommendations import WEAK_CONFIDENCE
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.ads.troubles import known
from app.modules.integrations.models import AdAccount

ACCOUNT_NOTES = 25
REFUSAL = "refusal"
ISSUE = "issue"
ADVICE = "advice"


@dataclass(frozen=True, slots=True)
class ProviderNote:
    kind: str
    title: str
    body: str
    where: str
    ref: ExternalRef
    code: str = ""
    others: int = 0
    campaign_pk: str = ""


def provider_notes(*, campaign: Campaign) -> tuple[ProviderNote, ...]:
    """Everything the provider has said about this campaign and what is in it."""
    notes: list[ProviderNote] = []
    adsets = list(campaign.adsets)
    ads = [ad for adset in adsets for ad in adset.ads]
    for ad in ads:
        notes.extend(_refusals(ad))
    notes.extend(_issues(campaign))
    for adset in adsets:
        notes.extend(_issues(adset))
    for ad in ads:
        notes.extend(_issues(ad))
    notes.extend(_advice(campaign))
    for adset in adsets:
        notes.extend(_advice(adset))
    return tuple(notes)


def _account(
    db: Session, owner: User, ad_account: AdAccount | None
) -> AdAccount | None:
    from app.modules.integrations.selectors import active_ad_account

    return ad_account if ad_account is not None else active_ad_account(db, owner=owner)


def _running(column: Any) -> ColumnElement[bool]:
    return column.not_in([str(item) for item in NOT_RUNNING])


def account_notes(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None = None,
    limit: int = ACCOUNT_NOTES,
    answered: Collection[str] = (),
    scope: PageScope | None = None,
) -> tuple[ProviderNote, ...]:
    """What the provider says is broken, across the whole cabinet."""
    account = _account(db, owner, ad_account)
    if account is None:
        return ()
    campaigns = db.scalars(
        select(Campaign).where(
            Campaign.owner_id == owner.id,
            Campaign.ad_account_id == account.id,
            ~_beyond(scope, Campaign.external_id, level="campaign"),
            _running(Campaign.delivery),
        )
    ).all()
    adsets = db.scalars(
        select(AdSet)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            AdSet.owner_id == owner.id,
            Campaign.ad_account_id == account.id,
            ~_beyond(scope, AdSet.external_id, level="adset"),
            _running(AdSet.delivery),
        )
    ).all()
    ads = db.scalars(
        select(Ad)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            Ad.owner_id == owner.id,
            Campaign.ad_account_id == account.id,
            ~_beyond(scope, AdSet.external_id, level="adset"),
            _running(Ad.delivery),
        )
        .options(selectinload(Ad.adset))
    ).all()
    notes: list[ProviderNote] = []
    for ad in ads:
        notes.extend(_refusals(ad))
    for campaign in campaigns:
        notes.extend(_issues(campaign))
    for adset in adsets:
        notes.extend(_issues(adset))
    for ad in ads:
        notes.extend(_issues(ad))
    skipped = set(answered)
    return _collapsed([note for note in notes if note.ref.id not in skipped])[:limit]


def account_advice(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None = None,
    limit: int = ACCOUNT_NOTES,
    scope: PageScope | None = None,
) -> tuple[ProviderNote, ...]:
    """What the provider suggests could be better, across the whole cabinet."""
    account = _account(db, owner, ad_account)
    if account is None:
        return ()
    campaigns = db.scalars(
        select(Campaign).where(
            Campaign.owner_id == owner.id,
            Campaign.ad_account_id == account.id,
            ~_beyond(scope, Campaign.external_id, level="campaign"),
            _running(Campaign.delivery),
        )
    ).all()
    adsets = db.scalars(
        select(AdSet)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            AdSet.owner_id == owner.id,
            Campaign.ad_account_id == account.id,
            ~_beyond(scope, AdSet.external_id, level="adset"),
            _running(AdSet.delivery),
        )
    ).all()
    found: list[ProviderNote] = []
    for campaign in campaigns:
        found.extend(_advice(campaign))
    for adset in adsets:
        found.extend(_advice(adset))
    return _collapsed(found)[:limit]


def _collapsed(notes: list[ProviderNote]) -> tuple[ProviderNote, ...]:
    """One line per fault, however many objects are carrying it."""
    first: dict[tuple[str, str, str], ProviderNote] = {}
    extra: dict[tuple[str, str, str], int] = {}
    for note in notes:
        key = (note.kind, str(note.title), str(note.body))
        if key in first:
            extra[key] = extra.get(key, 0) + 1
            continue
        first[key] = note
    return tuple(replace(note, others=extra.get(key, 0)) for key, note in first.items())


def _beyond(scope: PageScope | None, column: Any, *, level: str) -> ColumnElement[bool]:
    if scope is None:
        return false()
    hidden = scope.blocked if level == "campaign" else scope.outside
    return column.in_(list(hidden)) if hidden else false()


def _name(row: Campaign | AdSet | Ad) -> str:
    return str(row.name or row.external_id)


_LEVELS: dict[type, Level] = {Campaign: "campaign", AdSet: "adset", Ad: "ad"}


def _ref(row: Campaign | AdSet | Ad) -> ExternalRef:
    return ExternalRef(
        provider=cast("ProviderName", row.provider),
        level=_LEVELS[type(row)],
        id=str(row.external_id),
    )


def _text(value: Any) -> str:
    return str(value).strip() if value else ""


def _issues(row: Campaign | AdSet | Ad) -> list[ProviderNote]:
    found = []
    for issue in row.issues or ():
        if not isinstance(issue, dict):
            continue
        code = _text(issue.get("code"))
        title = _text(issue.get("summary"))
        body = _text(issue.get("message"))
        said = known(code)
        if said is not None:
            title, body = str(said.headline), str(said.detail)
        if not title and not body:
            continue
        found.append(
            ProviderNote(
                kind=ISSUE,
                title=title or body,
                body=body,
                where=_name(row),
                ref=_ref(row),
                code=code,
                campaign_pk=_campaign_pk(row),
            )
        )
    return found


def _campaign_pk(row: Campaign | AdSet | Ad) -> str:
    if isinstance(row, Campaign):
        return str(row.id)
    if isinstance(row, AdSet):
        return str(row.campaign_id)
    return str(row.adset.campaign_id)


def _advice(row: Campaign | AdSet) -> list[ProviderNote]:
    found = []
    for item in row.recommendations or ():
        if not isinstance(item, dict):
            continue
        if _text(item.get("confidence")).upper() in WEAK_CONFIDENCE:
            continue
        title = _text(item.get("title"))
        body = _text(item.get("message"))
        if not title and not body:
            continue
        found.append(
            ProviderNote(
                kind=ADVICE,
                title=title or body,
                body=body,
                where=_name(row),
                ref=_ref(row),
                code=_text(item.get("code")),
            )
        )
    return found


def _refusals(ad: Ad) -> list[ProviderNote]:
    feedback = ad.review_feedback or {}
    overall = feedback.get("overall") if isinstance(feedback, dict) else None
    if not isinstance(overall, dict):
        return []
    return [
        ProviderNote(
            kind=REFUSAL,
            title=_text(policy),
            body=_text(reason),
            where=_name(ad),
            ref=_ref(ad),
            campaign_pk=_campaign_pk(ad),
        )
        for policy, reason in overall.items()
        if _text(reason)
    ]
