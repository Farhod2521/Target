"""What can go wrong between a picker and a rule.

Every one of these is a situation the advertiser can correct on the screen
they are looking at: a source the provider does not build from, an action
it does not offer for that source, a window longer than it will look back.

None of them carries a sentence. Each carries the values a sentence would
need, because the wording belongs to the Django layer in the reader's
language - a message written in Uzbek here is one that cannot be
translated and cannot be logged.
"""


class AudienceRuleError(Exception):
    """Base for everything this module raises."""


class SourceNotSupported(AudienceRuleError):
    """This provider builds no audience from this kind of source.

    Reachable from a real screen rather than only from a bug: the set of
    sources is the provider's answer, and a form drawn from one provider's
    answer can be submitted after the account has moved to another.
    """

    def __init__(self, *, kind: str) -> None:
        super().__init__(f"no audience can be built from {kind!r}")
        self.kind = kind


class ActionNotSupported(AudienceRuleError):
    """The source exists; this is not something it reports people doing.

    Both halves travel, because neither alone identifies the problem: a
    lead form does not report a purchase and a pixel does not report a
    message, and "unsupported action" without the source names nothing.
    """

    def __init__(self, *, kind: str, action: str) -> None:
        super().__init__(f"{kind!r} does not report {action!r}")
        self.kind = kind
        self.action = action


class RetentionTooLong(AudienceRuleError):
    """The window asked for is longer than the provider will look back.

    Carries the maximum as well as the request, because the only useful
    thing a screen can say here is the number that would have worked.
    """

    def __init__(self, *, kind: str, days: int, maximum: int) -> None:
        super().__init__(f"{kind!r} looks back at most {maximum} days, not {days}")
        self.kind = kind
        self.days = days
        self.maximum = maximum


class RetentionNotOffered(AudienceRuleError):
    """A window this product does not put in front of anybody.

    Not the same failure as :class:`RetentionTooLong` and worth telling
    apart. That one is the provider's limit; this one is a value that never
    appeared in the picker, which means a hand-edited form rather than a
    person choosing badly.
    """

    def __init__(self, *, days: int) -> None:
        super().__init__(f"{days} is not one of the windows this product offers")
        self.days = days


class BreadthNotOffered(AudienceRuleError):
    """A width this product does not put in front of anybody.

    The twin of :class:`RetentionNotOffered` and reached the same way: the
    value never appeared in a picker, so a request carrying one is a
    hand-edited form rather than a person choosing badly. Providers accept
    far more than the three offered - Meta takes twenty - and the extra
    seventeen are choices nobody could describe the difference between.
    """

    def __init__(self, *, breadth: str) -> None:
        super().__init__(f"{breadth!r} is not one of the widths this product offers")
        self.breadth = breadth


class CountryUnknown(AudienceRuleError):
    """There is no country to build the audience inside.

    Not a validation nicety. Every platform builds a lookalike out of one
    country's population, so a missing code is not a field left blank - it
    is the operation having no meaning. It happens for a real reason: the
    country comes from the advertiser's own profile, and a profile filled
    in before that field existed has nothing in it.

    Carries whatever was there, which is usually the empty string and
    occasionally a country *name* somebody typed - and the two want
    different sentences from whoever renders this.
    """

    def __init__(self, *, country: str) -> None:
        super().__init__(f"{country!r} is not a country an audience can be built in")
        self.country = country


__all__ = [
    "ActionNotSupported",
    "AudienceRuleError",
    "BreadthNotOffered",
    "CountryUnknown",
    "RetentionNotOffered",
    "RetentionTooLong",
    "SourceNotSupported",
]
