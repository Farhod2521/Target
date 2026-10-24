"""Django-compatible pbkdf2_sha256 hashes: existing users keep their passwords."""

import base64
import hashlib
import hmac
import secrets

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
COMMON = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "password",
        "password1",
        "qwerty123",
        "qwertyui",
        "11111111",
        "00000000",
        "abcd1234",
        "iloveyou",
        "admin123",
        "parol123",
    }
)


class PasswordInvalid(ValueError):
    pass


def validate_password(password: str, *, email: str = "", full_name: str = "") -> None:
    """Django's four validators, with the Uzbek sentences the project wrote for them."""
    if len(password) < MIN_LENGTH:
        raise PasswordInvalid(
            "Parol juda qisqa. Kamida %(min_length)d ta belgi bo'lsin."
            % {"min_length": MIN_LENGTH}
        )
    if password.lower() in COMMON:
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
