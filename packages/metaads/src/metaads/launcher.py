"""Meta's creation sequence, expressed in the domain's own types.

Not a port, and deliberately so. CLAUDE.md defers ``CreativePort`` and
``BudgetPort``, and the reason applies here too: creating a campaign is one
*intent* but six provider-shaped steps, and an interface invented from a
single provider would be shaped exactly like that provider. So the launch
service reaches into this package through the escape hatch the same
document allows for platform-specific screens.

What this class buys, given that, is the boundary. The service names
:class:`MetaLauncher` once and then deals in ``ExternalRef``,
``ActionResult`` and ``adskit`` exceptions - so the day a second provider
arrives, the sequence is what gets rewritten and not everything that reads
its result. Meta's error codes stop here, in :func:`metaads.adapter.session`.

Every method defaults to ``dry_run=True``. That default is repeated rather
than centralised on purpose: the safe value has to be what somebody gets
for forgetting, at every single call site.

Uploading the owner's picture is next door, in :class:`metaads.assets
.MetaAssets`, because an upload is the one thing in the sequence that is
never rolled back.
"""

from typing import Any

from adskit.dto import ActionResult
from adskit.refs import ExternalRef, Level

from metaads import PROVIDER
from metaads.adapter import session
from metaads.boosts import (
    PROMOTED_MEDIA_FIELDS,
    BoostSpec,
    create_boost_creative,
    read_creative,
)
from metaads.campaigns import read_adset_settings
from metaads.leadforms import create_lead_form
from metaads.restage import create_from_story
from metaads.specs import STATUS_PAUSED, AdSetSpec, CampaignSpec, CreativeSpec
from metaads.specs import LeadFormSpec as FormSpec
from metaads.stories import create_creative
from metaads.writes import (
    create_ad,
    create_adset,
    create_campaign,
    delete_object,
)


class MetaLauncher:
    """The six writes that turn a proposal into a paused campaign.

    Stateless, like every adapter here: the token arrives per call and one
    connection is opened and closed per call. A worker killed mid-sequence
    leaks nothing - what it leaves behind is objects at Meta, which is what
    the caller's ``created_refs`` is for.
    """

    # --- The objects -----------------------------------------------------
    def create_form(
        self,
        *,
        page: ExternalRef,
        spec: FormSpec,
        page_token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The lead form, on the page, with the page's own token.

        First of the sequence because it is the only step that can fail for
        a reason the owner can fix - a missing privacy policy - and failing
        first means failing before anything exists to roll back.
        """
        with session(page_token) as graph:
            created = create_lead_form(
                page_id=page.id,
                spec=spec,
                page_token=page_token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="form",
            external_id=created,
            dry_run=dry_run,
            applied={"name": spec.name, "questions": len(spec.questions)},
        )

    def create_campaign(
        self,
        *,
        account: ExternalRef,
        spec: CampaignSpec,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        with session(token) as graph:
            created = create_campaign(
                account_id=account.id,
                spec=spec,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="campaign",
            external_id=created,
            dry_run=dry_run,
            applied={
                "name": spec.name,
                "objective": spec.objective,
                "status": spec.status,
                "daily_budget_minor": spec.daily_budget_minor,
                "bid_strategy": spec.bid_strategy,
                "budget_sharing": spec.budget_sharing,
                "special_ad_categories": list(spec.special_ad_categories),
                "special_ad_category_country": list(spec.special_ad_category_country),
            },
        )

    def create_adset(
        self,
        *,
        account: ExternalRef,
        spec: AdSetSpec,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The audience and the budget, with what Meta declined to keep.

        The only step whose ``dropped`` is ever non-empty, and the reason
        that field exists at all: Meta removes interests and placements it
        no longer supports, answers 200, and says nothing.
        """
        with session(token) as graph:
            created = create_adset(
                account_id=account.id,
                spec=spec,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="adset",
            external_id=created.id,
            dry_run=dry_run,
            applied={
                "name": spec.name,
                "daily_budget_minor": spec.daily_budget_minor,
                "optimization_goal": spec.optimization_goal,
                "status": spec.status,
            },
            dropped=created.dropped,
            # The targeting as Meta holds it, so a caller can see what was
            # added as well as what was lost - see ``writes.changed_from``.
            raw_response={"targeting": created.returned},
        )

    def adset_settings(self, *, adset: ExternalRef, token: str) -> dict[str, Any]:
        """What a new ad set copied from this one must carry beyond the mirror."""
        with session(token) as graph:
            return read_adset_settings(adset_id=adset.id, token=token, client=graph)

    def create_creative(
        self,
        *,
        account: ExternalRef,
        spec: CreativeSpec,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        with session(token) as graph:
            created = create_creative(
                account_id=account.id,
                spec=spec,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="creative",
            external_id=created,
            dry_run=dry_run,
            applied={"name": spec.name, "is_video": bool(spec.video_id)},
        )

    def boost_creative(
        self,
        *,
        account: ExternalRef,
        spec: BoostSpec,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The same step as :meth:`create_creative`, from a post that exists.

        A second method rather than a branch inside the first, because the
        two take different objects and mean different things. One publishes
        a post while it makes the ad; this one points at a post somebody
        published weeks ago, which keeps the likes, the comments and the
        place it already has in a profile.

        Everything after it is identical - the ad names a creative and an
        ad set and does not care which of the two made it.
        """
        with session(token) as graph:
            created = create_boost_creative(
                account_id=account.id,
                spec=spec,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="creative",
            external_id=created,
            dry_run=dry_run,
            applied={
                "name": spec.name,
                "source_instagram_media_id": spec.media_id,
                "instagram_user_id": spec.instagram_user_id,
                "call_to_action": spec.call_to_action,
            },
        )

    def promoted_media(self, *, creative: ExternalRef, token: str) -> tuple[str, ...]:
        """Which Instagram posts a boosted creative actually advertises.

        Read after the creative exists, because Meta accepting a creative
        is not Meta keeping the post in it: the ``effective_`` field is what
        the ad will show, and a creative that fell back to a new post
        answers with a different id there - or with none. Both ids are
        returned, empties dropped, for the caller to compare.
        """
        with session(token) as graph:
            row = read_creative(
                creative_id=creative.id,
                token=token,
                fields=PROMOTED_MEDIA_FIELDS,
                client=graph,
            )
        found = (
            str(row.get("effective_instagram_media_id", "")),
            str(row.get("source_instagram_media_id", "")),
        )
        return tuple(media_id for media_id in found if media_id)

    def restage_creative(
        self,
        *,
        account: ExternalRef,
        name: str,
        story: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """A creative from a story spec that came back from Meta and was edited.

        The third way to make one, beside :meth:`create_creative` and
        :meth:`boost_creative`, and the only one that starts from something
        that already exists. It is what "change what this advert says"
        turns into: Meta does not allow a creative to be edited, so the old
        block is copied, two fields are written over it, and the result is
        a new object - see :mod:`metaads.restage`.

        Everything after it is the same as after the other two. The ad step
        names a creative and does not care which of the three made it.
        """
        with session(token) as graph:
            created = create_from_story(
                account_id=account.id,
                name=name,
                story=story,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

        return self._done(
            level="creative",
            external_id=created,
            dry_run=dry_run,
            applied={"name": name, "restaged": True},
        )

    def create_ad(
        self,
        *,
        account: ExternalRef,
        adset: ExternalRef,
        creative: ExternalRef,
        name: str,
        token: str,
        dry_run: bool = True,
        status: str = STATUS_PAUSED,
    ) -> ActionResult:
        """One advert under a group, switched off unless told otherwise.

        Off is right for a launch, which switches the whole tree on at the
        end. It is wrong for an advert made to *replace* one that is
        running: the old one is switched off next, and a new one made off
        leaves the group delivering nothing - so that caller passes
        ``STATUS_ACTIVE``.
        """
        with session(token) as graph:
            created = create_ad(
                account_id=account.id,
                adset_id=adset.id,
                creative_id=creative.id,
                name=name,
                token=token,
                client=graph,
                dry_run=dry_run,
                status=status,
            )

        return self._done(
            level="ad",
            external_id=created,
            dry_run=dry_run,
            applied={"name": name, "status": status},
        )

    def remove(self, *, ref: ExternalRef, token: str, dry_run: bool = True) -> bool:
        """Delete one object, for a rollback walking its refs backwards.

        A dry-run id answers true without a call, which is checked inside
        the package rather than here: a rollback must not be the place where
        a synthetic id first reaches Meta.
        """
        with session(token) as graph:
            return delete_object(
                object_id=ref.id, token=token, client=graph, dry_run=dry_run
            )

    # --- Translation -----------------------------------------------------
    @staticmethod
    def _done(
        *,
        level: Level,
        external_id: str,
        dry_run: bool,
        applied: dict[str, object],
        dropped: dict[str, object] | None = None,
        raw_response: dict[str, object] | None = None,
    ) -> ActionResult:
        return ActionResult(
            ok=True,
            ref=ExternalRef(provider=PROVIDER, level=level, id=external_id),
            applied=applied,
            dropped=dropped or {},
            dry_run=dry_run,
            raw_response=raw_response or {},
        )
