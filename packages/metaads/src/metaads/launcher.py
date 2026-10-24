"""Meta's creation sequence, expressed in the domain's own types."""

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
    """The six writes that turn a proposal into a paused campaign."""

    def create_form(
        self,
        *,
        page: ExternalRef,
        spec: FormSpec,
        page_token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The lead form, on the page, with the page's own token."""
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
        """The audience and the budget, with what Meta declined to keep."""
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
            raw_response={"targeting": created.returned},
        )

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
        """The same step as :meth:`create_creative`, from a post that exists."""
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
        """Which Instagram posts a boosted creative actually advertises."""
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
        """A creative from a story spec that came back from Meta and was edited."""
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
        """One advert under a group, switched off unless told otherwise."""
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
        """Delete one object, for a rollback walking its refs backwards."""
        with session(token) as graph:
            return delete_object(
                object_id=ref.id, token=token, client=graph, dry_run=dry_run
            )

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
