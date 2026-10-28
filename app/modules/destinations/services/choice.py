"""The choice an owner makes before Google: where their leads are written."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.destinations.constants import SheetMode
from app.modules.destinations.exceptions import FormNotFound, OwnFileUnavailable
from app.modules.destinations.selectors import picker_enabled
from app.modules.leads.selectors import owner_form


@dataclass(frozen=True, slots=True)
class SheetChoice:
    """One of the three ways of writing, and for the third, which forms.

    ``only_form_id`` is empty for "every form", and always empty outside
    ``OWN_FILE``.
    """

    mode: SheetMode
    only_form_id: str = ""

    def as_session(self) -> dict[str, str]:
        """Plain strings, kept beside the state while the person is at Google."""
        return {"mode": self.mode, "only_form_id": self.only_form_id}


def choice_from_session(stored: object) -> SheetChoice | None:
    """The choice the start of the handshake kept, or ``None`` for none."""
    if not isinstance(stored, dict):
        return None
    mode = stored.get("mode")
    if mode not in SheetMode.values:
        return None
    return SheetChoice(
        mode=SheetMode(mode), only_form_id=str(stored.get("only_form_id") or "")
    )


def check_choice(db: Session, *, user: User, choice: SheetChoice) -> SheetChoice:
    """The choice as it may be carried out, or the reason it may not.

    Asked before the browser leaves for Google and again when it comes back.
    """
    if choice.mode != SheetMode.OWN_FILE:
        return SheetChoice(mode=choice.mode)
    if not picker_enabled():
        raise OwnFileUnavailable
    if (
        choice.only_form_id
        and owner_form(db, owner=user, form_id=choice.only_form_id) is None
    ):
        raise FormNotFound
    return choice


__all__ = ["SheetChoice", "check_choice", "choice_from_session"]
