"""Deterministic method calculations. All state is JSON-compatible."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from pairwise_prioritizer.models import Project
from pairwise_prioritizer.ranking import BradleyTerry

from .core import ASSUMPTION_STATUSES, assumption_quadrant, assumption_review, register
from .issue_tree import nested, nodes_for


@dataclass(frozen=True)
class Pairwise:
    id: str = "pairwise"
    name: str = "Pairwise Ranking"
    category: str = "Decision & Prioritization"
    description: str = "Compare every pair; calculate Bradley–Terry strengths."

    def validate(self, state: dict) -> list[str]:
        if not isinstance(state, dict) or not isinstance(state.get("ranking"), dict):
            return ["Add at least two items."]
        try:
            project = Project.from_dict(state["ranking"])
            if len(project.items) < 2:
                return ["Add at least two items."]
        except Exception:
            return ["Comparison set has invalid items or judgments."]
        return []

    def calculate(self, state: dict) -> dict:
        if issues := self.validate(state):
            raise ValueError(" ".join(issues))
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
        criteria = state.get("criteria", []) if isinstance(state, dict) else []
        alternatives = state.get("alternatives", []) if isinstance(state, dict) else []
        if (
            not isinstance(criteria, list)
            or not isinstance(alternatives, list)
            or any(not isinstance(row, dict) for row in [*criteria, *alternatives])
        ):
            return ["Criteria and alternatives must be lists of named rows."]
        for label, rows in (("Criterion", criteria), ("Alternative", alternatives)):
            names = [row.get("name") for row in rows]
            if any(not isinstance(value, str) or not value.strip() for value in names):
                issues.append(f"{label} names must be distinct nonblank text.")
            elif len(set(names)) != len(names):
                issues.append(f"{label} names must be distinct nonblank text.")
        if len(criteria) < 1 or len(alternatives) < 2:
            issues.append("Enter criteria and at least two alternatives.")
        weights = [c.get("weight") for c in criteria]
        if (
            not weights
            or any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights)
            or not math.isfinite(sum(w for w in weights if type(w) in (int, float) and math.isfinite(w)))
            or sum(w for w in weights if type(w) in (int, float) and math.isfinite(w)) <= 0
        ):
            issues.append("Weights must be finite, nonnegative numbers with a positive total.")
        if any(c.get("direction", "benefit") not in ("cost", "benefit") for c in criteria):
            issues.append("Direction must be benefit or cost.")
        for alternative in alternatives:
            if not isinstance(alternative.get("scores", []), list) or len(alternative.get("scores", [])) != len(
                criteria
            ):
                issues.append("Each alternative needs one score per criterion.")
            elif any(
                type(s) not in (int, float) or not math.isfinite(s) or not 0 <= s <= 10 for s in alternative["scores"]
            ):
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


def _optional_text_issue(row: dict, keys: tuple[str, ...], label: str) -> str:
    for key in keys:
        if key in row and row[key] is not None and not isinstance(row[key], str):
            return f"{label} {key.replace('_', ' ')} must be text."
    return ""


@dataclass(frozen=True)
class Assumptions:
    id: str = "assumptions"
    name: str = "Key Assumptions Check"
    category: str = "Problem Analysis"
    description: str = "Identify low-confidence, high-impact assumptions and validation tests."
    # Optional per-assumption planning fields; ratings stay separate and user-supplied.
    TEXT_FIELDS = ("action", "basis", "change_mind")

    def validate(self, state: dict) -> list[str]:
        rows = state.get("entries") if isinstance(state, dict) else None
        if not isinstance(rows, list) or not rows:
            return ["Add at least one assumption."]
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not isinstance(row.get("statement"), str) or not row["statement"].strip():
                return [f"Assumption {index} needs a statement."]
            for key, low, high in (("confidence", 0, 100), ("impact", 1, 10)):
                value = row.get(key)
                if type(value) is not int or not low <= value <= high:
                    return [f"Assumption {index} {key} must be your whole-number rating from {low} to {high}."]
            if issue := _optional_text_issue(row, self.TEXT_FIELDS, f"Assumption {index}"):
                return [issue]
            if row.get("status") not in (None, "", *ASSUMPTION_STATUSES):
                return [f"Assumption {index} status must be one of: {', '.join(ASSUMPTION_STATUSES)}."]
        return []

    @staticmethod
    def risk(row: dict) -> float:
        return (1 - row["confidence"] / 100) * row["impact"]

    @staticmethod
    def quadrant(row: dict) -> str:
        return assumption_quadrant(row["confidence"] < 50, row["impact"] >= 6)

    def calculate(self, state: dict) -> dict:
        if issues := self.validate(state):
            raise ValueError(" ".join(issues))
        # Sorted rows are the saved entry objects so editors can map back to them.
        rows = sorted(state["entries"], key=self.risk, reverse=True)
        return {
            "priorities": rows,
            "quadrants": [f"{self.quadrant(row)}: {row['statement']}" for row in rows],
            "review": assumption_review([(row["statement"], self.quadrant(row), row.get("status")) for row in rows]),
            "note": "Quadrants: confidence below 50 is low; impact 6 or more is high. Ratings are your judgments.",
        }

    def summarize(self, state: dict) -> str:
        return f"{len(state.get('entries', []))} assumptions recorded; highest-risk first."


@dataclass(frozen=True)
class Premortem:
    id: str = "premortem"
    name: str = "Premortem"
    category: str = "Risk"
    description: str = "Imagine failure, record causes, then assign preventive actions."
    TEXT_FIELDS = ("action", "category", "owner", "warning_sign")

    def validate(self, state: dict) -> list[str]:
        rows = state.get("entries") if isinstance(state, dict) else None
        if not isinstance(rows, list) or not rows:
            return ["Add at least one failure mode."]
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not isinstance(row.get("statement"), str) or not row["statement"].strip():
                return [f"Failure mode {index} needs a statement."]
            for key, low, high in (("likelihood", 0, 100), ("impact", 1, 10)):
                value = row.get(key)
                if type(value) is not int or not low <= value <= high:
                    return [f"Failure mode {index} {key} must be your whole-number rating from {low} to {high}."]
            if issue := _optional_text_issue(row, self.TEXT_FIELDS, f"Failure mode {index}"):
                return [issue]
        return []

    def calculate(self, state: dict) -> dict:
        if issues := self.validate(state):
            raise ValueError(" ".join(issues))
        risks = sorted(state["entries"], key=lambda r: r["likelihood"] * r["impact"], reverse=True)
        clusters: dict[str, list[str]] = {}
        for row in risks:
            clusters.setdefault((row.get("category") or "").strip() or "Unclustered", []).append(row["statement"])
        return {"risks": risks, "clusters": dict(sorted(clusters.items()))}

    def summarize(self, state: dict) -> str:
        return f"{len(state.get('entries', []))} potential failure modes recorded."


@dataclass(frozen=True)
class IssueTree:
    id: str = "issue_tree"
    name: str = "Issue Tree"
    category: str = "Problem Analysis"
    description: str = "Decompose a question into testable branches."

    def validate(self, state: dict) -> list[str]:
        try:
            if not nodes_for(state):
                return ["Add at least one branch."]
            nested(state)
        except (KeyError, ValueError, TypeError) as exc:
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
        if not isinstance(state, dict):
            return ["Decision journal must be an object."]
        if not isinstance(state.get("decision"), str) or not state["decision"].strip():
            issues.append("Describe the decision.")
        if not isinstance(state.get("chosen"), str) or not state["chosen"].strip():
            issues.append("Record the chosen option.")
        dates = {}
        for key, label in (("decision_date", "Decision date"), ("review_date", "Review date")):
            raw = state.get(key, "")
            if raw:
                try:
                    if date.fromisoformat(raw).isoformat() != raw:
                        raise ValueError
                    dates[key] = date.fromisoformat(raw)
                except (TypeError, ValueError):
                    issues.append(f"{label} must be YYYY-MM-DD.")
        if len(dates) == 2 and dates["review_date"] < dates["decision_date"]:
            issues.append("Review date must be on or after the decision date.")
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
            and not str(state.get("actual_outcome") or "").strip()
            and date.fromisoformat(review_date) <= date.today()
        )
        return {
            "status": "Recorded" if not issues else "Draft",
            "decision": state.get("decision", ""),
            "decision_date": state.get("decision_date", ""),
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
