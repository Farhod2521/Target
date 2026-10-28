"""Handing work to the worker. Tasks are imported inside, as ``tasks`` imports these."""


def queue_prepare(*, link_id: str) -> None:
    from app.modules.destinations.tasks import prepare_sheet_task

    prepare_sheet_task.delay(link_id)


def queue_delivery(*, link_id: str) -> None:
    from app.modules.destinations.tasks import deliver_to_sheet_task

    deliver_to_sheet_task.delay(link_id)


def queue_revoke(*, link_id: str) -> None:
    from app.modules.destinations.tasks import revoke_sheet_token_task

    revoke_sheet_token_task.delay(link_id)


def queue_check(*, link_id: str) -> None:
    from app.modules.destinations.tasks import check_sheet_link_task

    check_sheet_link_task.delay(link_id)
