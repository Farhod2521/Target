import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from adskit.dto import LeadDTO
from metaads import tracing

from app.common.db import utcnow
from app.common.trace import NoTrace, Trace, enabled, shape
from core.leads import NormalisedLead, columns_of, empty_columns, landings

logger = logging.getLogger(__name__)
TRACE_DIR: Final = "logs/leads"
LeadTrace = Trace


@contextmanager
def tracing_lead(subject: str) -> Iterator[LeadTrace]:
    if not enabled():
        yield NoTrace()
        return
    trace = Trace(subject=str(subject), started=utcnow(), title="Lid")
    try:
        with tracing.watching(trace.meta):
            yield trace
    finally:
        written = trace.flush(TRACE_DIR)
        if written is not None:
            logger.info("lead trace written: %s", written)


def record_delivery(trace: LeadTrace, *, event: Any) -> None:
    trace.step(1, "Webhook xabari")
    trace.inputs("payload", event.payload)
    trace.inputs(
        "qator",
        {
            "id": str(event.id),
            "provider": event.provider,
            "signature_valid": event.signature_valid,
            "page_external_id": event.page_external_id,
            "leadgen_external_id": event.leadgen_external_id,
            "adset_external_id": event.adset_external_id,
            "status": event.status,
            "attempts": event.attempts,
            "created_at": event.created_at,
        },
    )


def record_route(trace: LeadTrace, *, page: Any, adset: str = "") -> None:
    trace.step(2, "Egasi va darvoza")
    if page is None:
        trace.note(
            "Bu sahifa hech kimga ulanmagan - lid ORPHAN bo'lib qoladi va Meta'ga umuman murojaat qilinmaydi."
        )
        return
    trace.decision(
        "sahifa",
        {
            "page_id": str(page.id),
            "page_external_id": page.external_id,
            "page_name": page.name,
            "owner_id": str(page.owner_id),
            "leadgen_subscribed": page.leadgen_subscribed,
            "is_active": page.is_active,
        },
    )
    trace.decision(
        "guruh",
        {
            "adset_external_id": adset,
            "izoh": "xabar adset ko'rsatmadi - organik yoki test lidi bo'lishi mumkin"
            if not adset
            else "lid shu guruhga yoziladi; xarajati bor-yo'qligini hisobotlar hal qiladi",
        },
    )


def record_fetch(trace: LeadTrace, *, lead: LeadDTO) -> None:
    trace.step(3, "Meta'dan o'qildi")
    trace.decision(
        "lid",
        {
            "leadgen_id": lead.ref.id,
            "form_id": lead.form.id if lead.form is not None else "",
            "campaign_external_id": lead.campaign_external_id,
            "adset_external_id": lead.adset_external_id,
            "ad_external_id": lead.ad_external_id,
            "submitted_at": lead.submitted_at,
            "is_organic": lead.is_organic,
            "kalitlar": [str(item.get("name", "")) for item in lead.field_data],
        },
    )


def record_mapping(trace: LeadTrace, *, lead: LeadDTO, fields: NormalisedLead) -> None:
    trace.step(4, "Kalitlar qayerga tushdi")
    mapping_table(trace, field_data=lead.field_data, stored=columns_of(fields))


def mapping_table(trace: LeadTrace, *, field_data: Any, stored: dict[str, str]) -> None:
    rows: list[tuple[Any, ...]] = [
        (
            f"`{item.key}`",
            f"`{' | '.join(shape(value) for value in item.values) or '(bo`sh)'}`",
            _landed(item),
        )
        for item in landings(field_data=field_data, stored=stored)
    ]
    trace.table("MOSLASHTIRISH", ("kalit", "qiymat (shakl)", "qayerga"), rows)
    empty = empty_columns(stored=stored)
    if empty:
        trace.note(
            "Bo'sh qolgan ustunlar: "
            + ", ".join(f"`Lead.{column}`" for column in empty)
            + ". Yuqoridagi jadvalda o'sha ustunga mos kalit bo'lsa - normalizatsiya yiqilgan; bo'lmasa - forma bunday savol so'ramagan."
        )


def _landed(item: Any) -> str:
    if not item.column:
        return "`answers` + `field_data_raw`"
    if item.lost:
        return f"`Lead.{item.column}` - BO'SH QOLDI"
    return f"`Lead.{item.column}`"


def record_row(trace: LeadTrace, *, row: Any) -> None:
    trace.step(5, "DB yozuvi")
    trace.decision(
        "Lead",
        {
            "id": str(row.id),
            "owner_id": str(row.owner_id),
            "provider": row.provider,
            "leadgen_id": row.leadgen_id,
            "full_name": shape(row.full_name),
            "phone_e164": shape(row.phone_e164),
            "email": shape(row.email),
            "city": shape(row.city),
            "answers_kalitlari": sorted(row.answers),
            "field_data_raw_soni": len(row.field_data_raw or []),
            "form_id": str(row.form_id or ""),
            "campaign_external_id": row.campaign_external_id,
            "adset_external_id": row.adset_external_id,
            "ad_external_id": row.ad_external_id,
            "submitted_at": row.submitted_at,
            "received_at": row.received_at,
            "fetched_at": row.fetched_at,
            "is_organic": row.is_organic,
        },
    )
    if row.form_id is None:
        trace.note(
            "`Lead.form` bo'sh: bu forma bizning jadvalimizda yo'q. Lid saqlandi, lekin formaga bog'lanmadi - forma sinxroni ishlamagan yoki forma Ads Manager'da qo'lda yasalgan."
        )


def record_outcome(trace: LeadTrace, *, outcome: str, event: Any = None) -> None:
    trace.step(6, "Natija")
    trace.decision(
        "yakun",
        {
            "outcome": outcome,
            "event_status": getattr(event, "status", ""),
            "event_error_code": getattr(event, "error_code", ""),
            "event_error_message": getattr(event, "error_message", ""),
        },
    )
