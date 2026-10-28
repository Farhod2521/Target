"""Which country a visitor is in, judged from the address they came from.

Only used to choose how prices are shown, so a wrong answer costs nothing:
someone behind a VPN sees the other currency. Cloudflare's ``CF-IPCountry``
wins when a request carries it. Otherwise the address is looked up in
DB-IP's free country database (CC BY 4.0), kept on disk at
``settings.geoip_db`` and fetched again once a month by
:func:`refresh_country_db`. With no database yet, every visitor is unknown.
"""

import ipaddress
import logging
import os
import sys
import tempfile
import threading
import zlib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import maxminddb

from app.common.config import settings

logger = logging.getLogger(__name__)

DOWNLOAD = "https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
# Cloudflare's answers for "no idea" and "Tor".
UNKNOWN = frozenset({"", "XX", "T1"})
# A database that cannot place this address is not one to switch to.
PROBE = ("8.8.8.8", "US")

_lock = threading.Lock()
_open: tuple[float, maxminddb.Reader] | None = None


def country_of(*, headers: Mapping[str, str], address: str) -> str:
    """The visitor's ISO country code, upper case; ``""`` when unknown."""
    flagged = {k.lower(): v for k, v in headers.items()}.get("cf-ipcountry", "")
    flagged = flagged.strip().upper()
    if flagged not in UNKNOWN:
        return flagged
    return lookup(address)


def lookup(address: str) -> str:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return ""
    if not ip.is_global:
        return ""
    reader = _reader()
    if reader is None:
        return ""
    return _country(reader, str(ip))


def refresh_country_db(*, now: datetime) -> bool:
    """Fetch the newest monthly database unless the one on disk is as new."""
    path = settings.geoip_db
    built = _built_at(path)
    for month in _months(now):
        if built is not None and built >= month:
            return False
        url = DOWNLOAD.format(month=month.strftime("%Y-%m"))
        try:
            fetched = _download(url, into=path.parent)
        except (httpx.HTTPError, zlib.error) as exc:
            logger.warning(
                "geoip.download_failed", extra={"url": url, "error": str(exc)}
            )
            return False
        if fetched is None:
            continue
        if not _usable(fetched):
            fetched.unlink(missing_ok=True)
            logger.warning("geoip.unusable_download", extra={"url": url})
            return False
        os.replace(fetched, path)
        logger.info("geoip.refreshed", extra={"month": month.strftime("%Y-%m")})
        return True
    return False


def _reader() -> maxminddb.Reader | None:
    """The database on disk, opened again whenever the file is replaced."""
    global _open
    try:
        stamp = settings.geoip_db.stat().st_mtime
    except OSError:
        return None
    with _lock:
        if _open is None or _open[0] != stamp:
            try:
                reader = maxminddb.open_database(
                    str(settings.geoip_db), mode=maxminddb.MODE_MEMORY
                )
            except (OSError, ValueError, maxminddb.InvalidDatabaseError) as exc:
                logger.warning("geoip.unreadable", extra={"error": str(exc)})
                return None
            _open = (stamp, reader)
        return _open[1]


def _country(reader: maxminddb.Reader, address: str) -> str:
    try:
        record = reader.get(address)
    except ValueError:
        return ""
    if not isinstance(record, dict):
        return ""
    country = record.get("country")
    if not isinstance(country, dict):
        return ""
    return str(country.get("iso_code") or "").upper()


def _months(now: datetime) -> Iterator[datetime]:
    """This month, then the last: DB-IP publishes a month's file during it."""
    this = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    yield this
    yield (this - timedelta(days=1)).replace(day=1)


def _built_at(path: Path) -> datetime | None:
    try:
        with maxminddb.open_database(str(path), mode=maxminddb.MODE_MEMORY) as reader:
            return datetime.fromtimestamp(reader.metadata().build_epoch, UTC)
    except (OSError, ValueError, maxminddb.InvalidDatabaseError):
        return None


def _download(url: str, *, into: Path) -> Path | None:
    """The gunzipped file next to its final place, or None when not published."""
    into.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        handle, name = tempfile.mkstemp(dir=into, suffix=".part")
        inflate = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in response.iter_bytes():
                    out.write(inflate.decompress(chunk))
                out.write(inflate.flush())
        except (zlib.error, httpx.HTTPError):
            Path(name).unlink(missing_ok=True)
            raise
    return Path(name)


def _usable(path: Path) -> bool:
    try:
        with maxminddb.open_database(str(path), mode=maxminddb.MODE_MEMORY) as reader:
            return _country(reader, PROBE[0]) == PROBE[1]
    except (OSError, ValueError, maxminddb.InvalidDatabaseError):
        return False


def main(argv: list[str]) -> int:
    if refresh_country_db(now=datetime.now(UTC)):
        print(f"Yangilandi: {settings.geoip_db}")
    else:
        print(f"Yangilash shart emas yoki bo'lmadi: {settings.geoip_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
