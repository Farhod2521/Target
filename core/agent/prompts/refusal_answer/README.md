`refusal_answer` explains one refused launch and says, in numbered steps,
what the advertiser does about it. It is free text, like `chat_answer`, and
goes through the same figure gate.

**The answer is kept and served to the next advertiser** who meets the same
refusal - see `apps.chat.models.RefusalAnswer` and
`core.chat.refusal.refusal_key`. That is why the prompt forbids the
advertiser's own names and figures: the reader's own case is shown above
the answer, in Meta's words, and the answer below it has to be true for
everyone with the same code.

Links are names, not addresses: the model writes `[[tolov]]` from the list
in the facts and `core.chat.links` fills in the reader's own address when
the answer is drawn. A refusal this product caused
(`apps.chat.constants.OUR_FAULT_KEYS`) is answered without steps.
