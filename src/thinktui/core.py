"""Analysis records and independent method registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Session:
    project_id: str
    method_id: str
    title: str
    id: str = field(default_factory=lambda: str(uuid4()))
    problem_statement: str = ""
    objective: str = ""
    context: str = ""
    stakeholders: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    decisions: list[dict[str, Any]] = field(default_factory=list)
    method_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=timestamp)
    updated_at: str = field(default_factory=timestamp)
    completed_at: str | None = None


class ThinkingMethod(Protocol):
    id: str
    name: str
    category: str
    description: str

    def validate(self, state: dict[str, Any]) -> list[str]: ...
    def calculate(self, state: dict[str, Any]) -> dict[str, Any]: ...
    def summarize(self, state: dict[str, Any]) -> str: ...


METHODS: dict[str, ThinkingMethod] = {}

# Assumption validation status (spec §40). Blank means not yet tested.
ASSUMPTION_STATUSES = ("Untested", "Testing", "Supported", "Weak", "Falsified")
# Plain-language test results shown in editors and reviews; saved values stay as above.
ASSUMPTION_STATUS_LABELS = {
    "Untested": "Not yet tested",
    "Testing": "Testing now",
    "Supported": "Held",
    "Weak": "Mixed result",
    "Falsified": "Disproved",
}


def assumption_status_label(status: str | None) -> str:
    return ASSUMPTION_STATUS_LABELS.get(status or "Untested", status or "Not yet tested")


def assumption_review(rows: list[tuple[str, str, str | None]]) -> dict[str, Any]:
    """Summarize test results from (statement, quadrant, status) rows. Counts only; no judgments change."""
    statuses = [status or "Untested" for _, _, status in rows]
    tested = [status for status in statuses if status not in ("Untested", "Testing")]
    counts = [
        f"{statuses.count(status)} {ASSUMPTION_STATUS_LABELS[status].lower()}"
        for status in ("Supported", "Weak", "Falsified", "Testing")
        if statuses.count(status)
    ]
    return {
        "progress": f"{len(tested)} of {len(rows)} tested" + (f" ({', '.join(counts)})" if counts else ""),
        "disproved": [statement for statement, _, status in rows if status == "Falsified"],
        "untested_test_first": [
            statement
            for statement, quadrant, status in rows
            if quadrant == "TEST FIRST" and (status or "Untested") == "Untested"
        ],
    }


def assumption_quadrant(low_confidence: bool, high_impact: bool) -> str:
    """The Key Assumptions Check confidence × impact-if-wrong matrix (spec §22)."""
    if high_impact:
        return "TEST FIRST" if low_confidence else "Important"
    return "Monitor" if low_confidence else "Watch"


def register(method: ThinkingMethod) -> None:
    if method.id in METHODS:
        raise ValueError(f"Duplicate method: {method.id}")
    METHODS[method.id] = method
