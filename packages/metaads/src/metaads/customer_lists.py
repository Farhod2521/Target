"""Putting people into an audience Meta holds, and taking them back out.

**The one module in this package that carries anything about a person**,
which is why it is a file of its own rather than half of
:mod:`metaads.audiences`. That module creates and deletes a container; this
one fills and empties it, and the two have different rules, different
failure modes and - for anybody auditing where personal data goes - very
different weight.

What arrives here is already hashed. ``AudienceMemberDTO`` validates every
field as a SHA-256 digest, so a plaintext email address cannot be put in
one and therefore cannot reach this module. Normalising and hashing happens
in the domain, which has the phone-number parser and knows the advertiser's
country; see ``core.audiences.members`` for why that side of the boundary
and not this one.

**The two directions are one piece of code on purpose.** Adding and
removing send the same rows, in the same schema, to the same edge, and they
differ in the HTTP verb and in nothing else that matters. Written twice
they would drift, and the drift would be silent: a schema built one way for
an upload and another way for a removal takes somebody out of a column they
were never put into, and no error is reported by anybody.

Meta's two rules that shape everything below:

* **Ten thousand rows per request.** A longer list is split here, not by
  the caller: a caller splitting it would be a caller that had learned
  Meta's batching rules.
* **One schema per request.** The keys are named once and every row is
  positional against them, so the order is fixed and a row missing a key
  sends an empty string in its place.
"""

import secrets
from collections.abc import Sequence
from typing import Any, Final, Literal

from adskit.dto import AudienceMemberDTO

from metaads.client import GraphClient
from metaads.dto import MemberUploadRow
from metaads.parsing import parsed
from metaads.writing import delete_payload, graph_client, is_dry_run_id, post_object

# Meta's own cap on one request. A list longer than this is split.
MAX_MEMBERS_PER_CALL: Final = 10_000

# Meta's spelling for each key of a customer list, against the domain's.
#
# This table is the ``META_CURRENCY_PLACES`` of personal data: the domain
# names a field ``first_name`` and every platform abbreviates it
# differently - Meta as ``FN``, Google as ``hashed_first_name`` - so the
# provider's vocabulary stops here and one dictionary is the whole of it.
#
# Order is fixed rather than incidental. It decides the column order of
# every row sent, and a schema whose order changed between two batches of
# one upload would file phone numbers under email addresses.
SCHEMA_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("email", "EMAIL"),
    ("phone", "PHONE"),
    ("first_name", "FN"),
    ("last_name", "LN"),
    ("city", "CT"),
    ("country", "COUNTRY"),
)

# Which way the rows are going. Not a boolean: a flag argument at four call
# sites reads as ``True`` and says nothing, and this one decides whether
# personal data is being handed over or withdrawn.
Direction = Literal["add", "remove"]
ADD: Final[Direction] = "add"
REMOVE: Final[Direction] = "remove"


def add_members(
    *,
    audience_id: str,
    members: Sequence[AudienceMemberDTO],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> MemberUploadRow:
    """Post a customer list. The call that carries people towards Meta.

    Everything in ``members`` is already a digest and cannot be otherwise.
    """
    return _send(
        audience_id=audience_id,
        members=members,
        token=token,
        client=client,
        dry_run=dry_run,
        direction=ADD,
    )


def remove_members(
    *,
    audience_id: str,
    members: Sequence[AudienceMemberDTO],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> MemberUploadRow:
    """Take people back out of an audience, by the digests that put them in.

    The only handle there is. Meta will not read a customer list back, so
    the plaintext has to be turned into the same digests a second time -
    which is why every path that erases a person calls this *before* it
    erases what it knows about them, and never after.

    Removing somebody who is not in the audience is not an error. Meta
    counts the row as received and takes it off nobody, which is what makes
    the honest call possible at all: whether a particular person is in a
    particular audience cannot be known from this side.
    """
    return _send(
        audience_id=audience_id,
        members=members,
        token=token,
        client=client,
        dry_run=dry_run,
        direction=REMOVE,
    )


def _send(
    *,
    audience_id: str,
    members: Sequence[AudienceMemberDTO],
    token: str,
    client: GraphClient | None,
    dry_run: bool,
    direction: Direction,
) -> MemberUploadRow:
    """One list, in as many requests as Meta's cap needs.

    **The schema is the union of what this list actually holds**, not all
    six keys. A column nobody filled would be a column of empty strings on
    every row - bytes Meta charges nothing for and a person reading the
    request has to rule out - and Meta matches on whichever keys are
    present regardless.

    Rows missing one of the chosen keys send an empty string in its place,
    which is Meta's own answer to a partial row in a multi-key list.

    The counts that come back are summed across the parts: a caller wants
    to know how many of *its list* were taken, not how many of the last
    batch.
    """
    fields = _schema_for(members)
    if dry_run or is_dry_run_id(audience_id) or not fields:
        return _rehearsed(audience_id=audience_id, members=members, fields=fields)

    batches = [
        members[start : start + MAX_MEMBERS_PER_CALL]
        for start in range(0, len(members), MAX_MEMBERS_PER_CALL)
    ]
    # A session only when there is more than one request to tie together,
    # and only on the way in. Meta accepts a single call without one, and
    # inventing a session for it would put an identifier in the audit trail
    # that names nothing. A removal never carries one: a session exists so
    # Meta can report several requests as one upload, and there is no such
    # aggregate on the way out.
    session_id = _session_id() if direction == ADD and len(batches) > 1 else 0

    received = 0
    invalid = 0
    samples: dict[str, str] = {}
    answered = MemberUploadRow(audience_id=audience_id)

    with graph_client(client, token) as graph:
        for sequence, batch in enumerate(batches, start=1):
            answered = _one_batch(
                audience_id=audience_id,
                batch=batch,
                fields=fields,
                session_id=session_id,
                sequence=sequence,
                is_last=sequence == len(batches),
                token=token,
                client=graph,
                direction=direction,
            )
            received += answered.num_received
            invalid += answered.num_invalid_entries
            samples.update(answered.invalid_entry_samples)

    return MemberUploadRow(
        audience_id=answered.audience_id or audience_id,
        session_id=answered.session_id or (str(session_id) if session_id else ""),
        num_received=received,
        num_invalid_entries=invalid,
        invalid_entry_samples=samples,
    )


def _one_batch(
    *,
    audience_id: str,
    batch: Sequence[AudienceMemberDTO],
    fields: tuple[tuple[str, str], ...],
    session_id: int,
    sequence: int,
    is_last: bool,
    token: str,
    client: GraphClient,
    direction: Direction,
) -> MemberUploadRow:
    """One request's worth of rows, in the direction asked for.

    The verb is the whole difference, and it is a real DELETE rather than a
    POST that means one: an access log where somebody's personal data was
    withdrawn has to say so, because that log is the evidence when an
    erasure is questioned.
    """
    data: dict[str, Any] = {
        "payload": {
            "schema": [meta_key for _, meta_key in fields],
            "data": [_row(member, fields) for member in batch],
        }
    }
    if session_id:
        data["session"] = {
            "session_id": session_id,
            "batch_seq": sequence,
            "last_batch_flag": is_last,
        }

    path = f"{audience_id}/users"
    send = post_object if direction == ADD else delete_payload
    payload = send(path=path, data=data, token=token, client=client)
    return parsed(MemberUploadRow, payload)


def _row(member: AudienceMemberDTO, fields: tuple[tuple[str, str], ...]) -> list[str]:
    """One person as a row of digests, in the schema's own order."""
    return [getattr(member, name) for name, _ in fields]


def _schema_for(
    members: Sequence[AudienceMemberDTO],
) -> tuple[tuple[str, str], ...]:
    """The keys at least one of these rows actually carries.

    Empty when the list is empty or holds nothing but blank rows, which is
    what makes the caller's "nobody to send" case answerable without a
    request: a call with an empty schema is refused by Meta with an error
    about a parameter rather than with the truth, which is that there was
    nobody in the list.
    """
    return tuple(
        (name, meta_key)
        for name, meta_key in SCHEMA_KEYS
        if any(getattr(member, name) for member in members)
    )


def _rehearsed(
    *,
    audience_id: str,
    members: Sequence[AudienceMemberDTO],
    fields: tuple[tuple[str, str], ...],
) -> MemberUploadRow:
    """What a rehearsal reports: everything accepted, nothing sent.

    Counting the rows rather than answering zero, because a dry run is
    something a person reads to check their own list before sending it, and
    "0 received" from a rehearsal of nine hundred rows reads as a problem
    with the nine hundred rows.
    """
    return MemberUploadRow(
        audience_id=audience_id,
        num_received=len(members) if fields else 0,
    )


def _session_id() -> int:
    """A number Meta will accept as naming one multi-part upload.

    Random rather than derived from the clock, because this package has no
    clock - and rather than derived from the audience, because two uploads
    into the same audience are two sessions and Meta would merge their
    counts.
    """
    return secrets.randbits(48)


__all__ = [
    "ADD",
    "MAX_MEMBERS_PER_CALL",
    "REMOVE",
    "SCHEMA_KEYS",
    "Direction",
    "add_members",
    "remove_members",
]
