`change_refusal` explains why Meta refused a change to a running advert -
a pause, a budget, an audience, a delete - and says, in numbered steps, what
the advertiser does about it. Written once per Meta code and subcode, with
no chat: the campaigns screen shows it under the failed change.

Like `refusal_answer`, **the answer is kept and served to the next
advertiser** who meets the same refusal (`chat_refusal_answers`, keys under
`core.chat.refusal.change_refusal_key`), so the prompt forbids the
advertiser's own names and figures. Its version is stored as `change-v1`
so the launch prompt's stale versions never retire it.

Links are names; `app.modules.chat.selectors.change_refusal` fills in the
reader's own addresses.
