import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.common.config import settings
from app.common.exceptions import ConfigurationError, DecryptionFailed

FINGERPRINT_LENGTH = 32


def _cipher() -> MultiFernet:
    if not settings.encryption_key:
        raise ConfigurationError("ENCRYPTION_KEY is missing")
    keys = [settings.encryption_key, *settings.encryption_key_fallbacks]
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt(value: str) -> bytes:
    return _cipher().encrypt(value.encode())


def decrypt(value: bytes) -> str:
    try:
        return _cipher().decrypt(bytes(value)).decode()
    except InvalidToken as exc:
        raise DecryptionFailed("stored value did not decrypt") from exc


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:FINGERPRINT_LENGTH]
