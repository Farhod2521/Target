"""The only place that talks to Meta.

Every Graph API call in every project that uses this package goes through
here, so retries, timeouts, rate-limit handling and the API version have
exactly one implementation.

The package knows nothing about this project: tokens arrive as plain
strings, configuration arrives through constructors, and the current time
arrives as an argument. Encryption, storage and refresh are the caller's
problem, which is what makes the package portable.
"""

from typing import Final

from adskit.refs import ProviderName

# The registry key this package answers to. Written once here so that
# `registry.get(PROVIDER)` and `ProviderConnection.provider` cannot drift,
# and so no caller has to type the string.
PROVIDER: Final = ProviderName("meta")

__all__ = ["PROVIDER"]
