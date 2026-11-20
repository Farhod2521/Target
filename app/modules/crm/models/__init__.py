from app.modules.crm.models.crm import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
    CrmStageMove,
)

__all__ = [
    "CrmActivity",
    "CrmCard",
    "CrmLostReason",
    "CrmMember",
    "CrmSetup",
    "CrmStage",
    "CrmStageMove",
]

# Registers the flush listener that writes ``CrmStageMove`` rows: wherever
# the models are loaded, a card cannot change column unrecorded.
from app.modules.crm import moves as _moves  # noqa: E402, F401
