from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Final

NO_PAGE: Final = ""


@dataclass(frozen=True, slots=True)
class PageScope:
    pages: dict[str, str] = field(default_factory=dict)
    page_of: dict[str, str] = field(default_factory=dict)
    campaign_of: dict[str, str] = field(default_factory=dict)
    blocked: frozenset[str] = frozenset()
    outside: frozenset[str] = frozenset()
    current: str = ""
    others: dict[str, str] = field(default_factory=dict)
    elsewhere: frozenset[str] = frozenset()
    elsewhere_campaigns: frozenset[str] = frozenset()
    unbuilt: frozenset[str] = frozenset()
    unbuilt_campaigns: frozenset[str] = frozenset()
    account_of: dict[str, str] = field(default_factory=dict)
    current_account: str = ""
    guessed: frozenset[str] = frozenset()

    @property
    def adset_ids(self) -> tuple[str, ...]:
        return tuple(self.page_of)

    @property
    def campaign_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.campaign_of.values()))

    @property
    def has_unplaced(self) -> bool:
        return NO_PAGE in self.page_of.values()

    def allows_adset(self, adset_id: str) -> bool:
        return adset_id in self.page_of

    def hides_adset(self, adset_id: str) -> bool:
        return adset_id in self.outside

    def allows_campaign(self, campaign_id: str) -> bool:
        return campaign_id not in self.blocked

    def allows_page(self, page_id: str) -> bool:
        return page_id in self.pages

    def name_of(self, page_id: str) -> str:
        return self.pages.get(page_id, "")

    def adsets_by_page(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = defaultdict(list)
        for adset_id, page in self.page_of.items():
            found[page].append(adset_id)
        return dict(found)

    def hides(self, *, level: str, external_id: str, parent: str = "") -> bool:
        if level == "campaign":
            return not self.allows_campaign(external_id)
        if level == "adset":
            return self.hides_adset(external_id)
        if level == "ad":
            return bool(parent) and self.hides_adset(parent)
        if level == "page":
            return not self.allows_page(external_id)
        return False

    def on_other_page(self, *, level: str, external_id: str, parent: str = "") -> bool:
        if level == "campaign":
            return external_id in self.elsewhere_campaigns
        if level == "adset":
            return external_id in self.elsewhere
        if level == "ad":
            return parent in self.elsewhere
        return False

    def only(self, page_id: str, account: str = "") -> "PageScope":
        kept = {page_id, NO_PAGE} if page_id in self.pages else set()
        page_of = {
            adset_id: page
            for adset_id, page in self.page_of.items()
            if page in kept
            and (not account or self.account_of.get(adset_id, account) == account)
        }
        campaign_of = {
            adset_id: campaign
            for adset_id, campaign in self.campaign_of.items()
            if adset_id in page_of
        }
        held = set(campaign_of.values())
        moved = {adset_id for adset_id in self.page_of if adset_id not in page_of}
        moved_campaigns = {
            campaign for campaign in self.campaign_of.values() if campaign not in held
        }
        return PageScope(
            pages={page_id: self.pages[page_id]} if kept else {},
            page_of=page_of,
            campaign_of=campaign_of,
            blocked=self.blocked | moved_campaigns,
            outside=self.outside | moved,
            current=page_id if kept else "",
            others={
                other: name for other, name in self.pages.items() if other not in kept
            },
            elsewhere=frozenset(moved),
            elsewhere_campaigns=frozenset(moved_campaigns),
            account_of={
                adset_id: owner_account
                for adset_id, owner_account in self.account_of.items()
                if adset_id in page_of
            },
            current_account=account if kept else "",
            guessed=self.guessed & frozenset(page_of),
        )

    def was_built_elsewhere(
        self, *, level: str, external_id: str, parent: str = ""
    ) -> bool:
        if level == "campaign":
            return external_id in self.unbuilt_campaigns
        if level == "adset":
            return external_id in self.unbuilt
        if level == "ad":
            return parent in self.unbuilt
        return False

    def built_here(self, campaign_ids: frozenset[str]) -> "PageScope":
        page_of = {
            adset_id: page
            for adset_id, page in self.page_of.items()
            if self.campaign_of.get(adset_id, "") in campaign_ids
        }
        moved = {adset_id for adset_id in self.page_of if adset_id not in page_of}
        moved_campaigns = {
            campaign
            for adset_id, campaign in self.campaign_of.items()
            if adset_id in moved
        } - set(campaign_ids)
        return replace(
            self,
            page_of=page_of,
            campaign_of={
                adset_id: campaign
                for adset_id, campaign in self.campaign_of.items()
                if adset_id in page_of
            },
            blocked=self.blocked | moved_campaigns,
            outside=self.outside | moved,
            unbuilt=self.unbuilt | frozenset(moved),
            unbuilt_campaigns=self.unbuilt_campaigns | frozenset(moved_campaigns),
        )

    def marking(self, built: "PageScope") -> "PageScope":
        return replace(
            self, unbuilt=built.unbuilt, unbuilt_campaigns=built.unbuilt_campaigns
        )

    def page_of_campaign(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for adset_id, campaign in self.campaign_of.items():
            found.setdefault(campaign, self.page_of.get(adset_id, NO_PAGE))
        return found
