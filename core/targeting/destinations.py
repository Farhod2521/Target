"""Where an ad sends the person who taps it - in the domain's own words.

**Not** :attr:`~core.targeting.presets.Preset.destination_type`, and the two
being separate is the whole content of this module. That one is Meta's
field, sent verbatim, and its allowed values depend on the objective beside
it: ``OUTCOME_SALES`` takes ``WEBSITE`` and ``OUTCOME_TRAFFIC`` does not
take it at all, even though both goals send somebody to the same website.
So the provider's field cannot answer "does this goal go to a site" - it
answers "which of this objective's destinations did you pick", and for a
traffic ad set the honest answer is to send nothing.

This is the question the launch sequence actually asks, and it is ours:
**what does the ad have to be built out of.** A form on the ad needs a lead
form created and hung on the creative; a website needs a link and a button
that opens it. Two shapes, two code paths, and the preset is what says
which - as data, never as ``if goal == "sales"``.

Reading it off the provider's field is what this replaces: that works only
while ``ON_AD`` is the one shape built, and breaks on a second one carrying
a *blank* provider field.

One of the six is answered twice. "chat" says a conversation opens; **which
messaging surface** it opens on is a second question with a second answer,
and the table below is what pairs each surface with the provider words that
go with it. It lives here rather than in the catalogue for one reason: a
value identical in all twelve preset files is a product decision wearing a
preset's clothes.
"""

from dataclasses import dataclass
from typing import Final, Literal

# Where the tap lands.
#
#   form     a form Meta hosts, on the ad itself
#   website  the advertiser's own site, through a link on the creative
#   phone    the dialler, prefilled
#   chat     a conversation - Messenger, Instagram Direct, WhatsApp
#   store    a place on a map, to walk into
#   nothing  nowhere. An awareness ad is seen and not acted on
#   profile  the business's own Instagram profile, inside the app
#
# Six rather than a boolean, and the three this product cannot build yet are
# here rather than left out: the catalogue keeps the presets designed for
# them, and a preset whose destination has no name would have to say so
# with an empty string - which reads as "forgotten" rather than as
# "designed, not built".
AdDestination = Literal[
    "form", "website", "phone", "chat", "store", "nothing", "profile"
]

DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"form", "website", "phone", "chat", "store", "nothing", "profile"}
)

# The shapes the launch sequence knows how to build today.
#
# A fact about **this repository**, not about the provider - which is why it
# is expressed in our vocabulary and lives here rather than in a table of
# Meta's fields. Every stage that teaches the sequence a new shape adds one
# entry, and nothing else in the catalogue has to be re-derived.
#
# Five of the six. None of the last two needs a new step, a new object or
# anything the rollback has to learn: they are the same creative with a
# different button on it - a number to dial, or no button at all.
#
# ``store`` is the one that stays out, and it is not waiting on this
# repository. Meta optimises and reports a store visit against a **Place
# Page Set**, which is built from a parent Page with child location Pages
# under it; a single shop with a single Page is not that.
#
# ``profile`` is the same creative again, with the profile's own address in
# the button - built from the connected account, never typed.
DELIVERABLE: Final[frozenset[str]] = frozenset(
    {"form", "website", "chat", "phone", "nothing", "profile"}
)


# Which messaging surface the conversation opens on.
#
# **Our word on the left, the provider's on the right**, and the two are
# named together because they are one decision: Meta pairs each surface
# with the button that opens it, and sending a Messenger button beside an
# Instagram destination is refused. Splitting them across two files is how
# they would come to disagree.
#
# Not in the catalogue: a value identical in all twelve files is a product
# decision wearing a preset's clothes. Each of these lines would be copied
# twelve times and read as though a category had chosen it.
ChatChannel = Literal["messenger", "instagram"]


@dataclass(frozen=True, slots=True)
class Channel:
    """One surface, and the two provider words that go with it."""

    # What the ad set is told. Also what the creative's button carries as
    # its app destination - the same word in both places at this version,
    # which is a fact about today's vocabulary rather than a rule.
    destination_type: str
    # Meta refuses the pairing when this is wrong: an Instagram Direct ad
    # takes ``INSTAGRAM_MESSAGE`` and nothing else.
    call_to_action: str


CHANNELS: Final[dict[str, Channel]] = {
    "messenger": Channel(destination_type="MESSENGER", call_to_action="MESSAGE_PAGE"),
    "instagram": Channel(
        destination_type="INSTAGRAM_DIRECT", call_to_action="INSTAGRAM_MESSAGE"
    ),
}

# Messenger, and not because it is better. It is the one every advertiser
# here has: a page is what this product already requires, and an Instagram
# account is connected to it by hand or not at all. A default that needed
# a second connection would be a default that fails for whoever has not
# made one.
DEFAULT_CHAT_CHANNEL: Final[ChatChannel] = "messenger"


def channel(name: str) -> Channel:
    """The surface behind a channel name, falling back to the safe one.

    Falls back rather than raising, and it is the one place in this module
    that does. The name arrives from a stored answer, and a launch holding
    a channel this version no longer knows is not a launch to refuse -
    it is a launch whose owner chose the option that everybody has.
    """
    return CHANNELS.get(name, CHANNELS[DEFAULT_CHAT_CHANNEL])


def is_deliverable(destination: str) -> bool:
    """Whether the sequence can build an ad that lands here."""
    return destination in DELIVERABLE


def needs_lead_form(destination: str) -> bool:
    """Whether a lead form has to be created and hung on the creative.

    The one step of the sequence that cannot be undone - Meta refuses a
    DELETE on a form - so a goal that does not need one must not make one.
    """
    return destination == "form"


def opens_chat(destination: str) -> bool:
    """Whether tapping the ad opens a conversation rather than a page.

    What this decides is the **button**. A chat ad's call to action carries
    ``app_destination`` instead of a link, and an ad built the other way is
    not a broken chat ad - it is a working website ad, sending somebody who
    was promised a conversation to a page instead. Nothing on any screen
    afterwards would say so.

    It also decides whether the wizard asks for a greeting, which is the
    one question this destination adds and the only one it can: the
    provider hosts the conversation, so there is nothing else to build.
    """
    return destination == "chat"


def needs_link(destination: str) -> bool:
    """Whether the ad has to carry the advertiser's own address.

    True only for the site. Every creative Meta accepts carries a link, but
    on the other five it is a formality nobody follows; here it is the
    product being sold, and sending the wrong one spends the advertiser's
    budget driving traffic somewhere that is not theirs.
    """
    return destination == "website"


def needs_phone(destination: str) -> bool:
    """Whether the ad has to carry a number the tap dials.

    The third field of its kind and the strictest of them. Meta takes the
    number in the button itself - ``{"link": "tel:+998..."}`` where an
    ordinary ad carries an address - and it takes it from nowhere else: not
    from the Page, not from the ad account, not from the preset.

    So an unanswered number is not a call ad without a number. It is a call
    ad whose button opens a **web page**, because that is what the other
    branch of the same key builds, and Meta accepts it. The campaign runs,
    reports clicks, and nobody rings.
    """
    return destination == "phone"


def shows_a_button(destination: str) -> bool:
    """Whether there is anywhere for a button to send anybody.

    False for exactly one destination, and it is the one that names itself:
    an awareness ad is seen and not acted on. Five of the six have a place
    the tap lands - a form, a site, a dialler, a thread, a map - and this
    one has none, so a button on it would be a promise of somewhere to go
    invented by the code that draws it.

    Meta has a value for that (``NO_BUTTON``) and the preset is what says
    so, like every other provider word. This function is what lets the gate
    and the tests state the rule in the domain's own vocabulary.
    """
    return destination != "nothing"


def opens_profile(destination: str) -> bool:
    """Whether tapping the ad opens the business's Instagram profile.

    What decides three things the other destinations never need. The
    button's address is the profile's, built from the connected account;
    the advert can only be shown on Instagram, because that is where the
    profile is; and the launch needs an Instagram account behind the page,
    because without one there is no profile to open.
    """
    return destination == "profile"
