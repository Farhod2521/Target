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

    @property
    def by_member(self) -> bool:
        return self.actor_id != self.owner_id


_current: ContextVar[Acting | None] = ContextVar("acting", default=None)


def acting() -> Acting | None:
    return _current.get()


def acting_for(owner_id: uuid.UUID) -> Acting | None:
    """The business this request works in, when it is this owner's."""
    held = _current.get()
    return held if held is not None and held.owner_id == owner_id else None


def act(held: Acting | None) -> None:
    _current.set(held)


@contextmanager
def override(held: Acting | None) -> Iterator[None]:
    token = _current.set(held)
    try:
        yield
    finally:
        _current.reset(token)
