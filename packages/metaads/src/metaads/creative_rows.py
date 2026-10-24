"""The creative and the ad, as they arrive nested in each other."""

from typing import Any

from pydantic import Field

from metaads.campaign_rows import IssueRow, ReviewFeedbackRow
from metaads.dto_base import MetaDTO, _text


class CreativeRow(MetaDTO):
    """One creative, as it arrives nested inside an ad.

    Read through ``/act_<id>/ads`` and not through ``/act_<id>/adcreatives``,
    which costs nothing: a nested expansion rides on a request that is
    already being made, exactly as ``issues_info`` does one level up. The
    account edge would be a fifth call and would answer with every creative
    the advertiser has ever made, including the ones no ad has pointed at
    for two years - and a creative no ad used has no figures, which makes it
    the one thing this table cannot say anything about.

    **The story spec is read back through the same table it is written by.**
    :mod:`metaads.stories` builds it, and the two blocks name three of the
    same fields differently:

    ======================  ==================  ===================
    what it is              image (link_data)   video (video_data)
    ======================  ==================  ===================
    the headline            ``name``            ``title``
    the line under it       ``description``     ``link_description``
    the picture             ``image_hash``      ``image_url``
    ======================  ==================  ===================

    Reading only ``link_data`` is how every video creative in an account
    comes back with an empty headline and nobody notices - the parse does
    not fail, it just answers blank. ``tests/packages/test_metaads_creatives``
    builds a spec with the writer and reads it back with this class, so the
    two halves of that table cannot drift apart.

    **A creative made from an existing page post carries no spec at all.**
    It names ``object_story_id`` instead, and its words live on the post
    rather than on the creative. Empty text on such a row is the truth and
    not a parse that missed.
    """

    id: str = ""
    name: str = ""
    status: str = ""
    thumbnail_url: str = ""
    object_story_id: str = ""
    object_story_spec: dict[str, Any] = Field(default_factory=dict)
    effective_object_story_id: str = ""
    actor_id: str = ""

    @property
    def kind(self) -> str:
        """Which of the three shapes this is: ``link``, ``video`` or ``post``."""
        if self._block("link_data"):
            return "link"
        if self._block("video_data"):
            return "video"
        if self.post_id:
            return "post"
        return ""

    @property
    def page_id(self) -> str:
        """The page the advert ran as: the spec's, or the actor Meta named."""
        return _text(self.object_story_spec.get("page_id")) or _text(self.actor_id)

    @property
    def post_id(self) -> str:
        """The post the advert promotes, whichever field carries it."""
        return _text(self.object_story_id) or _text(self.effective_object_story_id)

    @property
    def instagram_user_id(self) -> str:
        """The account the ad ran as, under the name v26.0 answers with."""
        return _text(self.object_story_spec.get("instagram_user_id"))

    @property
    def message(self) -> str:
        """The body text. The one field both blocks spell the same way."""
        return _text(self._data().get("message"))

    @property
    def headline(self) -> str:
        """``name`` on an image, ``title`` on a video. See the class note."""
        data = self._data()
        return _text(data.get("title") if self.kind == "video" else data.get("name"))

    @property
    def description(self) -> str:
        """``description`` on an image, ``link_description`` on a video."""
        data = self._data()
        return _text(
            data.get("link_description")
            if self.kind == "video"
            else data.get("description")
        )

    @property
    def link_url(self) -> str:
        """Where the button goes."""
        return _text(self._data().get("link"))

    @property
    def call_to_action(self) -> str:
        """The button's type, in Meta's vocabulary. ``SIGN_UP``, ``LEARN_MORE``."""
        action = self._data().get("call_to_action")
        if not isinstance(action, dict):
            return ""
        return _text(action.get("type"))

    @property
    def image_hash(self) -> str:
        """Empty on a video creative, whose picture is a URL and not a hash."""
        return _text(self._data().get("image_hash"))

    @property
    def video_id(self) -> str:
        return _text(self._data().get("video_id"))

    @property
    def image_url(self) -> str:
        """A video creative's thumbnail, which Meta requires and names oddly."""
        return _text(self._data().get("image_url"))

    @property
    def lead_form_id(self) -> str:
        """The form id, dug out of the button, or empty."""
        action = self._data().get("call_to_action")
        if not isinstance(action, dict):
            return ""
        value = action.get("value")
        if not isinstance(value, dict):
            return ""
        return _text(value.get("lead_gen_form_id"))

    def _data(self) -> dict[str, Any]:
        """Whichever of the two blocks this creative carries."""
        return self._block("link_data") or self._block("video_data")

    def _block(self, key: str) -> dict[str, Any]:
        block = self.object_story_spec.get(key)
        return block if isinstance(block, dict) else {}


class AdRow(MetaDTO):
    """One row of ``/act_<id>/ads``.

    The creative arrives nested rather than as a second read. The field
    that makes it necessary is the lead form id, which Meta buries four
    levels inside the story spec and without which a lead arriving by
    webhook cannot be attributed to the ad that bought it - the whole of
    CPQL. The rest of the creative costs nothing extra: it is more fields
    on a request that was being made anyway.

    A creative shared by three ads arrives three times, once on each. The
    caller stores it once - see ``store_creatives``.
    """

    id: str
    name: str = ""
    adset_id: str = ""
    status: str = ""
    effective_status: str = ""
    creative: CreativeRow = Field(default_factory=CreativeRow)
    issues_info: tuple[IssueRow, ...] = ()
    ad_review_feedback: ReviewFeedbackRow | None = None

    @property
    def creative_external_id(self) -> str:
        return self.creative.id

    @property
    def lead_form_external_id(self) -> str:
        """The form id this ad collects into, or empty."""
        return self.creative.lead_form_id
