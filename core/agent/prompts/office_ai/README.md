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
  as `[?]`, so the look-ups work out changes, shares and conversions
  themselves.
