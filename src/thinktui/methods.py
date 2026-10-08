"""Deterministic method calculations. All state is JSON-compatible."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from pairwise_prioritizer.models import Project
from pairwise_prioritizer.ranking import BradleyTerry

from .core import register
from .issue_tree import nested, nodes_for


@dataclass(frozen=True)
class Pairwise:
    id: str = "pairwise"
    name: str = "Pairwise Ranking"
    category: str = "Decision & Prioritization"
    description: str = "Compare every pair; calculate Bradley–Terry strengths."

    def validate(self, state: dict) -> list[str]:
        return [] if "ranking" in state else ["Add at least two items."]

    def calculate(self, state: dict) -> dict:
        project = Project.from_dict(state["ranking"])
        rows = BradleyTerry().calculate(project.items, list(project.comparisons.values()))
        return {
            "remaining": project.remaining,
            "total": project.total,
            "ranking": [
                {
                    "name": r.item.name,
                    "rank": r.rank,
                    "score": r.score,
                    "wins": r.wins,
                    "losses": r.losses,
                    "ties": r.ties,
                }
                for r in rows
            ],
        }

    def summarize(self, state: dict) -> str:
        result = self.calculate(state)
        return f"{result['total'] - result['remaining']}/{result['total']} comparisons completed."


@dataclass(frozen=True)
class Matrix:
    id: str = "matrix"
    name: str = "Weighted Decision Matrix"
    category: str = "Decision & Prioritization"
    description: str = "Score alternatives across weighted benefit and cost criteria."

    def validate(self, state: dict) -> list[str]:
        issues = []
        criteria = state.get("criteria", [])
        alternatives = state.get("alternatives", [])
        if len(criteria) < 1 or len(alternatives) < 2:
            issues.append("Enter criteria and at least two alternatives.")
        weights = [c.get("weight") for c in criteria]
        if (
            not weights
            or any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights)
            or sum(w for w in weights if type(w) in (int, float) and math.isfinite(w)) <= 0
        ):
            issues.append("Weights must be finite, nonnegative numbers with a positive total.")
        if any(c.get("direction", "benefit") not in ("cost", "benefit") for c in criteria):
            issues.append("Direction must be benefit or cost.")
        for alternative in alternatives:
            if len(alternative.get("scores", [])) != len(criteria):
                issues.append("Each alternative needs one score per criterion.")
            elif any(not isinstance(s, (int, float)) or not 0 <= s <= 10 for s in alternative["scores"]):
                issues.append("Scores must be numbers between 0 and 10.")
        return issues

    def calculate(self, state: dict) -> dict:
        issues = self.validate(state)
        if issues:
            raise ValueError(" ".join(issues))
        criteria = state["criteria"]
        total = sum(c["weight"] for c in criteria)
        weights = [c["weight"] / total for c in criteria]
        rows = []
        for alternative in state["alternatives"]:
            score = sum(
                w * (10 - s if c.get("direction") == "cost" else s)
                for w, c, s in zip(weights, criteria, alternative["scores"], strict=True)
            )
            rows.append({"name": alternative["name"], "score": round(score, 4)})
        rows.sort(key=lambda row: (-row["score"], row["name"]))
        return {"ranking": rows, "normalized_weights": weights}

    def summarize(self, state: dict) -> str:
        result = self.calculate(state)
        return f"Top alternative: {result['ranking'][0]['name']} ({result['ranking'][0]['score']:.2f}/10)."


@dataclass(frozen=True)
class Assumptions:
    id: str = "assumptions"
    name: str = "Key Assumptions Check"
    category: str = "Problem Analysis"
    description: str = "Identify low-confidence, high-impact assumptions and validation tests."

    def validate(self, state: dict) -> list[str]:
        return [] if state.get("entries") else ["Add at least one assumption."]

    def calculate(self, state: dict) -> dict:
        rows = state.get("entries", [])
        return {
            "priorities": sorted(
                rows,
                key=lambda r: (1 - r.get("confidence", 50) / 100) * r.get("impact", 5),
                reverse=True,
            )
        }

    def summarize(self, state: dict) -> str:
        return f"{len(state.get('entries', []))} assumptions recorded; highest-risk first."


@dataclass(frozen=True)
class Premortem:
    id: str = "premortem"
    name: str = "Premortem"
    category: str = "Risk"
    description: str = "Imagine failure, record causes, then assign preventive actions."

    def validate(self, state: dict) -> list[str]:
        return [] if state.get("entries") else ["Add at least one failure mode."]

    def calculate(self, state: dict) -> dict:
        return {
            "risks": sorted(
                state.get("entries", []),
                key=lambda r: r.get("likelihood", 1) * r.get("impact", 1),
                reverse=True,
            )
        }

    def summarize(self, state: dict) -> str:
        return f"{len(state.get('entries', []))} potential failure modes recorded."


@dataclass(frozen=True)
class IssueTree:
    id: str = "issue_tree"
    name: str = "Issue Tree"
    category: str = "Problem Analysis"
    description: str = "Decompose a question into testable branches."

    def validate(self, state: dict) -> list[str]:
        if not nodes_for(state):
            return ["Add at least one branch."]
        try:
            nested(state)
        except (KeyError, ValueError) as exc:
            return [str(exc)]
        return []

    def calculate(self, state: dict) -> dict:
        issues = self.validate(state)
        if issues:
            raise ValueError(" ".join(issues))
        return {"branches": nested(state)}

    def summarize(self, state: dict) -> str:
        return f"{len(nodes_for(state))} branches recorded."


@dataclass(frozen=True)
class DecisionJournal:
    id: str = "journal"
    name: str = "Decision Journal"
    category: str = "Decision & Prioritization"
    description: str = "Record the decision separately from the eventual outcome and review it later."

    def validate(self, state: dict) -> list[str]:
        issues = []
        if not state.get("decision", "").strip():
            issues.append("Describe the decision.")
        if not state.get("chosen", "").strip():
            issues.append("Record the chosen option.")
        review_date = state.get("review_date", "")
        if review_date:
            try:
                if date.fromisoformat(review_date).isoformat() != review_date:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append("Review date must be YYYY-MM-DD.")
        confidence = state.get("confidence", "")
        if confidence not in ("", None):
            try:
                value = int(confidence)
                if str(value) != str(confidence) or not 0 <= value <= 100:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append("Confidence must be a whole number between 0 and 100.")
        return issues

    def calculate(self, state: dict) -> dict:
        issues = self.validate(state)
        review_date = state.get("review_date", "")
        review_due = bool(
            not issues
            and review_date
            and not state.get("actual_outcome")
            and date.fromisoformat(review_date) <= date.today()
        )
        return {
            "status": "Recorded" if not issues else "Draft",
            "decision": state.get("decision", ""),
            "chosen": state.get("chosen", ""),
            "expected_outcome": state.get("expected_outcome", ""),
            "actual_outcome": state.get("actual_outcome", ""),
            "review_date": review_date,
            "review_due": review_due,
        }

    def summarize(self, state: dict) -> str:
        return f"{self.calculate(state)['status']}: {state.get('decision', '')}"


for _method in (Pairwise(), Matrix(), Assumptions(), Premortem(), IssueTree(), DecisionJournal()):
    register(_method)

# Each staged method owns its validation, calculation and example. Importing these
# modules is enough to add them to the library without editing screen dispatch.
from . import (  # noqa: E402, F401
    advanced_decisions,
    catalog_decisions,
    catalog_risk_forecast,
    catalog_systems,
    forecasting,
    strategy_risk,
)
