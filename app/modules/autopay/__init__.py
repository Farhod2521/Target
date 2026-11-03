"""Rahmat (Multicard) autopay: a card kept as a token, and the plan renewed from it.

The payer adds a card on Multicard's own page; only Multicard's token for it
is kept, encrypted. Shortly before a paid plan runs out, a bill for the same
plan is opened and its amount taken from the card. The debit is announced by
Multicard's ordinary signed payment callback, so the bill is settled - and
the plan extended - exactly as when the payer pays on the page.

Off until ``MULTICARD_AUTOPAY_ENABLED`` is set, and only where Rahmat itself
is configured.
"""
