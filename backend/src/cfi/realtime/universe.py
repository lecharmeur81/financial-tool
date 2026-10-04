"""Versioned parameters and fixed vocabulary for Real-Time Intelligence (Phase 35).

Mirrors every other ``*_parameters``/``universe`` module in this codebase (e.g.
``cfi.alerts.universe``, ``cfi.anomaly.universe``): declared policy constants, not values fitted
to any one metric's own distribution (R4), versioned so a future change is additive, not a silent
edit of today's behavior.
"""

from __future__ import annotations

__all__ = [
    "AI_MIN_INTERVAL_SECONDS",
    "AI_TRIGGER_SEVERITIES",
    "CYCLE_LOCK_KEY",
    "CYCLE_LOCK_TTL_SECONDS",
    "DATA_ARRIVAL_DEBOUNCE_KEY",
    "DATA_ARRIVAL_DEBOUNCE_SECONDS",
    "EVENT_SCHEMA_VERSION",
    "STATUS_VALUES",
]

EVENT_SCHEMA_VERSION = "intelligence_event.v1"

# --------------------------------------------------------------------------- AI-trigger policy
# ("Claude analysis should be considered only for events that are sufficiently significant.") Only
# the two upper severities (identical vocabulary to ``cfi.alerts.universe.SEVERITY_LEVELS`` —
# never a second ranking, R13) are "significant" enough to even be considered; "notable"/"info"
# transitions are exactly the kind of per-tick noise the spec says never to send to Claude.
AI_TRIGGER_SEVERITIES = frozenset({"elevated", "critical"})

# ("not already analyzed recently"): a declared minimum spacing between AI requests this service
# raises on its own initiative, independent of — and in addition to — the existing AI-trigger
# rate limit (``cfi.api.limiter.AI_TRIGGER_LIMIT``) and monthly budget
# (``Settings.ai_monthly_budget_usd``), neither of which this module bypasses or re-implements
# (R13).
AI_MIN_INTERVAL_SECONDS = 1800.0  # 30 minutes

STATUS_VALUES: tuple[str, ...] = ("new", "ai_requested")

# ("If concurrency protection is needed, use the existing database/queue mechanisms rather than
# inventing an unrelated locking system.") Redis already backs the Celery broker (ADR-0023) and
# the response cache (``cfi.cache.redis``) — this is the same client, used for the simplest
# standard distributed-lock idiom (``SET key value NX EX ttl``), not a new locking framework.
CYCLE_LOCK_KEY = "cfi:realtime:cycle_lock"
CYCLE_LOCK_TTL_SECONDS = 150  # comfortably longer than the task's own time_limit

# ("New data arrival should be able to trigger downstream change detection... Avoid noisy event
# generation.") Market data ingestion is the highest-frequency arrival this platform has (as
# often as every 30 seconds, ``cfi.worker.schedule.INTERVAL_SECONDS``); a bare debounce (one
# cycle request honoured, every one within this window skipped) is a "reasonable cadence" for
# triggering the deterministic cycle without calling it once per tick, while the unchanged
# 15-minute periodic sweep still covers every domain regardless of arrival timing.
DATA_ARRIVAL_DEBOUNCE_KEY = "cfi:realtime:data_arrival_debounce"
DATA_ARRIVAL_DEBOUNCE_SECONDS = 60
