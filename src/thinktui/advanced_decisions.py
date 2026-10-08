"""V0.2 deterministic analysis: ACH, expected value, decision trees, sensitivity, AHP."""

from __future__ import annotations

import math
from typing import Any

from .core import register


class StructuredMethod:
    id: str
    name: str
    category: str = "Decision & Prioritization"
    description: str
    example: dict

    def validate(self, state: dict) -> list[str]:
        try:
            self.calculate(state)
        except (ValueError, KeyError, TypeError) as exc:
            return [str(exc)]
        return []

    def summarize(self, state: dict) -> str:
        from .reports import plain_result

        lines = plain_result(self.calculate(state)).splitlines()
        return "\n".join(lines[:10]) + ("\n… open the report for all results" if len(lines) > 10 else "")


def number(value: Any, label: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number") from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{label} must be finite and at least {minimum}")
    return result


def probability(value: Any, label: str) -> float:
    result = number(value, label, 0)
    if result > 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must have a name")
    return value.strip()


class ACH(StructuredMethod):
    id = "ach"
    name = "Analysis of Competing Hypotheses"
    category = "Problem Analysis"
    description = "Rank hypotheses by weighted contradicting evidence, not supporting evidence."
    example = {
        "hypotheses": ["H1", "H2"],
        "evidence": [{"title": "Observed latency", "reliability": 1, "ratings": {"H1": "--", "H2": "+"}}],
    }
    RATINGS = {"--": -2, "-": -1, "0": 0, "+": 1, "++": 2, "?": None}

    def calculate(self, state: dict) -> dict:
        hypotheses = state.get("hypotheses", [])
        if len(hypotheses) < 2 or any(not isinstance(h, str) or not h.strip() for h in hypotheses):
            raise ValueError("Enter at least two named hypotheses")
        if len(set(hypotheses)) != len(hypotheses):
            raise ValueError("Hypothesis names must be distinct")
        evidence = state.get("evidence", [])
        if not evidence:
            raise ValueError("Enter at least one evidence item")
        totals = {h: 0.0 for h in hypotheses}
        diagnostics = []
        for row in evidence:
            title = name(row["title"], "Evidence")
            reliability = probability(row.get("reliability", 1), "Reliability")
            ratings = row["ratings"]
            if set(ratings) != set(hypotheses) or any(r not in self.RATINGS for r in ratings.values()):
                raise ValueError("Each evidence item must rate every hypothesis with ++, +, 0, -, -- or ?")
            known = [self.RATINGS[r] for r in ratings.values() if r != "?"]
            diagnosticity = max(known) - min(known) if len(known) > 1 else 0
            for h in hypotheses:
                value = self.RATINGS[ratings[h]]
                if value is not None and value < 0:
                    totals[h] += -value * diagnosticity * reliability
            diagnostics.append(
                {
                    "title": title,
                    "source": row.get("source", ""),
                    "diagnosticity": diagnosticity,
                    "reliability": reliability,
                    "ratings": ratings,
                }
            )
        ranking = sorted(totals, key=lambda h: (totals[h], h))
        return {
            "ranking": [{"hypothesis": h, "inconsistency": totals[h]} for h in ranking],
            "evidence": diagnostics,
            "note": "Lower weighted inconsistency is better; not a posterior probability.",
        }


class ExpectedValue(StructuredMethod):
    id = "expected_value"
    name = "Expected Value"
    description = "Compute probability-weighted outcomes for alternatives."
    example = {
        "alternatives": [
            {"name": "Build", "outcomes": [{"probability": 0.7, "value": 200}, {"probability": 0.3, "value": -50}]},
            {"name": "Wait", "outcomes": [{"probability": 1, "value": 0}]},
        ]
    }

    def calculate(self, state: dict) -> dict:
        alternatives = state.get("alternatives", [])
        if len(alternatives) < 2:
            raise ValueError("Enter at least two alternatives")
        rows = []
        for alternative in alternatives:
            label = name(alternative["name"], "Alternative")
            outcomes = alternative.get("outcomes", [])
            if not outcomes:
                raise ValueError(f"{label} needs outcomes")
            probs = [probability(row["probability"], "Outcome probability") for row in outcomes]
            if not math.isclose(sum(probs), 1, abs_tol=1e-8):
                raise ValueError(f"{label} probabilities must sum to 1")
            values = [number(row["value"], "Outcome value") for row in outcomes]
            rows.append({"name": label, "expected_value": sum(p * v for p, v in zip(probs, values, strict=True))})
        if len({row["name"] for row in rows}) != len(rows):
            raise ValueError("Alternative names must be distinct")
        return {
            "ranking": sorted(rows, key=lambda row: (-row["expected_value"], row["name"])),
            "note": "Values must share a common unit; probabilities are user judgments.",
        }


class DecisionTree(StructuredMethod):
    id = "decision_tree"
    name = "Decision Tree"
    description = "Roll back nested chance and decision nodes using expected values."
    example = {
        "tree": {
            "type": "decision",
            "branches": [
                {
                    "name": "Build",
                    "node": {
                        "type": "chance",
                        "branches": [
                            {"name": "Success", "probability": 0.7, "node": {"type": "outcome", "value": 200}},
                            {"name": "Failure", "probability": 0.3, "node": {"type": "outcome", "value": -50}},
                        ],
                    },
                },
                {"name": "Wait", "node": {"type": "outcome", "value": 0}},
            ],
        }
    }

    def calculate(self, state: dict) -> dict:
        def visit(node: dict, depth: int) -> dict:
            if depth > 50:
                raise ValueError("Tree exceeds 50 levels")
            kind = node["type"]
            if kind == "outcome":
                return {"type": kind, "expected_value": number(node["value"], "Outcome value")}
            if kind not in {"chance", "decision"} or not node.get("branches"):
                raise ValueError("Nodes must be outcomes or nonempty chance/decision branches")
            branches = [
                {
                    "name": name(b["name"], "Branch"),
                    "result": visit(b["node"], depth + 1),
                    **(
                        {"probability": probability(b["probability"], "Chance probability")} if kind == "chance" else {}
                    ),
                }
                for b in node["branches"]
            ]
            if len({b["name"] for b in branches}) != len(branches):
                raise ValueError("Branch names must be distinct")
            if kind == "chance":
                if not math.isclose(sum(b["probability"] for b in branches), 1, abs_tol=1e-8):
                    raise ValueError("Chance probabilities must sum to 1")
                value = sum(b["probability"] * b["result"]["expected_value"] for b in branches)
            else:
                value = max(b["result"]["expected_value"] for b in branches)
            result = {"type": kind, "expected_value": value, "branches": branches}
            if kind == "decision":
                result["highest_ev_branch"] = max(branches, key=lambda b: b["result"]["expected_value"])["name"]
            return result

        return {
            "analysis": visit(state["tree"], 0),
            "note": "Highest EV is a calculation, not a user-approved decision.",
        }


class Sensitivity(StructuredMethod):
    id = "sensitivity"
    name = "Sensitivity Analysis"
    description = "Find where two weighted alternatives switch as one criterion weight varies."
    example = {
        "criteria": [{"name": "Value", "weight": 0.5}, {"name": "Cost", "weight": 0.5, "direction": "cost"}],
        "alternatives": [{"name": "A", "scores": [9, 8]}, {"name": "B", "scores": [6, 2]}],
        "vary": "Value",
        "range": [0, 1],
    }

    def calculate(self, state: dict) -> dict:
        criteria = state.get("criteria", [])
        alternatives = state.get("alternatives", [])
        if len(criteria) < 2 or len(alternatives) != 2:
            raise ValueError("Enter at least two criteria and exactly two alternatives")
        names = [name(c["name"], "Criterion") for c in criteria]
        if len(set(names)) != len(names) or state.get("vary") not in names:
            raise ValueError("Criterion names must be unique and 'vary' must name one")
        vary = names.index(state["vary"])
        weights = [number(c["weight"], "Weight", 0) for c in criteria]
        other_total = sum(weights) - weights[vary]
        if other_total <= 0:
            raise ValueError("Other criteria need positive total weight")
        bounds = state.get("range", [0, 1])
        if len(bounds) != 2:
            raise ValueError("Range must contain two weights")
        low, high = [probability(x, "Range weight") for x in bounds]
        if low >= high:
            raise ValueError("Range lower bound must be less than upper bound")
        scores = []
        for alt in alternatives:
            label = name(alt["name"], "Alternative")
            if len(alt.get("scores", [])) != len(criteria):
                raise ValueError("Each alternative needs one score per criterion")
            scores.append((label, [number(v, "Score", 0) for v in alt["scores"]]))
            if any(v > 10 for v in scores[-1][1]):
                raise ValueError("Scores must be between 0 and 10")
        if scores[0][0] == scores[1][0]:
            raise ValueError("Alternative names must be distinct")
        if any(c.get("direction", "benefit") not in {"benefit", "cost"} for c in criteria):
            raise ValueError("Direction must be benefit or cost")

        def total(alt: list[float], weight: float) -> float:
            adjusted = [
                10 - value if c.get("direction") == "cost" else value for c, value in zip(criteria, alt, strict=True)
            ]
            return weight * adjusted[vary] + (1 - weight) * sum(
                weights[i] / other_total * adjusted[i] for i in range(len(criteria)) if i != vary
            )

        d0 = total(scores[0][1], low) - total(scores[1][1], low)
        d1 = total(scores[0][1], high) - total(scores[1][1], high)
        threshold = None if math.isclose(d0, d1) else low - d0 * (high - low) / (d1 - d0)
        if threshold is not None and not low - 1e-12 <= threshold <= high + 1e-12:
            threshold = None
        return {
            "vary": names[vary],
            "range": [low, high],
            "switch_weight": threshold,
            "endpoints": [
                {"weight": w, "scores": {label: total(values, w) for label, values in scores}} for w in (low, high)
            ],
            "note": "Other weights scale proportionally; scores are user judgments.",
        }


class AHP(StructuredMethod):
    id = "ahp"
    name = "Analytic Hierarchy Process"
    description = "Priority vectors and consistency ratio from reciprocal criteria/alternative matrices."
    example = {
        "criteria": ["Value", "Cost"],
        "alternatives": ["A", "B"],
        "criteria_matrix": [[1, 3], [1 / 3, 1]],
        "alternative_matrices": {"Value": [[1, 2], [0.5, 1]], "Cost": [[1, 0.5], [2, 1]]},
    }
    RI = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

    def _priority(self, matrix: list, n: int) -> dict:
        if len(matrix) != n or any(len(row) != n for row in matrix):
            raise ValueError("Matrix must be square and match its labels")
        values = [[number(v, "AHP judgment", 0) for v in row] for row in matrix]
        for i in range(n):
            for j in range(n):
                if values[i][j] <= 0 or not math.isclose(values[i][j] * values[j][i], 1, rel_tol=1e-5):
                    raise ValueError("AHP judgments must be positive and reciprocal")
        weights = [1 / n] * n
        for _ in range(1000):
            updated = [sum(values[i][j] * weights[j] for j in range(n)) for i in range(n)]
            total = sum(updated)
            updated = [v / total for v in updated]
            if max(abs(a - b) for a, b in zip(weights, updated, strict=True)) < 1e-12:
                weights = updated
                break
            weights = updated
        eigen = sum(sum(values[i][j] * weights[j] for j in range(n)) / weights[i] for i in range(n)) / n
        ci = max(0, (eigen - n) / (n - 1)) if n > 1 else 0
        return {"weights": weights, "consistency_index": ci, "consistency_ratio": ci / self.RI[n] if self.RI[n] else 0}

    def calculate(self, state: dict) -> dict:
        criteria, alternatives = state["criteria"], state["alternatives"]
        if not 1 <= len(criteria) <= 10 or not 2 <= len(alternatives) <= 10:
            raise ValueError("Use 1–10 criteria and 2–10 alternatives")
        if any(not isinstance(label, str) or not label.strip() for label in criteria + alternatives):
            raise ValueError("All labels must be nonempty")
        if len(set(criteria)) != len(criteria) or len(set(alternatives)) != len(alternatives):
            raise ValueError("Labels must be unique")
        criterion = self._priority(state["criteria_matrix"], len(criteria))
        matrices = state["alternative_matrices"]
        if set(matrices) != set(criteria):
            raise ValueError("Provide an alternative matrix for every criterion")
        priorities = {c: self._priority(matrices[c], len(alternatives)) for c in criteria}
        rows = [
            {
                "name": alt,
                "priority": sum(criterion["weights"][i] * priorities[c]["weights"][j] for i, c in enumerate(criteria)),
            }
            for j, alt in enumerate(alternatives)
        ]
        return {
            "ranking": sorted(rows, key=lambda r: -r["priority"]),
            "criteria": criterion,
            "alternatives_by_criterion": priorities,
            "warning": "Review judgments with consistency ratio > 0.1; low CR does not prove validity.",
        }


for method in (ACH(), ExpectedValue(), DecisionTree(), Sensitivity(), AHP()):
    register(method)
