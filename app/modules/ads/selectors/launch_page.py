"""Which page a preparation speaks from."""

from sqlalchemy.orm import Session

from app.modules.ads.models import CampaignLaunch
from app.modules.integrations.models import PageAccount


def launch_page(db: Session, *, launch: CampaignLaunch) -> PageAccount | None:
    """The page this preparation was opened against, whatever the header says."""
    from app.modules.integrations.selectors import active_page

    if launch.page_id is not None:
        return launch.page
    return active_page(db, owner=launch.owner)
