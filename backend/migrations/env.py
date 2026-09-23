"""Alembic environment.

The URL comes from ``CFI_DATABASE_URL`` via application settings. Migrations run synchronously with
psycopg 3 (same driver as the application). Logging goes through the application's
structured logger.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from cfi.core.config import get_settings
from cfi.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)

# No ORM metadata yet: migrations are written explicitly (additive-first, R10).
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        settings.database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args={"options": "-c timezone=UTC"},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
