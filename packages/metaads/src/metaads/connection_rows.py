"""The connect flow's mirrors: the token, and the assets hanging off it.

One file per lifecycle, along the same seam as the other row modules.
Import from ``metaads.dto`` - the import surface for every row - or from
here; both are the same class.
"""

from datetime import UTC, datetime

from pydantic import field_validator, model_validator

from metaads.dto_base import MetaDTO


class AccessTokenDTO(MetaDTO):
    """A token and how long it has left.

    ``expires_at`` is computed by the caller, not here: this package has no
    clock, and a package that reads the time cannot be tested without one.
    ``expires_in`` is what Meta actually sends - seconds from now - and the
    Django layer turns it into a date.

    Zero means "does not expire on its own", which is what Meta returns for
    page tokens derived from a long-lived user token. It is not a bug and
    must not be read as "already expired".
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0

    def __repr__(self) -> str:
        """Never print the token. This object ends up in tracebacks."""
        return f"AccessTokenDTO(expires_in={self.expires_in})"

    __str__ = __repr__


class GranularScopeDTO(MetaDTO):
    """One permission, and which of the person's assets it was given for.

    The consent dialog asks for a permission and then for the pages and
    Instagram accounts it covers, and the second question can be answered
    with fewer ticks than the person has. An empty ``target_ids`` is Meta
    saying the grant is not narrowed to particular assets.
    """

    scope: str = ""
    target_ids: tuple[str, ...] = ()


class TokenInfoDTO(MetaDTO):
    """What ``debug_token`` says about a token we already hold.

    The authoritative answer to "is this still good, when does it die,
    and what may it do". Meta will happily accept a token for one call
    and reject it for the next, so this is checked on a schedule rather
    than trusted from the moment of issue.

    ``error_code`` and ``error_subcode`` carry *why* an invalid token is
    invalid, flattened out of the nested object Meta puts them in. They
    are the same pair the refusal of an ordinary call carries, so one
    mapping in the caller can serve both - and without them "expired" and
    "the person removed this app in their settings" arrive here as the
    same ``is_valid: false``, which are two different sentences to show
    somebody and two different things to have happened.
    """

    app_id: str = ""
    user_id: str = ""
    is_valid: bool = False
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None
    error_code: int = 0
    error_subcode: int = 0
    granular_scopes: tuple[GranularScopeDTO, ...] = ()

    def targets(self, scope: str) -> tuple[str, ...]:
        """The asset ids ``scope`` was granted for; empty when not narrowed.

        Empty is also the answer for a scope that was not granted at all,
        which is ``scopes``'s question to settle, not this one's.
        """
        for grant in self.granular_scopes:
            if grant.scope == scope:
                return grant.target_ids
        return ()

    @model_validator(mode="before")
    @classmethod
    def _flatten_error(cls, value: object) -> object:
        """Lift ``error: {code, subcode}`` onto the model.

        Before rather than after, because the nested object is what
        arrives and ``extra="ignore"`` would otherwise drop it silently.
        Anything that is not the shape documented is left alone: a
        payload without an error is the ordinary case, and one whose
        error is not an object is somebody else's bug to survive rather
        than to raise on.
        """
        if not isinstance(value, dict):
            return value
        error = value.get("error")
        if not isinstance(error, dict):
            return value
        return {
            **value,
            "error_code": error.get("code", 0),
            "error_subcode": error.get("subcode", 0),
        }

    @field_validator("expires_at", mode="before")
    @classmethod
    def _from_unix(cls, value: object) -> object:
        """Meta sends a unix timestamp, and sends 0 for "never expires"."""
        if isinstance(value, int):
            return datetime.fromtimestamp(value, UTC) if value else None
        return value


class PersonDTO(MetaDTO):
    """Who a user token belongs to, by the name they go by.

    ``debug_token`` names the person by id only, and an id is not something
    anybody recognises on a screen. The name is what lets a sentence say
    *which* Facebook profile to sign in with - the question that matters
    when the person who connected a cabinet is not the one reading it.

    Both default to empty. A blank name is "not known", not an error worth
    refusing anything over.
    """

    id: str = ""
    name: str = ""


class PixelDTO(MetaDTO):
    """One conversion pixel on the advertiser's own website.

    The tag that lets a campaign optimise towards a purchase instead of
    towards a click. Only useful to a business that has a website, which is
    about half of them.

    ``last_fired_time`` is the field worth reading. A pixel that exists and
    has not seen an event in weeks is the most common reason a conversion
    campaign spends its budget and reports nothing, and it is visible here
    before a single so'm is committed.
    """

    id: str
    name: str = ""
    last_fired_time: datetime | None = None
    is_unavailable: bool = False

    @property
    def is_usable(self) -> bool:
        """Whether Meta will accept it in a promoted_object today."""
        return not self.is_unavailable


class PixelEventRow(MetaDTO):
    """One kind of event a pixel has been seen reporting, and how often.

    ``event`` is the name the snippet on the website fires it under -
    ``Lead``, ``ViewContent``, or whatever the site's developer invented.
    **Not the name an ad set optimises towards**: Meta spells the same
    event differently in the two places, and crossing between them is the
    caller's business and not this package's.

    ``count`` is what Meta returned for the window asked for. It only ever
    orders a list - an event fired twice a day is wired up, one fired once
    may have been somebody testing - so it is never money and never a
    result figure.
    """

    event: str
    count: int = 0


class MediaDTO(MetaDTO):
    """One thing an ad can be made out of: an image, a video, or a post.

    Three Graph edges with three shapes, read as one object because the
    screen that shows them is one grid of thumbnails and the choice between
    them is one choice.

    ``external_id`` is deliberately not called ``id``. An image is referred
    to by its **hash** and everything else by its id - the odd one out in
    Meta's own model, and the single detail most likely to be got wrong by
    code written against a guess.
    """

    kind: str
    external_id: str
    name: str = ""
    thumbnail_url: str = ""
    permalink_url: str = ""
    width: int = 0
    height: int = 0
    created_time: datetime | None = None

    # Whether the provider will let this be advertised at all, and why not.
    #
    # Only Instagram answers it, so ``None`` is the ordinary value and means
    # "not asked" rather than "no" - the same three states the page's
    # ``may_advertise`` uses, read the same way.
    #
    # It is a refusal and not a warning. A reel whose audio is licensed
    # comes back ineligible while its file downloads perfectly well, so a
    # picker reading only ``thumbnail_url`` would offer a video that gets
    # the finished ad rejected.
    #
    # The reason is Meta's own English sentence - "Remove or choose
    # different audio." - kept for the log and for support. A screen says
    # its own words.
    is_eligible: bool | None = None
    ineligible_reason: str = ""
