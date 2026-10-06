"""Persistence for the deterministic decision assessment (Phase 40).

``record`` is pure (no database): it turns a stored snapshot into assessment rows by calling the
existing Phase 38.3 ``build_decision_context`` - the same engine path the Phase 39 read service
uses. ``repository`` is the only part that touches PostgreSQL. This package lives outside
``cfi.decision`` because that package is deliberately database-free.
"""

from cfi.decision_store.record import (
    AssessmentRecord,
    StoredSnapshot,
    record_from_context,
    records_for_snapshot,
)
from cfi.decision_store.repository import (
    DecisionAssessmentRepository,
    persist_assessments_safely,
)

__all__ = [
    "AssessmentRecord",
    "DecisionAssessmentRepository",
    "StoredSnapshot",
    "persist_assessments_safely",
    "record_from_context",
    "records_for_snapshot",
]
