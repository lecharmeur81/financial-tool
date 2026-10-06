"""Decision history / change intelligence (Phase 41): deterministic comparison of persisted
``sig.decision_assessment`` rows. Nothing here assesses anything; ``compare`` and ``history`` are
pure, ``repository`` is a read-only query."""

from cfi.decision_history.compare import (
    AssessmentChange,
    ChangeDirection,
    ChangeKind,
    MalformedAssessmentError,
    PersistedAssessment,
    compare_assessments,
)
from cfi.decision_history.history import (
    HISTORY_CONTRACT_VERSION,
    HistoryEntry,
    HistoryState,
    build_history,
)
from cfi.decision_history.repository import DecisionHistoryRepository

__all__ = [
    "HISTORY_CONTRACT_VERSION",
    "AssessmentChange",
    "ChangeDirection",
    "ChangeKind",
    "DecisionHistoryRepository",
    "HistoryEntry",
    "HistoryState",
    "MalformedAssessmentError",
    "PersistedAssessment",
    "build_history",
    "compare_assessments",
]
