"""Canonical enumerations — must match DATA_DICTIONARY.md §3."""

from __future__ import annotations

from enum import StrEnum


class QualityStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    STALE = "stale"
    PARTIAL = "partial"
    ESTIMATED = "estimated"
    REVISED = "revised"
    SUSPECT = "suspect"
    CONFLICTING = "conflicting"
    PROVIDER_ERROR = "provider_error"


class EvidenceCategory(StrEnum):
    """R2 evidence hierarchy — attached to every value the API or AI returns."""

    OBSERVED = "observed"
    METRIC = "metric"
    SIGNAL = "signal"
    REGIME = "regime"
    AI_INTERPRETATION = "ai_interpretation"
    HYPOTHESIS = "hypothesis"
    USER_DECISION = "user_decision"


class PitReliability(StrEnum):
    NATIVE = "native"
    VENDOR_PIT = "vendor_pit"
    BACKFILLED_LATEST = "backfilled_latest"


class EvidenceClass(StrEnum):
    """How directly an actor label is evidenced (R5)."""

    DIRECT = "direct"
    ATTRIBUTED = "attributed"
    INFERRED = "inferred"


class AuthType(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
