"""Entity classification of on-chain addresses (R5).

An address is classified only from **evidence**:

- a *label* — a record in ``ref.entity_label`` saying which known entity an address belongs to,
  with its evidence class (``direct``: the entity itself published the address; ``attributed``: a
  named third party labels it), a confidence, the evidence text, the source and the period it is
  valid for; or
- its *size* — an unlabelled address holding at least ``LARGE_HOLDER_MIN`` is an **unknown large
  holder** (evidence class ``inferred``). Size never makes an address an exchange, institution,
  fund or market maker: large ≠ institutional. The database enforces the same rules (migration
  0005 CHECK constraints), so no code path can store an inferred institution.

Point in time: a label counts at time ``at`` for a view ``as_of`` only if it was available by
``as_of`` (``available_at``), recorded by ``knowledge_time`` (``recorded_at``) and valid at
``at`` (``valid_from`` / ``valid_to``, open ends allowed).

Precedence among labels that count: evidence class (direct before attributed), then confidence,
then the most recently available. Labels that disagree on the entity are reported as a conflict
next to the chosen one — never hidden.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from cfi.core.addresses import CHAINS, InvalidAddressError, canonical_address
from cfi.core.time import ensure_utc
from cfi.domain.enums import EvidenceClass

KnownClass = Literal[
    "exchange", "institution", "fund", "market_maker", "protocol", "miner", "government", "other"
]
KNOWN_CLASSES: tuple[KnownClass, ...] = (
    "exchange",
    "institution",
    "fund",
    "market_maker",
    "protocol",
    "miner",
    "government",
    "other",
)
UNKNOWN_LARGE = "unknown_large_holder"
UNLABELLED = "unlabelled"
LABEL_CLASSES: tuple[str, ...] = (*KNOWN_CLASSES, UNKNOWN_LARGE)
# Classes that can never rest on inference (R5): they need a direct or attributed source.
STRONG_EVIDENCE_ONLY = frozenset({"institution", "fund", "market_maker"})
# Judgment parameter: the size is observed, but whether one actor controls the address (and not,
# e.g., a custodian for many clients) is not known.
SIZE_RULE_CONFIDENCE = Decimal("0.5")
_EVIDENCE_RANK = {EvidenceClass.DIRECT: 0, EvidenceClass.ATTRIBUTED: 1, EvidenceClass.INFERRED: 2}

CLASS_LABELS: dict[str, str] = {
    "exchange": "Known exchange",
    "institution": "Known institution",
    "fund": "Known fund",
    "market_maker": "Known market maker",
    "protocol": "Known protocol",
    "miner": "Known miner / mining pool",
    "government": "Known government",
    "other": "Other known entity",
    UNKNOWN_LARGE: "Unknown large holder",
    UNLABELLED: "Unlabelled",
}


class LabelError(ValueError):
    """A label that breaks the classification rules."""


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    name: str
    actor_class: KnownClass
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id or not self.name:
            raise LabelError("entity_id and name are required")
        if self.actor_class not in KNOWN_CLASSES:
            raise LabelError(f"entity class {self.actor_class!r} is not a known-entity class")


@dataclass(frozen=True, slots=True)
class Label:
    """One address label. Mirrors the database rules of ``ref.entity_label``."""

    chain: str
    address: str
    actor_class: str
    entity_id: str | None
    evidence_class: EvidenceClass
    confidence: Decimal
    evidence: str
    source: str
    available_at: datetime
    source_url: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime | None = None
    label_id: int | None = None

    def __post_init__(self) -> None:
        if self.chain not in CHAINS:
            raise LabelError(f"unsupported chain {self.chain!r}")
        try:
            canonical = canonical_address(self.chain, self.address)
        except InvalidAddressError as exc:
            raise LabelError(f"invalid {self.chain} address {self.address!r}: {exc}") from exc
        object.__setattr__(self, "address", canonical)
        if self.actor_class not in LABEL_CLASSES:
            raise LabelError(f"unknown actor class {self.actor_class!r}")
        object.__setattr__(self, "evidence_class", EvidenceClass(self.evidence_class))
        if self.evidence_class is EvidenceClass.INFERRED and self.actor_class != UNKNOWN_LARGE:
            raise LabelError("an inferred label can only say 'unknown large holder' (R5)")
        if self.actor_class in STRONG_EVIDENCE_ONLY and self.evidence_class not in (
            EvidenceClass.DIRECT,
            EvidenceClass.ATTRIBUTED,
        ):
            raise LabelError(f"'{self.actor_class}' needs direct or attributed evidence (R5)")
        if (self.actor_class == UNKNOWN_LARGE) != (self.entity_id is None):
            raise LabelError("known classes name an entity; 'unknown large holder' names none")
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise LabelError("confidence must be within [0, 1]")
        if not self.evidence.strip() or not self.source.strip():
            raise LabelError("evidence and source are required for every label")
        object.__setattr__(self, "available_at", ensure_utc(self.available_at))
        for name in ("valid_from", "valid_to", "recorded_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, field=name))
        if self.valid_from and self.valid_to and self.valid_from >= self.valid_to:
            raise LabelError("valid_from must be earlier than valid_to")

    def counts(self, at: datetime, as_of: datetime, knowledge_time: datetime) -> bool:
        """Whether this label may be used for time ``at`` in a view as of ``as_of``."""
        if self.available_at > as_of:
            return False
        if self.recorded_at is not None and self.recorded_at > knowledge_time:
            return False
        if self.valid_from is not None and at < self.valid_from:
            return False
        return not (self.valid_to is not None and at >= self.valid_to)


@dataclass(frozen=True, slots=True)
class Classification:
    chain: str
    address: str
    actor_class: str
    evidence_class: str | None
    confidence: Decimal | None
    evidence: str
    source: str | None
    rule: str
    entity_id: str | None = None
    entity_name: str | None = None
    source_url: str | None = None
    label_id: int | None = None
    conflicts: tuple[Label, ...] = field(default=())

    @property
    def is_known(self) -> bool:
        return self.actor_class in KNOWN_CLASSES

    @property
    def display(self) -> str:
        if self.entity_name:
            return f"{CLASS_LABELS[self.actor_class]}: {self.entity_name}"
        return CLASS_LABELS[self.actor_class]


def _rank(label: Label) -> tuple[int, Decimal, float]:
    return (
        _EVIDENCE_RANK[label.evidence_class],
        -label.confidence,
        -label.available_at.timestamp(),
    )


def classify(
    chain: str,
    address: str,
    labels: Iterable[Label],
    *,
    at: datetime,
    as_of: datetime,
    knowledge_time: datetime,
    entities: dict[str, Entity],
    balance: Decimal | None = None,
    large_holder_min: Decimal | None = None,
    unit: str = "",
) -> Classification:
    """Classify one address at time ``at`` from the labels and, optionally, its balance."""
    address = canonical_address(chain, address)
    usable = sorted(
        (
            lb
            for lb in labels
            if lb.chain == chain and lb.address == address and lb.counts(at, as_of, knowledge_time)
        ),
        key=_rank,
    )
    known = [lb for lb in usable if lb.actor_class != UNKNOWN_LARGE]
    if known:
        best = known[0]
        conflicts = tuple(
            lb
            for lb in known[1:]
            if (lb.actor_class, lb.entity_id) != (best.actor_class, best.entity_id)
        )
        entity = entities.get(best.entity_id or "")
        return Classification(
            chain=chain,
            address=address,
            actor_class=best.actor_class,
            evidence_class=str(best.evidence_class),
            confidence=best.confidence,
            evidence=best.evidence,
            source=best.source,
            source_url=best.source_url,
            rule="label (" + str(best.evidence_class) + ")",
            entity_id=best.entity_id,
            entity_name=entity.name if entity else best.entity_id,
            label_id=best.label_id,
            conflicts=conflicts,
        )
    if balance is not None and large_holder_min is not None and balance >= large_holder_min:
        return Classification(
            chain=chain,
            address=address,
            actor_class=UNKNOWN_LARGE,
            evidence_class=str(EvidenceClass.INFERRED),
            confidence=SIZE_RULE_CONFIDENCE,
            evidence=(
                f"No label. Balance {balance:,.2f} {unit} ≥ {large_holder_min:,} {unit} (size "
                "only: says nothing about who controls the address)"
            ),
            source="size rule",
            rule=f"size rule: balance ≥ {large_holder_min:,} {unit}",
        )
    return Classification(
        chain=chain,
        address=address,
        actor_class=UNLABELLED,
        evidence_class=None,
        confidence=None,
        evidence="No label for this address",
        source=None,
        rule="no label",
    )


# ---------------------------------------------------------------------------- label files

CSV_COLUMNS = (
    "chain",
    "address",
    "actor_class",
    "entity_id",
    "entity_name",
    "evidence_class",
    "confidence",
    "evidence",
    "source",
    "source_url",
    "valid_from",
    "valid_to",
    "available_at",
)


@dataclass(frozen=True, slots=True)
class LabelFile:
    entities: dict[str, Entity]
    labels: tuple[Label, ...]


def _time(value: str, field: str, line: int) -> datetime | None:
    if not value:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value), field=field)
    except ValueError as exc:
        raise LabelError(f"line {line}: {field} {value!r} is not a timezone-aware time") from exc


def parse_label_csv(text: str) -> LabelFile:
    """Parse and validate a label file. Any invalid row rejects the whole file (all problems are
    listed), so a mistyped address or a rule violation is never imported partially."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_COLUMNS:
        raise LabelError(f"header must be: {','.join(CSV_COLUMNS)}")
    entities: dict[str, Entity] = {}
    labels: list[Label] = []
    problems: list[str] = []
    for line, row in enumerate(reader, start=2):
        try:
            entity_id = row["entity_id"] or None
            if entity_id is not None:
                entity = Entity(entity_id, row["entity_name"], row["actor_class"])  # type: ignore[arg-type]
                previous = entities.setdefault(entity_id, entity)
                if previous != entity:
                    raise LabelError(f"entity {entity_id!r} is defined differently on another line")
            elif row["entity_name"]:
                raise LabelError("entity_name given without entity_id")
            try:
                confidence = Decimal(row["confidence"])
            except InvalidOperation as exc:
                raise LabelError(f"confidence {row['confidence']!r} is not a number") from exc
            available_at = _time(row["available_at"], "available_at", line)
            if available_at is None:
                raise LabelError("available_at is required")
            labels.append(
                Label(
                    chain=row["chain"],
                    address=row["address"],
                    actor_class=row["actor_class"],
                    entity_id=entity_id,
                    evidence_class=EvidenceClass(row["evidence_class"]),
                    confidence=confidence,
                    evidence=row["evidence"],
                    source=row["source"],
                    source_url=row["source_url"] or None,
                    valid_from=_time(row["valid_from"], "valid_from", line),
                    valid_to=_time(row["valid_to"], "valid_to", line),
                    available_at=available_at,
                )
            )
        except (LabelError, ValueError) as exc:
            problems.append(f"line {line}: {exc}")
    if problems:
        raise LabelError("label file rejected:\n" + "\n".join(problems))
    keys = [(lb.chain, lb.address, lb.actor_class, lb.entity_id, lb.source) for lb in labels]
    if len(set(keys)) != len(keys):
        raise LabelError("label file rejected: the same label appears twice")
    return LabelFile(entities, tuple(labels))


def labels_for(labels: Sequence[Label], chain: str, address: str) -> list[Label]:
    return [lb for lb in labels if lb.chain == chain and lb.address == address]
