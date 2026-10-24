"""Goals whose ad opens a conversation instead of a page.

What a chat goal *is* - which is the third shape
``sends_to`` can name and the third entry in ``DELIVERABLE`` - is pinned
here; how it reaches Meta is pinned in ``tests/packages/test_metaads_creatives.py``
and how it reaches a customer in ``tests/apps/ads/test_launch_messages.py``.

Three things below are load-bearing beyond their own subject:

* **The greeting may be empty and the address may not.** Both are optional
  strings arriving through ``build``, and only one of them has a gate. The
  provider writes its own greeting when none is sent, so an unanswered one
  is a working ad; an unanswered address is a campaign spending somebody's
  money in a place nobody named.
* **The catalogue carries both texts or neither.** Half a welcome message
  is a thread that greets somebody and then leaves their own box empty.
* **No preset that sends nobody to a chat may carry one.** A greeting
  written under a lead preset reads, in the one file that decides what an
  ad is made of, like a sentence somebody will see.
"""

from pathlib import Path

import pytest

from core.targeting import (
    CHANNELS,
    DEFAULT_CHAT_CHANNEL,
    MAX_CHAT_QUESTIONS,
    MAX_GREETING_CHARS,
    MAX_QUESTION_CHARS,
    BusinessProfile,
    CatalogError,
    DestinationLinkMissing,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
    build,
    clean_questions,
    fallback,
    suggested_greeting,
    validate_launchable,
)
from core.targeting.destinations import opens_chat
from core.targeting.placements import names_a_placement

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(
    Path(__file__).resolve().parents[3] / "core" / "targeting" / "catalog"
)
CAFE = BusinessProfile(name="Osh Markazi", category="restaurant")
SHOP = BusinessProfile(name="Do'kon", category="ecommerce", country_code="UZ")


def every_preset() -> list:
    return [
        CATALOG.find(provider=PROVIDER, category=category.key, goal=preset.goal)
        for category in CATALOG.categories(provider=PROVIDER)
        for preset in CATALOG.goals(provider=PROVIDER, category=category.key)
    ]


def _write(path: Path, body: str) -> None:
    (path / "one.yaml").write_text(body, encoding="utf-8")


# --- What the catalogue says ---------------------------------------------
def test_every_messages_preset_opens_a_chat() -> None:
    """All twelve, named by the domain's word rather than by Meta's.

    ``destination_type: MESSENGER`` says which surface; ``sends_to: chat``
    says what the launch sequence has to build, and only the second is a
    question this repository can answer."""
    for preset in every_preset():
        if preset.goal == "messages":
            assert preset.sends_to == "chat", preset.key
            assert preset.opens_chat is True, preset.key


def test_a_chat_goal_needs_neither_a_form_nor_an_address() -> None:
    """Which is why it costs no new step: the one object the rollback
    cannot remove is not created, and the link stays the formality it is
    on a lead ad."""
    for preset in every_preset():
        if preset.opens_chat:
            assert preset.needs_lead_form is False, preset.key
            assert preset.needs_link is False, preset.key


def test_the_chat_goals_carry_both_texts() -> None:
    for preset in every_preset():
        if preset.opens_chat:
            assert preset.welcome_message, preset.key
            assert preset.autofill_message, preset.key


def test_no_other_goal_carries_either() -> None:
    """A greeting on a goal that cannot show one is a promise the
    catalogue is keeping and nothing can honour."""
    for preset in every_preset():
        if not preset.opens_chat:
            assert preset.welcome_message == "", preset.key
            assert preset.autofill_message == "", preset.key


def test_the_customers_own_line_is_the_same_sentence_everywhere() -> None:
    """It follows from the goal, not from the business. Asking a clinic to
    write the message its patient sends *to* it has no good answer on
    either side, which is why it is never asked."""
    lines = {p.autofill_message for p in every_preset() if p.opens_chat}

    assert len(lines) == 1


def test_the_greeting_fits_what_meta_accepts() -> None:
    """Meta refuses the creative past three hundred characters, five calls
    into a sequence that has already uploaded a picture."""
    for preset in every_preset():
        assert len(preset.welcome_message) <= MAX_GREETING_CHARS, preset.key
        assert len(preset.autofill_message) <= MAX_GREETING_CHARS, preset.key


def test_a_chat_preset_names_no_placement_either() -> None:
    """Where the tap lands and where the ad is *shown* are two questions.

    Answering the second per goal is how a preset comes to carry a
    placement Meta has taken off its own list - on a goal nobody can
    choose, so nothing ever says so. No preset names one and the loader
    refuses the block; this is the chat half of that rule.
    """
    for preset in every_preset():
        if preset.opens_chat:
            assert names_a_placement(preset.targeting) == (), preset.key


# --- What the loader refuses ---------------------------------------------
BASE = """
provider: meta
category: cafe
label: "Kafe"
version: 1
targeting_base:
  age_min: 20
presets:
  - goal: messages
    label: "Xabar"
    objective: OUTCOME_ENGAGEMENT
    optimization_goal: CONVERSATIONS
    billing_event: IMPRESSIONS
    sends_to: chat
    call_to_action: MESSAGE_PAGE
    destination_type: MESSENGER
"""


def test_a_chat_preset_with_no_greeting_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, BASE + '    autofill_message: "Salom"\n')

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "both required" in str(caught.value)


def test_a_chat_preset_with_no_autofill_is_refused(tmp_path: Path) -> None:
    """Half a welcome message greets somebody and then leaves their own
    message box empty, which reads as deliberate and is worse than the
    provider's own default."""
    _write(tmp_path, BASE + '    welcome_message: "Salom"\n')

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "both required" in str(caught.value)


def test_a_greeting_on_a_goal_that_opens_no_chat_is_refused(tmp_path: Path) -> None:
    _write(
        tmp_path,
        BASE.replace("sends_to: chat", "sends_to: form")
        + '    welcome_message: "Salom"\n    autofill_message: "Salom"\n',
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "cannot greet" in str(caught.value)


# --- The suggestion the wizard opens on ----------------------------------
def test_the_suggestion_carries_the_businesss_own_name() -> None:
    preset = CATALOG.find(provider=PROVIDER, category="restaurant", goal="messages")

    assert suggested_greeting(preset=preset, business=CAFE).startswith("Osh Markazi")


def test_a_goal_that_opens_no_chat_has_nothing_to_suggest() -> None:
    """So the caller can ask without checking first."""
    preset = CATALOG.find(provider=PROVIDER, category="restaurant", goal="leads")

    assert suggested_greeting(preset=preset, business=CAFE) == ""


def test_a_profile_with_no_name_yet_leaves_the_box_empty() -> None:
    """The one place in this package that swallows a failure instead of
    raising, and the reason is what is being built: everything else here
    builds a spec that spends money, and this fills a text box somebody is
    about to read. An empty box is a legal answer with a defined meaning -
    the provider greets them instead."""
    preset = CATALOG.find(provider=PROVIDER, category="restaurant", goal="messages")

    assert (
        suggested_greeting(
            preset=preset, business=BusinessProfile(name="", category="restaurant")
        )
        == ""
    )


def test_opens_chat_is_the_one_destination_and_not_a_family() -> None:
    """Read off our word rather than Meta's. A phone goal and a store goal
    are also "not a website" and neither opens a thread."""
    assert opens_chat("chat") is True
    for other in ("form", "website", "phone", "store", "nothing"):
        assert opens_chat(other) is False


# --- Two optional strings, one gate --------------------------------------
CONFIRMED = (Interest(label="Restoranlar", query="Restaurants", external_id="6003"),)


def _built(
    category: str,
    goal: str,
    *,
    welcome: str = "",
    link: str = "",
    channel: str = DEFAULT_CHAT_CHANNEL,
    questions: tuple[str, ...] = (),
):
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category=category,
            goal=goal,
            daily_budget_minor=1000,
            interests=CONFIRMED,
            chat_channel=channel,  # type: ignore[arg-type]
        ),
        business=CAFE if category == "restaurant" else SHOP,
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        link=link,
        welcome=welcome,
        questions=questions,
    )


def test_a_chat_launch_with_no_greeting_is_allowed() -> None:
    """The half of the pair most easily got wrong. An empty greeting
    reads exactly like an empty address one field away, and refusing it
    would stop a working ad over a sentence Meta writes itself."""
    built = _built("restaurant", "messages")

    assert built.welcome_text == ""
    validate_launchable(built)


def test_a_website_launch_with_no_address_still_is_not() -> None:
    """The other half, so the rule above cannot be read as "an optional
    string never stops a launch"."""
    with pytest.raises(DestinationLinkMissing):
        validate_launchable(_built("ecommerce", "traffic"))


def test_the_greeting_is_carried_and_the_catalogues_line_beside_it() -> None:
    """Carried rather than looked up again: the launch sequence has no
    catalogue and must not grow one."""
    built = _built("restaurant", "messages", welcome="Salom!")

    assert built.welcome_text == "Salom!"
    assert built.autofill_text
    assert built.opens_chat is True


def test_nothing_is_substituted_for_a_cleared_greeting() -> None:
    """Somebody who cleared the box asked for Meta's own greeting. Putting
    the catalogue's back would be answering the question after they
    answered it."""
    assert _built("restaurant", "messages", welcome="").welcome_text == ""


def test_a_lead_launch_carries_neither_line() -> None:
    built = _built("restaurant", "leads")

    assert built.welcome_text == ""
    assert built.autofill_text == ""
    assert built.opens_chat is False


# --- Which surface the conversation opens on -----------------------------
def test_the_two_channels_and_the_words_that_go_with_them() -> None:
    """Named together because Meta pairs them and refuses the mismatch: an
    Instagram Direct ad takes ``INSTAGRAM_MESSAGE`` and nothing else."""
    assert CHANNELS["messenger"].destination_type == "MESSENGER"
    assert CHANNELS["messenger"].call_to_action == "MESSAGE_PAGE"
    assert CHANNELS["instagram"].destination_type == "INSTAGRAM_DIRECT"
    assert CHANNELS["instagram"].call_to_action == "INSTAGRAM_MESSAGE"


def test_the_channel_decides_both_of_them() -> None:
    picked = _built("restaurant", "messages", channel="instagram")

    assert picked.destination_type == "INSTAGRAM_DIRECT"
    assert picked.call_to_action == "INSTAGRAM_MESSAGE"


def test_the_default_is_the_one_every_advertiser_has() -> None:
    """A page is what this product already requires; an Instagram account
    is connected to it by hand or not at all."""
    assert DEFAULT_CHAT_CHANNEL == "messenger"
    assert _built("restaurant", "messages").destination_type == "MESSENGER"


def test_a_channel_this_version_no_longer_knows_falls_back() -> None:
    """A stored answer, not a caller's argument. A launch holding a name
    that has been retired is not a launch to refuse - it is one whose
    owner gets the option everybody has."""
    assert _built("restaurant", "messages", channel="telegram").destination_type == (
        "MESSENGER"
    )


def test_no_other_goal_is_touched_by_it() -> None:
    """The answers are what the wizard collected, not a set assembled per
    goal - so a lead launch carries a channel and ignores it."""
    lead = _built("restaurant", "leads", channel="instagram")

    assert lead.destination_type == "ON_AD"
    assert lead.call_to_action == "SIGN_UP"


# --- Questions under the greeting ------------------------------------------
def test_every_chat_goal_offers_questions_meta_accepts() -> None:
    for preset in every_preset():
        if not preset.opens_chat:
            assert preset.chat_questions == ()
            continue
        assert 1 <= len(preset.chat_questions) <= MAX_CHAT_QUESTIONS, preset.category
        assert all(
            0 < len(question) <= MAX_QUESTION_CHARS
            for question in preset.chat_questions
        )


def test_questions_on_a_goal_that_opens_no_chat_are_refused(tmp_path: Path) -> None:
    _write(
        tmp_path,
        BASE.replace("sends_to: chat", "sends_to: form")
        + '    chat_questions: ["Narxi qancha?"]\n',
    )

    with pytest.raises(CatalogError):
        PresetCatalog.from_directory(tmp_path)


def test_the_owners_questions_are_trimmed_and_kept_once() -> None:
    assert clean_questions(["  Narxi  qancha? ", "", "narxi qancha?", "Bormi?"]) == (
        "Narxi qancha?",
        "Bormi?",
    )


def test_the_questions_are_carried_beside_the_greeting() -> None:
    built = _built("restaurant", "messages", welcome="Salom!", questions=("Bormi?",))

    assert built.welcome_questions == ("Bormi?",)


def test_questions_without_a_greeting_are_not_carried() -> None:
    assert (
        _built("restaurant", "messages", questions=("Bormi?",)).welcome_questions == ()
    )


def test_a_lead_launch_carries_no_questions() -> None:
    built = _built("restaurant", "leads", welcome="Salom!", questions=("Bormi?",))

    assert built.welcome_questions == ()
