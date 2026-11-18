`office_translation` puts a text the office wrote in one language into the
others, in one call: the answer an owner reads when Meta refuses them
(«Meta xatolari»), or a ready answer the assistant gives («AI chat»). The
answer is `core.agent.office_translation.OfficeTranslation` and is used
only when `checked` finds it to be the same text - the same `[[links]]`,
steps and list lines. See `app.modules.assistant.services.translate`. The
office can correct any language afterwards.
