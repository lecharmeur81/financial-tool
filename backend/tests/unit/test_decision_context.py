"""Phase 38.3 Decision Context: the bridge from a stored snapshot payload to the unchanged
Phase 38.2 engine. Payloads come from the real ``build_snapshot`` (see
``tests/decision_snapshots``).

The context must expose the engine's conclusions *unchanged*; most tests therefore compare the
context with a direct ``assess()`` over the same payload.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cfi.analyst.universe import SNAPSHOT_VERSION
from cfi.core.config import Settings
from cfi.decision import assess, context
from cfi.decision.context import (
    DecisionContext,
    InvalidSnapshotError,
    UnsupportedScopeError,
    build_decision_context,
)
from cfi.decision.identity import HashCheck, SnapshotRef, decision_input_hash
from cfi.decision.templates import TEMPLATES
from cfi.decision.universe import Freshness, Stance
from tests.decision_snapshots import build_real_snapshot, stored_form

BULLISH = ["S2", "S1", "N", "S1", "S2"]
CONFLICT = ["S2", "S2", "N", "A2", "A2"]


async def payload_for(
    mp: pytest.MonkeyPatch, settings: Settings, codes: list[str], **kwargs: Any
) -> dict[str, Any]:
    snap = await build_real_snapshot(mp, settings, codes, **kwargs)
    return stored_form(snap.payload())


# ------------------------------------------------------------------ 1. real-shaped adapter
async def test_real_snapshot_payload_shapes(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """The structures the context relies on, asserted on the real builder's output."""
    snap = await build_real_snapshot(monkeypatch, settings, BULLISH, question="q")
    live = snap.payload()
    assert live["snapshot_version"] == SNAPSHOT_VERSION == "analyst_snapshot.v1"
    assert live["as_of"] == "2026-10-05T12:00:00+00:00"  # datetime.isoformat(), tz-aware
    assert live["knowledge_time"] == "2026-10-05T12:05:00+00:00"
    assert datetime.fromisoformat(live["as_of"]).tzinfo is not None
    assert {f for node in live["fields"].values() for f in node} == {
        "display",
        "evidence_category",
        "quality_status",
        "unit",
        "source",
    }
    quality = live["tool_results"]["check_data_quality"]["data"]
    assert set(quality) == {
        "overall_status",
        "unavailable_tools",
        "degraded_tools",
        "conflicting_tools",
    }
    assert live["data_quality_state"] == quality["overall_status"]
    assert live["has_conflicts"] is bool(quality["conflicting_tools"])
    freshness = live["tool_results"]["get_whale_activity"]["data"]["assets"][1]["freshness"]
    assert set(freshness) == {"status", "latest", "expected_latest", "age_seconds", "rule", "note"}
    # The stored form holds the freshness dates as strings (the DB serializer uses default=str).
    stored = stored_form(live)
    assert (
        stored["tool_results"]["get_whale_activity"]["data"]["assets"][1]["freshness"]["latest"]
        == "2026-10-03"
    )
    # The three score-bearing domain tools carry the full ScoreResult (no "value" key).
    assert "value" not in stored["tool_results"]["get_liquidity"]["data"]["score"]
    assert "get_liquidity.score.band" in stored["fields"]


async def test_adapter_builds_a_context_from_live_and_stored_payloads(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, BULLISH)
    live, stored = snap.payload(), stored_form(snap.payload())
    from_live = build_decision_context(live, "BTC")
    from_stored = build_decision_context(stored, "BTC")
    assert from_live.assessment == from_stored.assessment
    assert from_live.deterministic_dict() == from_stored.deterministic_dict()
    assert from_stored.final_stance is Stance.STRONGLY_BULLISH


# ------------------------------------------------------------------ 2/9. determinism
async def test_repeatable_and_generated_at_independent(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH)
    one = build_decision_context(payload, "BTC", generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    two = build_decision_context(payload, "BTC", generated_at=datetime(2030, 6, 6, tzinfo=UTC))
    three = build_decision_context(payload, "BTC")
    assert one == two == three  # generated_at is outside equality
    assert one.deterministic_dict() == two.deterministic_dict() == three.deterministic_dict()
    assert "generated_at" not in one.deterministic_dict()
    assert one.to_dict()["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert three.to_dict()["generated_at"] is None
    assert json.dumps(one.deterministic_dict(), sort_keys=True) == json.dumps(
        two.deterministic_dict(), sort_keys=True
    )


async def test_input_payload_is_not_mutated(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH)
    before = json.dumps(payload, sort_keys=True)
    build_decision_context(payload, "BTC")
    assert json.dumps(payload, sort_keys=True) == before


# ------------------------------------------------------------------ 3/4/5. identity & hashes
async def test_snapshot_identity_and_hashes_are_preserved(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, BULLISH, question="q")
    payload = stored_form(snap.payload())
    ref = SnapshotRef(
        row_id=77,
        uuid="11111111-2222-3333-4444-555555555555",
        payload_hash=snap.snapshot_id,
        created_at=datetime(2026, 10, 5, 12, 6, tzinfo=UTC),
    )
    ctx = build_decision_context(payload, "BTC", snapshot_ref=ref)
    ident = ctx.identity
    assert (ident.row_id, ident.uuid) == (77, "11111111-2222-3333-4444-555555555555")
    assert ident.producer_payload_hash_stored == snap.snapshot_id
    assert ident.producer_hash_check is HashCheck.VERIFIED
    assert ident.decision_input_hash == decision_input_hash(payload)
    assert ident.decision_input_hash == ctx.assessment.snapshot_hash  # the engine's own value
    assert ident.decision_input_hash != ident.producer_payload_hash_stored
    assert ctx.observed_at == "2026-10-05T12:00:00+00:00"
    assert ctx.knowledge_time == "2026-10-05T12:05:00+00:00"
    assert ctx.snapshot_version == SNAPSHOT_VERSION
    assert (
        ctx.methodology_version,
        ctx.parameter_version,
        ctx.template_version,
    ) == (
        ctx.assessment.methodology_version,
        ctx.assessment.parameter_version,
        ctx.assessment.template_version,
    )
    again = build_decision_context(payload, "BTC", snapshot_ref=ref)
    assert again.identity == ctx.identity


async def test_a_hash_mismatch_is_reported_not_hidden_and_does_not_change_the_assessment(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH)
    bad = build_decision_context(payload, "BTC", snapshot_ref=SnapshotRef(payload_hash="0" * 64))
    plain = build_decision_context(payload, "BTC")
    assert bad.identity.producer_hash_check is HashCheck.MISMATCH
    assert plain.identity.producer_hash_check is HashCheck.UNVERIFIED
    assert bad.assessment == plain.assessment


# ------------------------------------------------------------------ 6. missing evidence
async def test_missing_evidence_stays_missing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(
        monkeypatch, settings, ["U", "S1", "N", "U", "S1"], regime=None, derivatives=None
    )
    ctx = build_decision_context(payload, "BTC")
    direct = assess(payload, "BTC")
    assert ctx.assessment == direct
    assert set(ctx.missing) == {"institutional", "macro"}
    assert {"regime", "derivatives"} <= set(ctx.missing_context)
    unavailable = set(ctx.data_quality.unavailable_components)
    assert any(c.startswith("institutional") for c in unavailable)
    assert any(c.startswith("macro") for c in unavailable)
    # Missing is never presented as a neutral (or any other directional) item.
    shown = {i.domain for i in (*ctx.supportive, *ctx.adverse, *ctx.neutral)}
    assert shown.isdisjoint({"institutional", "macro"})
    assert "get_institutional_flows" in ctx.data_quality.unavailable_tools
    assert ctx.data_quality.snapshot_state == "degraded"
    assert set(ctx.data_quality.missing_domains) == {"institutional", "macro"}
    assert ctx.data_quality.missing_domains == ctx.missing
    assert ctx.data_quality.missing_context == ctx.missing_context
    assert ctx.data_quality.quality_tool_present is True


async def test_all_directional_evidence_missing_is_insufficient_not_neutral(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, ["U"] * 5)
    ctx = build_decision_context(payload, "BTC")
    assert ctx.final_stance is Stance.INSUFFICIENT
    assert ctx.supportive == ()
    assert ctx.adverse == ()
    assert ctx.neutral == ()
    assert len(ctx.missing) == 5


# ------------------------------------------------------------------ 7. conflicts
async def test_directional_conflict_stays_visible(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, CONFLICT)
    ctx = build_decision_context(payload, "BTC")
    assert ctx.conflict is True
    assert ctx.data_quality.directional_conflict is True
    assert ctx.data_quality.source_conflicts is False  # a different thing, never merged
    assert {i.domain for i in ctx.supportive} == {"institutional", "whale"}
    assert {i.domain for i in ctx.adverse} == {"macro", "market_structure"}
    assert ctx.final_stance is Stance.NEUTRAL
    assert "CN-02" in ctx.reasons  # the conflict confidence downgrade fired and is listed


async def test_source_conflict_is_separate_from_directional_conflict(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(
        monkeypatch, settings, BULLISH, quality_status={"get_macro": "conflicting"}
    )
    ctx = build_decision_context(payload, "BTC")
    assert ctx.data_quality.source_conflicts is True
    assert ctx.data_quality.conflicting_tools == ("get_macro",)
    assert ctx.data_quality.directional_conflict is False
    assert ctx.conflict is False


# ------------------------------------------------------------------ 8. CAP-U
@pytest.mark.parametrize(
    ("kwargs", "rule", "ceiling"),
    [
        ({"regime": None}, "CU-01", Stance.NEUTRAL),
        ({"derivatives": None}, "CU-02", Stance.CAUTIOUSLY_BULLISH),
        ({"volatility": None}, "CU-03", Stance.CAUTIOUSLY_BULLISH),
    ],
)
async def test_cap_u_cannot_be_bypassed(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    kwargs: dict[str, Any],
    rule: str,
    ceiling: Stance,
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH, **kwargs)
    ctx = build_decision_context(payload, "BTC")
    direct = assess(payload, "BTC")
    assert ctx.assessment == direct  # not one value differs from the engine's result
    assert ctx.raw_stance is Stance.STRONGLY_BULLISH
    assert ctx.final_stance is ceiling
    assert [c.rule_id for c in ctx.cap_u] == [rule]
    assert ctx.cap_u[0].final_stance is ceiling
    assert ctx.cap_u[0].directional_stance_before_limits is ctx.raw_stance


async def test_least_permissive_cap_u_ceiling_wins_through_the_context(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH, regime=None, derivatives=None)
    ctx = build_decision_context(payload, "BTC")
    assert ctx.assessment == assess(payload, "BTC")
    assert ctx.final_stance is Stance.NEUTRAL
    assert {c.rule_id for c in ctx.cap_u} == {"CU-01", "CU-02"}


@pytest.mark.parametrize("scope", ["BTC", "ETH", "SOL", "XRP"])
@pytest.mark.parametrize("missing", [{}, {"regime": None}, {"derivatives": None}])
async def test_context_equals_the_engine_for_every_scope(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, scope: str, missing: dict[str, Any]
) -> None:
    codes = BULLISH if scope in ("BTC", "ETH") else ["S2", "S1", "N", "S1"]
    payload = await payload_for(monkeypatch, settings, codes, scope=scope, **missing)
    ctx = build_decision_context(payload, scope)
    assert ctx.assessment == assess(payload, scope)
    assert ctx.scope == scope


# ------------------------------------------------------------------ 10. source timestamps
async def test_source_timestamps_are_preserved(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, ["S2", "S1~", "N", "S1", "S2"])
    ctx = build_decision_context(payload, "BTC")
    by_domain = {s.domain: s for s in ctx.source_freshness}
    inst = by_domain["institutional"]
    assert inst.path == "tool_results.get_institutional_flows.data.assets[1].freshness"
    assert (inst.status, inst.latest, inst.expected_latest) == ("fresh", "2026-10-03", "2026-10-03")
    assert inst.age_seconds == 3600
    assert inst.rule
    assert inst.note
    whale = by_domain["whale"]
    assert (whale.status, whale.latest) == ("stale", "2026-09-25")
    assert whale.age_seconds == 777600
    # Score-bearing domains expose a status only (the payload has no source timestamp for them).
    assert by_domain["liquidity"].status == "fresh"
    assert by_domain["liquidity"].latest is None
    assert not any(s.after_knowledge_time for s in ctx.source_freshness)
    assert ctx.data_quality.look_ahead_violations == ()
    # Derivatives freshness is absent from v0 payloads, so no record is invented.
    assert "derivatives" not in by_domain


async def test_look_ahead_is_flagged_not_dropped(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH, latest_after_knowledge=True)
    ctx = build_decision_context(payload, "BTC")
    flagged = [s for s in ctx.source_freshness if s.after_knowledge_time]
    assert {s.domain for s in flagged} == {"institutional", "whale"}
    assert all(s.latest == "2026-10-09" for s in flagged)  # preserved verbatim
    assert set(ctx.data_quality.look_ahead_violations) == {s.path for s in flagged}
    assert ctx.assessment == assess(payload, "BTC")  # reported, never used to change the result


async def test_as_of_after_knowledge_time_is_flagged(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(
        monkeypatch,
        settings,
        BULLISH,
        as_of=datetime(2026, 10, 5, 13, 0, tzinfo=UTC),
        knowledge_time=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )
    ctx = build_decision_context(stored_form(snap.payload()), "BTC")
    assert "as_of" in ctx.data_quality.look_ahead_violations


# ------------------------------------------------------------------ 11. auditability
async def test_every_conclusion_traces_to_evidence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, CONFLICT)
    ctx = build_decision_context(payload, "BTC")
    items = (*ctx.supportive, *ctx.adverse, *ctx.neutral)
    assert items
    for item in items:
        assert item.field_ids or item.raw_paths, item.domain
        assert item.reason_ids, item.domain
        assert item.template_id in TEMPLATES
    # Field ids resolve to display strings copied verbatim from payload["fields"], or are listed
    # as unresolved - never silently dropped.
    wanted = {fid for r in ctx.assessment.readings for fid in r.field_ids}
    shown = {f.field_id for f in ctx.field_displays}
    assert shown | set(ctx.unresolved_field_ids) == wanted
    assert shown.isdisjoint(ctx.unresolved_field_ids)
    for f in ctx.field_displays:
        stored = payload["fields"][f.field_id]
        assert f.display == str(stored["display"])
        assert (f.evidence_category, f.quality_status, f.unit, f.source) == (
            stored["evidence_category"],
            stored["quality_status"],
            stored["unit"],
            stored["source"],
        )
    # The engine ids that the flattener never exposes are the tool-envelope statuses of the three
    # context-only tools; they are reported as unresolved, and their raw paths remain.
    assert set(ctx.unresolved_field_ids) <= {
        "calculate_divergence.status",
        "get_capital_rotation.status",
        "get_market_data.status",
    }
    # Every template id the result references has its fixed sentence attached.
    texts = dict(ctx.template_text)
    for tid in ctx.limitations + ctx.assessment.explanation.all_template_ids():
        assert tid in texts
    assert list(texts) == sorted(texts)
    # Every rule that fired is listed, in the engine's order.
    assert ctx.reasons == ctx.assessment.fired_rule_ids
    assert any(r.startswith("DS-") for r in ctx.reasons)


# ------------------------------------------------------------------ 12. rejection
@pytest.mark.parametrize("scope", ["DOGE", "btc", "", "market"])
async def test_unsupported_scope_is_rejected(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, scope: str
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH)
    with pytest.raises(UnsupportedScopeError):
        build_decision_context(payload, scope)
    assert issubclass(UnsupportedScopeError, ValueError)


async def test_invalid_snapshot_payloads_are_rejected(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    good = await payload_for(monkeypatch, settings, BULLISH)

    def mutated(**changes: Any) -> dict[str, Any]:
        out: dict[str, Any] = json.loads(json.dumps(good))
        for key, value in changes.items():
            if value is KeyError:
                del out[key]
            else:
                out[key] = value
        return out

    bad_inputs: list[Any] = [
        None,
        [],
        mutated(snapshot_version="test"),
        mutated(snapshot_version=KeyError),
        mutated(tool_results=KeyError),
        mutated(tool_results=[]),
        mutated(as_of=KeyError),
        mutated(as_of="not a time"),
        mutated(as_of="2026-10-05T12:00:00"),  # naive: no time zone
        mutated(knowledge_time=12345),
    ]
    for bad in bad_inputs:
        with pytest.raises(InvalidSnapshotError):
            build_decision_context(bad, "BTC")


# ------------------------------------------------------------------ 13. data quality
async def test_unavailable_stale_and_not_assessed_stay_distinct(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, ["S2~", "U", "N", "S1*", "S2"], regime=None)
    ctx = build_decision_context(payload, "BTC")
    dq = ctx.data_quality
    unavailable, stale = set(dq.unavailable_components), set(dq.stale_components)
    partial, not_assessed = set(dq.partial_components), set(dq.not_assessed_components)
    assert any(c.startswith("whale") for c in unavailable)
    assert any(c.startswith("institutional") for c in stale)
    assert any(c.startswith("macro") for c in partial)  # "*" marks a partial reading
    # Unavailable is not stale; not-assessed is not stale; derivatives freshness is not assessed.
    assert not any(c.startswith("whale") for c in stale)
    assert any(c.startswith("derivatives") for c in not_assessed)
    assert not any(c.startswith("derivatives") for c in stale)
    states = {r.component: r.freshness for r in dq.readings}
    assert Freshness.NOT_ASSESSED in states.values()
    assert dq.not_tracked == tuple(payload["not_tracked"])
    assert dq.snapshot_state == payload["data_quality_state"]
    assert ctx.limitations == ctx.assessment.limitations
    assert "regime" in ctx.missing_context


async def test_not_assessed_derivatives_never_caps_or_downgrades(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    payload = await payload_for(monkeypatch, settings, BULLISH)
    ctx = build_decision_context(payload, "BTC")
    assert ctx.cap_u == ()
    assert ctx.final_stance is ctx.raw_stance


# ------------------------------------------------------------------ 14. serialisation
async def test_to_dict_is_json_round_trippable_and_complete(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    snap = await build_real_snapshot(monkeypatch, settings, BULLISH, regime=None)
    ref = SnapshotRef(
        row_id=5,
        uuid="u-1",
        payload_hash=snap.snapshot_id,
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    ctx = build_decision_context(
        stored_form(snap.payload()),
        "BTC",
        snapshot_ref=ref,
        generated_at=datetime(2026, 10, 6, tzinfo=UTC),
    )
    as_dict = ctx.to_dict()
    text = json.dumps(as_dict, sort_keys=True)
    assert json.loads(text) == as_dict  # nothing is lost or altered by a JSON round trip
    assert json.dumps(ctx.to_dict(), sort_keys=True) == text  # repeatable
    summary = as_dict["summary"]
    assert summary["raw_stance"] == ctx.raw_stance.value
    assert summary["final_stance"] == ctx.final_stance.value
    assert summary["confidence"] == ctx.confidence.value
    assert summary["posture"] == ctx.posture.value
    assert summary["conflict"] is False
    assert summary["cap_u_rule_ids"] == [c.rule_id for c in ctx.cap_u]
    ident = as_dict["identity"]
    assert ident["row_id"] == 5
    assert ident["uuid"] == "u-1"
    assert ident["producer_payload_hash_stored"] == snap.snapshot_id
    assert ident["decision_input_hash"] != ident["producer_payload_hash_recomputed"]
    assert as_dict["assessment"]["final_stance"] == ctx.final_stance.value
    assert as_dict["assessment"]["cap_u"][0]["rule_id"] == "CU-01"
    for key in (
        "scope",
        "assessment",
        "data_quality",
        "source_freshness",
        "field_displays",
        "unresolved_field_ids",
        "template_text",
        "generated_at",
    ):
        assert key in as_dict


# ------------------------------------------------------------------ scope guard & isolation
def test_monitor_next_is_not_implemented() -> None:
    """The context only preserves missing / conflicting evidence and the methodology's explicit
    limitations; there is no monitor-next, confirmation, weakening or invalidation logic."""
    assert not hasattr(DecisionContext, "monitor_next")
    tree = ast.parse(Path(context.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.ClassDef)}
    names |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.arg) for a in [n]}
    banned = ("monitor", "confirm", "weaken", "invalidation", "trigger", "price_level")
    assert not {n for n in names if any(word in n.lower() for word in banned)}


FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy",
    "psycopg",
    "redis",
    "celery",
    "httpx",
    "requests",
    "aiohttp",
    "anthropic",
    "fastapi",
    "cfi.api",
    "cfi.db",
    "cfi.worker",
    "cfi.realtime",
    "cfi.providers",
    "cfi.analyst",
    "cfi.core",
    "cfi.derivatives",
    "cfi.regime",
    "cfi.decision.rules",
    "random",
    "time",
    "os",
    "subprocess",
    "socket",
)


@pytest.mark.parametrize("module", ["context", "identity"])
def test_new_modules_are_isolated(module: str) -> None:
    path = Path(context.__file__).with_name(f"{module}.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith(FORBIDDEN_IMPORT_PREFIXES), f"{module} imports {name}"
    # No clock and no randomness inside the deterministic path.
    for needle in ("datetime.now", "utcnow", "time.time", "perf_counter", "random.", "uuid4"):
        assert needle not in source, f"{module} uses {needle}"
