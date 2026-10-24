from urllib.parse import quote

from app.common.config import settings
from app.common.routes import reverse
from app.modules.miniapp.constants import NEXT_FIELD


def door_url(*, destination: str) -> str:
    return (
        settings.site_url
        + reverse("miniapp:entry")
        + f"?{NEXT_FIELD}={quote(destination)}"
    )


__all__ = ["door_url"]
