import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from metaads import PROVIDER
from metaads.webhooks import leadgen_notices, verification_challenge, verify_signature
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common import throttle
from app.common.config import settings
from app.common.dates import localtime
from app.common.db import SessionLocal, utcnow
from app.common.xlsx import workbook
from app.modules.accounts.models import User
from app.modules.leads import selectors, services
from app.modules.leads.constants import (
    OUTCOME_STATUS_LABELS,
    POLL_SECONDS,
    UNMARKED,
    UNSIGNED_DELIVERIES_PER_ADDRESS,
    UNSIGNED_WINDOW_SECONDS,
    OutcomeStatus,
)
from app.modules.leads.exceptions import NothingToRecover
from app.modules.leads.models import Lead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["leads"])
webhooks = APIRouter(tags=["webhooks"])
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SIGNATURE_HEADER = "X-Hub-Signature-256"
FORGERY_BUCKET = "webhook:leads:unsigned"
SEARCH_LIMIT = 80
AD_ID_LIMIT = 128


def read_filters(*, verdict: str, ad: str, adset: str, q: str) -> selectors.LeadFilters:
    chosen = verdict.strip()
    if chosen not in {item.value for item in OutcomeStatus} and chosen != UNMARKED:
        chosen = ""
    return selectors.LeadFilters(
        verdict=chosen,
        ad=ad.strip()[:AD_ID_LIMIT],
        adset=adset.strip()[:AD_ID_LIMIT],
        query=q.strip()[:SEARCH_LIMIT],
    )


def lead_out(
    lead: Lead, *, label: Any = None, place: Any = None, is_new: bool = False
) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "full_name": lead.full_name,
        "phone_e164": lead.phone_e164,
        "email": lead.email,
        "city": lead.city,
        "provider": lead.provider,
        "form": lead.form.name if lead.form else "",
        "campaign_external_id": lead.campaign_external_id,
        "adset_external_id": lead.adset_external_id,
        "ad_external_id": lead.ad_external_id,
        "submitted_at": lead.submitted_at,
        "is_test": lead.is_test,
        "is_organic": lead.is_organic,
        "anonymized_at": lead.anonymized_at,
        "verdict": getattr(lead, "verdict", None),
        "note": selectors.lead_note(lead),
        "source": asdict(label)
        if label is not None and hasattr(label, "__dataclass_fields__")
        else None,
        "place": asdict(place)
        if place is not None and hasattr(place, "__dataclass_fields__")
        else None,
        "is_new": is_new,
    }


def _pulse(
    db: Session, user: User, filters: selectors.LeadFilters
) -> tuple[selectors.ShownPage, selectors.LeadPulse]:
    shown = selectors.shown_page(db, owner=user)
    pulse = selectors.lead_pulse(
        db,
        owner=user,
        now=utcnow(),
        ad=filters.ad,
        adset=filters.adset,
        scope=shown.leads,
        deliveries=shown.deliveries,
    )
    return shown, pulse


def _live(
    db: Session,
    user: User,
    *,
    filters: selectors.LeadFilters,
    shown: selectors.ShownPage,
    pulse: selectors.LeadPulse,
    page: int,
    after: str,
) -> dict[str, Any]:
    from app.modules.ads.selectors import ad_labels
    from app.modules.crm.services import crm_open, is_running, lead_places

    listing = selectors.page_of_leads(
        db, owner=user, filters=filters, number=page, scope=shown.leads
    )
    labels = ad_labels(
        db,
        owner=user,
        external_ids=[lead.ad_external_id for lead in listing.rows] + [filters.ad],
    )
    crm_on = crm_open(db, owner=user) and is_running(db, owner=user)
    places = (
        lead_places(db, owner=user, lead_ids=[lead.id for lead in listing.rows])
        if crm_on
        else {}
    )
    since = datetime.fromisoformat(after) if after else None
    adset_name = ""
    if filters.adset:
        adset_name = next(
            (
                label.adset_name
                for label in labels.values()
                if label.adset_external_id == filters.adset and label.adset_name
            ),
            "",
        )
    return {
        "rows": [
            lead_out(
                row,
                label=labels.get(row.ad_external_id),
                place=places.get(str(row.id)),
                is_new=bool(since and row.submitted_at > since),
            )
            for row in listing.rows
        ],
        "crm_on": crm_on,
        "page": {
            "number": listing.number,
            "pages": listing.pages,
            "total": listing.total,
            "first": listing.first,
            "last": listing.last,
        },
        "counts": asdict(pulse.counts),
        "trouble": asdict(pulse.trouble) | {"total": pulse.trouble.total},
        "newest_at": pulse.newest_at,
        "filters": asdict(filters),
        "source": asdict(labels[filters.ad]) if filters.ad in labels else None,
        "adset_name": adset_name,
        "statuses": [
            {"value": k, "label": v} for k, v in OUTCOME_STATUS_LABELS.items()
        ],
        "unmarked": UNMARKED,
        "cursor": pulse.cursor,
        "seconds": POLL_SECONDS,
        "live": listing.number == 1,
    }


@router.get("")
def lead_list(
    db: Db,
    user: CurrentUser,
    verdict: str = "",
    ad: str = "",
    adset: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
    filters = read_filters(verdict=verdict, ad=ad, adset=adset, q=q)
    shown, pulse = _pulse(db, user, filters)
    body = _live(
        db, user, filters=filters, shown=shown, pulse=pulse, page=page, after=""
    )
    body["after"] = pulse.newest_at.isoformat() if pulse.newest_at else ""
    return body


@router.get("/stream", response_model=None)
def lead_stream(
    db: Db,
    user: CurrentUser,
    since: str = "",
    after: str = "",
    verdict: str = "",
    ad: str = "",
    adset: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
) -> dict[str, Any] | Response:
    filters = read_filters(verdict=verdict, ad=ad, adset=adset, q=q)
    shown, pulse = _pulse(db, user, filters)
    if pulse.cursor == since:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return _live(
        db, user, filters=filters, shown=shown, pulse=pulse, page=page, after=after
    )


@router.get("/sources")
def lead_sources(db: Db, user: CurrentUser, days: int | None = None) -> dict[str, Any]:
    from app.modules.metrics.selectors import ALL_TIME, DEFAULT_PERIOD, SOURCE_PERIODS
    from app.modules.metrics.selectors import lead_sources as report

    chosen = days if days in (*SOURCE_PERIODS, ALL_TIME) else DEFAULT_PERIOD
    return {
        "report": report(db, owner=user, days=chosen),
        "days": chosen,
        "periods": list(SOURCE_PERIODS),
        "all_time": ALL_TIME,
    }


@router.get("/export", response_model=None)
def lead_export(
    db: Db,
    user: CurrentUser,
    verdict: str = "",
    ad: str = "",
    adset: str = "",
    q: str = "",
) -> Response:
    from app.modules.ads.selectors import ad_labels, campaign_names

    filters = read_filters(verdict=verdict, ad=ad, adset=adset, q=q)
    leads = selectors.leads_to_export(
        db,
        owner=user,
        filters=filters,
        scope=selectors.shown_page(db, owner=user).leads,
    )
    if not leads:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Yuklab olish uchun lid yo'q."
        )
    labels = ad_labels(
        db, owner=user, external_ids=[lead.ad_external_id for lead in leads]
    )
    sheet = selectors.lead_sheet(
        leads=leads,
        ad_names={key: label.title for key, label in labels.items()},
        campaign_names=campaign_names(
            db, owner=user, external_ids=[lead.campaign_external_id for lead in leads]
        ),
    )
    content = workbook(sheet="Mijozlar", columns=sheet.columns, rows=sheet.rows)
    name = f"mijozlar-{localtime(utcnow()):%Y-%m-%d}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if sheet.truncated:
        headers["X-Truncated"] = str(len(sheet))
    return Response(content, media_type=XLSX_TYPE, headers=headers)


@router.post("/recover")
def recover(db: Db, user: CurrentUser) -> dict[str, Any]:
    try:
        queued = services.recover_leads(db, user=user, now=utcnow())
    except NothingToRecover as exc:
        return {"queued": 0, "detail": exc.message}
    db.commit()
    return {
        "queued": queued,
        "detail": "%(count)s ta ariza qayta so'ralmoqda. Ular ro'yxatda paydo bo'ladi."
        % {"count": queued},
    }


@router.get("/{pk}")
def lead_detail(pk: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    from app.modules.ads.selectors import ad_labels

    lead = selectors.lead_detail(
        db,
        owner=user,
        lead_id=pk,
        scope=selectors.subscribed_lead_scope(db, owner=user),
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    label = ad_labels(db, owner=user, external_ids=[lead.ad_external_id]).get(
        lead.ad_external_id
    )
    return lead_out(lead, label=label) | {
        "answer_rows": [asdict(row) for row in selectors.answer_rows(lead=lead)],
        "statuses": [
            {"value": k, "label": v} for k, v in OUTCOME_STATUS_LABELS.items()
        ],
    }


class VerdictIn(BaseModel):
    status: str = ""
    current: str = ""


@router.post("/{pk}/verdict")
def verdict(
    pk: uuid.UUID, body: VerdictIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    if body.status and body.status == body.current:
        services.clear_outcome(db, user=user, lead_id=str(pk))
    else:
        services.mark_outcome(db, user=user, lead_id=str(pk), status=body.status)
    db.commit()
    lead = selectors.lead_detail(
        db,
        owner=user,
        lead_id=pk,
        scope=selectors.subscribed_lead_scope(db, owner=user),
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return lead_out(lead)


@webhooks.get("/webhooks/meta/leads/", include_in_schema=False)
def leads_handshake(request: Request) -> Response:
    challenge = verification_challenge(
        mode=request.query_params.get("hub.mode", ""),
        token=request.query_params.get("hub.verify_token", ""),
        challenge=request.query_params.get("hub.challenge", ""),
        expected_token=settings.meta_webhook_verify_token,
    )
    if not challenge:
        logger.warning("leads webhook handshake refused")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return PlainTextResponse(challenge)


@webhooks.post("/webhooks/meta/leads/", include_in_schema=False)
async def leads_webhook(request: Request) -> Response:
    from app.modules.leads.tasks import import_lead_task

    body = await request.body()
    signed = verify_signature(
        body=body,
        header=request.headers.get(SIGNATURE_HEADER, ""),
        app_secret=settings.meta_app_secret,
    )
    if not signed and not throttle.hit(
        bucket=FORGERY_BUCKET,
        key=request.client.host if request.client else "",
        limit=UNSIGNED_DELIVERIES_PER_ADDRESS,
        window_seconds=UNSIGNED_WINDOW_SECONDS,
    ):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    try:
        parsed = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        logger.warning("leads webhook: body was not JSON")
        parsed = {}
    payload = parsed if isinstance(parsed, dict) else {}
    db = SessionLocal()
    try:
        events = services.record_delivery(
            db,
            provider=PROVIDER,
            payload=payload,
            notices=leadgen_notices(payload),
            signature_valid=signed,
        )
        db.commit()
        keys = [str(event.id) for event in events if services.accepted(event)]
        count = len(events)
    finally:
        db.close()
    if not signed:
        logger.warning("leads webhook: %s deliveries with a bad signature", count)
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    for key in keys:
        import_lead_task.delay(key)
    return JSONResponse({"received": count})
