"""Phase 51 diagnostics: the progress/checkpoint helper and the benchmark's timeout path.

No database, no seed, no benchmark: every test uses a temporary directory and fake services."""

from __future__ import annotations

import asyncio
import faulthandler
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.service import AlertService
from tests.integration import p51_progress as pp
from tests.integration import test_alert_evaluate_seeded_benchmark as bench

BACKEND = Path(__file__).resolve().parents[2]


def _read(progress: pp.Progress) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(progress.path.read_text(encoding="utf-8")))


def _progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pp.Progress:
    monkeypatch.delenv(pp.RUN_ID_ENV, raising=False)
    return pp.Progress(tmp_path / "diag", {"hourly_days": 10})


def _failed(progress: pp.Progress) -> bool:  # a function call, so mypy does not narrow the flag
    return progress._diagnostics_failed


def _others() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


def test_the_benchmark_cap_and_safety_constants_are_unchanged() -> None:
    assert bench.HARD_CAP_SECONDS == 900
    assert bench.EXPECTED_MARKER == "P51_DISPOSABLE"
    assert sorted(bench.APPROVED_DATABASES) == ["p51_scratch", "p51_scratch_test", "postgres"]


def test_checkpoint_is_atomic_machine_readable_and_not_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    data = _read(progress)
    assert data["kind"] == pp.CHECKPOINT_KIND
    assert data["kind"] != pp.REPORT_KIND
    assert data["status"] == "in_progress"
    assert {"run_id", "pid", "started_utc", "updated_utc"} <= set(data)
    assert not list(progress.directory.glob("*.tmp"))


def test_each_run_has_its_own_file_and_run_ids_never_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pp.RUN_ID_ENV, "launcher-run-1")
    first = pp.Progress(tmp_path, {})
    second = pp.Progress(tmp_path, {})
    assert first.run_id == "launcher-run-1"
    assert second.run_id != first.run_id
    assert second.path != first.path
    assert first.path.exists()
    assert second.path.exists()
    monkeypatch.setenv(pp.RUN_ID_ENV, "bad id with spaces/..")
    assert pp.Progress(tmp_path, {}).run_id != "bad id with spaces/.."


def test_default_location_is_outside_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(pp.PROGRESS_DIR_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert pp.progress_dir() == tmp_path / "cfi-p51-benchmark"
    monkeypatch.setenv(pp.PROGRESS_DIR_ENV, str(tmp_path / "elsewhere"))
    assert pp.progress_dir() == tmp_path / "elsewhere"


def test_the_current_stage_and_finished_stages_are_on_disk_mid_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with progress.stage("one"):
        pass
    with progress.stage("two"):
        data = _read(progress)
        assert data["status"] == "in_progress"
        assert data["current_stage"] == "two"
        assert [s["stage"] for s in data["stages_finished"]] == ["one"]


def test_failure_is_recorded_redacted_and_reraised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="boom"), progress.stage("seed"):
        raise ValueError("boom postgresql://user:hunter2@127.0.0.1:55432/db")
    data = _read(progress)
    assert data["status"] == "failed"
    assert data["current_stage"] == "seed"
    assert "hunter2" not in progress.path.read_text(encoding="utf-8")
    assert "***" in data["stages_finished"][-1]["error"]
    assert progress.complete(None) == "not_completed:failed"  # a failed run is never completed
    assert _read(progress)["status"] == "failed"


def test_pytest_fail_is_recorded_and_a_marked_timeout_is_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with pytest.raises(pytest.fail.Exception), progress.stage("a"):
        pytest.fail("assertion-style failure")
    assert _read(progress)["status"] == "failed"
    other = _progress(tmp_path, monkeypatch)
    other.timed_out = "evaluate_1"
    with pytest.raises(pytest.fail.Exception), other.stage("evaluate_1"):
        pytest.fail("TIMEOUT")
    assert _read(other)["status"] == "timeout"


def test_keyboard_interrupt_is_not_recorded_as_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with pytest.raises(KeyboardInterrupt), progress.stage("seed"):
        raise KeyboardInterrupt
    data = _read(progress)
    assert data["status"] == "interrupted"
    assert data["stages_finished"][-1]["status"] == "interrupted"


async def test_cancellation_is_recorded_and_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)

    async def work() -> None:
        with progress.stage("evaluate_1"):
            await asyncio.sleep(30)

    task = asyncio.create_task(work())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _read(progress)["status"] == "cancelled"


def test_a_process_that_dies_mid_stage_leaves_an_in_progress_checkpoint(tmp_path: Path) -> None:
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "from tests.integration.p51_progress import Progress\n"
        f"p = Progress(Path({str(tmp_path)!r}), {{}})\n"
        "with p.stage('done'):\n    pass\n"
        "with p.stage('seed'):\n    os._exit(9)\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(BACKEND), str(BACKEND / "src")])}
    env.pop(pp.RUN_ID_ENV, None)
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only child
        [sys.executable, "-c", code], cwd=BACKEND, env=env, check=False, capture_output=True
    )
    assert result.returncode == 9
    [file] = tmp_path.glob("p51_progress-*.json")
    data = json.loads(file.read_text(encoding="utf-8"))
    assert data["status"] == "in_progress"
    assert data["current_stage"] == "seed"
    assert [s["stage"] for s in data["stages_finished"]] == ["done"]


def test_completed_needs_an_intact_report_and_a_checkpoint_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    rendered = '{"kind": "p51_benchmark_report"}'
    written = progress.write_report(rendered)
    assert written is not None
    assert progress.complete(written) == "completed"
    data = _read(progress)
    assert data["status"] == "completed"
    assert data["report"]["verified"] is True
    assert data["report"]["sha256"] == hashlib.sha256(rendered.encode()).hexdigest()
    assert "P51_OUTCOME completed" in capsys.readouterr().out


def test_a_failed_report_write_is_never_recorded_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    (progress.directory / f"p51_benchmark_report-{progress.run_id}.json").mkdir()  # blocks replace
    assert progress.write_report("{}") is None
    assert progress.complete(None) == "report_not_persisted"
    data = _read(progress)
    assert data["status"] == "benchmark_finished_report_not_written"
    assert data["report"]["verified"] is False
    assert data["diagnostic_write_failures"] >= 1
    assert "P51_OUTCOME report_not_persisted" in capsys.readouterr().out


def test_a_report_changed_after_verification_is_not_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    written = progress.write_report("{}")
    assert written is not None
    written.write_text("tampered")
    assert progress.complete(written) == "report_not_persisted"
    assert _read(progress)["status"] == "benchmark_finished_report_not_written"


def test_a_verified_report_without_a_persisted_final_checkpoint_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    written = progress.write_report("{}")
    assert written is not None
    progress.path.unlink()
    progress.path.mkdir()  # every further checkpoint write now fails
    assert progress.complete(written) == "checkpoint_not_persisted"
    assert progress.state["status"] == "report_verified_checkpoint_unconfirmed"
    out = capsys.readouterr().out
    assert "P51_OUTCOME checkpoint_not_persisted" in out
    assert "UNCONFIRMED" in out
    assert "P51_OUTCOME completed" not in out


def test_an_unwritable_checkpoint_is_reported_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.delenv(pp.RUN_ID_ENV, raising=False)
    progress = pp.Progress(blocker, {})  # every write fails; the benchmark must not
    with progress.stage("seed"):
        pass
    assert "WARNING: could not write" in capsys.readouterr().out
    assert progress.state["diagnostic_write_failures"] >= 2


def test_a_console_that_cannot_encode_never_replaces_the_benchmark_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    ascii_out = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", ascii_out)
    with pytest.raises(ValueError, match="caf"), progress.stage("seed"):
        raise ValueError("café failed")
    ascii_out.flush()
    assert b"caf\\xe9" in ascii_out.buffer.getvalue()
    assert _read(progress)["status"] == "failed"


def _broken(*_: Any, **__: Any) -> bool:
    raise RuntimeError("diagnostics exploded")


def test_a_failure_in_the_instrumentation_cannot_mask_the_benchmark_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    monkeypatch.setattr(progress, "_flush", _broken)
    with pytest.raises(ValueError, match="real failure"), progress.stage("seed"):
        raise ValueError("real failure")
    progress.heartbeat("evaluate_1", 1.0, None)  # must not raise either
    assert "diagnostics error in stage end" in capsys.readouterr().out


def test_a_broken_stage_still_runs_the_body_and_keeps_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    monkeypatch.setattr(progress, "_flush", _broken)
    ran: list[str] = []
    with progress.stage("seed"):
        ran.append("body")
    assert ran == ["body"]
    with pytest.raises(KeyboardInterrupt), progress.stage("seed"):
        raise KeyboardInterrupt


def test_broken_diagnostics_are_never_reported_as_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    written = progress.write_report("{}")
    assert written is not None
    monkeypatch.setattr(progress, "_flush", _broken)
    assert progress.complete(written) == "diagnostics_error"
    assert _failed(progress)  # complete's own catch-all flags it as well
    out = capsys.readouterr().out
    assert "P51_OUTCOME diagnostics_error" in out
    assert "P51_OUTCOME completed" not in out
    monkeypatch.setattr(progress, "_write", _broken)
    assert progress.write_report("{}") is None


def test_a_swallowed_stage_bookkeeping_failure_blocks_the_completed_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    written = progress.write_report("{}")
    assert written is not None
    assert not _failed(progress)
    with monkeypatch.context() as broken:  # bookkeeping fails only while the stage runs
        broken.setattr(progress, "_flush", _broken)
        with pytest.raises(ValueError, match="real failure"), progress.stage("seed"):
            raise ValueError("real failure")  # the original exception still wins
    assert _failed(progress)
    # Fresh run whose only fault is a swallowed failure; report and checkpoint are otherwise fine.
    other = _progress(tmp_path, monkeypatch)
    written = other.write_report("{}")
    assert written is not None
    with monkeypatch.context() as broken:
        broken.setattr(other, "_flush", _broken)
        with other.stage("seed"):
            pass  # body succeeds; only the bookkeeping around it explodes
    assert other.state["status"] == "in_progress"
    capsys.readouterr()
    assert other.complete(written) == "diagnostics_error"
    out = capsys.readouterr().out
    assert "P51_OUTCOME diagnostics_error" in out
    assert "P51_OUTCOME completed" not in out
    assert _read(other)["status"] == "diagnostics_error"


def _oserror(*_: Any, **__: Any) -> None:
    raise OSError("disk full")


def _value_error(*_: Any, **__: Any) -> None:
    raise ValueError("console closed")


def _patch_flush(progress: pp.Progress, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(progress, "_flush", _broken)


def _patch_replace(_: pp.Progress, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(os, "replace", _oserror)  # every checkpoint write fails with OSError


def _patch_print(_: pp.Progress, mp: pytest.MonkeyPatch) -> None:
    mp.setattr("builtins.print", _value_error)  # the console, and its ASCII fallback, are gone


def _no_patch(_: pp.Progress, __: pytest.MonkeyPatch) -> None:
    return None


def _body_noop(_: pp.Progress) -> None:
    return None


def _body_unserialisable(progress: pp.Progress) -> None:
    progress.detail(bad=object())  # json.dumps then fails for every later checkpoint


def _body_corrupt_detail(progress: pp.Progress) -> None:
    progress.state["stage_detail"] = None  # the next detail()/stage end cannot update it
    progress.detail(rows=1)


_BOOKKEEPING_FAILURES: dict[
    str, tuple[Callable[[pp.Progress, pytest.MonkeyPatch], None], Callable[[pp.Progress], None]]
] = {
    "flush_raises": (_patch_flush, _body_noop),
    "checkpoint_write_oserror": (_patch_replace, _body_noop),
    "console_lost": (_patch_print, _body_noop),
    "unserialisable_detail": (_no_patch, _body_unserialisable),
    "corrupt_stage_detail": (_no_patch, _body_corrupt_detail),
}


def _failing_stage(progress: pp.Progress, body: Callable[[pp.Progress], None]) -> None:
    with progress.stage("seed"):
        body(progress)
        raise ValueError("real failure")


@pytest.mark.parametrize("case", sorted(_BOOKKEEPING_FAILURES))
def test_no_swallowed_bookkeeping_failure_can_be_followed_by_completed(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    patch, body = _BOOKKEEPING_FAILURES[case]
    # A benchmark whose body fails: the benchmark's own exception must be the one that escapes.
    failing = _progress(tmp_path / "a", monkeypatch)
    with monkeypatch.context() as mp:
        patch(failing, mp)
        with pytest.raises(ValueError, match="real failure"):
            _failing_stage(failing, body)
    assert _failed(failing)
    assert failing.state["status"] != "completed"
    # A benchmark that succeeds: only the bookkeeping failed, and the report is intact.
    ok = _progress(tmp_path / "b", monkeypatch)
    with monkeypatch.context() as mp:
        patch(ok, mp)
        with ok.stage("seed"):
            body(ok)
    assert _failed(ok)
    written = ok.write_report("{}")
    assert written is not None
    capsys.readouterr()
    assert ok.complete(written) == "diagnostics_error"
    out = capsys.readouterr().out
    assert "P51_OUTCOME diagnostics_error" in out
    assert "P51_OUTCOME completed" not in out
    # With an unserialisable state no checkpoint can be rewritten at all: the file on disk is
    # stale (never "completed"); the printed and returned outcome is the verdict.
    on_disk = "in_progress" if case == "unserialisable_detail" else "diagnostics_error"
    assert _read(ok)["status"] == on_disk


class _UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no text for this exception")


def test_an_exception_that_cannot_be_described_is_still_the_one_that_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with pytest.raises(_UnprintableError), progress.stage("seed"):
        raise _UnprintableError
    assert _failed(progress)
    assert progress.state["stages_finished"][-1]["error"] == "_UnprintableError"


def test_an_unexpected_error_while_writing_the_report_is_flagged_and_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    monkeypatch.setattr(pp, "_sha256_of", _broken)  # not an OSError: only the catch-all sees it
    assert progress.write_report("{}") is None
    assert _failed(progress)
    monkeypatch.undo()
    written = progress.write_report("{}")  # a retry that works does not clear the flag
    assert written is not None
    assert progress.complete(written) == "diagnostics_error"


def test_a_failed_stack_dump_start_and_close_are_flagged_and_never_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    monkeypatch.setattr(faulthandler, "dump_traceback_later", _oserror)
    progress.start_stack_dumps(0.2)
    assert _failed(progress)
    other = _progress(tmp_path / "other", monkeypatch)

    class BadHandle:
        def close(self) -> None:
            raise OSError("disk gone")

    other._stacks = cast("Any", BadHandle())
    assert not _failed(other)
    other.close()
    assert _failed(other)


def test_a_clean_run_is_still_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with progress.stage("seed"):
        progress.detail(rows=1)
    written = progress.write_report("{}")
    assert written is not None
    assert progress.complete(written) == "completed"
    assert not _failed(progress)
    assert "P51_OUTCOME completed" in capsys.readouterr().out


class _Engine:
    """Stands in for the AsyncEngine: no database, only a recorded ``dispose``."""

    def __init__(self, on_dispose: Callable[[], None] | None = None, *, fail: bool = False) -> None:
        self.disposed = 0
        self._on_dispose = on_dispose
        self._fail = fail

    async def dispose(self) -> None:
        self.disposed += 1
        if self._on_dispose is not None:
            self._on_dispose()
        if self._fail:
            raise RuntimeError("dispose failed")


class _Handle:
    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self._fail = fail

    def close(self) -> None:
        self.closed = True
        if self._fail:
            raise OSError("disk gone")


def _fake(engine: _Engine) -> AsyncEngine:
    return cast("AsyncEngine", engine)


async def test_completed_is_issued_only_after_the_engine_is_disposed_and_diagnostics_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    handle = _Handle()
    progress._stacks = cast("Any", handle)
    seen: dict[str, Any] = {}

    def during_disposal() -> None:
        seen["status"] = _read(progress)["status"]
        seen["stacks_open"] = not handle.closed  # diagnostics stay alive while disposing
        seen["outcome_already_printed"] = "P51_OUTCOME" in capsys.readouterr().out

    engine = _Engine(during_disposal)
    async with bench._lifecycle(_fake(engine), progress) as life:
        life.report = progress.write_report("{}")
    assert seen == {"status": "in_progress", "stacks_open": True, "outcome_already_printed": False}
    assert engine.disposed == 1
    assert handle.closed
    assert _read(progress)["status"] == "completed"
    assert "P51_OUTCOME completed" in capsys.readouterr().out


async def test_a_diagnostics_close_failure_blocks_completed_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    progress._stacks = cast("Any", _Handle(fail=True))
    engine = _Engine()
    async with bench._lifecycle(_fake(engine), progress) as life:
        life.report = progress.write_report("{}")
    assert engine.disposed == 1
    out = capsys.readouterr().out
    assert "stack file not closed cleanly" in out
    assert "P51_OUTCOME diagnostics_error" in out
    assert "P51_OUTCOME completed" not in out
    assert _read(progress)["status"] == "diagnostics_error"


async def test_an_engine_disposal_failure_after_success_is_never_completed_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    handle = _Handle()
    progress._stacks = cast("Any", handle)
    engine = _Engine(fail=True)
    with pytest.raises(RuntimeError, match="dispose failed"):
        async with bench._lifecycle(_fake(engine), progress) as life:
            life.report = progress.write_report("{}")
    assert handle.closed  # the diagnostics are closed even though disposal failed
    out = capsys.readouterr().out
    assert "P51_OUTCOME not_completed:cleanup_failed" in out
    assert "P51_OUTCOME completed" not in out
    data = _read(progress)
    assert data["status"] == "cleanup_failed"
    assert data["cleanup_failures"] == [{"step": "engine_dispose", "error": "RuntimeError"}]
    assert "dispose failed" not in progress.path.read_text(encoding="utf-8")  # type only, no text


async def _failing_benchmark(engine: _Engine, progress: pp.Progress) -> None:
    async with bench._lifecycle(_fake(engine), progress):
        with progress.stage("evaluate_1"):
            raise ValueError("real failure")


async def test_a_cleanup_failure_never_masks_the_original_benchmark_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    handle = _Handle(fail=True)  # the diagnostics fail to close AND the engine fails to dispose
    progress._stacks = cast("Any", handle)
    engine = _Engine(fail=True)
    with pytest.raises(ValueError, match="real failure"):
        await _failing_benchmark(engine, progress)
    assert engine.disposed == 1
    assert handle.closed
    out = capsys.readouterr().out
    assert "cleanup step engine_dispose failed (RuntimeError)" in out
    assert "stack file not closed cleanly" in out
    assert "P51_OUTCOME completed" not in out
    data = _read(progress)
    assert data["status"] == "failed"  # the benchmark's own status is not overwritten
    assert data["cleanup_failures"] == [{"step": "engine_dispose", "error": "RuntimeError"}]


async def test_cancellation_still_disposes_and_closes_and_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    handle = _Handle()
    progress._stacks = cast("Any", handle)
    engine = _Engine()

    async def work() -> None:
        async with bench._lifecycle(_fake(engine), progress):
            with progress.stage("evaluate_1"):
                await asyncio.sleep(30)

    task = asyncio.create_task(work())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.disposed == 1
    assert handle.closed
    assert _read(progress)["status"] == "cancelled"
    assert "P51_OUTCOME completed" not in capsys.readouterr().out


async def _fail_outside_any_stage(engine: _Engine, progress: pp.Progress) -> None:
    async with bench._lifecycle(_fake(engine), progress):
        raise ValueError("real failure outside any stage")


async def test_a_failure_outside_any_stage_is_aborted_not_a_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    engine = _Engine(fail=True)  # the disposal fails as well
    with pytest.raises(ValueError, match="outside any stage"):
        await _fail_outside_any_stage(engine, progress)
    out = capsys.readouterr().out
    assert "P51_OUTCOME not_completed:aborted" in out
    assert "after the benchmark's work finished" not in out  # the work did NOT finish
    assert "P51_OUTCOME completed" not in out
    data = _read(progress)
    assert data["status"] == "aborted"
    assert data["cleanup_failures"] == [{"step": "engine_dispose", "error": "RuntimeError"}]


async def test_a_stage_failure_status_is_not_replaced_by_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, expected in (("failed", "failed"), ("timeout", "timeout")):
        progress = _progress(tmp_path / name, monkeypatch)
        progress.timed_out = "evaluate_1" if name == "timeout" else None
        with pytest.raises(ValueError, match="real failure"):
            await _failing_benchmark(_Engine(fail=True), progress)
        assert _read(progress)["status"] == expected


async def test_an_unexpected_close_error_never_replaces_the_benchmark_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OddHandle:
        def close(self) -> None:
            raise RuntimeError("not an OSError or ValueError")

    progress = _progress(tmp_path / "a", monkeypatch)
    progress._stacks = cast("Any", OddHandle())
    with pytest.raises(ValueError, match="real failure"):
        await _failing_benchmark(_Engine(), progress)
    assert _failed(progress)
    ok = _progress(tmp_path / "b", monkeypatch)
    ok._stacks = cast("Any", OddHandle())
    async with bench._lifecycle(_fake(_Engine()), ok) as life:
        life.report = ok.write_report("{}")
    assert _read(ok)["status"] == "diagnostics_error"


async def test_an_interrupt_during_disposal_is_never_completed_and_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Documents the accepted behaviour: only ``Exception`` is handled, so a CancelledError during
    disposal propagates (replacing a benchmark exception, as asyncio does for a second cancel),
    the diagnostics are still closed, and the checkpoint stays ``in_progress`` (unconfirmed)."""

    class CancelledEngine(_Engine):
        async def dispose(self) -> None:
            self.disposed += 1
            raise asyncio.CancelledError

    progress = _progress(tmp_path, monkeypatch)
    handle = _Handle()
    progress._stacks = cast("Any", handle)
    with pytest.raises(asyncio.CancelledError):
        async with bench._lifecycle(_fake(CancelledEngine()), progress) as life:
            life.report = progress.write_report("{}")
    assert handle.closed
    assert _read(progress)["status"] == "in_progress"
    assert "P51_OUTCOME completed" not in capsys.readouterr().out


def test_the_wrapper_summary_pattern_ignores_the_diagnostics_own_lines() -> None:
    """A proxy, NOT a PowerShell test: the pattern is read from the .ps1 and applied with Python's
    ``re`` (case-insensitive, like Select-String). The .NET regex engine is unverified here."""
    script = BACKEND.parent / "Invoke-P51Pytest.ps1"
    if not script.exists():
        pytest.skip("Invoke-P51Pytest.ps1 is not next to the backend folder")
    match = re.search(r"-Pattern '([^']+)' -Quiet", script.read_text(encoding="utf-8"))
    assert match is not None
    pattern = re.compile(match.group(1), re.IGNORECASE)
    for line in (
        "[P51 +   12.3s] seed: failed in 3.2s (ValueError: boom)",
        "[P51 +    3.0s] truncate: ok in 0.1s",
        "FAILED tests/x.py::t - AssertionError: 5 passed in 3s",
    ):
        assert pattern.search(line) is None, line
    for line in (
        "36 passed in 5.48s",
        "============ 1 failed, 35 passed in 6.20s ============",
        "============ no tests ran in 0.01s ============",
        "2 skipped, 1 deselected in 0.5s",
    ):
        assert pattern.search(line) is not None, line


def test_close_never_raises_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BadHandle:
        def close(self) -> None:
            raise OSError("disk gone")

    progress = _progress(tmp_path, monkeypatch)
    progress._stacks = cast("Any", BadHandle())
    progress.close()
    progress.close()


def test_heartbeat_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    progress = _progress(tmp_path, monkeypatch)
    progress.heartbeat("evaluate_1", 61.0, "alert_evaluate_stage_timing:build_snapshot")
    beat = _read(progress)["heartbeat"]
    assert beat["label"] == "evaluate_1"
    assert beat["seconds"] == 61.0


def test_stack_dumps_are_written_while_the_main_thread_sleeps_and_while_it_computes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves only this, on this platform: the dump file grows during a sleep and during a
    CPU-bound pure-Python loop. It does not prove anything about a GIL-holding C call or Windows."""
    progress = _progress(tmp_path, monkeypatch)
    stacks = progress.directory / f"p51_stacks-{progress.run_id}.txt"
    progress.start_stack_dumps(0.2)
    time.sleep(0.5)
    during_sleep = stacks.read_text(encoding="utf-8").count("most recent call first")
    end = time.perf_counter() + 0.6
    while time.perf_counter() < end:
        pass
    during_busy = stacks.read_text(encoding="utf-8").count("most recent call first")
    progress.close()
    assert during_sleep >= 1
    assert during_busy > during_sleep


class _Slow:
    async def evaluate(self, **_: Any) -> object:
        await asyncio.sleep(30)
        return object()


class _Fast:
    async def evaluate(self, **_: Any) -> object:
        return object()


class _Broken:
    async def evaluate(self, **_: Any) -> object:
        raise RuntimeError("evaluate exploded")


async def test_evaluate_timeout_fails_as_a_timeout_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench, "HARD_CAP_SECONDS", 0.3)
    monkeypatch.setattr(bench, "HEARTBEAT_SECONDS", 0.1)
    progress = _progress(tmp_path, monkeypatch)
    with (
        pytest.raises(pytest.fail.Exception, match="TIMEOUT"),
        progress.stage("evaluate_1"),
    ):
        await bench._evaluate(cast("AlertService", _Slow()), progress, "evaluate_1")
    data = _read(progress)
    assert data["status"] == "timeout"
    assert data["heartbeat"]["label"] == "evaluate_1"
    assert data["stages_finished"][-1]["status"] == "timeout"
    assert _others() == []


async def test_evaluate_success_cleans_up_the_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with progress.stage("evaluate_1"):
        run = await bench._evaluate(cast("AlertService", _Fast()), progress, "evaluate_1")
    assert run.wall_seconds >= 0
    assert _read(progress)["stages_finished"][-1]["status"] == "ok"
    assert _others() == []


async def test_evaluate_failure_keeps_the_original_exception_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="evaluate exploded"), progress.stage("evaluate_1"):
        await bench._evaluate(cast("AlertService", _Broken()), progress, "evaluate_1")
    assert _read(progress)["status"] == "failed"
    assert _others() == []


async def test_outer_cancellation_propagates_through_evaluate_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = _progress(tmp_path, monkeypatch)
    task = asyncio.create_task(
        bench._evaluate(cast("AlertService", _Slow()), progress, "evaluate_1")
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _others() == []
