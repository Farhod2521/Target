"""Why a montage cannot go on, as the domain says it."""


class MontageError(Exception):
    """Base for the montage's own refusals."""


class NothingToKeepError(MontageError):
    """The plan named no stretch of the source that survives the checks."""
