"""Launches' Meta ids: are they still there, and why is the proposal locked.

Read-only by default. With ``--forget-missing`` it removes from ``created_refs``
only the ids Meta says no longer exist (or are DELETED); nothing is sent to Meta
except GET requests.

A launch being created or created keeps its ids whatever Meta says: they are
the record of what it made.

    docker compose exec -T api python - <launch_id> [<launch_id> ...] < tools/launch_refs_check.py
    docker compose exec -T api python - <launch_id> ... --forget-missing < tools/launch_refs_check.py
    docker compose exec -T api python - <launch_id> --restore-made < tools/launch_refs_check.py

``--restore-made`` puts a launch back to created when the wizard reopened it
after it was made and its campaign still lives at Meta.
"""

import sys
from uuid import UUID

from adskit.errors import ProviderError
from metaads.adapter import session
from metaads.errors import MetaAPIError

from app import models as _models  # noqa: F401
from app.bootstrap import register_providers
from app.common.db import SessionLocal
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import ROLLBACK_ORDER, LaunchStatus, LaunchStep
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.launches import stranded_refs
from app.modules.ads.services.access import launch_account_and_token
from app.modules.ads.services.launch import is_discardable

MADE = (LaunchStatus.CREATING, LaunchStatus.CREATED)


def main(launch_ids: list[str], forget: bool, restore: bool) -> None:
    register_providers()
    db = SessionLocal()
    for launch_id in launch_ids:
        print("=" * 20, launch_id)
        check(db, launch_id, forget, restore)


def check(db, launch_id: str, forget: bool, restore: bool) -> None:  # type: ignore[no-untyped-def]
    launch = db.get(CampaignLaunch, UUID(launch_id))
    if launch is None:
        print("launch not found")
        return
    print(
        "status:", launch.status, "| step:", launch.step, "| error:", launch.error_code
    )
    print("created_refs:", launch.created_refs)
    print("stranded:", stranded_refs(db, launch))
    print(
        "locked:",
        campaign_type_locked(launch=launch),
        "| discardable:",
        is_discardable(db, launch=launch),
    )

    _account, token = launch_account_and_token(db, launch=launch)
    gone: list[tuple[str, str]] = []
    live_campaign = False
    with session(token) as graph:
        for step in ROLLBACK_ORDER:
            for external_id in ref_field.ref_ids(launch.created_refs or {}, step):
                try:
                    got = graph.get(external_id, fields="id,name,effective_status")
                    state = str(got.get("effective_status", ""))
                    print(
                        f"{step} {external_id}: EXISTS {state} {got.get('name', '')!r}"
                    )
                    if state == "DELETED":
                        gone.append((step, external_id))
                    elif step == LaunchStep.CAMPAIGN:
                        live_campaign = True
                except (MetaAPIError, ProviderError) as exc:
                    print(f"{step} {external_id}: ERROR code={exc.code!r} {exc}")
                    if "does not exist" in str(exc) or "Unsupported get request" in str(
                        exc
                    ):
                        gone.append((step, external_id))

    print("missing at Meta:", gone)
    if restore:
        _restore(db, launch, live_campaign=live_campaign)
        return
    if not forget or not gone:
        return
    if launch.status in MADE:
        print("not forgotten: a created launch keeps its ids")
        return
    refs = fresh(launch, "created_refs")
    for step, external_id in gone:
        ref_field.clear(refs, step, external_id)
    db.commit()
    db.refresh(launch)
    print("after:", launch.created_refs)
    print(
        "locked:",
        campaign_type_locked(launch=launch),
        "| discardable:",
        is_discardable(db, launch=launch),
    )


def _restore(db, launch: CampaignLaunch, *, live_campaign: bool) -> None:  # type: ignore[no-untyped-def]
    """Put back a created launch the old wizard reopened, while its campaign lives.

    Its ids are kept; only the status says again what Meta says: it was made.
    """
    if launch.status in MADE:
        print("not restored: already", launch.status)
        return
    if not live_campaign:
        print("not restored: its campaign is not live at Meta")
        return
    launch.status = str(LaunchStatus.CREATED)
    launch.step = str(LaunchStep.VERIFY)
    launch.progress = 100
    db.commit()
    print("restored: status created, step verify")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(
        [item for item in args if not item.startswith("--")],
        "--forget-missing" in args,
        "--restore-made" in args,
    )
