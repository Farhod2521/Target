import re
import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, or_, select

from app.modules.sales.constants import SEARCH_DIGITS, SEARCH_LENGTH

_NOT_DIGITS = re.compile(r"\D")
_PUNCTUATION = " +-()@"


def search_term(raw: str) -> str:
    term = raw.strip()[:SEARCH_LENGTH]
    return term if term.strip(_PUNCTUATION) else ""


def _digits(term: str) -> str:
    digits = _NOT_DIGITS.sub("", term)
    return digits if len(digits) >= SEARCH_DIGITS else ""


def account_match(
    term: str, *, id_col: Any, full_name: Any, email: Any, phone: Any
) -> ColumnElement[bool]:
    """An account found by name, email, Facebook name, Telegram handle or number."""
    from app.modules.integrations.models import ProviderConnection
    from app.modules.notifications.models import TelegramChat

    handle = term.lstrip("@")
    matched: list[ColumnElement[bool]] = [
        full_name.icontains(term, autoescape=True),
        email.icontains(term, autoescape=True),
        exists(
            select(ProviderConnection.id).where(
                ProviderConnection.owner_id == id_col,
                ProviderConnection.external_user_name.icontains(term, autoescape=True),
            )
        ),
    ]
    if handle:
        matched.append(
            exists(
                select(TelegramChat.id).where(
                    TelegramChat.owner_id == id_col,
                    TelegramChat.username.icontains(handle, autoescape=True),
                )
            )
        )
    digits = _digits(term)
    if digits:
        matched.append(phone.contains(digits, autoescape=True))
    return or_(*matched)


def request_match(term: str, *, name: Any, phone_e164: Any) -> ColumnElement[bool]:
    matched: list[ColumnElement[bool]] = [name.icontains(term, autoescape=True)]
    digits = _digits(term)
    if digits:
        matched.append(phone_e164.contains(digits, autoescape=True))
    return or_(*matched)


def claim_match(term: str) -> ColumnElement[bool]:
    """A card whose account - or, for a request card, whose request - matches."""
    from app.modules.accounts.models import User
    from app.modules.public.models import ConsultRequest
    from app.modules.sales.models import SalesClaim

    by_account = exists(
        select(User.id).where(
            User.id == SalesClaim.owner_id,
            account_match(
                term,
                id_col=User.id,
                full_name=User.full_name,
                email=User.email,
                phone=User.phone,
            ),
        )
    )
    by_request = and_(
        SalesClaim.owner_id.is_(None),
        exists(
            select(ConsultRequest.id).where(
                ConsultRequest.id == SalesClaim.consult_id,
                request_match(
                    term, name=ConsultRequest.name, phone_e164=ConsultRequest.phone_e164
                ),
            )
        ),
    )
    return or_(by_account, by_request)


def subject_q(model: Any, subject_id: uuid.UUID | str) -> ColumnElement[bool]:
    """The rows of ``model`` about an account, or about a request with no account."""
    subject = uuid.UUID(str(subject_id))
    return or_(
        model.owner_id == subject,
        and_(model.owner_id.is_(None), model.consult_id == subject),
    )
