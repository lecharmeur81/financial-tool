"""Redis connection. Redis is never a source of truth (ADR-0024)."""

from __future__ import annotations

from collections.abc import Mapping

from redis.asyncio import Redis

from cfi.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    client: Redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=settings.health_check_timeout_seconds,
        socket_timeout=settings.health_check_timeout_seconds,
        health_check_interval=30,
    )
    return client


async def check_redis(client: Redis) -> Mapping[str, str]:
    pong = await client.ping()
    info = await client.info(section="server")
    return {
        "ping": "PONG" if pong else "no_response",
        "redis_version": str(info.get("redis_version")),
    }
