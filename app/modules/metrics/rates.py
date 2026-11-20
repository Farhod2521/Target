"""Reads the Central Bank's rates for every day not held yet.

Run once after the deploy that adds ``fx_rates``:

    python -m app.modules.metrics.rates

The first run reads the past 400 days, about twenty minutes. It may be
stopped and started again: it goes on from the last day it kept. After it,
the task on the clock keeps the table up to date by itself.
"""

from app.common.db import utcnow
from app.modules.metrics.services.rates import store_rates
from app.worker import task_session


def main() -> None:
    with task_session() as db:
        print(f"rates added: {store_rates(db, now=utcnow())}")


if __name__ == "__main__":
    main()
