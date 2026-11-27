`assistant` is the prompt of the one chat (`/api/v2/assistant`): the place a
client asks, fixes what is broken, changes their advertising and reaches a
person. It replaces nothing yet - `chat_answer` still answers the old chat.

It is built differently from `chat_answer`, for the faults that prompt had
at v28:

- **Two parts.** The text above the first `<!-- section: name -->` mark is
  the base and is sent as the cached system prompt. Each marked section is
  sent only when the question needs it (`core/assistant/prompt.py` decides,
  from the Context's headings and the person's words), in front of the
  Context, after the cached part.
- **Every look-up and every Context section is named**, one line each.
- **How to read a look-up's result arrives with the result**
  (`core/assistant/tools.py`, `READING`), not in the prompt.
- **`{{ language }}` is a language's name**, not its code.
- **No `%%SUPPORT%%` line.** Reaching a person is a look-up, `create_ticket`,
  which prepares a button; nothing is sent until the client presses it.

`v1` carries `chat_answer` v28's rules with the repeats taken out, and adds
"Solving a problem": call `account_health`, name the cause, give numbered
steps from the product's own words (`help_search`), and prepare a ticket
when no screen fixes it.

What makes an answer trustworthy is still not the prompt: figures pass
`core/chat/verify.py`, choice and reply lines are split off by
`core/chat/choices.py`, a change and a ticket are carried out by the
product only when their button is pressed.

`v2` adds what a look-up's "Ready fix" is and that it is copied, not
composed; that a code finds its own fix in `help_search`; the product's
name in the person's language («Targetolog AI», never "mahsulot"); and
correct spelling.

`v3` adds `report_gap`: a question left unanswered is told to the team,
who write the missing answer («Meta & AI» in the office) or build the
missing look-up. The person is never told.

`v6` adds `note_business`: what the person says about their own business
(what it sells, prices, terms) is prepared to be kept, with a button, and
the Context's "Business" section carries what was kept before.

`v7` adds `set_business_kind`: setup no longer asks what the business is,
so the Context says when its kind is only a guess from the page or not
known, and the assistant settles it in passing - one question, then a
confirm button.

Run the live cases after every change: `python -m tools.assistant_eval`.

`v4`: the client's request to Support is part of `account_health` (where
it stands, what it is about, whether Support wrote in the chat). A second
request for a problem Support has in hand is refused by `create_ticket`
unless the model marks it `new_problem`; the assistant no longer says «the
reply comes here» - Support usually calls.
Also in `v4`: `plans_and_prices` (the plans this person may buy, their
discount, the dollar rate in so'm - for a visitor too), and Meta's payment
standing of each ad account in `account_health` with the Billing Hub
address.
And `crm_outcomes`: per campaign, what the owner's CRM made of its leads
(Sotildi, Rad etildi, Sifatsiz, reasons). Hours of the day are never
offered (no such reading), and a change made in Ads Manager is said to be
made there, never by «somebody» - both in the readings that come with the
look-ups, the base having no room.

`v5`: «Where things are» - the cabinet's menu, pages, blocks and buttons
as the person sees them, so a place is named «Sozlash → Boshqaruv» and
never an address or a path. The look-ups' fix lines drop `/app/...` too,
and «Ulanishlar» is the block inside «Boshqaruv», not a page.
