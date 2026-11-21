"""The showcase account: one made-up customer who uses everything.

``seed`` writes a learning centre with thirty days behind it (and thirty
more before those, so every figure has something to be compared with):
adverts and their daily numbers, the leads they brought, a CRM board three
managers worked, the bills paid for it. ``wipe`` takes it all away again.

Nothing of it exists at Meta. The account's connection carries
``ConnectionStatus.DEMO``, which every screen reads as connected and no
job or click may ask a token of - see ``integrations.selectors.demo``. The
same mark keeps the account out of the office's counts, and is the only
thing ``wipe`` will delete by.

    python -m tools.demo_seed --email demo@example.com --password ...
    python -m tools.demo_delete --email demo@example.com
"""

from app.modules.demo.seed import Seeded, seed
from app.modules.demo.wipe import NotADemo, wipe

__all__ = ["NotADemo", "Seeded", "seed", "wipe"]
