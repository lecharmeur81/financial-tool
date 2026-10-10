"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cfi.api.errors import register_exception_handlers
from cfi.api.limiter import limiter
from cfi.api.middleware import REQUEST_ID_HEADER, request_context_middleware
from cfi.api.routes import (
    alerts,
    analyst,
    anomaly,
    brief,
    decision,
    decision_history,
    derivatives,
    divergence,
    health,
    ingestion,
    institutional,
    intelligence,
    intelligence_confirmation,
    intelligence_investment,
    intelligence_opportunities,
    intelligence_ranking,
    intelligence_risk,
    intelligence_snapshot,
    journal,
    liquidity,
    macro,
    market,
    market_structure,
    meta,
    paper,
    regime,
    retail,
    rotation,
    similarity,
    whales,
)
from cfi.cache.redis import check_redis, create_redis
from cfi.core.config import Settings, get_settings
from cfi.core.health import HealthCheck
from cfi.core.logging import configure_logging, get_logger
from cfi.db.engine import check_database, create_engine

log = get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    health_checks: Mapping[str, HealthCheck] | None = None,
) -> FastAPI:
    """Build the API.

    ``health_checks`` replaces the real database/Redis checks (tests only); when it is given,
    no connections are created.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checks is not None:
            app.state.health_checks = dict(health_checks)
            yield
            return

        engine = create_engine(settings)
        redis = create_redis(settings)
        app.state.engine = engine
        app.state.redis = redis
        app.state.health_checks = {
            "database": partial(check_database, engine),
            "redis": partial(check_redis, redis),
        }
        log.info("startup", environment=settings.environment, version=settings.version)
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()
            log.info("shutdown")

    # Production docs gating (Phase 28, Priority 3): the interactive docs and the raw OpenAPI
    # schema are a reconnaissance aid for an attacker and serve no purpose once there is no one
    # to click through them by hand, so both are disabled in production; every other environment
    # keeps them at their existing paths.
    is_production = settings.environment == "production"
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url=None if is_production else "/api/docs",
        openapi_url=None if is_production else "/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    # Rate limiting (Phase 28, Priority 2): app.state.limiter is slowapi's own convention; the
    # 429 it raises (slowapi.errors.RateLimitExceeded, a plain fastapi.HTTPException subclass) is
    # rendered by the StarletteHTTPException handler already registered below — no separate
    # handler needed, and the response keeps the project's one problem+json shape (ADR-0030)
    # instead of slowapi's own JSON format.
    app.state.limiter = limiter

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.middleware("http")(request_context_middleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(ingestion.router)
    app.include_router(market.router)
    app.include_router(institutional.router)
    app.include_router(whales.router)
    app.include_router(derivatives.router)
    app.include_router(liquidity.router)
    app.include_router(retail.router)
    app.include_router(macro.router)
    app.include_router(market_structure.router)
    app.include_router(divergence.router)
    app.include_router(regime.router)
    app.include_router(similarity.router)
    app.include_router(anomaly.router)
    app.include_router(rotation.router)
    app.include_router(analyst.router)
    app.include_router(brief.router)
    app.include_router(alerts.router)
    app.include_router(paper.router)
    app.include_router(journal.router)
    app.include_router(intelligence.router)
    app.include_router(intelligence_snapshot.router)
    app.include_router(intelligence_confirmation.router)
    app.include_router(intelligence_opportunities.router)
    app.include_router(intelligence_ranking.router)
    app.include_router(intelligence_risk.router)
    app.include_router(intelligence_investment.router)
    app.include_router(decision.router)
    app.include_router(decision_history.router)
    return app
