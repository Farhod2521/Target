import re

E164 = re.compile(r"^\+[1-9]\d{1,14}$")


def masked(e164: str) -> str:
    if len(e164) < 8:
        return e164
    return f"{e164[:5]}{'•' * (len(e164) - 7)}{e164[-2:]}"


def is_e164(value: str) -> bool:
    return bool(E164.match(value))
