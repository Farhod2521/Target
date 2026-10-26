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
    # Meta's own word: ACTIVE, IN_PROCESS, WITH_ISSUES, DELETED. Kept raw
    # like every other provider status here. A creative has no
    # ``effective_status`` and no delivery of its own - what delivers is the
    # ad that points at it.
    status: str = ""
    thumbnail_url: str = ""
    # Set when the creative promotes a post that already existed, and empty
    # for every creative built from a spec.
    object_story_id: str = ""
    object_story_spec: dict[str, Any] = Field(default_factory=dict)
    # What Meta answers when it made the post itself - a boosted page post,
    # an advert built from one in Ads Manager. Read only where the two
    # fields above are empty: they are what this product wrote, and what a
    # product wrote about its own advert is the better answer.
    effective_object_story_id: str = ""
    # The page the advert ran as, where the spec does not name one. Meta
    # fills it on creatives it built; it is a page id on a page's advert
    # and is left alone on anything else - see ``page_id``.
    actor_id: str = ""

    @property
    def kind(self) -> str:
        """Which of the three shapes this is: ``link``, ``video`` or ``post``.

        Empty when it is none of them, which is a creative shape this
        product does not build - a carousel, a dynamic asset feed. Recorded
        as unknown rather than guessed at.
        """
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
        """The account the ad ran as, under the name v26.0 answers with.

        ``instagram_actor_id`` is not read as a fallback, and that is a
        decision rather than an oversight: Meta retired the old spelling
        for every API version on 2025-09-09, so a creative still carrying
        it would have to predate that - and a column filled from a key the
        provider no longer sends is a column that quietly stops updating.
        """
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
        """Where the button goes.

        On a lead creative Meta never follows it - the tap opens the form -
        and still refuses a creative whose link points back at a page. So a
        stored link that looks unused is not: it is the field that decides
        whether this creative could be created at all.
        """
        return _text(self._data().get("link"))

    @property
    def call_to_action(self) -> str:
        """The button's type, in Meta's vocabulary. ``SIGN_UP``, ``LEARN_MORE``.

        Not translated. It is a word the advertiser chose from a list Meta
        defines, and there is no domain word it maps onto - what a screen
        shows is a label decided where the screen is.
        """
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
        """A video creative's thumbnail, which Meta requires and names oddly.

        Not the same field as ``thumbnail_url`` above: that one is Meta's
        own rendering of the whole creative and comes back on every kind,
        this one is the still the advertiser supplied for a video.
        """
        return _text(self._data().get("image_url"))

    @property
    def lead_form_id(self) -> str:
        """The form id, dug out of the button, or empty.

        Empty for every creative that does not collect leads, which is most
        creatives on most accounts - so an empty answer is normal and must
        not be logged as a failure.
        """
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
    # Never ``None``: an ad with no creative expansion gets an empty row
    # whose id is empty, which every accessor below already answers for.
    creative: CreativeRow = Field(default_factory=CreativeRow)
    issues_info: tuple[IssueRow, ...] = ()
    # Absent on every ad Meta did not refuse, which is most of them.
    ad_review_feedback: ReviewFeedbackRow | None = None

    @property
    def creative_external_id(self) -> str:
        return self.creative.id

    @property
    def lead_form_external_id(self) -> str:
        """The form id this ad collects into, or empty.

        Kept on the ad rather than read off the creative by every caller,
        because this is the ad's own answer to "where do my leads go" and
        the ad is what a webhook names. The digging itself belongs to the
        creative and lives there.
        """
        return self.creative.lead_form_id
