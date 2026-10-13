"""Remaining risk and estimation methods; probabilities only from explicit user input."""

from __future__ import annotations

import math

from .advanced_decisions import StructuredMethod, name, number, probability
from .core import register


class RiskMatrix(StructuredMethod):
    id = "risk_matrix"
    name = "Risk Matrix"
    category = "Risk"
    description = "View likelihood and impact separately alongside an ordinal screening product."
    example = {
        "scale_max": 5,
        "risks": [
            {"name": "Outage", "likelihood": 3, "impact": 5, "mitigation": "Failover", "owner": "Platform"},
            {"name": "Delay", "likelihood": 4, "impact": 2, "mitigation": "Pilot", "owner": "Delivery lead"},
        ],
    }

    def calculate(self, state: dict) -> dict:
        scale = state.get("scale_max", 5)
        if type(scale) is not int or not 2 <= scale <= 10:
            raise ValueError("Scale maximum must be an integer between 2 and 10")
        rows = state.get("risks", [])
        if not rows:
            raise ValueError("Enter risks")
        ranked = []
        for row in rows:
            label = name(row["name"], "Risk")
            likelihood, impact = row["likelihood"], row["impact"]
            if any(type(v) is not int or not 1 <= v <= scale for v in (likelihood, impact)):
                raise ValueError(f"Likelihood and impact must be integers from 1 to {scale}")
            ranked.append(
                {
                    "name": label,
                    "likelihood": likelihood,
                    "impact": impact,
                    "screening_product": likelihood * impact,
                    "mitigation": name(row["mitigation"], "Mitigation"),
                    **({"owner": row["owner"]} if isinstance(row.get("owner"), str) and row["owner"].strip() else {}),
                }
            )
        return {
            "scale_max": scale,
            "risks": sorted(ranked, key=lambda r: (-r["screening_product"], r["name"])),
            "warning": "Ordinal scale products are a screening heuristic, not a calibrated risk probability.",
        }


class _FaultLogic:
    """A bounded reduced ordered BDD, so a repeated basic event is never independent of itself."""

    MAX_NODES = 50_000
    MAX_EVENTS = 300

    def __init__(self) -> None:
        self.probabilities: list[float] = []
        self.names: dict[str, int] = {}
        self.nodes: dict[int, tuple[int, int, int]] = {}
        self.unique: dict[tuple[int, int, int], int] = {}
        self.cache: dict[tuple[str, int, int], int] = {}
        self.probability_cache: dict[int, float] = {0: 0.0, 1: 1.0}

    def leaf(self, label: str, chance: float) -> int:
        if label in self.names:
            index = self.names[label]
            if self.probabilities[index] != chance:
                raise ValueError(f"Basic event {label} has conflicting probabilities")
        else:
            if len(self.names) >= self.MAX_EVENTS:
                raise ValueError("Fault tree supports at most 300 distinct basic events")
            index = self.names[label] = len(self.names)
            self.probabilities.append(chance)
        return self.make(index, 0, 1)

    def make(self, variable: int, low: int, high: int) -> int:
        if low == high:
            return low
        key = variable, low, high
        if key not in self.unique:
            if len(self.unique) >= self.MAX_NODES:
                raise ValueError("Fault tree exceeds the 50,000-node calculation limit")
            node = len(self.nodes) + 2
            self.unique[key] = node
            self.nodes[node] = key
        return self.unique[key]

    def combine(self, gate: str, left: int, right: int) -> int:
        if gate == "AND" and (left == 0 or right == 0) or gate == "OR" and (left == 1 or right == 1):
            return 0 if gate == "AND" else 1
        if left == right:
            return left
        if gate == "AND" and left == 1 or gate == "OR" and left == 0:
            return right
        if gate == "AND" and right == 1 or gate == "OR" and right == 0:
            return left
        key = gate, min(left, right), max(left, right)
        if key not in self.cache:
            variable = min(self.nodes[left][0], self.nodes[right][0])

            def branch(node: int, side: int) -> int:
                return self.nodes[node][side + 1] if self.nodes[node][0] == variable else node

            low = self.combine(gate, branch(left, 0), branch(right, 0))
            high = self.combine(gate, branch(left, 1), branch(right, 1))
            self.cache[key] = self.make(variable, low, high)
        return self.cache[key]

    def chance(self, node: int) -> float:
        if node not in self.probability_cache:
            variable, low, high = self.nodes[node]
            p = self.probabilities[variable]
            self.probability_cache[node] = (1 - p) * self.chance(low) + p * self.chance(high)
        return self.probability_cache[node]


class FaultTree(StructuredMethod):
    id = "fault_tree"
    name = "Fault Tree Analysis"
    category = "Risk"
    description = "Calculate an AND/OR fault-tree probability only with explicit independence assumptions."
    example = {
        "top_event": "Service outage",
        "tree": {
            "type": "OR",
            "independent": True,
            "children": [
                {"type": "event", "name": "Network", "probability": 0.1},
                {"type": "event", "name": "Database", "probability": 0.2},
            ],
        },
    }

    def calculate(self, state: dict) -> dict:
        name(state["top_event"], "Top event")
        logic = _FaultLogic()

        def visit(node: dict, depth: int) -> tuple[dict, int]:
            if depth > 40:
                raise ValueError("Fault tree exceeds 40 levels")
            kind = node["type"]
            if kind == "event":
                label = name(node["name"], "Basic event")
                chance = probability(node["probability"], "Event probability")
                return {"name": label, "probability": chance}, logic.leaf(label, chance)
            if kind not in {"AND", "OR"} or node.get("independent") is not True:
                raise ValueError("Gates must be AND/OR and explicitly mark independent: true")
            children = node.get("children", [])
            if len(children) < 2:
                raise ValueError("Gates need two or more children")
            evaluated = [visit(child, depth + 1) for child in children]
            root = 1 if kind == "AND" else 0
            for _, child in evaluated:
                root = logic.combine(kind, root, child)
            return {
                "gate": kind,
                "probability": logic.chance(root),
                "children": [result for result, _ in evaluated],
            }, root

        result, _ = visit(state["tree"], 0)
        return {
            "top_event": state["top_event"],
            "result": result,
            "warning": "Distinct basic events assume independence; repeated names refer to the same event. Shared causes between distinct events remain unmodeled.",
        }


class BowTie(StructuredMethod):
    id = "bow_tie"
    name = "Bow-Tie Analysis"
    category = "Risk"
    description = "Connect threats and preventive controls to consequences and mitigating controls."
    example = {
        "hazard": "Critical API dependency",
        "top_event": "API unavailable",
        "threats": [
            {
                "name": "Vendor outage",
                "preventive_controls": ["Fallback"],
                "escalation_factors": ["Fallback shares the vendor's region"],
            }
        ],
        "consequences": [
            {
                "name": "Lost requests",
                "mitigating_controls": ["Queue and replay"],
                "escalation_factors": ["Queue fills during a long outage"],
            }
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["hazard"], "Hazard")
        name(state["top_event"], "Top event")
        for field, controls in (("threats", "preventive_controls"), ("consequences", "mitigating_controls")):
            if not state.get(field):
                raise ValueError(f"Add {field}")
            for row in state[field]:
                name(row["name"], field)
                if not isinstance(row.get(controls), list) or any(
                    not isinstance(v, str) or not v.strip() for v in row[controls]
                ):
                    raise ValueError(f"{controls} must be a list of named controls")
                factors = row.get("escalation_factors", [])
                if not isinstance(factors, list) or any(not isinstance(v, str) or not v.strip() for v in factors):
                    raise ValueError("Escalation factors must be a list of named conditions")
        return {
            "hazard": state["hazard"],
            "top_event": state["top_event"],
            "left_threats": state["threats"],
            "right_consequences": state["consequences"],
            "without_escalation_factors": [
                row["name"]
                for field in ("threats", "consequences")
                for row in state[field]
                if row.get("escalation_factors") in (None, [])
            ],
            "note": "Controls are user-identified; effectiveness is not assumed. Escalation factors are conditions "
            "that could make a control fail; a threat or consequence listed without any has not been challenged yet.",
        }


class Fermi(StructuredMethod):
    id = "fermi"
    name = "Fermi Estimation"
    category = "Forecasting"
    description = "Multiply or sum explicit, nonnegative estimated factors with sensitivity ranges."
    example = {
        "question": "Annual requests?",
        "operation": "product",
        "factors": [
            {"name": "Users", "low": 80, "estimate": 100, "high": 120},
            {"name": "Requests/user", "low": 8, "estimate": 10, "high": 12},
        ],
        "unit": "requests/year",
    }

    def calculate(self, state: dict) -> dict:
        name(state["question"], "Question")
        operation = state.get("operation")
        if operation not in {"product", "sum"}:
            raise ValueError("Operation must be product or sum")
        factors = state.get("factors", [])
        if len(factors) < 2:
            raise ValueError("Enter at least two estimated factors")
        rows = []
        for factor in factors:
            label = name(factor["name"], "Factor")
            low, estimate, high = (number(factor[key], key, 0) for key in ("low", "estimate", "high"))
            if not low <= estimate <= high:
                raise ValueError("Each factor requires low <= estimate <= high")
            rows.append({"name": label, "low": low, "estimate": estimate, "high": high})
        if len({r["name"] for r in rows}) != len(rows):
            raise ValueError("Factor names must be distinct")
        combine = math.prod if operation == "product" else sum
        return {
            "estimate": combine(r["estimate"] for r in rows),
            "low_case": combine(r["low"] for r in rows),
            "high_case": combine(r["high"] for r in rows),
            "unit": state.get("unit", "user-defined"),
            "factors": rows,
            "note": "Bounds are scenario extremes, not statistical confidence intervals.",
        }


class BayesianUpdate(StructuredMethod):
    id = "bayesian_update"
    name = "Bayesian Updating"
    category = "Forecasting"
    description = "Update a binary hypothesis from user-entered conditional likelihoods."
    example = {
        "hypothesis": "Vendor stable",
        "prior": 0.4,
        "evidence": [{"title": "Passed load test", "p_if_true": 0.9, "p_if_false": 0.2}],
    }

    def calculate(self, state: dict) -> dict:
        name(state["hypothesis"], "Hypothesis")
        prior = probability(state["prior"], "Prior")
        rows = state.get("evidence", [])
        if not rows:
            raise ValueError("Enter at least one evidence observation")
        updates = []
        posterior = prior
        for row in rows:
            title = name(row["title"], "Evidence")
            p_true = probability(row["p_if_true"], "P(evidence|hypothesis)")
            p_false = probability(row["p_if_false"], "P(evidence|not hypothesis)")
            marginal = posterior * p_true + (1 - posterior) * p_false
            if marginal == 0:
                raise ValueError("Observed evidence had zero probability under both models")
            posterior = posterior * p_true / marginal
            updates.append({"evidence": title, "posterior": posterior})
        return {
            "prior": prior,
            "posterior": posterior,
            "updates": updates,
            "warning": "Sequential updates assume supplied conditional likelihoods remain valid; do not double count correlated evidence.",
        }


for method in (RiskMatrix(), FaultTree(), BowTie(), Fermi(), BayesianUpdate()):
    register(method)
