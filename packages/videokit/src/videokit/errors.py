"""What can go wrong, in words that do not name the provider's codes."""


class VideoError(Exception):
    """Base for everything this package raises."""


class VideoTemporaryError(VideoError):
    """The provider was busy, slow or down. Another try may work."""


class VideoRejected(VideoError):
    """The provider read the request and refused it. Trying again will not help."""


class VideoAuthError(VideoRejected):
    """The key was missing or refused. A setup problem, not a user's."""


class MediaToolError(VideoError):
    """FFmpeg or FFprobe could not run, or could not read the file."""
