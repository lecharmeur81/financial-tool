"""Inbound HTTP rate limiting (Phase 28, Priority 2).

One shared ``Limiter``, keyed by client IP, applied only to specific mutating routes via the
``@limiter.limit(...)`` decorator — never to Celery tasks (``worker/app.py``, ``worker/schedule.py``
are untouched; a periodic job and an HTTP request are different things and this is HTTP-only).

Storage is in-memory (slowapi's default): each process counts its own hits. That is fine for this
project's single-instance dev/prod-lite deployment (CLAUDE.md A1), but a known limitation for a
horizontally-scaled, multi-instance production deployment, where each instance would enforce the
limit independently rather than sharing one counter — a shared backend (e.g. Redis, via slowapi's
``storage_uri``) would be needed there. Not implemented here: no multi-instance deployment exists
yet (R13: do not build for a deployment shape that is not this project's).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# The two AI-triggering endpoints (analyst.analyze, brief.generate) each queue a real Anthropic
# API call that costs money against Settings.ai_monthly_budget_usd — a much tighter limit than
# plain database writes, to stop a runaway or malicious client from burning through the monthly
# AI budget or flooding the "ai" Celery queue.
AI_TRIGGER_LIMIT = "5/hour"

# Every other protected mutating endpoint is a plain, already-cheap database write (create/close/
# cancel a paper trade, create/update a journal decision, acknowledge/resolve an alert, trigger one
# alert-evaluation cycle). Generous enough not to bother normal single-user usage, bounded enough
# to blunt an accidental client-side retry loop.
MUTATION_LIMIT = "30/minute"
