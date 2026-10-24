from app.common.config import settings
from app.modules.accounts.exceptions import BadPhone
from core.leads.phone import dial_code, to_e164


def clean_phone(raw: str) -> str:
    region = settings.default_country_code
    digits = "".join(ch for ch in raw if ch.isdigit())
    prefix = dial_code(region).lstrip("+") if region else ""
    if not digits or digits == prefix:
        raise BadPhone("Telefon raqamingizni kiriting.")
    e164 = to_e164(raw=raw.strip(), region=region)
    if not e164:
        raise BadPhone("Raqam noto'g'ri. Mamlakat kodi bilan to'liq yozing.")
    return e164


def normalize_email(email: str) -> str:
    name, _, domain = email.strip().rpartition("@")
    return f"{name}@{domain.lower()}" if name else email.strip()
