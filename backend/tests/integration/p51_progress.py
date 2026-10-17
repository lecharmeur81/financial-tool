"""Diagnostic-only progress markers and durable checkpoints for the Phase 51 seeded benchmark.

Never touches the database or the application. Records stage names, elapsed seconds, row counts,
a report hash and short redacted error text only - no connection URLs, credentials or payloads.

A *checkpoint* (``kind = p51_progress_checkpoint``) is not a *report*
(``kind = p51_benchmark_report``). Only ``status == "completed"`` means that every stage passed,
the durable report was written, re-hashed and found intact, and the final checkpoint was written
and read back carrying the same report hash. Any other status - ``in_progress`` on a stale file
included - is an incomplete or unconfirmed run.

"Persisted" here means: written to a temporary file, flushed and fsync'd, renamed over the target
with ``os.replace`` and read back. It does not promise survival of a power loss (the directory
entry is not fsync'd), and a read-back proves the bytes are visible, not that they are on the
platter.

Nothing in this module may raise into the benchmark or replace its exception: an I/O failure is
counted, printed and carried in the next successful checkpoint, and any other diagnostic error is
printed and swallowed (``Exception`` only - never ``BaseException``, so cancellation, Ctrl+C and
``pytest.fail`` always propagate).
"""

from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final

import pytest

PROGRESS_DIR_ENV: Final = "CFI_P51_PROGRESS_DIR"
RUN_ID_ENV: Final = "CFI_P51_RUN_ID"
CHECKPOINT_KIND: Final = "p51_progress_checkpoint"
REPORT_KIND: Final = "p51_benchmark_report"
HEARTBEAT_SECONDS: Final = 30.0
STACK_DUMP_SECONDS: Final = 300.0
_RUN_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_URL_CREDENTIALS: Final = re.compile(r"://[^@\s/]*@")


def progress_dir() -> Path:
    """Default: ``%LOCALAPPDATA%\\cfi-p51-benchmark`` - outside the repository and outside pytest's
    temporary directories. ``CFI_P51_PROGRESS_DIR`` overrides it."""
    override = os.environ.get(PROGRESS_DIR_ENV)
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "cfi-p51-benchmark"
    try:
        return Path.home() / ".cache" / "cfi-p51-benchmark"
    except RuntimeError:  # no home directory: still never inside the repository
        return Path(tempfile.gettempdir()) / "cfi-p51-benchmark"


def redact(value: str, limit: int = 300) -> str:
    return _URL_CREDENTIALS.sub("://***@", value)[:limit]


def _utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class Progress:
    def __init__(self, directory: Path, profile: Mapping[str, Any]) -> None:
        self.directory = directory
        given = os.environ.get(RUN_ID_ENV, "")
        run_id = given if _RUN_ID.fullmatch(given) else None
        run_id = run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        if self._taken(directory / f"p51_progress-{run_id}.json"):  # never overwrite another run
            run_id = f"{run_id}-{uuid.uuid4().hex[:8]}"
        self.run_id = run_id
        self.path = directory / f"p51_progress-{run_id}.json"
        self.timed_out: str | None = None  # stage label, set just before a timeout failure
        self._t0 = time.perf_counter()
        self._write_failures = 0
        self._last_write_error: str | None = None
        # In memory only. Set when diagnostic bookkeeping itself failed unexpectedly; once set,
        # ``complete`` can never report ``completed``. It never replaces the benchmark's exception.
        self._diagnostics_failed = False
        self._stacks: IO[str] | None = None
        self.state: dict[str, Any] = {
            "kind": CHECKPOINT_KIND,
            "run_id": run_id,
            "pid": os.getpid(),
            "started_utc": _utc(),
            "profile": dict(profile),
            # in_progress | completed | benchmark_finished_report_not_written
            # | report_verified_checkpoint_unconfirmed | diagnostics_error | cleanup_failed
            # | aborted | failed | timeout | cancelled | interrupted
            # Only "completed" is a completed benchmark.
            "status": "in_progress",
            "current_stage": None,
            "stages_finished": [],
            "stage_detail": {},
            "heartbeat": None,
            "report": None,
            "diagnostic_write_failures": 0,
        }
        self._flush()

    @staticmethod
    def _taken(path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return True  # cannot tell: be conservative and pick a different name

    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def _emit(self, line: str) -> None:
        """Print one flushed line; a console that cannot encode or accept it must not raise."""
        try:
            print(line, flush=True)
        except (OSError, ValueError, UnicodeError):
            try:
                print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
            except (OSError, ValueError, UnicodeError):
                self._diagnostics_failed = True  # the line is lost altogether

    def mark(self, message: str) -> None:
        self._emit(f"[P51 +{self.elapsed():8.1f}s] {message}")

    def _failed_write(self, name: str, error: str) -> bool:
        self._diagnostics_failed = True
        self._write_failures += 1
        self._last_write_error = error
        self._emit(
            f"[P51] WARNING: could not write {name} ({error}); "
            f"diagnostic write failures so far: {self._write_failures}"
        )
        return False

    def _write(self, path: Path, content: str) -> bool:
        """Temp file, fsync, ``os.replace``. A failure is counted and printed, never raised."""
        tmp = path.with_name(path.name + ".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            return self._failed_write(path.name, type(exc).__name__)
        return True

    def _flush(self) -> bool:
        """Persist the checkpoint. The result is checked only where a verdict depends on it
        (``complete``); a failed intermediate write is already counted, printed and carried in the
        next successful checkpoint."""
        self.state["updated_utc"] = _utc()
        self.state["elapsed_seconds"] = round(self.elapsed(), 1)
        self.state["diagnostic_write_failures"] = self._write_failures
        if self._last_write_error is not None:
            self.state["last_diagnostic_write_error"] = self._last_write_error
        try:
            content = json.dumps(self.state, indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            return self._failed_write(self.path.name, type(exc).__name__)
        return self._write(self.path, content)

    def detail(self, **values: Any) -> None:
        self._safely("detail", lambda: self.state["stage_detail"].update(values))

    def _safely(self, what: str, action: Callable[[], object]) -> None:
        """Run diagnostic bookkeeping; its failure is printed and never propagates."""
        try:
            action()
        except Exception as exc:
            self._diagnostics_failed = True
            self._emit(f"[P51] WARNING: diagnostics error in {what} ({type(exc).__name__})")

    def _enter(self, name: str) -> None:
        self.state.update(current_stage=name, stage_detail={})
        self.mark(f"{name}: start")
        self._flush()

    def _leave(self, name: str, status: str, error: str | None, seconds: float) -> None:
        entry: dict[str, Any] = {"stage": name, "status": status, "seconds": seconds}
        entry.update(self.state["stage_detail"])
        if error is not None:
            entry["error"] = error
        self.state["stages_finished"].append(entry)
        self.state["current_stage"] = None if status == "ok" else name
        if status != "ok":
            self.state["status"] = status
        self.mark(f"{name}: {status} in {seconds:.1f}s" + (f" ({error})" if error else ""))
        self._flush()

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[None]:
        began = time.perf_counter()
        self._safely("stage start", lambda: self._enter(name))
        status = "interrupted"  # stays so for KeyboardInterrupt/SystemExit, which are not caught
        error: str | None = None
        try:
            yield
            status = "ok"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except (Exception, pytest.fail.Exception) as exc:  # recorded, then always re-raised
            status = "timeout" if self.timed_out == name else "failed"
            try:
                error = f"{type(exc).__name__}: {redact(str(exc))}"
            except Exception:  # a broken __str__ must not hide the real exception
                self._diagnostics_failed = True
                error = type(exc).__name__
            raise
        finally:
            seconds = round(time.perf_counter() - began, 2)
            self._safely("stage end", lambda: self._leave(name, status, error, seconds))

    def heartbeat(self, label: str, seconds: float, last_event: str | None) -> None:
        def record() -> None:
            self.state["heartbeat"] = {
                "label": label,
                "seconds": round(seconds, 1),
                "last_completed_event": last_event,
                "utc": _utc(),
            }
            self.mark(f"{label}: running {seconds:.0f}s; last completed event: {last_event}")
            self._flush()

        self._safely("heartbeat", record)

    def start_stack_dumps(self, interval: float = STACK_DUMP_SECONDS) -> None:
        """Dump every thread's stack to a file each ``interval`` seconds (``faulthandler`` watchdog
        thread; code locations only, never variable values)."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._stacks = (self.directory / f"p51_stacks-{self.run_id}.txt").open(
                "w", encoding="utf-8"
            )
            faulthandler.dump_traceback_later(interval, repeat=True, file=self._stacks)
        except (OSError, RuntimeError, ValueError) as exc:
            self._diagnostics_failed = True
            self.mark(f"WARNING: stack dumps not started ({type(exc).__name__})")
            self.close()

    def close(self) -> None:
        """Never raises an ``Exception``, so it can sit in a ``finally`` without hiding the
        benchmark's exception. Any failure is recorded and blocks ``completed``."""
        self._safely("cancel stack dumps", faulthandler.cancel_dump_traceback_later)
        handle, self._stacks = self._stacks, None
        if handle is not None:
            try:
                handle.close()
            except Exception as exc:
                self._diagnostics_failed = True
                self._emit(f"[P51] WARNING: stack file not closed cleanly ({type(exc).__name__})")

    def body_aborted(self) -> None:
        """The benchmark body exited with an exception. If no stage recorded it (the status is
        still ``in_progress``, e.g. a failure or Ctrl+C between stages) the run is marked
        ``aborted``, so a later cleanup failure cannot be described as "after the work finished"."""

        def record() -> None:
            if self.state["status"] == "in_progress":
                self.state["status"] = "aborted"
                self._flush()
                self.mark(
                    "P51_OUTCOME not_completed:aborted: the benchmark body exited with an "
                    "exception outside any recorded stage"
                )

        self._safely("body_aborted", record)

    def cleanup_failed(self, what: str, exc: Exception) -> None:
        """A REQUIRED cleanup step (the engine disposal) failed. If the run was still
        ``in_progress`` the outcome is ``not_completed:cleanup_failed``; a run that already failed,
        timed out or was interrupted keeps its own status and only gains a warning. Only the
        exception type is recorded, never its text."""

        def record() -> None:
            name = type(exc).__name__
            self.state.setdefault("cleanup_failures", []).append({"step": what, "error": name})
            if self.state["status"] == "in_progress":
                self.state["current_stage"] = None
                self.state["status"] = "cleanup_failed"
                self._flush()
                self.mark(
                    f"P51_OUTCOME not_completed:cleanup_failed: {what} failed ({name}) after the "
                    "benchmark's work finished; the result is NOT confirmed"
                )
            else:
                self._flush()
                self.mark(
                    f"WARNING: cleanup step {what} failed ({name}); the run's own status "
                    f"({self.state['status']}) is unchanged"
                )

        self._safely("cleanup_failed", record)

    def write_report(self, rendered: str) -> Path | None:
        """Write the durable report and read it back. ``None`` means it is NOT safely on disk."""
        try:
            return self._write_report(rendered)
        except Exception as exc:
            self._diagnostics_failed = True
            self._emit(f"[P51] WARNING: diagnostics error in write_report ({type(exc).__name__})")
            return None

    def _write_report(self, rendered: str) -> Path | None:
        path = self.directory / f"p51_benchmark_report-{self.run_id}.json"
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        verified = self._write(path, rendered) and _sha256_of(path) == digest
        self.state["report"] = {"path": str(path), "sha256": digest, "verified": verified}
        self._flush()  # intermediate; ``complete`` re-checks everything and reads the file back
        if not verified:
            self.mark(
                "WARNING: durable report NOT written or not verified; the report is still printed "
                "and written under the pytest temporary directory"
            )
        return path if verified else None

    def _on_disk_matches(self) -> bool:
        """The checkpoint file, read back, holds this run's status and report record."""
        try:
            on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(
            isinstance(on_disk, dict)
            and on_disk.get("run_id") == self.run_id
            and on_disk.get("status") == self.state["status"]
            and on_disk.get("report") == self.state["report"]
        )

    def complete(self, report: Path | None) -> str:
        """Final verdict, printed as one ``P51_OUTCOME`` line and returned:

        * ``completed`` - report re-hashed and intact, final checkpoint written and read back with
          the same report record. The only outcome that means a durable, consistent result.
        * ``report_not_persisted`` - the report is not safely on disk.
        * ``checkpoint_not_persisted`` - the report is intact but the final checkpoint could not be
          written or read back: the report/checkpoint pair is UNCONFIRMED.
        * ``diagnostics_error`` - the diagnostics themselves failed (also when the failure was
          swallowed earlier, e.g. during stage bookkeeping): nothing is confirmed.
        * ``not_completed:<status>`` - the run already failed, timed out or was interrupted, or
          (``cleanup_failed``) the engine disposal failed after the work finished.

        Lifecycle (``_lifecycle`` in the benchmark): body, then engine disposal, then closing the
        diagnostics, then this method. So ``completed`` requires a successful disposal and a clean
        close; a failure of either is recorded before the verdict and prevents it. Nothing runs
        after the verdict except pytest's own fixture teardown, which this module does not and
        cannot vouch for.
        """
        try:
            return self._complete(report)
        except Exception as exc:
            self._diagnostics_failed = True
            self._emit(
                "[P51] P51_OUTCOME diagnostics_error: the diagnostics failed "
                f"({type(exc).__name__}); the durable result is NOT confirmed"
            )
            return "diagnostics_error"

    def _complete(self, report: Path | None) -> str:
        if self.state["status"] != "in_progress":
            outcome = f"not_completed:{self.state['status']}"
            self.mark(f"P51_OUTCOME {outcome}")
            return outcome
        self.state["current_stage"] = None
        recorded = self.state["report"] or {}
        if report is None or _sha256_of(report) != recorded.get("sha256"):
            self.state["status"] = "benchmark_finished_report_not_written"
            persisted = self._flush() and self._on_disk_matches()
            self.mark(
                "P51_OUTCOME report_not_persisted: the benchmark finished but the durable report "
                "is not safely on disk; final checkpoint "
                + ("written and read back" if persisted else "also not confirmed")
            )
            return "report_not_persisted"
        if self._diagnostics_failed:  # a swallowed bookkeeping error: never claim "completed"
            self.state["status"] = "diagnostics_error"
            self._flush()  # best effort
            self.mark(
                "P51_OUTCOME diagnostics_error: the diagnostics failed earlier in this run; report "
                f"{report.name} (sha256 {recorded['sha256']}) is intact on disk, but the "
                "report/checkpoint pair is UNCONFIRMED"
            )
            return "diagnostics_error"
        self.state["status"] = "completed"
        if self._flush() and self._on_disk_matches():
            self.mark(
                f"P51_OUTCOME completed: report {report.name} (sha256 {recorded['sha256']}) is "
                f"intact and {self.path.name} was written and read back with the same report record"
            )
            return "completed"
        self.state["status"] = "report_verified_checkpoint_unconfirmed"
        self._flush()  # best effort; if it also fails the file on disk may still say in_progress
        self.mark(
            f"P51_OUTCOME checkpoint_not_persisted: the benchmark finished and report "
            f"{report.name} (sha256 {recorded['sha256']}) is intact, but the final checkpoint "
            "could not be written or read back; the checkpoint on disk may still say "
            "in_progress; the report/checkpoint pair is UNCONFIRMED"
        )
        return "checkpoint_not_persisted"
