"""The only place that talks to Meta."""

from typing import Final

from adskit.refs import ProviderName

PROVIDER: Final = ProviderName("meta")

__all__ = ["PROVIDER"]
