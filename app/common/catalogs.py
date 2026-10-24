from zoneinfo import available_timezones

_IANA_AREAS = (
    "Africa/",
    "America/",
    "Antarctica/",
    "Arctic/",
    "Asia/",
    "Atlantic/",
    "Australia/",
    "Europe/",
    "Indian/",
    "Pacific/",
)


def timezone_choices() -> list[tuple[str, str]]:
    zones = sorted(
        zone for zone in available_timezones() if zone.startswith(_IANA_AREAS)
    )
    return [("UTC", "UTC"), *((zone, zone.replace("_", " ")) for zone in zones)]


COUNTRIES: tuple[tuple[str, str], ...] = (
    ("AE", "Birlashgan Arab Amirliklari"),
    ("AM", "Armaniston"),
    ("AZ", "Ozarbayjon"),
    ("BY", "Belarus"),
    ("CA", "Kanada"),
    ("CN", "Xitoy"),
    ("DE", "Germaniya"),
    ("ES", "Ispaniya"),
    ("FR", "Fransiya"),
    ("GB", "Buyuk Britaniya"),
    ("GE", "Gruziya"),
    ("IN", "Hindiston"),
    ("IT", "Italiya"),
    ("JP", "Yaponiya"),
    ("KG", "Qirg'iziston"),
    ("KR", "Janubiy Koreya"),
    ("KZ", "Qozog'iston"),
    ("MD", "Moldova"),
    ("PL", "Polsha"),
    ("QA", "Qatar"),
    ("RU", "Rossiya"),
    ("SA", "Saudiya Arabistoni"),
    ("TJ", "Tojikiston"),
    ("TM", "Turkmaniston"),
    ("TR", "Turkiya"),
    ("UA", "Ukraina"),
    ("US", "AQSH"),
    ("UZ", "O'zbekiston"),
)
COUNTRY_CODES = frozenset(code for code, _ in COUNTRIES)
