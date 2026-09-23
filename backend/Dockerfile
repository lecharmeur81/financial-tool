# syntax=docker/dockerfile:1
# Backend image (FastAPI API + Alembic migrations).
#   target "dev"     — includes test/lint/type-check tools; used by docker compose (development).
#   target "runtime" — production dependencies only (used from the production phase onward).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"
# Pinned uv, same version that produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
RUN groupadd --system cfi && useradd --system --gid cfi --home-dir /app --no-create-home cfi
# Raw payload archive (ADR-0019). Created here so a Docker volume mounted on it is owned by cfi.
RUN mkdir -p /data/raw && chown -R cfi:cfi /data
WORKDIR /app

# ---------------------------------------------------------------- development image
FROM base AS dev
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project
COPY src ./src
RUN uv sync --frozen
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
# The app user may create cache folders (.pytest_cache, .ruff_cache, .mypy_cache) in /app;
# the source files themselves stay root-owned and read-only for it.
RUN chown cfi:cfi /app
USER cfi
EXPOSE 8000
CMD ["uvicorn", "cfi.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- runtime image
FROM base AS runtime
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
USER cfi
EXPOSE 8000
CMD ["uvicorn", "cfi.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
