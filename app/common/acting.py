"""The business one request works in, for code that asks «which page and
account is the cabinet on?».

The cabinet's answer lives in the database: the owner's current page and
account, the same for every request. A request that names a business (the
``X-Business`` header) is answered about that business instead, without the
owner's own choice being moved: the pair is kept here for the length of the
request, and the selectors that read the current page and account return it.

It is also how a member of a business works its adverts: the request runs as
the business's owner, on the business's pair, and ``actor_id`` keeps who it
really was.

A business may advertise on other networks too, from one account on each.
Those are kept in ``accounts``; a request that names a business is answered
about that account, and about none where the business has none on the
network. ``ads`` is what a member may do with the adverts of each network;
it is empty for the owner, who may do everything.

Kept in a context variable, as the request's language is: set by the async
dependency, it is seen by the endpoint and everything it calls, and by
nothing outside the request. A background task starts with none; what it
needs of the pair is given to it as arguments.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Acting:
    business_id: uuid.UUID
    owner_id: uuid.UUID
    actor_id: uuid.UUID
    page_id: uuid.UUID | None
    ad_account_id: uuid.UUID | None
    accounts: tuple[tuple[str, uuid.UUID], ...] = ()
    ads: tuple[tuple[str, str], ...] = ()

    @property
    def by_member(self) -> bool:
        return self.actor_id != self.owner_id

    @property
    def account_ids(self) -> frozenset[uuid.UUID]:
        """Every ad account the business advertises from."""
        found = {account_id for _, account_id in self.accounts}
        if self.ad_account_id is not None:
            found.add(self.ad_account_id)
        return frozenset(found)

    def account(self, provider: str) -> uuid.UUID | None:
        """The business's account on a network other than Meta."""
        return dict(self.accounts).get(str(provider))

    def allows(self, provider: str, *, write: bool) -> bool:
        """Whether who is acting may read, or change, this network's adverts."""
        if not self.by_member:
            return True
        level = dict(self.ads).get(str(provider))
        return level is not None and (not write or level == "edit")


_current: ContextVar[Acting | None] = ContextVar("acting", default=None)


def acting() -> Acting | None:
    return _current.get()


def acting_for(owner_id: uuid.UUID) -> Acting | None:
    """The business this request works in, when it is this owner's."""
    held = _current.get()
    return held if held is not None and held.owner_id == owner_id else None


def require_network(owner_id: uuid.UUID, provider: str, *, write: bool) -> None:
    """Refuse a member of the business this request names who holds no grant
    over this network's adverts. Nothing is asked of a request that names no
    business, or of the owner."""
    held = acting_for(owner_id)
    if held is not None and not held.allows(provider, write=write):
        from app.modules.businesses.exceptions import NoAccess

        raise NoAccess


def act(held: Acting | None) -> None:
    _current.set(held)


@contextmanager
def override(held: Acting | None) -> Iterator[None]:
    token = _current.set(held)
    try:
        yield
    finally:
        _current.reset(token)
