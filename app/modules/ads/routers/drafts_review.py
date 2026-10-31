"""The draft's presses past the plan, its editor and the plan's lead form.

Every press answers with the whole draft read again, the editor's with the
editor, as the cabinet's calls expect (``packages/api/src/launch.ts``).
"""

import uuid
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, Db
from app.common import throttle
from app.common.exceptions import DomainError, InputRefused, NotFound
from app.modules.ads.constants import GEO_SEARCHES_PER_MINUTE, MAX_GEO_SEARCH
from app.modules.ads.contract.launch import taps as kept
from app.modules.ads.contract.launch.draft import text_in
from app.modules.ads.contract.launch.edit import edit_from, proposal_patch
from app.modules.ads.contract.launch.forms import (
    chat_reading,
    form_variant,
    panel,
    pick_in,
)
from app.modules.ads.contract.launch.review import REGENERATE, review_status
from app.modules.ads.contract.launch.shapes import (
    ChatQuestionReading,
    DepthIn,
    ExistingForm,
    FormVariant,
    LaunchDraft,
    LeadFormPanel,
    LeadFormSave,
    NameIn,
    PlaceFound,
    ProposalEdit,
)
from app.modules.ads.inputs.media import MediaContinueIn
from app.modules.ads.routers import launch as plan_routes
from app.modules.ads.routers import launch_forms as form_routes
from app.modules.ads.routers import launch_media as media_routes
from app.modules.ads.routers import launch_review as review_routes
from app.modules.ads.routers.drafts import (
    launch_of,
    read_draft,
    renamed,
    tapped_goal,
    text_taps,
)
from app.modules.ads.routers.drafts_google import (
    create_google,
    google_of,
    retry_google,
)
from app.modules.ads.routers.launch_forms import AutoIn
from app.modules.ads.routers.launch_review import CreateIn
from app.modules.ads.selectors.review_proposal import launch_country
from app.modules.ads.selectors.variants import launch_variants
from app.modules.ads.services.locations import place_query, search_places

router = APIRouter(prefix="/launch/drafts", tags=["launch"])

# An upload's tile before the network takes it in: its position names it.
UPLOAD_TILE: Final = "upload-"
GEO_SEARCH_BUCKET: Final = "geo-search"
# A lead form refusal's fields, as the layer names them.
FORM_FIELDS: Final[dict[str, str]] = {
    "lead_form": "formId",
    "website": "ending.website",
    "telegram": "ending.telegram",
    "phone": "ending.phone",
}


def _draft(db: Db, user: CurrentUser, draft_id: uuid.UUID) -> LaunchDraft:
    launch = launch_of(db, user=user, draft_id=draft_id)
    db.refresh(launch)
    return read_draft(db, user=user, launch=launch)


def _restart_poll(draft_id: uuid.UUID) -> None:
    taps = kept.read(draft_id)
    kept.counted(taps, "review", 0)
    kept.write(draft_id, taps)


@router.post("/{draft_id}/build", response_model=LaunchDraft)
def build(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    """«Davom etish» on the pictures: the tiles ticked and the offer typed, then the AI, once.

    A tile the launch already holds is not sent again (it would be added
    twice), nor one the last library read did not list (a deleted file).
    """
    launch = launch_of(db, user=user, draft_id=draft_id)
    taps = kept.read(launch.id)
    held = {
        str(variant.media_asset_id)
        for variant in launch_variants(db, launch=launch)
        if variant.media_asset_id
    }
    known = set(taps["known"]) if taps.get("known") is not None else None
    fresh = [
        tile
        for tile in taps.get("media") or []
        if tile not in held
        and not tile.startswith(UPLOAD_TILE)
        and (known is None or tile in known)
    ]
    media_routes.media_continue(
        launch.id,
        MediaContinueIn(asset_ids=fresh, text=text_in(text_taps(launch, taps))),
        db,
        user,
    )
    _restart_poll(launch.id)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/regenerate/{section}", response_model=LaunchDraft)
def regenerate(
    draft_id: uuid.UUID, section: str, db: Db, user: CurrentUser
) -> LaunchDraft:
    """«Boshqacha qilib ko'r»: the AI writes one section again, once per section."""
    asked = REGENERATE.get(section)
    if asked is None:
        raise DomainError("Bu bo'limni qayta yozib bo'lmaydi.")
    review_routes.regenerate(draft_id, asked, db, user)
    _restart_poll(draft_id)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/name", response_model=LaunchDraft)
def rename(draft_id: uuid.UUID, body: NameIn, db: Db, user: CurrentUser) -> LaunchDraft:
    review_routes.rename(draft_id, review_routes.NameIn(name=body.name), db, user)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/budget/fit", response_model=LaunchDraft)
def fit_budget(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    review_routes.fit_budget(draft_id, db, user)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/ads/trim", response_model=LaunchDraft)
def trim_ads(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    review_routes.trim_ads(draft_id, db, user)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/start", response_model=LaunchDraft)
def start_delivery(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    """«Yoqish»: switch on a campaign that was made but did not start by itself."""
    review_routes.start_ads(draft_id, db, user)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/create", response_model=LaunchDraft)
def create(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    """Create the campaign at the network. This is the press that spends."""
    google = google_of(db, user=user, draft_id=draft_id)
    if google is not None:
        return create_google(db, user=user, launch=google)
    review_routes.create(draft_id, CreateIn(confirmed=False), db, user)
    _restart_poll(draft_id)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/retry", response_model=LaunchDraft)
def retry(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    """«Qayta urinish»: a refused creation is created again; a proposal never written is asked again."""
    google = google_of(db, user=user, draft_id=draft_id)
    if google is not None:
        return retry_google(db, user=user, launch=google)
    state = review_routes.review_poll(draft_id, db, user, tries=0, shown="")["state"]
    if review_status(state) == "failed":
        review_routes.create(draft_id, CreateIn(confirmed=False), db, user)
    else:
        review_routes.retry(draft_id, db, user)
    _restart_poll(draft_id)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
def discard(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> Response:
    review_routes.discard(draft_id, db, user)
    kept.forget(draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{draft_id}/clean-up", status_code=status.HTTP_204_NO_CONTENT)
def clean_up(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> Response:
    """Remove what a failed creation left at the network."""
    review_routes.clean_up(draft_id, db, user)
    kept.forget(draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _review(db: Db, user: CurrentUser, draft_id: uuid.UUID) -> dict[str, Any]:
    return review_routes.review(draft_id, db, user, shown="")


def _editor(answer: dict[str, Any]) -> ProposalEdit:
    try:
        return ProposalEdit.model_validate(edit_from(answer))
    except LookupError as missing:
        raise NotFound("Taklif hali tayyor emas.") from missing


@router.get("/{draft_id}/edit", response_model=ProposalEdit)
def editor(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> ProposalEdit:
    """The proposal editor's tabs."""
    launch_of(db, user=user, draft_id=draft_id)
    return _editor(_review(db, user, draft_id))


@router.put("/{draft_id}/edit", response_model=LaunchDraft)
def save_edit(
    draft_id: uuid.UUID, body: ProposalEdit, db: Db, user: CurrentUser
) -> LaunchDraft:
    """The editor saved: compared with the proposal as it stands, only what changed is sent."""
    launch_of(db, user=user, draft_id=draft_id)
    answer = _review(db, user, draft_id)
    if not answer.get("proposal"):
        raise NotFound("Taklif hali tayyor emas.")
    patch = proposal_patch(body.model_dump(by_alias=False), answer)
    if patch.model_fields_set:
        review_routes.save_edit(draft_id, patch, db, user)
    return _draft(db, user, draft_id)


@router.get("/{draft_id}/locations", response_model=list[PlaceFound])
def locations(
    draft_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    q: str = Query("", max_length=MAX_GEO_SEARCH),
    country: str = Query("", pattern="^([A-Za-z]{2})?$"),
) -> list[PlaceFound]:
    """The place search: anywhere in the world, the given country's rows first."""
    launch = launch_of(db, user=user, draft_id=draft_id)
    query = place_query(q)
    if not query:
        return []
    if not throttle.hit(
        bucket=GEO_SEARCH_BUCKET,
        key=str(user.id),
        limit=GEO_SEARCHES_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    rows = search_places(
        db,
        launch=launch,
        query=query,
        country_code=country or launch_country(db, launch=launch),
    )
    return [
        PlaceFound(
            id=row["key"],
            name=row["name"],
            type=row["kind"],
            context=row["context"],
            country_code=row["country_code"],
        )
        for row in rows
    ]


@router.post("/{draft_id}/edit/forms/refresh", response_model=list[ExistingForm])
def refresh_edit_forms(
    draft_id: uuid.UUID, db: Db, user: CurrentUser
) -> list[ExistingForm]:
    """Ask the network for the page's lead forms again; the list as it stands."""
    review_routes.refresh_forms(draft_id, db, user)
    return _editor(_review(db, user, draft_id)).form.existing


@router.post("/{draft_id}/ads/{position}/remove", response_model=ProposalEdit)
def remove_ad(
    draft_id: uuid.UUID, position: int, db: Db, user: CurrentUser
) -> ProposalEdit:
    """The bin on one advert (1-based, as the screen numbers them)."""
    answer = review_routes.remove_ad(draft_id, max(0, position - 1), db, user)
    return _editor(answer)


def _depth(
    draft_id: uuid.UUID, depth: str, db: Db, user: CurrentUser, *, ask: bool
) -> FormVariant:
    key = f"depth-{'deep' if depth == 'deep' else 'short'}"
    chosen = "deep" if depth == "deep" else "short"
    taps = kept.read(draft_id)
    answer = (
        form_routes.ask_form_depth(draft_id, chosen, db, user)
        if ask
        else form_routes.form_depth(
            draft_id, chosen, db, user, tries=kept.tries(taps, key)
        )
    )
    kept.counted(taps, key, answer.get("tries") or 0)
    kept.write(draft_id, taps)
    return FormVariant.model_validate(form_variant(answer))


@router.get("/{draft_id}/form-depth/{depth}", response_model=FormVariant)
def form_depth(
    draft_id: uuid.UUID, depth: str, db: Db, user: CurrentUser
) -> FormVariant:
    """One depth's questions as they stand; pending until written."""
    return _depth(draft_id, depth, db, user, ask=False)


@router.post("/{draft_id}/form-depth/{depth}", response_model=FormVariant)
def ask_form_depth(
    draft_id: uuid.UUID, depth: str, db: Db, user: CurrentUser
) -> FormVariant:
    """Have one depth's questions written, unless they are or are being."""
    return _depth(draft_id, depth, db, user, ask=True)


# ---- the lead form on the plan ----


@router.get("/{draft_id}/form", response_model=LeadFormPanel)
def lead_form(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LeadFormPanel:
    """The «Lid formasi» layer, for the goal tapped on the plan."""
    launch_of(db, user=user, draft_id=draft_id)
    taps = kept.read(draft_id)
    answer = form_routes.lead_form(
        draft_id,
        db,
        user,
        goal=tapped_goal(taps),
        since=str(taps.get("forms_since") or ""),
        tries=kept.tries(taps, "form"),
    )
    kept.counted(taps, "form", answer.get("forms_tries") or 0)
    if answer.get("forms_since"):
        taps["forms_since"] = answer["forms_since"]
    kept.write(draft_id, taps)
    return LeadFormPanel.model_validate(panel(answer))


@router.post("/{draft_id}/form/refresh", response_model=LeadFormPanel)
def refresh_lead_forms(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LeadFormPanel:
    """Ask the network for the page's forms again; the layer answers itself."""
    launch_of(db, user=user, draft_id=draft_id)
    taps = kept.read(draft_id)
    answer = form_routes.refresh_form_list(draft_id, db, user, goal=tapped_goal(taps))
    if answer.get("error"):
        raise DomainError(answer["error"])
    if answer.get("forms_since"):
        taps["forms_since"] = answer["forms_since"]
    kept.counted(taps, "form", answer.get("forms_tries") or 0)
    kept.write(draft_id, taps)
    return LeadFormPanel.model_validate(panel(answer))


@router.put("/{draft_id}/form", response_model=LaunchDraft)
def save_lead_form(
    draft_id: uuid.UUID, body: LeadFormSave, db: Db, user: CurrentUser
) -> LaunchDraft:
    launch_of(db, user=user, draft_id=draft_id)
    taps = kept.read(draft_id)
    try:
        form_routes.pick_form(
            draft_id,
            pick_in(body.model_dump(by_alias=False), tapped_goal(taps)),
            db,
            user,
        )
    except InputRefused as refusal:
        raise renamed(refusal, FORM_FIELDS) from refusal
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/form/auto", response_model=LaunchDraft)
def auto_lead_form(
    draft_id: uuid.UUID, body: DepthIn, db: Db, user: CurrentUser
) -> LaunchDraft:
    """«Ko'p va arzon» / «Kam, lekin sifatli»: the AI picks the form at that depth."""
    launch_of(db, user=user, draft_id=draft_id)
    goal = tapped_goal(kept.read(draft_id))
    form_routes.form_by_ai(draft_id, AutoIn(goal=goal, depth=body.depth), db, user)
    return _draft(db, user, draft_id)


@router.post("/{draft_id}/form/new", response_model=LaunchDraft)
def new_lead_form(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    """«Yangi forma yaratish»: drop the chosen form, build a new one."""
    form_routes.new_form(draft_id, db, user)
    return _draft(db, user, draft_id)


# ---- chat questions on the plan ----


@router.get("/{draft_id}/chat-questions", response_model=ChatQuestionReading)
def chat_questions(
    draft_id: uuid.UUID, db: Db, user: CurrentUser
) -> ChatQuestionReading:
    taps = kept.read(draft_id)
    answer = plan_routes.chat_questions(
        draft_id, db, user, tries=kept.tries(taps, "chat")
    )
    kept.counted(taps, "chat", answer.get("tries") or 0)
    kept.write(draft_id, taps)
    return ChatQuestionReading.model_validate(chat_reading(answer))


@router.post("/{draft_id}/chat-questions", response_model=ChatQuestionReading)
def ask_chat_questions(
    draft_id: uuid.UUID, db: Db, user: CurrentUser
) -> ChatQuestionReading:
    """Ask the AI for the questions a chat advert offers under its greeting."""
    answer = plan_routes.ask_chat_questions(draft_id, db, user)
    taps = kept.read(draft_id)
    kept.counted(taps, "chat", 0)
    kept.write(draft_id, taps)
    return ChatQuestionReading.model_validate(chat_reading(answer))


__all__ = ["router"]
