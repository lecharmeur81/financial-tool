from __future__ import annotations

import asyncio
from collections.abc import Mapping

from cfi.core.health import run_check, run_checks


async def _ok() -> Mapping[str, str]:
    return {"version": "1"}


async def _boom() -> Mapping[str, str]:
    raise ConnectionRefusedError("postgresql://user:secret@host/db refused")


async def _slow() -> Mapping[str, str]:
    await asyncio.sleep(1)
    return {}


async def test_ok_check() -> None:
    result = await run_check(_ok, timeout_seconds=1)
    assert result.status == "ok"
    assert result.detail == {"version": "1"}
    assert result.error is None


async def test_failed_check_reports_class_name_only() -> None:
    result = await run_check(_boom, timeout_seconds=1)
    assert result.status == "error"
    # Only the class name is exposed: the message may contain connection secrets.
    assert result.error == "ConnectionRefusedError"


async def test_timeout() -> None:
    result = await run_check(_slow, timeout_seconds=0.05)
    assert result.status == "error"
    assert result.error == "timeout"


async def test_run_checks_runs_all() -> None:
    results = await run_checks({"a": _ok, "b": _boom}, timeout_seconds=1)
    assert {k: v.status for k, v in results.items()} == {"a": "ok", "b": "error"}
