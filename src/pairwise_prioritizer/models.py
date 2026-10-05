"""Domain objects and JSON-safe serialization for a ranking project."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def pair_key(a: str, b: str) -> str:
    """Canonical key for an unordered pair of distinct item IDs."""
    if a == b:
        raise ValueError("An item cannot be compared with itself")
    return ":".join(sorted((a, b)))


class Outcome(StrEnum):
    """Outcome relative to the stored (oriented) a/b item IDs."""

    A_WINS = "a_wins"
    B_WINS = "b_wins"
    TIE = "tie"


@dataclass
class Item:
    """A priority candidate."""

    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now)


@dataclass
class Comparison:
    """Most recent effective decision for a pair."""

    item_a_id: str
    item_b_id: str
    outcome: Outcome
    sequence: int
    decided_at: str = field(default_factory=now)
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def key(self) -> str:
        return pair_key(self.item_a_id, self.item_b_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this comparison."""
        return {**asdict(self), "outcome": self.outcome.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Comparison:
        """Deserialize this comparison."""
        return cls(**{**data, "outcome": Outcome(data["outcome"])})


@dataclass
class Change:
    """Reversible decision, retained even after undo for audit purposes."""

    key: str
    before: dict[str, Any] | None
    after: dict[str, Any]


@dataclass
class Project:
    """Persisted state; order is a seeded list of oriented pairs."""

    name: str
    items: list[Item]
    order: list[tuple[str, str]]
    seed: int
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    created_at: str = field(default_factory=now)
    modified_at: str = field(default_factory=now)
    comparisons: dict[str, Comparison] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    undo_stack: list[Change] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.order)

    @property
    def remaining(self) -> int:
        return self.total - len(self.comparisons)

    @property
    def status(self) -> str:
        if not self.comparisons:
            return "Not Started"
        return "Completed" if not self.remaining else "In Progress"

    def to_dict(self) -> dict[str, Any]:
        """Serialize all state, including reproducible order and full audit trail."""
        return {
            "schema_version": 1,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "items": [asdict(item) for item in self.items],
            "order": self.order,
            "seed": self.seed,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "comparisons": {key: value.to_dict() for key, value in self.comparisons.items()},
            "skipped": self.skipped,
            "pending": self.pending,
            "undo_stack": [asdict(change) for change in self.undo_stack],
            "audit": self.audit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Read a saved project; reject incompatible schema versions."""
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported project format")
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            items=[Item(**item) for item in data["items"]],
            order=[tuple(pair) for pair in data["order"]],
            seed=data["seed"],
            created_at=data["created_at"],
            modified_at=data["modified_at"],
            comparisons={k: Comparison.from_dict(v) for k, v in data["comparisons"].items()},
            skipped=list(data.get("skipped", [])),
            pending=list(data.get("pending", [])),
            undo_stack=[Change(**change) for change in data.get("undo_stack", [])],
            audit=list(data.get("audit", [])),
        )
