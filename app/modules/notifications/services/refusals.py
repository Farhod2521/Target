from app.modules.agent.exceptions import SuggestionClosed, SuggestionStale

CLOSING = (SuggestionClosed, SuggestionStale)


def refusal_words(exc: Exception) -> str:
    return str(exc) or "Hozir bajarib bo'lmadi. Kabinetda ko'ring."


__all__ = ["CLOSING", "refusal_words"]
