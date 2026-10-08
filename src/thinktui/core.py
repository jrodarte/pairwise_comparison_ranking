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


def register(method: ThinkingMethod) -> None:
    if method.id in METHODS:
        raise ValueError(f"Duplicate method: {method.id}")
    METHODS[method.id] = method
