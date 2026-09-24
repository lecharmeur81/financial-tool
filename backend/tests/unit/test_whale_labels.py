"""Entity classification (R5): evidence, source and confidence on every classification; size
never makes an institution; labels obey point-in-time and validity rules; conflicts are shown."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from cfi.core.addresses import is_valid_address
from cfi.domain.enums import EvidenceClass
from cfi.whales.label_store import SEED_FILES, seed_text
from cfi.whales.labels import (
    CSV_COLUMNS,
    STRONG_EVIDENCE_ONLY,
    UNKNOWN_LARGE,
    UNLABELLED,
    Entity,
    Label,
    LabelError,
    classify,
    parse_label_csv,
)
from tests.whale_fakes import btc_address

T = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ADDR = btc_address(1)
ENTITIES = {
    "x1": Entity("x1", "Exchange One", "exchange"),
    "f1": Entity("f1", "Fund One", "fund"),
    "i1": Entity("i1", "Institution One", "institution"),
}


def label(**kw: Any) -> Label:
    base: dict[str, Any] = {
        "chain": "bitcoin",
        "address": ADDR,
        "actor_class": "exchange",
        "entity_id": "x1",
        "evidence_class": EvidenceClass.ATTRIBUTED,
        "confidence": Decimal("0.6"),
        "evidence": "listed by a named source",
        "source": "Source A",
        "available_at": T - timedelta(days=10),
    }
    return Label(**(base | kw))


def run(labels: list[Label], **kw: Any) -> Any:
    args: dict[str, Any] = {"at": T, "as_of": T, "knowledge_time": T, "entities": ENTITIES}
    return classify("bitcoin", ADDR, labels, **(args | kw))


# ------------------------------------------------------------------ label rules


@pytest.mark.parametrize("actor", ["institution", "fund", "market_maker", "exchange", "protocol"])
def test_inferred_evidence_can_never_name_a_known_class(actor: str) -> None:
    with pytest.raises(LabelError, match="inferred"):
        label(actor_class=actor, evidence_class=EvidenceClass.INFERRED)


def test_strong_evidence_classes_are_the_three_the_rules_name() -> None:
    assert frozenset({"institution", "fund", "market_maker"}) == STRONG_EVIDENCE_ONLY


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"actor_class": UNKNOWN_LARGE, "evidence_class": EvidenceClass.INFERRED}, "names none"),
        ({"entity_id": None}, "names none"),
        ({"confidence": Decimal("1.2")}, "confidence"),
        ({"confidence": Decimal("-0.1")}, "confidence"),
        ({"evidence": "  "}, "evidence and source"),
        ({"source": ""}, "evidence and source"),
        ({"address": ADDR[:-1] + ("a" if ADDR[-1] != "a" else "b")}, "invalid bitcoin address"),
        ({"chain": "solana"}, "unsupported chain"),
        ({"actor_class": "whale"}, "unknown actor class"),
        ({"valid_from": T, "valid_to": T}, "valid_from"),
    ],
)
def test_label_validation(kw: dict[str, Any], message: str) -> None:
    with pytest.raises(LabelError, match=message):
        label(**kw)


def test_unknown_large_holder_label_is_inferred_without_entity() -> None:
    lb = label(actor_class=UNKNOWN_LARGE, entity_id=None, evidence_class=EvidenceClass.INFERRED)
    assert lb.entity_id is None


def test_bech32_label_address_is_stored_lower_case() -> None:
    lb = label(address="BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
    assert lb.address == "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


# ------------------------------------------------------------------ classification


def test_label_classification_carries_evidence_source_and_confidence() -> None:
    c = run([label(source_url="https://example.org/list")])
    assert c.actor_class == "exchange"
    assert c.entity_name == "Exchange One"
    assert c.evidence_class == "attributed"
    assert c.confidence == Decimal("0.6")
    assert c.evidence == "listed by a named source"
    assert c.source == "Source A"
    assert c.source_url == "https://example.org/list"
    assert c.display == "Known exchange: Exchange One"
    assert c.conflicts == ()


@pytest.mark.parametrize("balance", [Decimal(1_000), Decimal(500_000), Decimal(10) ** 9])
def test_size_alone_gives_unknown_large_holder_never_an_institution(balance: Decimal) -> None:
    c = run([], balance=balance, large_holder_min=Decimal(1_000), unit="BTC")
    assert c.actor_class == UNKNOWN_LARGE
    assert c.evidence_class == "inferred"
    assert c.confidence == Decimal("0.5")
    assert c.entity_id is None
    assert c.source == "size rule"
    assert "says nothing about who controls" in c.evidence
    assert c.actor_class not in ("institution", "fund", "market_maker", "exchange")


def test_below_the_size_threshold_is_unlabelled() -> None:
    c = run([], balance=Decimal("999.99"), large_holder_min=Decimal(1_000), unit="BTC")
    assert c.actor_class == UNLABELLED
    assert c.evidence_class is None
    assert c.confidence is None
    assert run([]).actor_class == UNLABELLED  # no balance known


def test_a_label_wins_over_the_size_rule() -> None:
    c = run([label()], balance=Decimal(10**6), large_holder_min=Decimal(1_000))
    assert c.actor_class == "exchange"


def test_direct_evidence_beats_attributed_and_conflicts_are_reported() -> None:
    attributed = label(confidence=Decimal("0.9"))
    direct = label(
        actor_class="fund",
        entity_id="f1",
        evidence_class=EvidenceClass.DIRECT,
        confidence=Decimal("0.7"),
        source="Fund One disclosure",
    )
    c = run([attributed, direct])
    assert (c.actor_class, c.evidence_class, c.source) == ("fund", "direct", "Fund One disclosure")
    assert c.conflicts == (attributed,)


def test_higher_confidence_wins_within_the_same_evidence_class() -> None:
    low = label(confidence=Decimal("0.4"), source="Low")
    high = label(
        actor_class="institution", entity_id="i1", confidence=Decimal("0.8"), source="High"
    )
    c = run([low, high])
    assert c.source == "High"
    assert [x.source for x in c.conflicts] == ["Low"]


def test_agreeing_labels_are_not_conflicts() -> None:
    c = run([label(source="A"), label(source="B", confidence=Decimal("0.5"))])
    assert c.source == "A"
    assert c.conflicts == ()


def test_label_published_after_as_of_is_not_used() -> None:
    later = label(available_at=T + timedelta(hours=1))
    assert run([later]).actor_class == UNLABELLED
    assert run([later], as_of=T + timedelta(hours=1)).actor_class == "exchange"


def test_label_recorded_after_knowledge_time_is_not_used() -> None:
    lb = label(recorded_at=T + timedelta(minutes=1))
    assert run([lb]).actor_class == UNLABELLED
    assert run([lb], knowledge_time=T + timedelta(minutes=1)).actor_class == "exchange"


def test_label_validity_period_bounds_the_classified_time() -> None:
    lb = label(valid_from=T - timedelta(days=5), valid_to=T - timedelta(days=1))
    assert run([lb], at=T - timedelta(days=3)).actor_class == "exchange"
    assert run([lb], at=T - timedelta(days=6)).actor_class == UNLABELLED
    assert run([lb], at=T - timedelta(days=1)).actor_class == UNLABELLED  # valid_to exclusive


def test_labels_for_other_addresses_or_chains_are_ignored() -> None:
    other = label(address=btc_address(2))
    assert run([other]).actor_class == UNLABELLED


# ------------------------------------------------------------------ label files

HEADER = ",".join(CSV_COLUMNS)


def csv_row(**kw: str) -> str:
    base = {
        "chain": "bitcoin",
        "address": ADDR,
        "actor_class": "exchange",
        "entity_id": "x1",
        "entity_name": "Exchange One",
        "evidence_class": "attributed",
        "confidence": "0.6",
        "evidence": "listed",
        "source": "Source A",
        "source_url": "",
        "valid_from": "",
        "valid_to": "",
        "available_at": "2026-09-24T05:29:20+00:00",
    } | kw
    return ",".join(base[c] for c in CSV_COLUMNS)


def test_label_file_parses_entities_and_labels() -> None:
    parsed = parse_label_csv("\n".join([HEADER, csv_row(), csv_row(address=btc_address(2))]))
    assert list(parsed.entities) == ["x1"]
    assert len(parsed.labels) == 2


def test_every_bad_row_is_listed_and_nothing_is_imported() -> None:
    text = "\n".join(
        [
            HEADER,
            csv_row(),
            csv_row(address="1BadAddressxxxxxxxxxxxxxxxxxxxxxxx"),
            csv_row(address=btc_address(3), evidence_class="inferred", actor_class="institution"),
            csv_row(address=btc_address(4), available_at="2026-09-24T05:29:20"),  # naive
            csv_row(address=btc_address(5), confidence="high"),
        ]
    )
    with pytest.raises(LabelError) as err:
        parse_label_csv(text)
    message = str(err.value)
    for line in ("line 3", "line 4", "line 5", "line 6"):
        assert line in message
    assert "line 2" not in message


def test_label_file_rejects_wrong_header_duplicates_and_redefined_entities() -> None:
    with pytest.raises(LabelError, match="header"):
        parse_label_csv("chain,address\nbitcoin," + ADDR)
    with pytest.raises(LabelError, match="twice"):
        parse_label_csv("\n".join([HEADER, csv_row(), csv_row()]))
    with pytest.raises(LabelError, match="defined differently"):
        parse_label_csv(
            "\n".join([HEADER, csv_row(), csv_row(address=btc_address(2), entity_name="Other")])
        )


def test_shipped_seed_file_is_valid_attributed_and_checksum_verified() -> None:
    parsed = parse_label_csv(seed_text(SEED_FILES[0]))
    assert len(parsed.labels) == 27
    assert all(is_valid_address("bitcoin", lb.address) for lb in parsed.labels)
    assert {lb.evidence_class for lb in parsed.labels} == {EvidenceClass.ATTRIBUTED}
    assert {lb.source for lb in parsed.labels} == {"BitInfoCharts"}
    assert all(lb.confidence == Decimal("0.6") for lb in parsed.labels)
    assert all('wallet label "' in lb.evidence for lb in parsed.labels)
    classes = {e.actor_class for e in parsed.entities.values()}
    assert classes == {"exchange", "institution", "miner", "government", "other"}
    # nicknames without an identifiable entity ("Mr.100" …) are not in the file
    assert "1Ay8vMC7R1UbyCCZRVULMV7iQpHSAbguJP" not in {lb.address for lb in parsed.labels}
