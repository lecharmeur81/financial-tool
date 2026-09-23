# Backend — Capital Flow Intelligence

Python 3.12 · FastAPI · SQLAlchemy (async, psycopg 3) · Alembic · Redis · structlog.
Project rules: `../CLAUDE.md`. Architecture: `../ARCHITECTURE.md`.

Commands (run from `backend/`, with [uv](https://docs.astral.sh/uv/)):

| Task | Command |
|---|---|
| Install | `uv sync` |
| Run API (needs CFI_DATABASE_URL, CFI_REDIS_URL) | `uv run uvicorn cfi.api.app:create_app --factory --reload` |
| Migrate | `uv run alembic upgrade head` |
| Tests (unit + API) | `uv run pytest -m "not integration"` |
| Integration tests (real DB + Redis) | `uv run pytest -m integration` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` (check only: `--check`) |
| Type check | `uv run mypy` |

Inside Docker Compose, prefix with `docker compose exec api` (e.g. `docker compose exec api pytest`).
