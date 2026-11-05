"""Django-compatible pbkdf2_sha256 hashes: existing users keep their passwords."""

import base64
import gzip
import hashlib
import hmac
import secrets
from functools import cache
from pathlib import Path

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 1_200_000


def make_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_urlsafe(16)[:22]
    digest = _digest(password, salt, iterations)
    return f"{ALGORITHM}${iterations}${salt}${digest}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    return hmac.compare_digest(_digest(password, salt, int(iterations)), digest)


def needs_rehash(encoded: str) -> bool:
    parts = encoded.split("$")
    return len(parts) != 4 or parts[0] != ALGORITHM or int(parts[1]) < ITERATIONS


def _digest(password: str, salt: str, iterations: int) -> str:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return base64.b64encode(raw).decode("ascii").strip()


MIN_LENGTH = 8
# Django's own list (BSD), the 20 000 the old project refused; ours on top.
COMMON_FILE = Path(__file__).with_name("common-passwords.txt.gz")
OURS = frozenset({"parol123", "parol1234", "qwertyui"})


@cache
def common() -> frozenset[str]:
    with gzip.open(COMMON_FILE, "rt", encoding="utf-8") as lines:
        return frozenset(line.strip() for line in lines) | OURS


class PasswordInvalid(ValueError):
    pass


def validate_password(password: str, *, email: str = "", full_name: str = "") -> None:
    """Django's four validators, with the Uzbek sentences the project wrote for them."""
    if len(password) < MIN_LENGTH:
        raise PasswordInvalid(
            "Parol juda qisqa. Kamida %(min_length)d ta belgi bo'lsin."
            % {"min_length": MIN_LENGTH}
        )
    if password.lower().strip() in common():
        raise PasswordInvalid("Bu parol juda ko'p ishlatiladi. Boshqasini tanlang.")
    if password.isdigit():
        raise PasswordInvalid("Parol faqat raqamlardan iborat bo'lmasin.")
    lowered = password.lower()
    for label, value in (("email", email.split("@")[0]), ("ism", full_name)):
        value = value.lower().strip()
        if len(value) >= 3 and (value in lowered or lowered in value):
            raise PasswordInvalid(
                "Parol «%(verbose_name)s» maydoniga juda o'xshash."
                % {"verbose_name": label}
            )
