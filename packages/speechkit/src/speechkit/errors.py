"""What can go wrong, without the provider's own codes."""


class SpeechError(Exception):
    """Base for everything this package raises."""


class SpeechTemporaryError(SpeechError):
    """Busy, slow or down. Another try may work."""


class SpeechRejected(SpeechError):
    """The provider refused the request. Trying again will not help."""


class SpeechAuthError(SpeechRejected):
    """The key was missing or refused."""
