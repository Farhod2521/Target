"""Google Ads answers as typed values."""

from pydantic import BaseModel, ConfigDict

_CONFIG = ConfigDict(frozen=True, extra="ignore")


class CustomerDTO(BaseModel):
    """One Google Ads account a person can reach.

    ``currency`` and ``time_zone`` are set for good when the account is
    created - Google offers no way to change either - so they are read once
    and trusted. ``is_manager`` marks an account that only holds other
    accounts and cannot run a campaign itself. ``is_test`` marks one made
    from a test manager account: it serves nothing and spends nothing.
    """

    model_config = _CONFIG

    id: str
    name: str = ""
    currency: str = ""
    time_zone: str = ""
    is_manager: bool = False
    is_test: bool = False
    status: str = ""

    @property
    def display_id(self) -> str:
        """``1234567890`` as Google's own screens print it: ``123-456-7890``."""
        digits = self.id
        if len(digits) != 10 or not digits.isdigit():
            return digits
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

    @property
    def can_advertise(self) -> bool:
        """Whether a campaign could be created in it today."""
        return self.status == "ENABLED" and not self.is_manager


__all__ = ["CustomerDTO"]
