from collections.abc import Mapping, Sequence

from telegramkit import Button

from app.modules.notifications.keys import survey_press_data
from app.modules.notifications.services.compose import escaped
from app.modules.surveys.constants import QuestionKind
from app.modules.surveys.selectors import AskedQuestion, DueSurvey

TICK = "✓ "
ECHO_CHARS = 120


def question_text(
    *, due: DueSurvey, step: int, answers: Mapping[str, Sequence[str]]
) -> str:
    question = due.questions[step]
    lines: list[str] = []
    if step == 0:
        lines.append(f"<b>{escaped(due.title)}</b>")
        if due.intro:
            lines.append(escaped(due.intro))
        lines.append("")
    asked = due.asked(answers)
    place = asked.index(step) + 1 if step in asked else step + 1
    count = f"{place}/{max(len(asked), place)}"
    lines.append(f"<b>{count}.</b> {escaped(question.text)}")
    hint = _hint(question)
    if hint:
        lines.append(f"<i>{hint}</i>")
    return "\n".join(lines)


def question_buttons(
    *, due: DueSurvey, step: int, picks: list[int]
) -> tuple[Button, ...]:
    question = due.questions[step]
    buttons: list[Button] = []
    if question.kind == QuestionKind.CHOICE and question.allows_many:
        for index, option in enumerate(question.options):
            mark = TICK if index in picks else ""
            buttons.append(
                Button(
                    text=f"{mark}{option}",
                    data=survey_press_data(step=step, action="t", value=index),
                    row="own",
                )
            )
        buttons.append(
            Button(
                text="Tayyor",
                data=survey_press_data(step=step, action="d"),
                row="own",
                style="primary",
            )
        )
    elif question.kind == QuestionKind.CHOICE:
        buttons.extend(
            (
                Button(
                    text=option,
                    data=survey_press_data(step=step, action="o", value=index),
                    row="own",
                )
                for index, option in enumerate(question.options)
            )
        )
    elif question.kind == QuestionKind.NUMBER:
        buttons.extend(
            Button(
                text=str(number),
                data=survey_press_data(step=step, action="n", value=number),
            )
            for number in question.numbers
        )
    if not question.is_required:
        buttons.append(
            Button(
                text="O'tkazib yuborish",
                data=survey_press_data(step=step, action="s"),
                row="own",
            )
        )
    buttons.append(
        Button(
            text="Keyinroq", data=survey_press_data(step=step, action="l"), row="own"
        )
    )
    return tuple(buttons)


def answered_line(*, question: AskedQuestion, values: list[str]) -> str:
    if not values:
        shown = "o'tkazib yuborildi"
    elif question.kind == QuestionKind.CHOICE:
        shown = ", ".join(question.options[int(value)] for value in values)
    elif question.kind == QuestionKind.TEXT and len(values[0]) > ECHO_CHARS:
        shown = values[0][:ECHO_CHARS] + "…"
    else:
        shown = values[0]
    return f"\n\n✅ {escaped(shown)}"


def _hint(question: AskedQuestion) -> str:
    if question.kind == QuestionKind.TEXT:
        return "Javobingizni shu yerga yozib yuboring."
    if question.kind == QuestionKind.CHOICE and question.allows_many:
        return "Bir nechtasini tanlab, «Tayyor»ni bosing."
    return ""
