"""API key authentication (Phase 28, Priority 1).

Applied only to mutating endpoints (POST/PUT/PATCH/DELETE) and the two AI-triggering endpoints
(``analyst.analyze``, ``brief.generate``) — the Next.js frontend only ever issues GETs (Phase 27
audit), so every GET/read endpoint stays open, intentionally.

Fail-secure design: ``Settings`` refuses to construct at all when
``CFI_ENVIRONMENT=production`` and no ``CFI_API_KEY`` is configured (see
``cfi.core.config.Settings._api_key_required_in_production``) — the app (and every worker) refuses
to boot rather than silently serving unauthenticated mutating traffic. By the time this dependency
runs, a production deployment is therefore guaranteed to have ``settings.api_key`` set, so the only
remaining branches here are: no key configured (dev/test — pass through) and a key configured (any
environment — require a matching header).
"""

from __future__ import annotations

import secrets

from fastapi import Request

from cfi.core.errors import UnauthorizedError

API_KEY_HEADER = "X-API-Key"


async def require_api_key(request: Request) -> None:
    settings = request.app.state.settings
    api_key = settings.api_key
    if api_key is None:
        # Dev/test only: Settings construction already guarantees this is unreachable when
        # CFI_ENVIRONMENT=production.
        return
    supplied = request.headers.get(API_KEY_HEADER)
    if supplied is None or not secrets.compare_digest(supplied, api_key.get_secret_value()):
        raise UnauthorizedError("Missing or invalid X-API-Key header.")
