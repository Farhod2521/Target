"""A transcript: the words, each with when it was said."""

from pydantic import BaseModel, ConfigDict, Field


class Word(BaseModel):
    """One spoken word and its place in the recording, in seconds."""

    model_config = ConfigDict(frozen=True)

    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Transcript(BaseModel):
    """Everything that was said, as text and word by word."""

    model_config = ConfigDict(frozen=True)

    language: str = ""
    text: str = ""
    words: tuple[Word, ...] = ()

    @property
    def silent(self) -> bool:
        """Nothing was said: music, noise, or no sound at all."""
        return not self.words
