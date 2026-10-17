"""Investment-alert cycle block (Phase 51 Stage 6): evaluate and plan, never persist.

Specification: ``METHODOLOGY_INVESTMENT_ALERTS.md`` revision 6 (§4 items 4 and 5, §11) and ADR-0087.
**Experimental and not validated against historical outcomes.** One function,
``run_investment_cycle``, is called by ``cfi.alerts.service.AlertService.evaluate`` after the 11
existing alert types are fully processed. It reads the cycle's stored snapshot (exactly once, by
id, through an injected ``SnapshotReader``), builds the Phase 49 decision, evaluates it with the
pure evaluator and plans its lifecycle with the persistence gate **off**. It creates, persists,
resolves, clears and re-arms nothing: it holds a read-only reader and no repository.

Failure isolation (M-3)
* An ordinary ``Exception`` is contained: it becomes ``status="internal_error"`` and one error log
  with the traceback, and the function returns normally, so the 11 types are unaffected.
* ``SoftTimeLimitExceeded``, ``TimeLimitExceeded``, ``asyncio.CancelledError`` and
  ``KeyboardInterrupt`` are re-raised first, before the ordinary handler, with no log and no
  record. There is no ``BaseException`` handler and no bare ``except`` (``SystemExit`` and
  ``GeneratorExit`` are never caught either).
* A refusal (adapter or evaluator) is an ordinary result, not an error: ``status="refused"``,
  an evaluation with no outcomes, and no candidate anywhere.

Logging (one ``investment_alert_cycle`` event per cycle, at the highest applicable level)
* Fields are a fixed whitelist per status (``LOG_FIELDS``). No payload, uuid, hash, credential or
  exception message is ever a field. A refusal logs its closed reason and, for a builder refusal,
  the known exception class name only.
* Residual exposure, accepted and documented: the traceback attached to an ``internal_error`` log
  contains the exception message, and the logging redactor (``cfi.core.logging``) does not redact
  rendered tracebacks. That message can include SQL text, bound parameters, host details or
  quoted payload fragments.
* The logging call itself is outside the containment: a failure of the logging system is not an
  investment failure and is not hidden.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

from cfi.alerts.investment_adapter import SnapshotReader, read_and_build
from cfi.alerts.investment_alerts import (
    REFUSAL_REASONS,
    InvestmentAlertValidationError,
    InvestmentEvaluation,
    InvestmentLifecyclePlan,
    evaluate_investment_alerts,
    plan_investment_lifecycle,
)

__all__ = [
    "CYCLE_STATUSES",
    "DEFECT_LIKE_REFUSALS",
    "EVENT_NAME",
    "LOG_FIELDS",
    "WARNING_REFUSALS",
    "CycleLogger",
    "InvestmentCycleResult",
    "run_investment_cycle",
]

EVENT_NAME: Final = "investment_alert_cycle"
CYCLE_STATUSES: Final[tuple[str, ...]] = ("evaluated", "refused", "internal_error")

# Refusal reasons that most likely indicate a defect (a row committed moments ago is absent, a row
# is malformed, the decision disagrees with its own row, the builders broke their own contract, the
# cycle's own clock is wrong). They are still ordinary refusals (status ``refused``, no raise), but
# they are logged at error level, not as routine operation.
DEFECT_LIKE_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "snapshot_not_found",
        "snapshot_row_invalid",
        "snapshot_identity_mismatch",
        "decision_contract_invalid",
        "snapshot_time_invalid",
        "snapshot_time_in_future",
    }
)
# A designed input refusal by a Phase 44 to 49 builder: warning.
WARNING_REFUSALS: Final[frozenset[str]] = frozenset({"decision_inputs_refused"})

# The only keys a log event of each status may carry.
LOG_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "evaluated": (
        "snapshot_id",
        "status",
        "class_a",
        "class_b",
        "class_c",
        "incomplete_decision_assets",
        "integrity_gates",
        "persistence_enabled",
        "duration_ms",
    ),
    "refused": (
        "snapshot_id",
        "status",
        "refusal_reason",
        "refusal_detail",
        "persistence_enabled",
        "duration_ms",
    ),
    "internal_error": ("snapshot_id", "status", "error_class", "duration_ms"),
}

_GATE_KEYS: Final = ("look_ahead", "producer_hash")


class CycleLogger(Protocol):
    """The three structlog-style methods the block uses."""

    def info(self, event: str, **fields: Any) -> object: ...

    def warning(self, event: str, **fields: Any) -> object: ...

    def error(self, event: str, **fields: Any) -> object: ...


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class InvestmentCycleResult:
    """What one cycle's investment block produced. Data only; nothing here is persisted."""

    status: str
    evaluation: InvestmentEvaluation | None
    plan: InvestmentLifecyclePlan | None
    refusal_reason: str | None
    error_class: str | None
    duration_ms: int

    def __post_init__(self) -> None:
        if self.status not in CYCLE_STATUSES:
            raise InvestmentAlertValidationError(f"unknown cycle status: {self.status!r}")
        if not _plain_int(self.duration_ms) or self.duration_ms < 0:
            raise InvestmentAlertValidationError("duration_ms must be a non-negative int")
        if self.status == "internal_error":
            if self.evaluation is not None or self.plan is not None:
                raise InvestmentAlertValidationError("an internal error has no evaluation or plan")
            if self.refusal_reason is not None:
                raise InvestmentAlertValidationError("an internal error is not a refusal")
            if not isinstance(self.error_class, str) or not self.error_class.strip():
                raise InvestmentAlertValidationError("an internal error names its class")
            return
        if self.error_class is not None:
            raise InvestmentAlertValidationError("only an internal error has an error class")
        if self.evaluation is None or self.plan is None:
            raise InvestmentAlertValidationError("an evaluated or refused cycle has both parts")
        if self.plan.persistence_enabled:
            raise InvestmentAlertValidationError("persistence is disabled in Phase 51")
        if self.status == "refused":
            if not (self.evaluation.refused and self.plan.refused):
                raise InvestmentAlertValidationError("a refused cycle has a refused evaluation")
            if self.refusal_reason not in REFUSAL_REASONS:
                raise InvestmentAlertValidationError("a refusal has a closed reason")
            if self.refusal_reason != self.evaluation.refusal_reason:
                raise InvestmentAlertValidationError("refusal reason mismatch")
        else:
            if self.evaluation.refused or self.plan.refused or self.refusal_reason is not None:
                raise InvestmentAlertValidationError("an evaluated cycle is not a refusal")


def _gate_names(decision: object) -> tuple[str, ...]:
    """The Phase 46 gates that triggered, read defensively (a diagnostic only, never decisive)."""
    if not isinstance(decision, Mapping):
        return ()
    gates = decision.get("gates")
    if not isinstance(gates, Mapping):
        return ()
    names: list[str] = []
    for key in _GATE_KEYS:
        gate = gates.get(key)
        if isinstance(gate, Mapping) and gate.get("triggered") is True:
            names.append(key)
    return tuple(names)


def _incomplete_assets(evaluation: InvestmentEvaluation) -> tuple[str, ...]:
    return tuple(
        o.asset
        for o in evaluation.outcomes
        if o.outcome_class == "B" and o.reason == "incomplete_decision"
    )


def _loggable_id(snapshot_id: object) -> int | None:
    return (
        snapshot_id if isinstance(snapshot_id, int) and not isinstance(snapshot_id, bool) else None
    )


def _elapsed_ms(started: float, monotonic: Callable[[], float]) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _log_completed(
    logger: CycleLogger,
    snapshot_id: int,
    result: InvestmentCycleResult,
    evaluation: InvestmentEvaluation,
    plan: InvestmentLifecyclePlan,
    *,
    detail: str | None,
    gates: tuple[str, ...],
) -> None:
    if result.status == "refused":
        fields: dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "status": "refused",
            "refusal_reason": result.refusal_reason,
            "refusal_detail": detail,
            "persistence_enabled": plan.persistence_enabled,
            "duration_ms": result.duration_ms,
        }
        if result.refusal_reason in WARNING_REFUSALS:
            logger.warning(EVENT_NAME, **fields)
        else:  # a defect-like reason; any reason not known to be routine fails toward error
            logger.error(EVENT_NAME, **fields)
        return
    incomplete = _incomplete_assets(evaluation)
    fields = {
        "snapshot_id": snapshot_id,
        "status": "evaluated",
        "class_a": evaluation.count("A"),
        "class_b": evaluation.count("B"),
        "class_c": evaluation.count("C"),
        "incomplete_decision_assets": list(incomplete),
        "integrity_gates": list(gates),
        "persistence_enabled": plan.persistence_enabled,
        "duration_ms": result.duration_ms,
    }
    if "producer_hash" in gates:
        logger.error(EVENT_NAME, **fields)
    elif gates or incomplete:
        logger.warning(EVENT_NAME, **fields)
    else:
        logger.info(EVENT_NAME, **fields)


async def run_investment_cycle(
    reader: SnapshotReader,
    snapshot_id: int,
    *,
    now: datetime,
    logger: CycleLogger,
    monotonic: Callable[[], float] = time.monotonic,
) -> InvestmentCycleResult:
    """Evaluate and plan the investment alerts of one stored snapshot. Persists nothing.

    Reads the snapshot exactly once. Returns normally for every ordinary outcome, including an
    unexpected ordinary exception (``internal_error``); a time-limit or cancellation signal
    propagates unchanged. The persistence gate is never overridden here.
    """
    started = monotonic()
    try:
        outcome = await read_and_build(reader, snapshot_id)
        gates: tuple[str, ...] = ()
        if outcome.refusal_reason is not None:
            evaluation = InvestmentEvaluation(
                refused=True, refusal_reason=outcome.refusal_reason, outcomes=()
            )
        else:
            if outcome.identity is None:
                raise InvestmentAlertValidationError("a usable outcome carries an identity")
            evaluation = evaluate_investment_alerts(outcome.decision, outcome.identity, now=now)
            gates = _gate_names(outcome.decision)
        plan = plan_investment_lifecycle(evaluation, None, now=now)
        result = InvestmentCycleResult(
            status="refused" if evaluation.refused else "evaluated",
            evaluation=evaluation,
            plan=plan,
            refusal_reason=evaluation.refusal_reason,
            error_class=None,
            duration_ms=_elapsed_ms(started, monotonic),
        )
        detail = outcome.detail
    except (SoftTimeLimitExceeded, TimeLimitExceeded, asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception as exc:
        error_class = f"{type(exc).__module__}.{type(exc).__qualname__}"
        failed = InvestmentCycleResult(
            status="internal_error",
            evaluation=None,
            plan=None,
            refusal_reason=None,
            error_class=error_class,
            duration_ms=_elapsed_ms(started, monotonic),
        )
        logger.error(
            EVENT_NAME,
            snapshot_id=_loggable_id(snapshot_id),
            status="internal_error",
            error_class=error_class,
            duration_ms=failed.duration_ms,
            exc_info=True,
        )
        return failed
    _log_completed(logger, snapshot_id, result, evaluation, plan, detail=detail, gates=gates)
    return result
