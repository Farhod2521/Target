"""Office labels carry a code beside them, so another language can word them."""

from app.modules.ads.selectors.launch_settings import (
    AUTOFILLED,
    OPEN_ANSWER,
    WITH_OPTIONS,
    FormQuestion,
)
from app.modules.boards.constants import SEED_COLUMNS, is_default_column_name


def test_every_question_kind_label_has_a_code() -> None:
    codes = {
        label: FormQuestion(label="", kind_label=label, options=(), by="").kind
        for label in (AUTOFILLED, WITH_OPTIONS, OPEN_ANSWER)
    }

    assert codes == {
        AUTOFILLED: "autofilled",
        WITH_OPTIONS: "options",
        OPEN_ANSWER: "open",
    }


def test_a_seeded_name_is_default_and_any_other_is_not() -> None:
    seed = SEED_COLUMNS[0]
    board, code, name = str(seed.board), seed.code, str(seed.name)

    assert is_default_column_name(board=board, code=code, name=name)
    assert not is_default_column_name(board=board, code=code, name=name + " 2")
    assert not is_default_column_name(board=board, code="no-such", name=name)
