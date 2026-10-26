"""One creation attempt, written down in full."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from metaads import tracing
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.trace import NoTrace, Trace, enabled, redact

logger = logging.getLogger(__name__)
TRACE_DIR: Final = "logs/launches"
LaunchTrace = Trace
__all__ = [
    "TRACE_DIR",
    "LaunchTrace",
    "NoTrace",
    "record_outcome",
    "record_preparation",
    "redact",
    "tracing_launch",
]


@contextmanager
def tracing_launch(launch_id: str) -> Iterator[LaunchTrace]:
    """Trace everything inside this block, Graph calls included."""
    if not enabled():
        yield NoTrace()
        return
    trace = Trace(subject=str(launch_id), started=utcnow(), title="Reklama yaratish")
    try:
        with tracing.watching(trace.meta):
            yield trace
    finally:
        written = trace.flush(TRACE_DIR)
        if written is not None:
            logger.info("launch trace written: %s", written)


def record_preparation(
    db: Session,
    trace: LaunchTrace,
    *,
    launch: Any,
    business: Any,
    built: Any,
    account: Any,
    page: Any,
) -> None:
    """Everything that happened before the button, read back off the rows."""
    from app.modules.ads import draft as draft_field
    from app.modules.ads.constants import DraftSection
    from app.modules.ads.selectors.variants import launch_variants
    from app.modules.audit.models import LLMCall

    trace.step(0, "Sehrgar javoblari")
    trace.inputs("launch.answers", launch.answers)
    trace.inputs(
        "tasdiqlangan bo'limlar",
        {
            section: draft_field.chosen(launch.draft, section)
            for section in DraftSection.values
        },
    )
    trace.inputs(
        "reklama matnlari (Meta'ga ketadigan)",
        [
            {
                "position": variant.position,
                "primary_text": variant.primary_text,
                "headline": variant.headline,
                "description": variant.description,
            }
            for variant in launch_variants(db, launch=launch)
        ],
    )
    trace.inputs(
        "biznes",
        {
            "name": business.name,
            "category": business.category,
            "country_code": business.country_code,
            "city": business.city,
            "lat": business.lat,
            "lng": business.lng,
            "timezone": business.timezone,
            "website": business.website,
        },
    )
    trace.inputs(
        "ulanish",
        {
            "ad_account": account.external_id,
            "account_currency": account.currency,
            "min_daily_budget_minor": account.min_daily_budget_minor,
            "timezone": account.timezone,
            "page": page.external_id,
            "page_name": page.name,
            "leadgen_subscribed": page.leadgen_subscribed,
        },
    )
    trace.step(1, "Preset topildi va renderlandi")
    trace.decision(
        "katalog",
        {"preset_key": built.preset_key, "preset_version": built.preset_version},
    )
    trace.decision(
        "provayder so'zlari",
        {
            "objective": built.objective,
            "optimization_goal": built.optimization_goal,
            "billing_event": built.billing_event,
            "destination_type": built.destination_type,
            "sends_to": built.sends_to,
            "call_to_action": built.call_to_action,
            "link_url": built.link_url,
            "special_ad_categories": list(built.special_ad_categories),
            "special_ad_category_countries": list(built.special_ad_category_countries),
            "promoted_object": dict(built.promoted_object),
            "needs_conversion_source": built.needs_conversion_source,
            "needs_lead_form": built.needs_lead_form,
        },
    )
    trace.decision("render natijasi", dict(built.targeting))
    trace.step(2, "Claude chaqiruvlari")
    calls = list(
        db.scalars(
            select(LLMCall)
            .where(
                LLMCall.owner_id == launch.owner_id,
                LLMCall.related_id == str(launch.id),
            )
            .order_by(LLMCall.created_at)
        )
    )
    if not calls:
        others = db.scalar(
            select(func.count(LLMCall.id)).where(LLMCall.owner_id == launch.owner_id)
        )
        trace.note(
            f"Bu launch uchun yozilgan LLM chaqiruvi yo'q. Egada jami {others} ta yozuv bor."
        )
    for call in calls:
        trace.decision(
            f"{call.purpose} · {call.prompt_name} {call.prompt_version}",
            {
                "model": call.model,
                "status": call.status,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cost_minor": call.cost_minor,
                "currency": call.currency,
                "latency_ms": call.latency_ms,
                "related_type": call.related_type,
                "created_at": call.created_at,
            },
        )
    trace.decision("javob (draft, to'liq)", launch.draft)
    trace.step(3, "Struktura validatsiyasi")
    if built.adjustments:
        trace.decision(
            "o'zgartirildi",
            [
                {"field": a.field, "reason": a.reason, "detail": a.detail}
                for a in built.adjustments
            ],
        )
    else:
        trace.note("Hech narsa olib tashlanmadi.")
    trace.step(4, "Qiziqishlar")
    asked = draft_field.chosen(launch.draft, DraftSection.INTERESTS) or []
    blocks = built.targeting.get("flexible_spec") or []
    sent = [
        item
        for block in blocks
        if isinstance(block, dict)
        for item in block.get("interests") or []
    ]
    trace.inputs("so'raldi", asked)
    trace.decision("yuboriladi", sent)
    kept = {str(item.get("id", "")) for item in sent if isinstance(item, dict)}
    trace.decision(
        "tashlandi",
        [
            item
            for item in asked
            if isinstance(item, dict) and str(item.get("external_id", "")) not in kept
        ],
    )
    trace.step(5, "Auditoriya hajmi")
    trace.decision(
        "saqlangan qamrov",
        {
            "lower": launch.audience_lower,
            "upper": launch.audience_upper,
            "estimated_at": launch.estimated_at,
        },
    )
    trace.decision(
        "byudjet",
        {"daily_budget_minor": launch.daily_budget_minor, "currency": launch.currency},
    )


def record_outcome(trace: LaunchTrace, *, launch: Any, result: str) -> None:
    trace.step(13, "Natija")
    trace.decision(
        "yakun",
        {
            "result": result,
            "status": launch.status,
            "step": launch.step,
            "progress": launch.progress,
            "created_refs": launch.created_refs,
            "dropped": launch.dropped,
            "error_code": launch.error_code,
            "error_message": launch.error_message,
        },
    )
