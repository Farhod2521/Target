"""TZ 2.4 «Yangi forma yaratish»: a form for a running lead advert's page.

A launch builds its form as one step of the launch; an advert that already
runs has no launch to hang one on, so this is the same form made on its own:
the name and the phone always, the owner's questions after them, the
business's privacy page and its default thank-you line. Made at once, with
the page's token, so the dialog can choose it the moment it answers.
"""

import logging
from datetime import datetime

from metaads import PROVIDER
from metaads.leadforms import create_lead_form, questions_for
from metaads.specs import LeadFormSpec, LeadQuestionSpec
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.ads.constants import CUSTOM, LEAD_FORM_NAME_MAX, QUESTION_TYPES
from app.modules.ads.exceptions import FormNeedsBusiness, UnknownLeadForm
from app.modules.ads.models import Ad
from app.modules.ads.selectors.lead_form import default_title, privacy_url
from app.modules.ads.services.access import _decrypted
from app.modules.ads.services.swap import form_page
from app.modules.businesses.selectors import business_for_page

logger = logging.getLogger(__name__)

# What every form here asks first: who, and how to reach them.
CONTACTS: tuple[str, ...] = ("full_name", "phone")


def new_form(
    db: Session, *, owner: User, ad: Ad, name: str, questions: list[str], now: datetime
) -> tuple[str, str]:
    """The form made on the advert's page; its id and its name."""
    from app.modules.leads.services import record_lead_form

    page = form_page(db, owner=owner, ad=ad)
    business = business_for_page(db, owner=owner, page=page)
    if page is None:
        raise UnknownLeadForm
    if business is None:
        raise FormNeedsBusiness
    called = (name.strip() or f"{business.name} — {now:%d.%m.%Y %H:%M}")[
        :LEAD_FORM_NAME_MAX
    ]
    spec = LeadFormSpec(
        name=called,
        privacy_policy_url=privacy_url(business),
        questions=(
            *(LeadQuestionSpec(kind=QUESTION_TYPES[kind]) for kind in CONTACTS),
            *(
                LeadQuestionSpec(kind=CUSTOM, label=label.strip())
                for label in questions
                if label.strip()
            ),
        ),
        thank_you_title=default_title(business),
    )
    made = create_lead_form(
        page_id=page.external_id,
        spec=spec,
        page_token=_decrypted(page),
        dry_run=settings.ads_dry_run,
    )
    # Kept in dry-run too: the dialog chooses it next, as it would a real one.
    record_lead_form(
        db,
        owner=owner,
        page=page,
        provider=PROVIDER,
        external_id=made,
        name=called,
        questions=questions_for(spec.questions),
        privacy_policy_url=spec.privacy_policy_url,
    )
    return made, called


__all__ = ["CONTACTS", "new_form"]
