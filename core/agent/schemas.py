"""The shapes Claude is required to answer in.

Pydantic here, unlike the dataclasses next door. These are wire formats -
they become a JSON Schema that the API enforces as a tool signature - and
that is the one job pydantic does that a dataclass cannot. Domain values
stay dataclasses; see ``contracts.py``.

Every field carries a description, because the description is the only
instruction the model sees at the moment it fills that field in. A prompt
can ask for Uzbek labels; a field description is what makes the model
remember on the fourteenth one.

Lists are bounded on both ends. An unbounded list is how a well-behaved
prompt returns forty interests one day and two the next.
"""

from typing import Final, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# The provider's own bounds, imported rather than restated. ``core.targeting``
# clamps a spec to these before it is sent, so the numbers are its to know; a
# second copy here is a second copy to change, and the half that gets missed
# is the half nobody sees until Meta refuses a campaign.
from core.targeting import (
    MAX_AGE,
    MAX_CHAT_QUESTIONS,
    MAX_QUESTION_CHARS,
    MAX_RADIUS_KM,
    MIN_AGE,
    MIN_RADIUS_KM,
)

# How many life events and behaviours a draft may name. Past this the
# audience is narrowed by too many conditions at once.
MAX_TRAITS: Final = 4

# What a lead form may ask. The first four are questions the provider fills
# in from the person's own profile, which is why a form built from them
# converts several times better than one asking them to type. ``custom`` is
# the escape hatch and costs a keystroke every time it is used.
QuestionKind = Literal["full_name", "phone", "email", "city", "custom"]


class InterestProposal(BaseModel):
    """One interest, named twice and justified once."""

    label: str = Field(
        description="Qiziqish nomi o'zbekcha, foydalanuvchi o'qishi uchun.",
        max_length=120,
    )
    query: str = Field(
        description=(
            "The same interest as Meta's own English catalogue name, e.g. "
            "'Restaurants', 'Barbershop'. This string is searched for "
            "verbatim, so use the common English term, not a translation."
        ),
        max_length=120,
    )
    # Three or four words, not a sentence. This field is repeated once per
    # interest and a sentence apiece makes it the largest single thing the
    # model writes - two thirds of the answer, and the two thirds nobody
    # reads twice. It sits under a checkbox; a phrase is what fits there.
    reason: str = Field(
        description=(
            "Nega mos - 3-5 so'z, o'zbekcha, 70 belgidan oshmasin. Jumla emas."
        ),
        max_length=70,
    )
    recommended: bool = Field(
        description=(
            "True faqat eng mos 4-6 tasi uchun. Ular ekranda belgilangan "
            "holda ochiladi, qolganlari tanlanmagan turadi."
        )
    )


class AudienceProposal(BaseModel):
    """Age, gender and how far away, with the reasoning kept."""

    age_min: int = Field(
        description=f"Eng kichik yosh, {MIN_AGE}-{MAX_AGE}.",
        ge=MIN_AGE,
        le=MAX_AGE,
    )
    age_max: int = Field(
        description=f"Eng katta yosh, {MIN_AGE}-{MAX_AGE}.",
        ge=MIN_AGE,
        le=MAX_AGE,
    )

    # ``Literal`` rather than ``int``, because this schema is sent to the
    # API as a tool definition and an enum in it is checked on their side,
    # before a token of the answer is written. A bare int would let a stray
    # 0 or 3 through here, past the builder - which only ever filters this
    # list on the *edit* path - and all the way to Meta, where it surfaces
    # as a refused campaign at the one moment nothing can be done about it.
    genders: list[Literal[1, 2]] = Field(
        description=(
            "Bo'sh ro'yxat - hamma. [1] - erkaklar, [2] - ayollar. "
            "Mahsulot aniq bir jinsga qaratilmagan bo'lsa bo'sh qoldiring."
        ),
        max_length=2,
    )
    radius_km: int = Field(
        description=(
            "Biznes joylashuvidan qancha km. Restoran uchun 3-7, klinika "
            "uchun 10-15, ko'chmas mulk uchun 25+."
        ),
        ge=MIN_RADIUS_KM,
        le=MAX_RADIUS_KM,
    )
    reason: str = Field(
        description=(
            "Nega shu auditoriya - bitta jumla, o'zbekcha, 160 belgidan oshmasin."
        ),
        max_length=160,
    )

    @field_validator("age_min", "age_max", "radius_km", mode="before")
    @classmethod
    def _within_what_meta_allows(cls, value: object, info: ValidationInfo) -> object:
        """Pull a provider bound back inside itself instead of refusing the
        answer that carried it.

        A model that proposes sixteen for a moped shop is not making an
        argument the product could honour by asking again - Meta refuses to
        deliver below eighteen, so the nearest legal reading of "as young
        as possible" *is* eighteen. Refusing instead throws away the whole
        answer: the audience, the interests, the advert copy and the form
        questions, every one of them fine, over a field with one legal
        value in the direction the model was pointing.

        The cost of that refusal is what makes this worth doing rather than
        arguing about in the prompt. The constraint speaks only after a
        whole answer has been written, so the price of a single number is
        another call, another half-minute of somebody watching a spinner,
        and no guarantee the second answer keeps inside a bound the first
        one did not.

        The radius is here for the same reason. Leaving it out would be an
        asymmetry inside one model, where an age eight years low is
        repaired and a radius twenty kilometres wide is fatal. Both bounds
        belong to the provider, both are already clamped by
        ``core.targeting`` further down, and neither has a second reading.

        Only out-of-range numbers move. Anything else - a string, a null,
        a missing field - is handed on untouched, so the field constraints
        and pydantic's own message stay in charge of what is genuinely a
        malformed answer rather than an out-of-bounds one.
        """
        if not isinstance(value, int) or isinstance(value, bool):
            return value
        low, high = (
            (MIN_RADIUS_KM, MAX_RADIUS_KM)
            if info.field_name == "radius_km"
            else (MIN_AGE, MAX_AGE)
        )
        return min(max(value, low), high)

    @model_validator(mode="after")
    def _the_range_runs_upwards(self) -> "AudienceProposal":
        """Refused rather than repaired, unlike the clamp above.

        The two look like one rule and are not. An age outside the
        platform's bounds has exactly one legal reading in the direction
        the model was pointing, so it can be moved. A range that runs
        downwards has two - swap them, or one of the numbers is the typo -
        and guessing which produces an audience nobody asked for.

        ``core.targeting`` decides the same thing: ``clamp_age`` raises on
        an inverted range instead of sorting it. The problem is where it
        raises. Nothing in ``apps/`` catches ``InvalidTargeting``, so a
        proposal that got past validation here would be stored and blow up
        while the spec was being built - inside the guard that turns
        anything unlisted into "Xatolik yuz berdi", with no code the screen
        could translate and nothing for anybody to retry.

        Said here, it is a re-ask instead: the client hands the model this
        sentence and its own answer, and the fields that were right are
        kept.
        """
        if self.age_min > self.age_max:
            raise ValueError(f"age_min {self.age_min} is above age_max {self.age_max}")
        return self


class CreativeProposal(BaseModel):
    """One ad's words. The button is not chosen here - it follows from the goal
    and is decided where the creative is built - but the closing sentence has
    to ask for what that button does, which is why the prompt is told where it
    sends somebody.

    One of several. A launch builds up to three ads in one ad set, and each
    gets its own copy written from a different angle - which is the whole
    point of putting three up. What varies between them is the *approach*,
    not the vocabulary; the prompt is where that is enforced, because a
    schema cannot tell two paraphrases apart.
    """

    # Meta cuts the primary text off at about 125 characters on a phone
    # and hides the rest behind "See more". The limit is in the
    # description as well as in the field, and that
    # repetition is the point: ``max_length`` is a validator, and a
    # validator only speaks after the answer is written. The description is
    # the sentence the model reads *while* writing it - so a cap named only
    # in the field is a cap discovered by failing, which costs a whole
    # second attempt at a whole answer's latency.
    #
    # Three Uzbek sentences land within a few characters of three hundred,
    # which is exactly the shape of an intermittent refusal: most answers
    # fit and some do not.
    primary_text: str = Field(
        description=(
            "Reklamaning asosiy matni, o'zbekcha. 2-3 qisqa jumla, "
            "hammasi bo'lib 300 belgidan oshmasin. Aniq foyda, keyin nima "
            "qilish kerakligi. Emoji ishlatmang."
        ),
        max_length=300,
    )
    # The one field whose description is *stricter* than its validator, and
    # deliberately: forty is what fits on a phone, sixty is what would
    # actually be refused. Aiming at the first leaves room for the model to
    # miss by a word without costing a second attempt.
    headline: str = Field(
        description="Sarlavha, o'zbekcha, 40 belgidan oshmasin.",
        max_length=60,
    )
    description: str = Field(
        description="Qo'shimcha qator, o'zbekcha, 120 belgidan oshmasin.",
        max_length=120,
    )


class FormQuestion(BaseModel):
    """One question on the lead form."""

    kind: QuestionKind = Field(
        description=(
            "full_name, phone, email va city - Meta o'zi to'ldiradi. "
            "custom - foydalanuvchi qo'lda yozadi yoki tanlaydi."
        )
    )
    label: str = Field(
        description="Savol matni o'zbekcha. Standart turlar uchun ham yozing.",
        max_length=100,
    )
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Faqat custom uchun va faqat tanlov savoli bo'lsa. "
            "2-5 variant, o'zbekcha. Aks holda bo'sh."
        ),
        max_length=5,
    )


class QuestionOptions(BaseModel):
    """The answers a lead-form question offers, for one question.

    Its own call and its own shape, because it is asked at a different
    moment from everything else here: the questions are proposed with the
    campaign, and this is asked when the owner writes one of their own.
    """

    options: list[str] = Field(
        description=(
            "2-5 ta javob varianti, o'zbekcha, qisqa. "
            "Savolga tanlov mos kelmasa - bo'sh ro'yxat."
        ),
        max_length=5,
    )


class ChatQuestions(BaseModel):
    """The questions a customer taps under a chat advert's greeting.

    Asked only when the owner presses for questions, and only ever shown to
    them as rows to edit - a proposal, like the options above.
    """

    questions: list[str] = Field(
        description=(
            "3 ta savol, o'zbekcha (lotin), mijoz tilidan, har biri 40 "
            "belgigacha va savol belgisi bilan tugaydi."
        ),
        min_length=1,
        max_length=MAX_CHAT_QUESTIONS,
    )

    @field_validator("questions")
    @classmethod
    def _short(cls, value: list[str]) -> list[str]:
        kept = [" ".join(item.split()) for item in value]
        return [item for item in kept if 0 < len(item) <= MAX_QUESTION_CHARS]


class GoalIntent(BaseModel):
    """What an owner's own words ask the advert to bring.

    Keys rather than names, and only keys from the list the prompt gives:
    the answer is settled against the goals this business can actually
    launch - see ``core.agent.goal_reading`` - and anything else is dropped
    rather than shown.
    """

    goals: list[str] = Field(
        description=(
            "Goal keys from the offered list only. One when the words point "
            "at one result; two when they ask for two different results and "
            "neither is said to matter more; empty when they do not say what "
            "a customer should do."
        ),
        max_length=2,
    )
    quote: str = Field(
        description=(
            "The three to six words of the owner's text that decided the "
            "goal, copied exactly as written. Empty when goals is empty."
        ),
        max_length=80,
    )
    wants_sale: bool = Field(
        description=(
            "True when the owner wants people to buy online - pay on a site "
            "or put something in a basket - rather than get in touch."
        ),
    )


class GoalChoice(BaseModel):
    """Which row of the first step's table an owner's own words ask for.

    One row is the objective, where the result happens and what is
    maximised, together. Keys only, and only from the table the prompt
    lists - see ``core.agent.goal_reading.read_goal_choice``, which drops
    anything else.
    """

    choice: str = Field(
        description=(
            "One row key from the table. Empty when the words do not say what "
            "a customer should do."
        ),
        max_length=40,
    )
    alternatives: list[str] = Field(
        description=(
            "Zero to two other row keys, only when the words fit them as well "
            "as the choice. Never the choice again."
        ),
        max_length=2,
    )
    quote: str = Field(
        description=(
            "The three to six words of the owner's text that decided the "
            "choice, copied exactly as written. Empty when choice is empty."
        ),
        max_length=80,
    )
    wants_sale: bool = Field(
        description=(
            "True when the owner wants people to buy online - pay on a site "
            "or put something in a basket - rather than get in touch."
        ),
    )


class LaunchDraft(
    BaseModel,
    # What the model is told this object is. Without it the docstring below
    # would be sent in its place - and that is written for whoever edits
    # this file rather than for the model deciding which keys to write.
    json_schema_extra={
        "description": (
            "One campaign proposal: the audience, the interests, the life "
            "events that describe the customer, the adverts' words and the "
            "lead form's questions, each under its own key."
        )
    },
):
    """Everything the review screen shows, from one call.

    One call rather than several: the sections have to agree with each
    other. An audience proposed without knowing what the campaign is for
    produces ages that contradict the rest of the answer, and the person
    reading the screen sees two answers written by strangers.
    """

    audience: AudienceProposal
    interests: list[InterestProposal] = Field(
        description=(
            "8-10 ta qiziqish. Keng va tor aralash: keng bo'lsa yetkazish "
            "oson, tor bo'lsa mos odam ko'proq."
        ),
        # Six rather than eight at the bottom. The lower bound is not a
        # product rule - the screen is usable with six - it is a validation
        # failure waiting to happen, and a failure here costs a second full
        # call at twice the latency to produce the same answer again.
        min_length=6,
        max_length=12,
    )
    # Names copied from the category's closed list of life events and
    # behaviours, which the prompt carries - never a name of the model's
    # own. The draft is matched against that list when it is stored, so a
    # made-up name ticks nothing.
    #
    # Required rather than defaulted to empty. A key the schema lets the
    # model skip is a key it skips, and "skipped" and "none fits" would then
    # look the same.
    traits: list[str] = Field(
        description=(
            "Promptdagi hayot voqealari va odatlar ro'yxatidan faqat shu "
            "biznes mijoziga aniq mos keladiganlarining nomi, o'zgarishsiz. "
            "Mos kelmasa - bo'sh ro'yxat, bu odatiy javob."
        ),
        max_length=MAX_TRAITS,
    )

    @field_validator("traits", mode="before")
    @classmethod
    def _first_traits(cls, value: object) -> object:
        """The first few, rather than the whole draft refused for a fifth.

        A fifth trait that fits is not a wrong answer, and refusing it asked
        for the whole draft again - a second call for one extra name.
        """
        return value[:MAX_TRAITS] if isinstance(value, list) else value

    # **For the pictures that have no words of their own.** A file
    # uploaded to the library or picked from it is a picture and a file
    # name; nothing on it is something a customer has read. So the model
    # writes one advert per such picture, from what the owner said it is
    # about. A post still goes with its own caption and gets nothing here,
    # which is why the list may be empty.
    #
    # **No ceiling on the list, and that is deliberate.** How many pictures
    # a launch may hold is the account's setting, not the product's - this
    # layer cannot read it and must not carry a copy of it. A number
    # written here would be a second ceiling that the first one silently
    # outgrows, and the failure it would cause is the worst kind: a whole
    # proposal refused by validation, several seconds and a bill after it
    # was written, because the owner raised a limit in an .env file.
    #
    # What holds the count to the pictures is the prompt, which names the
    # exact number - ``build_draft.ad_copy_variables`` counts it - and the
    # pairing afterwards, which walks the variants and takes the advert
    # sitting at each one's index.
    creatives: list[CreativeProposal] = Field(
        default_factory=list,
        description=(
            "Promptda aytilgan sonda reklama - ro'yxatdagi har rasmga "
            "bittadan, o'sha tartibda. Har biri boshqa yondashuv: muammodan, "
            "natijadan yoki takliftan boshlanadi. Ro'yxat bo'sh bo'lsa - bo'sh."
        ),
    )
    # The fewest questions that let somebody follow up - name and phone are
    # almost always enough, and every extra question costs leads. The
    # schema description is what the model reads while filling the field
    # in, so it has to say the same thing the prompt does.
    #
    # Only for an advert that opens a form. Every other goal is asked with
    # ``LaunchDraftWithoutForm`` below.
    form_questions: list[FormQuestion] = Field(
        description="2-3 savol, kamida ism va telefon.",
        min_length=2,
        max_length=4,
    )


class LaunchDraftWithoutForm(LaunchDraft):
    """The same proposal, for an advert with no form behind it.

    A chat, a call, a website or a view shows nobody a question, so the list
    is fixed at empty instead of being written, billed and thrown away. The
    key stays, so everything that stores a ``LaunchDraft`` stores this too;
    a goal change throws the draft away and asks again with the other one.
    """

    form_questions: list[FormQuestion] = Field(
        default_factory=list,
        description="Bu reklamada forma yo'q - bo'sh ro'yxat.",
        max_length=0,
    )


class LaunchDraftDeepForm(LaunchDraft):
    """The same proposal, for an owner who asked for fewer, better leads.

    Up to seven questions rather than four: after the name and the number,
    the ones that tell a business whether this person is ready to buy.
    """

    form_questions: list[FormQuestion] = Field(
        description="4-7 savol, kamida ism va telefon, qolgani tanlov savoli.",
        min_length=4,
        max_length=7,
    )


class CreativeSection(BaseModel):
    """The ad copy alone, for the "try something else" button.

    Rewrites ``LaunchDraft.creatives``. Offered only when the launch has a
    picture that is not an Instagram post.

    A wrapper rather than a bare list, for the reason the two below it are
    wrappers: the structured-output tool takes an object, and a schema
    whose root is an array is a schema the model fills in inconsistently.

    No ceiling, for the reason ``LaunchDraft.creatives`` has none: the
    account's picture limit is not readable here.
    """

    creatives: list[CreativeProposal] = Field(min_length=1)


class InterestSection(BaseModel):
    """The interests alone, for the "try something else" button."""

    interests: list[InterestProposal] = Field(
        description=(
            "8-10 ta qiziqish. Keng va tor aralash: keng bo'lsa yetkazish "
            "oson, tor bo'lsa mos odam ko'proq."
        ),
        # The same eight-to-ten asked for above, accepted from six to
        # twelve for the same reason: the lower bound is not a product
        # rule, it is a validation failure waiting to happen, and one here
        # costs a second full call to produce the same answer again.
        min_length=6,
        max_length=12,
    )


class FormSection(BaseModel):
    """The lead form questions alone, for the same button."""

    form_questions: list[FormQuestion] = Field(min_length=2, max_length=4)


class DeepFormSection(BaseModel):
    """The lead form questions alone, for an owner who asked for fewer, better leads."""

    form_questions: list[FormQuestion] = Field(min_length=4, max_length=7)


class TranslatedTerm(BaseModel):
    """One typed name and the provider's word for it. Nothing else.

    Two fields rather than reusing ``InterestProposal``, which also carries
    a reason and a recommendation. Both would be written by the model, paid
    for, and thrown away unread by the caller - this answer only ever
    becomes a lookup key.
    """

    label: str = Field(
        description="Foydalanuvchi yozgani, o'zgarishsiz.",
        max_length=120,
    )
    query: str = Field(
        description="Meta katalogidagi inglizcha atama.",
        max_length=120,
    )


class TranslatedTerms(BaseModel):
    """Owner-typed interest names, turned into what the provider calls them.

    Batched: ten names is one call. Asking once per word is both slower and
    dearer for an answer of four tokens.
    """

    terms: list[TranslatedTerm] = Field(
        description=(
            "Har kiritilgan nom uchun bitta band, o'sha tartibda. "
            "Mos atama topilmasa, eng yaqin kengrog'ini bering."
        ),
        max_length=20,
    )


# How many entries one review call answers. The shortlist is sent in parts of
# this size: the faults the provider reports are proposed however many there
# are, and a list longer than the answer may be was a night lost whole.
MAX_NOTES: Final = 10
# How long one sentence beside a button may be - roughly three lines on a
# phone, which is as much as anybody reads there.
REASON_CHARS: Final = 220


class DecisionNote(BaseModel):
    """One shortlisted change, judged and explained.

    The model never adds an entry and never changes what a change *is* -
    the ad set, the kind and the figure were all decided by arithmetic
    before this call. Two things are asked of it: whether the numbers it
    was shown actually support the change, and how to say so to somebody
    who does not know what an ad set is.
    """

    index: int = Field(
        description=(
            "Ro'yxatdagi taklif raqami, o'zgarishsiz. Har taklif uchun "
            "bitta band, hech biri tushib qolmasin."
        ),
        ge=0,
    )
    keep: bool = Field(
        description=(
            "True - taklif ko'rsatilsin. False - raqamlar buni "
            "oqlamaydi, ko'rsatilmasin. Shubha bo'lsa True qo'ying: "
            "qarorni foydalanuvchi qabul qiladi."
        )
    )
    # Shown to the advertiser verbatim, so it is written as a sentence and
    # not as a label.
    reason: str = Field(
        description=(
            "Nega - 1-2 jumla, 220 belgidan oshmasin, oddiy til bilan. Aniq "
            "raqamni ayting (necha kun, qancha sarf, nechta natija). "
            "'adset', 'CPM', 'optimizatsiya' kabi so'zlar ishlatilmaydi. "
            "keep=False bo'lsa ham nega deb yozing."
        ),
    )

    @field_validator("reason")
    @classmethod
    def _short(cls, value: str) -> str:
        """Trimmed to a phone's three lines rather than refused.

        A sentence a few words too long was a whole answer thrown away - and
        with it the night's proposals, every one of them, over one clause.
        Cut at the last word that fits, and said to be cut.
        """
        text = " ".join(value.split())
        if len(text) <= REASON_CHARS:
            return text
        cut = text[: REASON_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return cut + "…"


class AgentReview(BaseModel):
    """The night's shortlist, gone through one entry at a time.

    One call for the whole list rather than one per change. The entries
    compete for the same budget and the same attention - dropping one
    because another already covers it is a judgement that needs both in
    view - and three separate calls cost three times as much to produce an
    answer that is less consistent.
    """

    notes: list[DecisionNote] = Field(
        description="Har taklif uchun bitta band, kelgan tartibda.",
        max_length=MAX_NOTES,
    )


class GoogleSearchDraft(
    BaseModel,
    json_schema_extra={
        "description": (
            "One Google Search advert: the searches it should appear for, "
            "the searches it must not, and the headlines and descriptions "
            "Google combines into the advert."
        )
    },
):
    """What the Google wizard's words step shows, from one call.

    The limits are Google's own and are named in each description as well
    as enforced by the field, for the reason ``CreativeProposal`` gives: a
    validator only speaks after the answer is written, and a refusal costs
    a whole second call. The bottoms are lower than the prompt asks for, so
    a slightly short answer is usable rather than refused.
    """

    keywords: list[str] = Field(
        description=(
            "10-20 ta kalit so'z: odamlar Google'da shu biznesni qidirganda "
            "yozadigan iboralar. O'zbekcha (lotin) va ruscha aralash, 2-4 "
            "so'zdan. Har biri 80 belgidan oshmasin. Biznes nomini yozmang."
        ),
        min_length=5,
        max_length=20,
    )
    negative_keywords: list[str] = Field(
        description=(
            "0-15 ta minus so'z: reklama ko'rinmasligi kerak bo'lgan "
            "qidiruvlar (masalan 'bepul', 'ish', 'vakansiya', 'o'zi qilish')."
        ),
        max_length=15,
    )
    headlines: list[str] = Field(
        description=(
            "10-15 ta sarlavha, har biri 30 belgidan OSHMASIN (bo'sh joy ham "
            "hisoblanadi). Har biri boshqacha: xizmat, foyda, shahar, "
            "chaqiruv. Takrorlanmasin. Emoji va undov belgisi yo'q."
        ),
        min_length=3,
        max_length=15,
    )
    descriptions: list[str] = Field(
        description=(
            "4 ta tavsif, har biri 90 belgidan OSHMASIN. Aniq foyda va nima "
            "qilish kerakligi. Takrorlanmasin."
        ),
        min_length=2,
        max_length=4,
    )
    path1: str = Field(
        default="",
        description="Manzil qatoridagi birinchi so'z, 15 belgidan oshmasin.",
        max_length=15,
    )
    path2: str = Field(
        default="",
        description="Ikkinchi so'z, 15 belgidan oshmasin. path1 bo'lmasa bo'sh.",
        max_length=15,
    )
