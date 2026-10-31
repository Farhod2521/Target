`action_refusal` explains why Meta refused something the owner pressed outside
a launch or a change to a running advert: a file sent to the library, an
audience, a place search, connecting the account. Written once per operation
and Meta code, with no chat: the screen shows it in the refusal dialog.

Like `change_refusal`, **the answer is kept and served to the next
advertiser** (`chat_refusal_answers`, the key's first word names the
operation), so the prompt forbids the advertiser's own names and figures. Its
version is stored as `action-v1`.

Links are names; `app.modules.chat.selectors.change_refusal` fills in the
reader's own addresses.
