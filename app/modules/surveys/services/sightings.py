"""Who was shown a survey and who put it off: the office's funnel."""

import uuid

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.surveys.models import SurveySighting


def note_seen(db: Session, *, survey_id: uuid.UUID | str, owner_id: uuid.UUID) -> None:
    """The first sight stands; asking again on the next page adds nothing."""
    now = utcnow()
    db.execute(
        insert(SurveySighting)
        .values(
            id=uuid.uuid4(),
            created_at=now,
            updated_at=now,
            survey_id=uuid.UUID(str(survey_id)),
            owner_id=owner_id,
        )
        .on_conflict_do_nothing(constraint="uniq_survey_sighting")
    )


def note_later(db: Session, *, survey_id: uuid.UUID | str, owner_id: uuid.UUID) -> None:
    note_seen(db, survey_id=survey_id, owner_id=owner_id)
    db.execute(
        update(SurveySighting)
        .where(
            SurveySighting.survey_id == uuid.UUID(str(survey_id)),
            SurveySighting.owner_id == owner_id,
        )
        .values(later_count=SurveySighting.later_count + 1, updated_at=utcnow())
    )
