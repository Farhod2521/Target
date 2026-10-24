from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdvertWords:
    message: str
    headline: str
    description: str
    asset_id: str = ""


__all__ = ["AdvertWords"]
