from app.common.choices import Choices


class SurveyAudience(Choices):
    EVERYONE = "everyone"
    PLANS = "plans"
    PEOPLE = "people"


SURVEY_AUDIENCE_LABELS = {
    SurveyAudience.EVERYONE: "Barchaga",
    SurveyAudience.PLANS: "Tarifdagilarga",
    SurveyAudience.PEOPLE: "Tanlanganlarga",
}


class QuestionKind(Choices):
    TEXT = "text"
    CHOICE = "choice"
    NUMBER = "number"


QUESTION_KIND_LABELS = {
    QuestionKind.TEXT: "Matn",
    QuestionKind.CHOICE: "Tanlov",
    QuestionKind.NUMBER: "Raqam",
}


class SurveyState(Choices):
    DRAFT = "draft"
    TRANSLATING = "translating"
    READY = "ready"
    FAILED = "failed"


SURVEY_STATE_LABELS = {
    SurveyState.DRAFT: "Qoralama",
    SurveyState.TRANSLATING: "Tarjima qilinmoqda",
    SurveyState.READY: "Tayyor",
    SurveyState.FAILED: "Tarjima bo'lmadi",
}


class ResponseChannel(Choices):
    WEB = "web"
    MINIAPP = "miniapp"
    BOT = "bot"


RESPONSE_CHANNEL_LABELS = {
    ResponseChannel.WEB: "Sayt",
    ResponseChannel.MINIAPP: "Mini app",
    ResponseChannel.BOT: "Telegram bot",
}
MAX_QUESTIONS = 10
NUMBER_FLOOR = 0
NUMBER_CEILING = 10
MIN_OPTIONS = 2
MAX_OPTIONS = 10
NAME_MAX = 120
TITLE_MAX = 200
INTRO_MAX = 500
QUESTION_MAX = 300
OPTION_MAX = 120
TRANSLATION_PROMPT = "survey_translation"
RELATED_TYPE = "survey"
TRANSLATION_STALE_MINUTES = 10
SNOOZE_SECONDS = 10 * 60
SNOOZE_KEY = "survey:snooze:{user_id}"
ANSWER_TEXT_MAX = 2000
