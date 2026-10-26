"""Provider-independent failures.

An adapter's job is to land every provider failure on one of these. Nothing
above this package should ever have to know that Meta calls an expired token
"code 190", because the day Google is added that knowledge is wrong.

The split that matters is :attr:`ProviderError.retryable`. Retrying a
permission error does not fix the permission, it just burns the rate-limit
budget that the retryable failures need.
"""

from adskit.dto import RetiredOptionDTO


class AdsError(Exception):
    """Root of everything this package raises."""


class ProviderNotRegistered(AdsError):
    """``registry.get`` was asked for a provider nobody registered.

    Almost always a startup-order bug: the lookup ran before the app config
    that registers the bundle.
    """


class PortNotAvailable(AdsError):
    """A provider is registered, but cannot do this yet.

    Raised by the placeholder implementations a bundle is filled with while
    a provider is being built out. Failing at the call site names the port
    and the provider; the alternative - leaving the field empty - fails as
    an ``AttributeError`` on None somewhere that names neither.
    """

    def __init__(self, *, provider: str, port: str) -> None:
        super().__init__(f"{provider} cannot do {port} yet")
        self.provider = provider
        self.port = port


class ProviderError(AdsError):
    """A call to a provider failed.

    ``code`` is the provider's own identifier, kept only so it can be logged
    and stored. Branching on it above this package is what the whole error
    hierarchy exists to prevent.
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        # What the provider wrote *for the advertiser*, kept apart from
        # ``message``, which it writes for whoever called the API. The two
        # are different texts with different audiences: "Invalid parameter"
        # names no parameter and helps nobody, while the pair beside it says
        # what was refused and, often, what to do about it.
        #
        # Empty is normal. Most refusals carry only the developer string,
        # and a screen that promises an explanation it does not have is
        # worse than one that stays with its own sentence.
        self.user_title = user_title
        self.user_message = user_message


class AuthFailed(ProviderError):
    """The token is expired, revoked, or was never valid.

    Not retryable: the same token will fail the same way. Someone has to
    reconnect the account.
    """


class PermissionDenied(ProviderError):
    """The token is valid but lacks the scope, or the app lacks the review.

    Not retryable for the same reason as :class:`AuthFailed`, and retrying
    permission failures is a documented way to get an app flagged.
    """


class InvalidRequest(ProviderError):
    """The provider rejected the payload.

    This is our bug, not theirs. Retrying sends the same wrong payload
    again, so it is raised to be seen rather than swallowed.
    """


class NotFound(ProviderError):
    """The object is gone, or was never visible to this token."""


class TermsNotAccepted(ProviderError):
    """The provider is waiting for the advertiser to agree to something.

    Its own class rather than one more ``InvalidRequest`` because it is the
    only refusal in this family the *owner* can clear, and they can only
    clear it if they are told what it is. Lead forms are where it bites:
    every provider that hosts a form on the advertiser's behalf makes them
    accept terms about the data first, once per page, and until they do the
    ad set is refused with a message about a parameter.

    Not retryable, and not a bug on our side. Nothing changes until a
    person opens the provider's own page and clicks agree.
    """


class AccountActionRequired(ProviderError):
    """The advertising account is held until its owner does something.

    A sibling of :class:`TermsNotAccepted` and separate from it for the
    same reason: the token is valid, the payload is correct, and nothing
    the caller sends will be accepted until a person opens the provider's
    own console and completes a step there - a security check, a verified
    identity, a billing detail.

    Its own class because a held account answers a create call with a
    refusal that reads like a rejected payload. Without this, an advertiser
    is told to rewrite their ad three times while the account sits waiting
    for a confirmation button nobody has mentioned.
    """


class BudgetTooLow(ProviderError):
    """The daily budget is under the floor this provider enforces.

    Its own class for the same reason as the two above: it is a refusal the
    owner clears themselves, in about ten seconds, on a screen this product
    already has. Without it the refusal arrives as a rejected payload and
    the advertiser is told to change their text or their picture - advice
    that cannot work and that they will follow twice before giving up.

    The floor is not one number. It differs per currency, per account, and
    per what the ad set optimises toward - roughly double for the rare
    events this catalogue mostly buys - which is why the provider is
    allowed to be the one that says so.
    """


class PaymentMethodMissing(ProviderError):
    """The ad account has no payment method the provider will charge.

    Its own class because the fix is on the provider's billing page, which
    nothing in this product can reach - and as a rejected payload the
    advertiser would be sent to change their text or their picture.
    """


class LeadFormPrivacyMissing(ProviderError):
    """The lead form on the ad links to no privacy policy.

    Its own class because the fix is a different form, not different text
    or a different picture - which is what a rejected payload tells the
    advertiser to change.
    """


class BidStrategyRefused(ProviderError):
    """The provider will not buy this goal with the bid strategy sent.

    A price cap on a goal the provider only buys with its automatic
    bidding. Its own class for the reason :class:`BudgetTooLow` is: as a
    rejected payload it reaches the screen as "change your text or your
    picture", and the fix is the price cap.

    Not retryable. The same pair is refused the same way.
    """


class LocationNotRecognized(ProviderError):
    """The audience names a place the provider does not recognise.

    A point in open sea, a coordinate pair that is not a coordinate pair, a
    place key the catalogue no longer has. Its own class because the fix is
    the audience's geography and nothing else: as a rejected payload it
    reaches the screen as "change your text or your picture", which the
    advertiser follows and which cannot work.

    Not retryable. The same geography is refused the same way until
    somebody changes it.
    """


class LocationsOverlap(ProviderError):
    """Two of the audience's places cover the same ground.

    A city named beside the region it lies in, or a place named twice. Each
    place is valid on its own, which is why this is not
    :class:`LocationNotRecognized`: the fix is to drop one of them, and a
    sentence about an unknown place sends somebody looking for a misspelling
    that is not there.

    Not retryable. The same pair is refused the same way.
    """


class MediaTooLarge(ProviderError):
    """The provider would not take the file in the request it was sent in.

    Refused on size before the file was read, so nothing about the picture
    itself is known to be wrong - a smaller or shorter file of the same kind
    goes through. Its own class for the reason :class:`LocationNotRecognized`
    is: as a rejected payload it would send somebody to rewrite the words of
    an ad whose only problem is the weight of one file.

    Not retryable. The same bytes are refused the same way.
    """


class TargetingOptionRetired(ProviderError):
    """The audience names a catalogue entry the provider has withdrawn.

    Its own class for the reason :class:`BudgetTooLow` is: without it the
    refusal arrives as a rejected payload and the advertiser is told to
    change their text or their picture - advice that cannot work, and that
    they will follow twice before deciding the product is broken. Here it
    is worse than in that case, because nothing they can type into the ad
    will ever clear it: the dead word is in the audience.

    **It carries the repair.** Providers answer this refusal with the
    mapping from the withdrawn entry to the one that replaced it, which is
    the only place that mapping exists - the catalogue search goes on
    returning the dead entry, so no amount of re-confirming finds this out.
    Dropping the pairs and keeping the sentence would leave the one failure
    in this family that a person cannot fix by hand either, because they
    have no way to learn which id was refused.

    Not retryable. The same audience is refused the same way for ever.
    """

    def __init__(
        self,
        message: str,
        *,
        retired: tuple[RetiredOptionDTO, ...] = (),
        code: str = "",
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(
            message, code=code, user_title=user_title, user_message=user_message
        )
        self.retired = retired


class RateLimited(ProviderError):
    """The call budget is spent or close to it.

    ``retry_after_seconds`` is the provider's estimate of when access
    returns. It is a floor, not a promise.
    """

    retryable = True

    def __init__(
        self, message: str, *, code: str = "", retry_after_seconds: int = 0
    ) -> None:
        super().__init__(message, code=code)
        self.retry_after_seconds = retry_after_seconds


class TemporaryFailure(ProviderError):
    """A transient fault: a 5xx, a timeout, a connection reset.

    The only family where a backoff retry is the correct response.
    """

    retryable = True


class ResultTruncated(ProviderError):
    """The provider had more rows than the read was allowed to fetch.

    **Nothing failed.** Every request was answered; the answer was simply
    larger than one read's page ceiling. It is an error here because of
    what the alternative looks like downstream: a short list is the same
    object as a complete one, so a caller handed a truncated answer stores
    it as fact and every figure built on it is quietly low.

    ``retryable`` is true, and it means something specific: the same
    request will truncate again, but a *narrower* one will not. The caller
    that knows how to narrow - a date range, a level - is the one that
    should catch this; everything else should treat it as a step that did
    not happen.

    ``rows_read`` says how much came back before the ceiling, for a log
    line that can answer "how close was it".
    """

    retryable = True

    def __init__(
        self, message: str, *, code: str = "", rows_read: int = 0, pages: int = 0
    ) -> None:
        super().__init__(message, code=code)
        self.rows_read = rows_read
        self.pages = pages
