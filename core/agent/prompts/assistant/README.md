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

Run the live cases after every change: `python -m tools.assistant_eval`.
