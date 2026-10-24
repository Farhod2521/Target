"""The ad account and the page, as Meta answers them.

``_minor_units`` lives in ``dto_base`` because the campaign rows need it
too.
"""

from typing import Final

from pydantic import Field, field_validator

from metaads.dto_base import MetaDTO, _minor_units

# Meta's key for the agreement a customer list needs. Its sibling
# ``website_custom_audience_tos`` covers audiences built from site traffic
# and is a different signature for a different block.
_CUSTOM_AUDIENCE_TOS: Final = "custom_audience_tos"


class BusinessRefDTO(MetaDTO):
    """The business portfolio an ad account belongs to.

    One field, because one is what it is for: Meta's own console addresses
    are scoped by business, and without the id there is no way to open an
    account's media library for the person who owns it - see
    ``accounts.media_library_url``.
    """

    id: str = ""


class AdAccountDTO(MetaDTO):
    """One ad account, as Meta describes it.

    ``currency`` and ``timezone_name`` are the two fields that make this
    worth storing rather than looking up: every figure Meta reports about
    this account is denominated in the first and cut at midnight in the
    second, and neither has to match what the advertiser told us.
    """

    id: str
    name: str = ""
    # Which business portfolio holds this account, when Meta says.
    #
    # Absent for a personal ad account, and absent for a token that may not
    # read it - two different things with one shape, and both are handled
    # the same way by the only caller: no id, no library link. Read as an
    # object because Meta answers one, and flattened by the property below
    # rather than carried nested, which is the bargain
    # ``PageDTO.instagram_business_account`` already makes.
    business: "BusinessRefDTO | None" = None
    currency: str = ""
    timezone_name: str = Field(default="", alias="timezone_name")
    account_status: int = 0
    # Meta's own number for *why* the account is off, kept as it arrives.
    # Never translated and never shown: the published meanings move, and a
    # wrong "why your account is disabled" is worse than none at all.
    disable_reason: int = 0
    spend_cap: str = ""
    # How much this account has spent against that cap, in minor units and
    # in Meta's usual shape for money.
    #
    # Read only because ``spend_cap`` alone answers half the question. A
    # cap is a ceiling and a ceiling means nothing without a level: an
    # account at eighty percent of its limit is running normally, and one
    # that has reached it has stopped delivering with no error anywhere
    # and no figure on any screen that moves.
    amount_spent: str = ""
    # The smallest daily budget this account will accept, as a string of
    # minor units - Meta's usual shape for money. Zero means it did not
    # say, which is not the same as "no minimum" and must not be read as
    # permission to send anything.
    min_daily_budget: str = ""

    # Which of Meta's agreements have been signed against this account, as
    # ``{name: 1}``. Two of them gate customer-list audiences and they are
    # not the same agreement, which is why both are read rather than one.
    #
    # ``tos_accepted`` is the *account's*: somebody with admin rights on
    # the business signed. ``user_tos_accepted`` is *this token's owner*,
    # and for an ordinary user token that is the one Meta actually enforces
    # - the create call is refused when the person making it has not
    # personally agreed, however thoroughly their colleague did.
    #
    # Empty for a token that may not read them, which is a third state and
    # is treated the way every other unread permission here is: as
    # permission to carry on and let Meta refuse if it means to.
    tos_accepted: dict[str, int] = Field(default_factory=dict)
    user_tos_accepted: dict[str, int] = Field(default_factory=dict)

    @field_validator("spend_cap", "amount_spent", "min_daily_budget", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> object:
        """Money arrives quoted on some edges and bare on others.

        ``spend_cap`` comes back as a string and ``min_daily_budget``, in
        the same object, as a number - Meta's inconsistency, and pydantic
        does not bridge it. Refusing the number would be defensible if the
        cost were not what it is: the whole ad account list fails to parse,
        and a customer who has just approved access on Meta's own screens
        is returned to a blank error page.
        """
        if value is None:
            # Null and absent both mean "Meta did not say", and only one of
            # them is a shape this model has to survive by accident.
            return ""
        if isinstance(value, bool):
            return value
        return str(value) if isinstance(value, int | float) else value

    @property
    def business_id(self) -> str:
        """The portfolio this account is in, or empty for "Meta did not say".

        Empty is the ordinary answer for a personal account and the honest
        one for a token without ``business_management``; the caller turns
        both into the same thing, which is a link it does not offer.
        """
        return self.business.id if self.business else ""

    @property
    def min_daily_budget_minor(self) -> int:
        """The floor as an integer, or zero when Meta did not answer."""
        return _minor_units(self.min_daily_budget) or 0

    @property
    def spend_cap_minor(self) -> int:
        """The account's total ceiling, or zero for no cap at all.

        Zero and "no cap" are the same thing here, unlike on a campaign: an
        account Meta reports a cap of nought for is an account with no cap,
        because a ceiling of nothing is not a state Meta lets an account be
        in.
        """
        return _minor_units(self.spend_cap) or 0

    @property
    def amount_spent_minor(self) -> int:
        """How much has been spent against that ceiling."""
        return _minor_units(self.amount_spent) or 0

    @property
    def cap_reached(self) -> bool:
        """Whether this account has stopped delivering for want of headroom.

        The failure it names has no other signal. Meta does not disable the
        account, does not refuse a write and does not mark the campaigns
        rejected - delivery simply stops, and the only trace is a spend
        figure that does not move. An advertiser looking at that has no way
        to tell it from a campaign nobody is seeing.
        """
        return bool(self.spend_cap_minor) and (
            self.amount_spent_minor >= self.spend_cap_minor
        )

    @property
    def is_usable(self) -> bool:
        """Status 1 is active. Everything else cannot run ads today.

        2 is disabled, 3 unsettled, 7 pending risk review, 9 in grace
        period, 101 closed. Offering a closed account in a picker produces
        a campaign that silently never delivers.
        """
        return self.account_status == 1

    @property
    def custom_audience_terms_accepted(self) -> bool | None:
        """Whether a customer list may be uploaded to this account.

        Three states, like a page's advertising rights and for the same
        reason. ``True`` and ``False`` are Meta answering; ``None`` means it
        was not asked - an account read before this field was requested, or
        a token without the permission to see it - and every caller reads
        that as permission to carry on. Refusing an upload over a question
        nobody put costs more than the refusal saves, and Meta will refuse
        it properly a moment later with its own words attached.

        The user's own signature wins where there is one. Meta enforces
        acceptance per person for an ordinary user token, so an account
        whose business has agreed still refuses somebody who has not.
        """
        for signatures in (self.user_tos_accepted, self.tos_accepted):
            if signatures:
                return bool(signatures.get(_CUSTOM_AUDIENCE_TOS))
        return None


class PageLocationDTO(MetaDTO):
    """Where a page says its business is.

    Read to *offer*, never to target. It is the answer to "is there anything
    better than a blank field here" on the one screen where the owner has
    given us nothing yet, and every part of it can be wrong: a page filled
    in years ago, an office rather than the shop, or nothing at all - only
    pages filed under a physical-business category are ever asked for this.

    ``city_id`` is the field worth having and the reason this is read at
    all. It is Meta's own geography key, the same one ``adgeolocation``
    answers with, which turns "the page says Tashkent" from a word that has
    to be searched for into a key that can be targeted directly.

    ``latitude`` and ``longitude`` arrive as JSON numbers, which is what
    they stay here. Coordinates become ``Decimal`` at the Django boundary,
    where the column that holds them is; converting in a DTO parsed straight
    from a float would only invent precision Meta never sent.
    """

    city: str = ""
    city_id: int = 0
    country: str = ""
    street: str = ""
    zip: str = ""
    latitude: float | None = None
    longitude: float | None = None

    @property
    def has_pin(self) -> bool:
        """Whether a radius could be drawn around this.

        Both or neither. One coordinate is not half a location, it is a
        point on the equator or on the prime meridian, and a radius drawn
        round it delivers to open water.
        """
        return self.latitude is not None and self.longitude is not None


class InstagramAccountDTO(MetaDTO):
    """The Instagram account a page speaks for.

    Two fields and no more, because two is what the page list needs to
    carry: the id goes on an ad creative that opens an Instagram
    conversation, and the handle is how somebody recognises which account
    that is. The rest of the profile - picture, biography, the counts - is
    read on its own call into :class:`~metaads.instagram_rows.InstagramProfileDTO`,
    so that a page list a person is waiting on does not grow by it.
    """

    id: str
    username: str = ""


class PageDTO(MetaDTO):
    """One Facebook page, with the token that reads its leads.

    The page token is not the user token. Lead retrieval and webhook
    subscription both need this one, and it is issued per page - which is
    why it is stored beside the page rather than derived when needed.
    """

    id: str
    name: str = ""
    access_token: str = ""
    tasks: tuple[str, ...] = ()
    # Absent for most pages, and that is the normal case rather than a
    # failure: Meta only asks for an address from pages filed under a
    # physical-business category.
    location: PageLocationDTO | None = None
    # Three states, not two. ``None`` is "Meta did not say", which is what
    # a page read before this field was asked for looks like, and it has to
    # stay tellable from a plain no: refusing a launch on the strength of a
    # field nobody read would cost more than the refusal it prevents.
    leadgen_tos_accepted: bool | None = None
    # The Instagram account this page speaks for, when there is one.
    #
    # Absent for most pages and that is ordinary: an Instagram account has
    # to be connected to a page by hand, and plenty of businesses have one
    # of the two. Read as an object because Meta answers it as one, and
    # flattened below rather than carried nested - the id is the whole of
    # what an ad creative needs, and a caller holding a DTO for one field
    # is a caller writing ``page.instagram_business_account.id`` with a
    # ``None`` in the middle of it.
    instagram_business_account: "InstagramAccountDTO | None" = None
    # The second way a page and an Instagram account get joined, and not a
    # copy of the first. ``instagram_business_account`` is the account
    # linked while it was being converted to a professional one;
    # this is the account connected afterwards in the page's settings.
    # The two can name different accounts, and a page that answers only
    # the first one hides the second from somebody who sees both in Meta.
    connected_instagram_account: "InstagramAccountDTO | None" = None

    @property
    def instagram_accounts(self) -> tuple["InstagramAccountDTO", ...]:
        """Every Instagram account this page speaks for, without repeats.

        The business-conversion one first, because it is the one every
        page read before this field existed already stored as its own.
        """
        found: list[InstagramAccountDTO] = []
        for account in (
            self.instagram_business_account,
            self.connected_instagram_account,
        ):
            if account is not None and all(a.id != account.id for a in found):
                found.append(account)
        return tuple(found)

    @property
    def instagram_id(self) -> str:
        """The account an ad may run Instagram Direct conversations from.

        Empty when the page has none, which is the only answer a screen
        needs: an ad that opens an Instagram thread is refused without it,
        and there is nothing to fall back to - a Facebook page cannot
        receive an Instagram message on somebody's behalf.
        """
        accounts = self.instagram_accounts
        return accounts[0].id if accounts else ""

    @property
    def instagram_username(self) -> str:
        """What the owner calls it. Shown, never sent."""
        accounts = self.instagram_accounts
        return accounts[0].username if accounts else ""

    @property
    def may_manage(self) -> bool:
        """Whether this account can subscribe the page to lead webhooks.

        A page somebody was given ANALYZE on will list here and then fail
        at ``subscribed_apps`` with a permission error, which reads like a
        bug in us rather than a missing role on their side.
        """
        return "MANAGE" in self.tasks

    def __repr__(self) -> str:
        return f"PageDTO(id={self.id!r}, name={self.name!r})"

    __str__ = __repr__
