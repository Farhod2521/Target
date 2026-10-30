"""The seven capabilities a provider must offer.

Each one was designed by asking "how would Google do this?" first. Ports
whose answer was unclear - creative assembly, budget pacing - are
deliberately absent. Until they exist, screens that need them use the
provider package directly, which is an honest escape hatch rather than a
leaky abstraction.

Structure is not abstracted, intent is. There is no universal AdSet model
here, because no two platforms agree on what one is.

Every method takes its token as an argument. Ports hold no credentials, no
connection and no clock: an implementation is a stateless translator.
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from adskit.dto import (
    AccountStateDTO,
    ActionResult,
    AdDTO,
    AdPreviewDTO,
    AdSetDTO,
    AudienceDTO,
    AudienceMemberDTO,
    AudienceRuleDTO,
    CampaignDTO,
    ConversionReceiptDTO,
    GrantDTO,
    InterestDTO,
    LeadDTO,
    LeadEventDTO,
    LeadFormDTO,
    LocationDTO,
    LookalikeSpecDTO,
    MemberUploadDTO,
    MetricsDTO,
    ObjectsDTO,
    PeopleCountDTO,
    ReachDTO,
    RuleSupportDTO,
    SegmentMetricsDTO,
    StatusDTO,
)
from adskit.refs import BreakdownKind, ExternalRef, Level, MinorUnits, TraitKind


@runtime_checkable
class CampaignControlPort(Protocol):
    """Read the shape of an account, and start or stop what is in it."""

    def list_campaigns(
        self, *, account: ExternalRef, token: str
    ) -> list[CampaignDTO]: ...

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        """Every ad set in the account, not every ad set in one campaign.

        Account-level because that is one paged read instead of one read
        per campaign, and the call budget is the scarce resource here: an
        advertiser with forty campaigns would otherwise spend forty calls
        to answer a question the provider will answer in one.
        """
        ...

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        """Every ad in the account, for the same reason.

        Each ad carries its own creative when the provider sends one, and
        every provider does: the content is part of the ad's answer, not a
        second object to go and fetch. So there is no ``list_creatives``
        here - a port method for it would legitimise a call that buys
        nothing except the creatives no ad is using.

        ``AdDTO.creative`` is ``None`` when the provider answered without
        one, which means a read that did not ask - never an ad with no
        content.
        """
        ...

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        """These campaigns, ad groups and ads, and nothing else in the account.

        The narrow read beside the three lists above, for a caller that
        knows exactly which objects it wants - the ones a launch has just
        made. The lists answer for the whole account, so one object
        anywhere in it the provider cannot describe fails all of them; a
        read by ref is answered for the refs alone.

        ``account`` is passed because a provider may only be asked in an
        account's name. Refs of a level this port does not hold are
        ignored, and a ref the provider no longer knows is left out of the
        answer rather than raised: gone is an ordinary answer here, the same
        one the lists give by omission.
        """
        ...

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO: ...

    def read_account(self, *, account: ExternalRef, token: str) -> AccountStateDTO:
        """Whether the account can pay for its advertising right now.

        One call per account, on every sync of it. A provider that cannot
        say raises :class:`~adskit.errors.PortNotAvailable`; the caller
        keeps what it last knew.
        """
        ...

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        """How many ad groups one campaign holds that have not been removed.

        Deleted and archived groups are not counted: they take no room in
        the campaign and deliver nothing. Everything else is, whoever made
        it - a group added by hand counts the same as one made here.

        One campaign rather than the account, because the account read is
        paged and a large account runs out of pages long before it runs out
        of groups. Every platform can answer this about one campaign.
        """
        ...

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        """Where this ad can be seen the way its audience will see it.

        **Here rather than on a port of its own, for the reason
        ``list_ads`` gives above.** The content of an ad is already this
        port's business - every platform answers with it as part of the ad
        - and "what does it look like" is the same question asked about the
        same object, with the same ref and the same token. A port with one
        method would also have to be supplied by every provider bundle,
        which would make the next provider write a refusing stub for one
        button.

        ``ref`` names the ad or the creative behind it, whichever the
        caller holds; providers answer for both. ``ad_format`` is the
        provider's own name for a surface - see :class:`~adskit.dto.
        AdPreviewDTO`. Not every combination of creative and surface is
        supported anywhere, and an unsupported one is refused rather than
        answered empty, so a caller asking for a shape this ad cannot take
        gets a ``ProviderError`` and not a blank frame.

        No ``dry_run``. This changes nothing on the account.
        """
        ...

    def set_status(
        self,
        *,
        ref: ExternalRef,
        status: str,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Pause or resume. ``dry_run`` defaults to True on every write.

        ``status`` is one of :data:`adskit.refs.Delivery`'s two switchable
        words - ``"active"`` or ``"paused"`` - and not the provider's own.
        The adapter translates; a caller sending ``"ACTIVE"`` has written
        Meta's vocabulary into a service, which is the thing this package
        exists to prevent. Anything else is refused rather than guessed at:
        ``"pending"`` and ``"rejected"`` describe what a provider decided
        and are not states an advertiser can ask for.
        """
        ...

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace the daily budget on whichever object holds it.

        A port rather than a provider-specific call, because the question
        is the same everywhere: every platform lets an advertiser say how
        much a day, and every one of them enforces a floor under it.

        ``ref`` carries the level for a reason that is not about providers
        at all. The budget sits on the campaign when its owner put it
        there and one level down otherwise, and that is a choice made per
        account rather than per platform. The caller has just read the
        object and is the only one that knows; a port guessing would be a
        port silently editing the wrong row half the time.

        ``daily_budget_minor`` is an integer count of the account
        currency's smallest unit, like every other amount that crosses
        this boundary. The account's currency is not passed with it: the
        provider already denominates the account and would ignore a second
        opinion.
        """
        ...

    def set_end_time(
        self,
        *,
        ref: ExternalRef,
        end_time: str,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Say when this object should stop delivering.

        A port method rather than a Meta call, because "until when" is a
        question every platform answers: Google has a campaign end date and
        Meta an ad set end time, and an advertiser saying "run this until
        the end of the month" is not asking about either of them.

        ``end_time`` is ISO-8601 text with an offset rather than a
        ``datetime``. Rendering one needs a timezone, the packages have no
        clock and no locale, and a caller that has already decided what
        "the end of the month" means in the business's own timezone is the
        only party that can say. See ``AdSetSpec.start_time``, which is a
        string for the same reason.

        **Setting only.** Removing an end date is a different call on at
        least one provider and is not part of this port: an absent field
        means "no change" to Meta, so there is no value here that could
        express it, and a method that silently did nothing would be worse
        than one that does not exist.
        """
        ...

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The most this object may spend in total, ever.

        A ceiling and not a rate, which is why it is not :meth:`set_budget`
        with a different argument: the daily budget says how fast the money
        goes out and this says when it stops going out at all. Both exist
        on every large platform and an advertiser can want either without
        the other.

        ``spend_cap_minor`` is an integer count of the account currency's
        smallest unit, like every other amount crossing this boundary.

        Providers enforce a minimum and refuse a cap below what has already
        been spent. Neither is checked here for the reason :meth:`set_budget`
        gives about its own floor: the figures are the provider's, they
        change, and a copy on this side is a copy to keep in step.
        """
        ...

    def delete(
        self,
        *,
        ref: ExternalRef,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Take one object off the account for good.

        A port method rather than a Meta call, because every platform has
        one: Meta deletes a campaign together with its ad sets and ads,
        Google marks a campaign ``REMOVED`` and stops everything under it.
        Neither can be undone, which is why nothing above this offers an
        undo for it and why the domain photographs the object before asking.

        ``ref`` names the object at its own level. Removing a campaign
        removes what is inside it on every platform this was designed
        against, so a caller does not walk down and delete the children
        first.
        """
        ...


@runtime_checkable
class MetricsPort(Protocol):
    """Daily performance figures."""

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        """Inclusive date range, in the ad account's timezone.

        The caller passes the range explicitly - the port has no clock and
        cannot decide what "yesterday" means.
        """
        ...

    def fetch_breakdown(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        kind: BreakdownKind,
        token: str,
    ) -> list[SegmentMetricsDTO]:
        """The same range, cut into segments instead of summed.

        A second call and not an option on the first, because that is what
        the providers do: asked for a breakdown, they answer the slices and
        stop answering the total. Every platform draws the line in the same
        place - Meta has ``breakdowns``, Google has segments - which is why
        this is a port method rather than something a screen reaches into
        the provider package for.

        ``kind`` is the domain's word for the cut and is refused rather than
        guessed at when a provider has no such view. ``level`` says which
        rung is being cut up; a provider that will not cut at that rung says
        so rather than answering a different one.

        The result is **one row per object per day per slice**, which is one
        to two orders of magnitude more rows than the summary call over the
        same range. That is the whole cost of this method, and it is why the
        caller decides how far back to ask rather than always asking for
        everything it is allowed to.
        """
        ...

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        """How many people each object reached, once per range.

        **Not derivable from** :meth:`fetch_daily`. A person who saw the ad
        on three days is three people in three daily rows and one person
        over the range, and only the provider can tell them apart - so the
        range has to be asked about as a range.

        Several ranges in one call because every screen offers several and
        the provider answers them together; one row per object per range
        comes back. An object that reached nobody in a range has no row for
        it. A provider that cannot answer the question returns nothing
        rather than refusing, and the caller falls back to what it has.
        """
        ...


@runtime_checkable
class LeadSourcePort(Protocol):
    """Where leads come from, and how we ask to be told about them."""

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        """Every form on one page, whatever state each is in.

        Per page rather than per account, and that is not a Meta detail: a
        lead form belongs to the thing that publishes it - a page, a
        business profile - on every platform that hosts one, and the
        credential that reads it is that thing's.

        The ones that stopped collecting come back too, and are wanted. A
        form that is archived still holds the leads it collected, and its
        row is what makes them readable; a caller that dropped it would be
        deleting the meaning of data it keeps.
        """
        ...

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO: ...

    def list_leads(
        self,
        *,
        form: ExternalRef,
        since: datetime,
        token: str,
        until: datetime | None = None,
    ) -> list[LeadDTO]:
        """Reconciliation path, for leads a webhook never delivered.

        ``until`` closes the window, and it exists for one caller: a form
        whose window holds more leads than one read may fetch answers
        :class:`~adskit.errors.ResultTruncated`, and the only way to read
        it at all is a narrower window - which needs an end as well as a
        start. ``None`` is "up to now".
        """
        ...

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Ask the provider to start sending webhooks.

        Skipping this is silent: no error, no leads, no clue why. Which is
        also why the caller is expected to show whether it happened rather
        than trust that it did - a rehearsed subscription and a real one
        look identical from here.

        ``dry_run`` because this writes to somebody's page, like every
        other write in this package. It spends no money, and that is not
        the line: the line is whether a call reaches an account we do not
        own.
        """
        ...


@runtime_checkable
class AudiencePort(Protocol):
    """Who an ad set is shown to."""

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        """The catalogue rows the provider recognises under these names.

        Every platform draws the same line: an advertiser thinks in words,
        and the platform targets ids. Meta answers a list of names in one
        call, Google looks the same words up among its user-interest
        resources, and both refuse a word that is not in their catalogue.
        That agreement is why this is a port and the reach estimate next to
        it is not.

        A name that comes back missing **is the answer**, not a failure:
        it means the provider has no such interest, and the caller drops it
        with a reason rather than retrying. Order and length of the result
        therefore do not match the input, and the caller matches by name.

        Batched because the question is asked about a whole chosen list at
        once, and one call for ten names is the difference between a screen
        that confirms while somebody reads it and one that makes them wait.
        """
        ...

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        """The rows of a **closed** catalogue that match these names.

        Its own method rather than a ``kind`` argument on
        :meth:`find_interests` above, because the two ask the provider
        different questions and get different guarantees back.

        That one is a *search*: an advertiser types a word, the platform
        answers a ranked guess, and a name that comes back missing means the
        platform has no such interest. This is a *browse*: behaviours and
        life events are a fixed list the platform publishes, so a name is
        matched against it exactly, and a name that is not there was never
        going to be.

        Both halves of that difference are real on every platform. Meta
        searches ``adinterest`` and browses ``adTargetingCategory`` by
        class; Google searches user interests and enumerates its life-event
        and in-market categories. Folding them into one method would hide
        which kind of answer a caller is holding - and the two need
        different handling: an unmatched interest is worth asking a model to
        rephrase, and an unmatched life event is a name that does not exist.

        Matching is by name and is the implementation's job, for the reason
        the batching in :meth:`find_interests` is: the caller would
        otherwise have to learn that this class is browsed rather than
        queried, and how many rows come back, and how the platform cases
        them.

        ``kind`` is refused rather than guessed at when a provider has no
        such class - the same contract :meth:`MetricsPort.fetch_breakdown`
        has for a cut it will not make.

        **Why this exists at all.** A wedding hall, a removals firm and a
        mortgage broker have no interest worth targeting: nobody is
        "interested in" moving house. Their entire audience is one row in a
        list of about a dozen, and this is the method that reaches it.
        """
        ...

    def find_locations(
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        """The places the provider recognises under this word.

        The geography half of the same problem :meth:`find_interests`
        solves: an owner says "Toshkent" and every platform targets a key it
        issued. Meta answers from ``adgeolocation``, Google from its geo
        target constants, and both refuse a place name in a targeting spec.

        **One query, not a list.** ``find_interests`` above is batched
        because Meta will answer a whole list of names in one call; no
        provider offers the same for geography, so a batched signature here
        would be a single call hiding a loop, and the caller could not see
        what it costs. It is affordable because of what is being asked: a
        campaign is aimed at one city, or three, never at thirty.

        ``country_code`` narrows rather than filters. Place names repeat
        across the world - there is a Tashkent in Kazakhstan too - and
        without the advertiser's own country the top result is decided by
        which one is more famous.

        Ranked, not exact. This answers "what did you mean", so the caller
        shows the rows to a person and lets them choose; a match picked
        automatically from a fuzzy search is how a campaign for a shop in
        Tashkent ends up delivering in another country.
        """
        ...

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, Any],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        """How many people this spec would reach, before anything is created.

        Here rather than in an ``EstimatePort`` of its own. The question
        is the same everywhere - every platform shows an audience-size meter
        while an advertiser drags the sliders - and it is the only feedback
        that makes "we widened your radius" mean anything to somebody who
        has never bought an ad.

        ``optimization_goal`` is the provider's own word and travels opaque,
        exactly as ``targeting`` does: the size of an audience depends on
        what the platform is being asked to optimise for, and inventing a
        neutral vocabulary for that would be inventing the abstraction this
        package refuses to invent from one example.

        Answering is not promised. A provider that has not finished
        computing says so through ``ReachDTO.ready`` rather than by
        guessing, and the caller shows nothing rather than a zero.
        """
        ...

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace the targeting spec.

        ``targeting`` passes through as an opaque dict, in the provider's own
        shape. An ``AudienceIntent`` abstraction is not built until there is
        a second provider to abstract over, because inventing one from a
        single example produces a model shaped exactly like that example.

        What came back may not be what went in - see ``ActionResult.dropped``.
        ``ActionResult.applied["targeting"]`` is what the provider holds
        afterwards when it could be read back, else what was sent.
        """
        ...

    def read_targeting(self, *, ref: ExternalRef, token: str) -> dict[str, Any]:
        """The spec this ad set holds right now, in the provider's own shape.

        Read just before :meth:`apply` replaces it: the spec goes out whole,
        so one built on an older copy undoes whatever was changed since -
        in the provider's own manager, or by the provider itself.
        """
        ...

    def same_targeting(self, first: dict[str, Any], second: dict[str, Any]) -> bool:
        """Whether two specs aim at the same people.

        The provider's own question, because only it knows which of its keys
        are the audience and which are its bookkeeping: Meta expands a city
        key into a whole location and adds defaults nobody sent, and a plain
        ``==`` would call every ad set changed.
        """
        ...


@runtime_checkable
class AudienceSourcePort(Protocol):
    """The audiences an advertiser owns, as objects with a life of their own.

    Separate from :class:`AudiencePort` above, and the line between them is
    not read against write - ``apply`` writes too. It is **lifetime and
    ownership**. Everything on that port is scoped to one ad set's spec: a
    word looked up so it can go into one, a size measured for one, a spec
    replaced on one. Everything here belongs to the *account*, is pointed at
    by many ad sets, outlives all of them, and has to be kept in step on a
    schedule. That is the same distinction that puts
    :class:`CampaignControlPort` and :class:`MetricsPort` in different
    protocols.

    Three things follow from it, and each one would have been wrong on the
    other port:

    * **Creating is not idempotent.** ``apply`` replaces a spec whole, so
      calling it twice changes nothing the second time. Calling
      :meth:`create_audience` twice produces two audiences with the same
      name, each holding somebody's personal data. Protocols are read as a
      set of things that behave alike, and these two do not.
    * **This is where personal data leaves.** :meth:`add_members` is the
      only method in this package that carries anything about a person
      *towards* a provider. Saying so once, here, is worth more than saying
      it in six call sites - and it is why the members arrive already
      hashed: see :class:`~adskit.dto.AudienceMemberDTO`.
    * **The provider answers later.** An audience is not usable the moment
      it is created. Every platform processes an upload for hours, so the
      state is read rather than assumed, and nothing here promises a
      finished object.

    Asked of Google first, like every other port. It splits the same way:
    targeting criteria sit on the ad group, while a customer list is a
    ``UserList`` with its own service, its own size figure and its own
    processing state. The division is not a Meta artefact.
    """

    def list_audiences(self, *, account: ExternalRef, token: str) -> list[AudienceDTO]:
        """Every audience on the account, whatever state each is in.

        Account level, like the campaign port's reads and for the same
        reason: one paged call answers a question that would otherwise cost
        one call per audience, and the call budget is the scarce resource.

        The ones this product did not create come back too, and are wanted.
        An advertiser who built an audience by hand has one that ads can be
        aimed at, and a list that hid it would be a picker missing the row
        somebody was looking for.
        """
        ...

    def get_audience(self, *, ref: ExternalRef, token: str) -> AudienceDTO:
        """One audience, read fresh.

        Here as well as in the list because of what happens after an
        upload. The provider spends hours counting, and the screen that
        wants to know whether it has finished is asking about *one*
        audience - re-reading the whole account to answer that would spend
        a paged call to learn one field.
        """
        ...

    def create_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Make an empty audience that a customer list can be uploaded into.

        Empty, always. No provider accepts the people and the container in
        one call, and pretending otherwise here would hide a two-step
        failure - an audience created, an upload refused - behind a single
        return value that cannot describe it.

        ``description`` is not decoration and is worth passing. An
        advertiser looking at this list in the provider's own console a
        year from now has the name and this, and nothing else, to tell one
        upload from another.

        **The provider may refuse until its owner agrees to something.**
        Every platform makes an advertiser accept terms about uploaded
        personal data before the first customer list, once per account, and
        that refusal arrives here as
        :class:`~adskit.errors.TermsNotAccepted` - the same class a lead
        form's refusal uses, because it is the same kind of problem and
        only a person can clear it.
        """
        ...

    def supported_rules(self) -> list[RuleSupportDTO]:
        """Which rule audiences this provider will build, and how far back.

        No account, no token, no call - a table this implementation carries
        because it is provider knowledge and nothing else here is allowed
        to hold it. The same shape as the money rules: what the domain
        needs to draw a form, answered by the one layer that knows the
        platform's own limits.

        Asked before anything is created, which is the point. The
        alternative is a person choosing "the last year" on a lead form,
        pressing create, and being told no by a third party - and the
        maximum they should have been offered was never anywhere a screen
        could read it.

        A source this provider cannot build from is absent rather than
        present with an empty list. Absent means "not offered here", which
        is what a picker needs; empty would read as a source that exists
        and does nothing.
        """
        ...

    def create_rule_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        rule: AudienceRuleDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Make an audience the provider fills in itself, from a rule.

        Its own method rather than an argument on :meth:`create_audience`,
        because the two produce objects with opposite post-conditions. That
        one makes an **empty** container whose whole purpose is to have
        people uploaded into it. This one makes an audience that is already
        being populated by the provider and that no upload may ever touch -
        :meth:`add_members` against one is refused.

        **No personal data is involved, at any point.** The provider knows
        who visited, watched or wrote in; this hands over a description of
        which of them to gather. Nothing is collected here, nothing is
        hashed, and the customer-list terms an advertiser signs before
        :meth:`create_audience` do not apply.

        The audience is not usable when this returns, for a different
        reason than a customer list is not. There, the provider is matching
        rows; here, it is gathering history - and how much history there is
        to gather depends on how far back the rule looks and how busy the
        source was. Both are read afterwards through the same two states.

        A pair the provider does not offer is refused before the call, out
        of :meth:`supported_rules`, with both halves named.
        """
        ...

    def create_lookalike_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        spec: LookalikeSpecDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Make an audience of people who resemble an audience that exists.

        The third create, and its own method for the reason the second one
        is: the post-conditions differ from both. :meth:`create_audience`
        makes an empty container waiting for an upload;
        :meth:`create_rule_audience` describes people by what they did;
        this describes them by **who they are like**, and its whole input
        is another audience that must already be usable.

        **No personal data is involved, and no seed data crosses either.**
        The people in the seed stay on the provider - this hands over its
        id, not its contents. Which also means the customer-list terms are
        not in play, even when the seed is a customer list: agreeing to
        upload other people's details was done when they were uploaded.

        **The seed is a ref rather than a bare id, and that matters more
        here than anywhere else in this package.** Every other id crossing
        this boundary is recognisable if it lands in the wrong call - a
        page id is not a pixel id. Two audience ids are indistinguishable,
        so the provider is the only thing that can tell an audience of this
        account's from one belonging to somebody else's platform.

        **Which seeds are allowed is the provider's answer and is asked of
        the audience, not of this method.** :attr:`AudienceDTO.can_seed`
        says whether one may be built from a given audience; a caller that
        ignores it gets the provider's refusal instead, which names less.

        Not usable when this returns, for the third distinct reason in this
        protocol. A customer list is matching rows and a rule audience is
        gathering history; this one is being *modelled*, which every
        platform describes in hours. Read through the same two states.
        """
        ...

    def add_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Add people to an audience. The one call that carries a customer list.

        ``members`` are already hashed and cannot be otherwise - the DTO
        refuses to hold anything that is not a digest. Normalising and
        hashing needs a phone-number parser and a locale, and neither
        belongs in a package that has no idea which country the advertiser
        is in.

        **One-way.** No provider will read a list back, so nothing here
        returns members and nothing ever will. What comes back is how many
        rows were taken and how many were refused, which is the only
        feedback there is on whether the normalisation was right:
        a rule applied wrongly produces rows a provider accepts the shape
        of and matches to nobody.

        Splitting a large list across calls is the implementation's job,
        not the caller's. Providers cap a single request and expect the
        parts to be tied together by a session they issue, and a caller
        doing that itself would be a caller that has learned the provider's
        batching rules.
        """
        ...

    def remove_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Take people back out of an audience. The other half of the one-way door.

        Hashed like :meth:`add_members`, and for a stronger reason. There
        is no way to ask a provider "which of these people are in it" - the
        list cannot be read back - so the only handle on somebody already
        uploaded is the same digest that put them there. A caller that has
        lost the plaintext has lost the ability to withdraw them, which is
        why every path that erases a person removes them here *before* it
        erases what it knows about them.

        **Not the same as deleting the audience.** That removes everybody
        and is what an account erasure does; this is the finer instrument,
        for the one person who asked, in an audience that keeps working.

        Removing somebody who is not in it is not an error on any platform
        seen so far, and callers depend on that: whether a particular
        person was in a particular audience is not knowable from this side,
        so the honest call is made against every audience they could be in.

        The answer is a :class:`MemberUploadDTO` because the providers
        answer in the same shape - rows taken, rows refused - and a second
        DTO holding the same two integers would be two names for one fact.
        ``received`` reads as "rows the provider accepted from us" in both
        directions.
        """
        ...

    def delete_audience(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Remove the audience, and with it everything uploaded into it.

        The only way this product can withdraw personal data it sent, and
        therefore not merely tidying up. When an account is erased, the
        rows here go with it; leaving an audience behind would leave a
        customer's customers on somebody else's platform after the customer
        asked to be forgotten.

        Refusal is expected in one case and is not an error worth hiding:
        an audience an ad set is still using cannot be deleted on some
        platforms until it is no longer referenced.
        """
        ...


@runtime_checkable
class ConversionPort(Protocol):
    """What became of a lead after the provider handed it over.

    The one port that carries an answer *back*. Everything else in this
    package asks a provider something and reads what it says; this tells it
    something it does not know and could not find out - whether the person
    it delivered was worth having.

    That is not a reporting nicety, it is the difference between two
    machines. A platform optimises towards the event it is told about, and
    the only event it can see by itself is a form being submitted. So an
    advertiser measuring a cost per *qualified* lead while the platform buys
    submissions is paying for one thing and counting another, and the gap
    widens as the optimiser gets better at the wrong job.

    Asked of Google first, like every other port here, and it splits the
    same way: Meta takes lead-stage events on a dataset, Google takes an
    offline conversion import against the click id it issued, and both are
    "here is an id you gave me, here is what happened next". The division is
    not a Meta artefact.

    **Nothing personal crosses this boundary.** The provider is not being
    told who somebody is - it already knows, it introduced them - only how
    it went. See :class:`~adskit.dto.LeadEventDTO`, whose shape is what
    makes that structural rather than a promise.
    """

    def report_leads(
        self,
        *,
        dataset: ExternalRef,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        """Send a batch of verdicts. Returns how many the provider took.

        ``dataset`` is where the provider files them, and it is a ref rather
        than a bare id for the reason a lookalike's seed is: an id on its
        own cannot say which platform issued it, and a dataset id and an
        audience id are indistinguishable strings.

        **Batched, and the batch is the unit of retry.** Every platform caps
        one request and every platform de-duplicates on the event id inside
        it, which together mean the honest failure mode is "send the whole
        lot again" - so splitting a long list is this implementation's job
        and not the caller's, exactly as it is for a customer list.

        ``dry_run`` because this writes to somebody's account. It spends no
        money and creates no object, and that is not the line: what it does
        is change what a platform optimises the account's spending towards,
        which is a larger consequence than either.

        **Order does not matter and lateness is normal.** A verdict is given
        when somebody gets round to answering the telephone, which may be
        days after the lead arrived, and every platform accepts a backdated
        event inside its own window. What each of them refuses is an event
        older than that window - which arrives here as a count lower than
        the batch rather than as an error, because a lead that has aged out
        is not a failure to retry.
        """
        ...

    def report_window_days(self) -> int:
        """How far back a verdict may still be sent, in whole days.

        No account, no token, no call - a number this implementation carries
        because it is provider knowledge and nothing else is allowed to hold
        it, exactly like :meth:`AudienceSourcePort.supported_rules` next
        door.

        Read **before** a batch is built rather than discovered from the
        answer. A verdict past the window is one the provider will not
        count, and a caller that sent it anyway would mark it reported, stop
        retrying, and record a figure nothing on the platform agrees with.
        """
        ...


@runtime_checkable
class ConnectPort(Protocol):
    """How a person lets this product act on their advertising account.

    Every platform here does it the same way at this height: the browser is
    sent to the provider's consent screen, comes back with a one-time code,
    and the code is traded for a token. Google and Meta differ in what the
    token is - Meta's own token stretched to sixty days, Google's refresh
    token - and that difference stays behind this port.

    The one port built with configuration: the app's own id and secret are
    handed to the implementation's constructor, never read from the
    environment. A person's token still travels as an argument, as it does
    everywhere else in this module.
    """

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        """Where to send the browser.

        ``state`` is generated by the caller, kept in the session and
        compared on the way back - it is what ties the callback to the
        person who started it.
        """
        ...

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        """Trade the callback's code for a token that lasts.

        ``redirect_uri`` must be the same string the browser was sent with,
        trailing slash included; every provider compares it exactly.
        """
        ...

    def access_token(self, *, stored: str) -> str:
        """The token a call is made with, from the one that was stored.

        ``stored`` is :attr:`GrantDTO.token` as the caller kept it. Meta's
        stored token is used as it is; Google's is a refresh token, traded
        here for an access token that lives an hour. Every caller asks this
        before a call rather than knowing which kind it holds - that
        knowledge is exactly what must not leave the adapter.

        A grant that was withdrawn raises :class:`~adskit.errors.AuthFailed`.
        """
        ...
