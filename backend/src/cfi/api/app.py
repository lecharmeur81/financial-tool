"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cfi.api.errors import register_exception_handlers
from cfi.api.middleware import REQUEST_ID_HEADER, request_context_middleware
from cfi.api.routes import (
    derivatives,
    divergence,
    health,
    ingestion,
    institutional,
    liquidity,
    macro,
    market,
    market_structure,
    meta,
    regime,
    retail,
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

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings

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
    return app
