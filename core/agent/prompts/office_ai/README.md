`office_ai` is the prompt of the office's own assistant
(`/api/v2/office/ai`): people who run Targetolog ask about the product as a
business - sign-ups, payments, plans, what waits - and it answers from the
office's read-only figures.

- The whole file is the cached system prompt. Today's date and who is
  asking (and whether they see money) follow it, uncached.
- Look-ups are `core/officeai/tools.py`; what each returns is
  `app/modules/officeai/selectors/facts.py`. Money look-ups are left out
  of the list for roles that do not see money on the dashboard.
- Figures pass `core/chat/verify.py`: a figure no look-up returned is shown
  as `[?]`, so the look-ups work out changes, differences, shares and
  conversions themselves. Three other spellings pass: a looked-up day by
  its month's name, a looked-up amount cut short ("12,45 mln"), and the row
  numbers of a list.
- v2: the figures rules say the above, and that a list cut short is spoken
  of only by the rows given.
