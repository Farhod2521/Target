"""Reads the Central Bank's rates for every day not held yet.

Run once after the deploy that adds ``fx_rates``:

    python -m app.modules.metrics.rates

The first run reads the past 400 days, the newest first, about twenty
minutes. It may be stopped and started again: a day already held is not
asked for twice. After it, the task on the clock keeps the table up to date
by itself. Until the recent days are held, figures that cross currencies
answer «no rate» rather than a number.
"""

from app.common.db import utcnow
from app.modules.metrics.services.rates import store_rates
from app.worker import task_session


def main() -> None:
    with task_session() as db:
        print(f"rates added: {store_rates(db, now=utcnow())}")


if __name__ == "__main__":
    main()
