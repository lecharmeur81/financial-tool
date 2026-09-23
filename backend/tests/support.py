"""Test helpers: a fake clock whose ``sleep`` advances time instantly (no real waiting)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Monotonic seconds for rate limiters/breakers, plus a recorded async ``sleep``."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class WallClock:
    """Settable UTC wall clock for the ingestion engine."""

    def __init__(self, now: datetime) -> None:
        self.current = now

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


T0 = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
