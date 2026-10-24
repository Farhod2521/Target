"""Putting people into an audience Meta holds, and taking them back out."""

import secrets
from collections.abc import Sequence
from typing import Any, Final, Literal

from adskit.dto import AudienceMemberDTO

from metaads.client import GraphClient
from metaads.dto import MemberUploadRow
from metaads.parsing import parsed
from metaads.writing import delete_payload, graph_client, is_dry_run_id, post_object

MAX_MEMBERS_PER_CALL: Final = 10_000

SCHEMA_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("email", "EMAIL"),
    ("phone", "PHONE"),
    ("first_name", "FN"),
    ("last_name", "LN"),
    ("city", "CT"),
    ("country", "COUNTRY"),
)

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
    """Post a customer list. The call that carries people towards Meta."""
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
    """Take people back out of an audience, by the digests that put them in."""
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
    """One list, in as many requests as Meta's cap needs."""
    fields = _schema_for(members)
    if dry_run or is_dry_run_id(audience_id) or not fields:
        return _rehearsed(audience_id=audience_id, members=members, fields=fields)

    batches = [
        members[start : start + MAX_MEMBERS_PER_CALL]
        for start in range(0, len(members), MAX_MEMBERS_PER_CALL)
    ]
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
    """One request's worth of rows, in the direction asked for."""
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
    """The keys at least one of these rows actually carries."""
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
    """What a rehearsal reports: everything accepted, nothing sent."""
    return MemberUploadRow(
        audience_id=audience_id,
        num_received=len(members) if fields else 0,
    )


def _session_id() -> int:
    """A number Meta will accept as naming one multi-part upload."""
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
