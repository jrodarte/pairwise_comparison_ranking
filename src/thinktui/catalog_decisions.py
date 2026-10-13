"""Remaining decision and problem-analysis catalog methods; user data stays authoritative."""

from __future__ import annotations

import math
from uuid import NAMESPACE_URL, uuid5

from pairwise_prioritizer.models import Comparison, Item, Outcome
from pairwise_prioritizer.ranking import BradleyTerry

from .advanced_decisions import StructuredMethod, name, number, probability
from .core import ASSUMPTION_STATUSES, assumption_quadrant, assumption_review, register
from .issue_tree import nested, nodes_for


class BradleyTerryMethod(StructuredMethod):
    id = "bradley_terry"
    name = "Bradley–Terry Ranking"
    description = "Score recorded pair outcomes; for guided complete pairs use Pairwise Ranking."
    example = {"items": ["Alpha", "Beta"], "comparisons": [{"a": "Alpha", "b": "Beta", "outcome": "a_wins"}]}

    def calculate(self, state: dict) -> dict:
        labels = [name(label, "Item") for label in state.get("items", [])]
        if len(labels) < 2 or len(set(labels)) != len(labels):
            raise ValueError("Enter at least two distinct items")
        items = [Item(name=label, id=str(uuid5(NAMESPACE_URL, "thinktui:item:" + label))) for label in labels]
        ids = {item.name: item.id for item in items}
        pairs = set()
        comparisons = []
        for i, row in enumerate(state.get("comparisons", []), 1):
            a, b = name(row["a"], "Left item"), name(row["b"], "Right item")
            if a not in ids or b not in ids or a == b:
                raise ValueError("Comparisons need two different listed items")
            key = frozenset((a, b))
            if key in pairs:
                raise ValueError("Duplicate comparison")
            pairs.add(key)
            try:
                outcome = Outcome(row["outcome"])
            except ValueError:
                raise ValueError("Outcome must be a_wins, b_wins or tie") from None
            comparisons.append(Comparison(ids[a], ids[b], outcome, i))
        if not comparisons:
            raise ValueError("Record at least one comparison")
        ranked = BradleyTerry().calculate(items, comparisons)
        return {
            "ranking": [
                {
                    "name": r.item.name,
                    "score": r.score,
                    "rank": r.rank,
                    "wins": r.wins,
                    "losses": r.losses,
                    "ties": r.ties,
                }
                for r in ranked
            ],
            "note": "Scores are relative strengths, not probabilities or confidence intervals.",
        }


class ValueOfInformation(StructuredMethod):
    id = "value_of_information"
    name = "Value of Information"
    description = "Compare expected values before and after imperfect or perfect information."
    example = {
        "states": [{"name": "Demand", "probability": 0.6}, {"name": "No demand", "probability": 0.4}],
        "actions": [
            {"name": "Build", "payoffs": {"Demand": 100, "No demand": -50}},
            {"name": "Wait", "payoffs": {"Demand": 0, "No demand": 0}},
        ],
        "signals": [
            {"name": "Positive", "likelihoods": {"Demand": 0.8, "No demand": 0.2}},
            {"name": "Negative", "likelihoods": {"Demand": 0.2, "No demand": 0.8}},
        ],
        "research_cost": 5,
    }

    def calculate(self, state: dict) -> dict:
        states, actions, signals = (state.get(key, []) for key in ("states", "actions", "signals"))
        if len(states) < 2 or len(actions) < 2 or len(signals) < 2:
            raise ValueError("Enter at least two states, actions and signals")
        names = [name(row["name"], "State") for row in states]
        action_names = [name(row["name"], "Action") for row in actions]
        signal_names = [name(row["name"], "Signal") for row in signals]
        if any(len(set(group)) != len(group) for group in (names, action_names, signal_names)):
            raise ValueError("Names must be unique within states, actions and signals")
        priors = {row["name"]: probability(row["probability"], "State probability") for row in states}
        if not math.isclose(sum(priors.values()), 1, abs_tol=1e-8):
            raise ValueError("State probabilities must sum to 1")
        payoffs = {}
        for action in actions:
            if set(action["payoffs"]) != set(names):
                raise ValueError("Each action needs one payoff per state")
            payoffs[action["name"]] = {s: number(v, "Payoff") for s, v in action["payoffs"].items()}
        likelihoods = {}
        for signal in signals:
            if set(signal["likelihoods"]) != set(names):
                raise ValueError("Each signal needs a likelihood in every state")
            likelihoods[signal["name"]] = {
                s: probability(v, "Signal likelihood") for s, v in signal["likelihoods"].items()
            }
        for s in names:
            if not math.isclose(sum(likelihoods[z][s] for z in signal_names), 1, abs_tol=1e-8):
                raise ValueError("Signal likelihoods conditional on each state must sum to 1")
        base = max(sum(priors[s] * payoff[s] for s in names) for payoff in payoffs.values())
        perfect = sum(priors[s] * max(payoff[s] for payoff in payoffs.values()) for s in names)
        with_signal = sum(
            max(sum(priors[s] * likelihoods[z][s] * payoff[s] for s in names) for payoff in payoffs.values())
            for z in signal_names
        )
        cost = number(state.get("research_cost", 0), "Research cost", 0)
        return {
            "best_without_information": base,
            "perfect_information_value": max(0, perfect - base),
            "sample_information_value": max(0, with_signal - base),
            "net_sample_information_value": with_signal - base - cost,
            "note": "EVPI/EVSI depend on user-supplied priors, payoffs and signal accuracy; no guarantee.",
        }


class OpportunityCost(StructuredMethod):
    id = "opportunity_cost"
    name = "Opportunity Cost"
    description = "Expose the best foregone alternative and value gap without making a decision."
    example = {
        "chosen": "Build",
        "alternatives": [
            {"name": "Build", "value": 80},
            {"name": "Buy", "value": 90},
            {"name": "Do nothing", "value": 0},
        ],
        "unit": "expected value points",
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("alternatives", [])
        if len(rows) < 2:
            raise ValueError("Enter two or more alternatives")
        values = {name(r["name"], "Alternative"): number(r["value"], "Value") for r in rows}
        if len(values) != len(rows) or state.get("chosen") not in values:
            raise ValueError("Alternatives must be distinct and chosen must match one")
        foregone = max((r for r in values if r != state["chosen"]), key=lambda r: values[r])
        return {
            "chosen": state["chosen"],
            "chosen_value": values[state["chosen"]],
            "best_foregone": foregone,
            "opportunity_cost": values[foregone],
            "gap_vs_chosen": values[foregone] - values[state["chosen"]],
            "unit": state.get("unit", "user-defined"),
            "note": "Opportunity cost is the best forgone value; gap can be negative.",
        }


class Reversibility(StructuredMethod):
    id = "reversibility"
    name = "Reversibility Analysis"
    description = "Compare rollback cost, time, triggers and exit plans independently."
    example = {
        "alternatives": [
            {
                "name": "Pilot",
                "rollback_cost": 10,
                "rollback_days": 5,
                "trigger": "Low adoption",
                "exit_plan": "Retire pilot",
            },
            {
                "name": "Full migration",
                "rollback_cost": 100,
                "rollback_days": 90,
                "trigger": "Service failure",
                "exit_plan": "Restore backup",
            },
        ]
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("alternatives", [])
        if len(rows) < 2:
            raise ValueError("Compare two or more alternatives")
        results = []
        for row in rows:
            results.append(
                {
                    "name": name(row["name"], "Alternative"),
                    "rollback_cost": number(row["rollback_cost"], "Rollback cost", 0),
                    "rollback_days": number(row["rollback_days"], "Rollback days", 0),
                    "trigger": name(row["trigger"], "Trigger"),
                    "exit_plan": name(row["exit_plan"], "Exit plan"),
                }
            )
        if len({row["name"] for row in results}) != len(results):
            raise ValueError("Alternatives must be distinct")
        return {
            "alternatives": results,
            "note": "Cost and time are separate dimensions; no invented reversibility score.",
        }


class HypothesisTree(StructuredMethod):
    id = "hypothesis_tree"
    name = "Hypothesis Tree"
    category = "Problem Analysis"
    description = "Decompose a question into alternative, testable hypotheses."
    example = {
        "question": "Why did response time rise?",
        "nodes": [
            {"id": "root", "parent_id": None, "label": "Request path changed", "kind": "hypothesis"},
            {"id": "test", "parent_id": "root", "label": "Compare traces", "kind": "test"},
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["question"], "Question")
        nodes = nodes_for(state)
        if not nodes or any(row.get("kind") not in {"hypothesis", "test"} for row in nodes):
            raise ValueError("Enter hypothesis/test nodes with a kind")
        return {
            "hypotheses": nested(state),
            "kinds": {row["id"]: row["kind"] for row in nodes},
            "note": "A hypothesis is not a finding until tested.",
        }


class AssumptionMapping(StructuredMethod):
    id = "assumption_mapping"
    name = "Assumption Mapping"
    category = "Problem Analysis"
    description = "Place assumptions by confidence and impact; surface what to test first."
    example = {
        "assumptions": [
            {
                "statement": "API remains available",
                "basis": "Vendor status page",
                "confidence": 0.3,
                "impact": 9,
                "test": "Review SLA",
                "change_mind": "Two outages in one quarter",
                "status": "Untested",
            },
            {
                "statement": "Docs up to date",
                "basis": "Recent release notes",
                "confidence": 0.8,
                "impact": 3,
                "test": "Check samples",
                "change_mind": "A sample fails against the live API",
                "status": "Supported",
            },
        ]
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("assumptions", [])
        if not rows:
            raise ValueError("Add assumptions")
        ranked = []
        for row in rows:
            conf = probability(row["confidence"], "Confidence")
            impact = number(row["impact"], "Impact", 1)
            if impact > 10:
                raise ValueError("Impact is on a 1–10 scale")
            status = row.get("status") or "Untested"
            if status not in ASSUMPTION_STATUSES:
                raise ValueError("Status must be one of: " + ", ".join(ASSUMPTION_STATUSES))
            for key in ("basis", "change_mind"):
                if row.get(key) is not None and not isinstance(row[key], str):
                    raise ValueError(key.replace("_", " ").capitalize() + " must be text")
            ranked.append(
                {
                    "statement": name(row["statement"], "Assumption"),
                    "confidence": conf,
                    "impact": impact,
                    "test": name(row["test"], "Validation test"),
                    "priority": (1 - conf) * impact,
                    "quadrant": assumption_quadrant(conf < 0.5, impact >= 6),
                    "status": status,
                    **{key: row[key] for key in ("basis", "change_mind") if row.get(key)},
                }
            )
        ranked.sort(key=lambda r: -r["priority"])
        return {
            "priorities": ranked,
            "review": assumption_review([(r["statement"], r["quadrant"], r["status"]) for r in ranked]),
            "note": "Confidence is a user judgment, not measured probability.",
        }


class RootCause(StructuredMethod):
    id = "root_cause"
    name = "Root Cause Analysis"
    category = "Problem Analysis"
    description = "Record candidate causes with supporting, contradicting and missing evidence."
    example = {
        "problem": "Timeouts after deploy",
        "causes": [
            {
                "claim": "Pool exhausted",
                "supporting": ["Connection count rose"],
                "contradicting": ["CPU unchanged"],
                "test": "Measure wait time",
            }
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["problem"], "Problem")
        causes = state.get("causes", [])
        if not causes:
            raise ValueError("Enter candidate causes")
        for row in causes:
            name(row["claim"], "Candidate cause")
            name(row["test"], "Disconfirming test")
            if not isinstance(row.get("supporting"), list) or not isinstance(row.get("contradicting"), list):
                raise ValueError("Evidence lists must be arrays")
        return {
            "candidate_causes": causes,
            "note": "No cause is proven by its presence in this record; test competing explanations.",
        }


class FiveWhys(StructuredMethod):
    id = "five_whys"
    name = "Five Whys"
    category = "Problem Analysis"
    description = "Trace a user-entered causal chain and identify a testable root-cause hypothesis."
    example = {
        "problem": "Deploy delayed",
        "chain": [
            {"why": "Why delayed?", "answer": "Tests were blocked"},
            {"why": "Why blocked?", "answer": "Environment unavailable"},
        ],
        "root_test": "Check environment availability logs",
    }

    def calculate(self, state: dict) -> dict:
        name(state["problem"], "Problem")
        chain = state.get("chain", [])
        if not 1 <= len(chain) <= 5:
            raise ValueError("Record one to five why/answer pairs")
        for row in chain:
            name(row["why"], "Why question")
            name(row["answer"], "Answer hypothesis")
        return {
            "chain": chain,
            "candidate_root": chain[-1]["answer"],
            "root_test": name(state["root_test"], "Root test"),
            "note": "Five Whys can oversimplify interacting causes; verify links.",
        }


class Fishbone(StructuredMethod):
    id = "fishbone"
    name = "Fishbone / Ishikawa"
    category = "Problem Analysis"
    description = "Group potential causes by user-defined categories without implying causality."
    example = {
        "effect": "Low API adoption",
        "categories": [
            {"name": "Process", "causes": ["Slow approval"]},
            {"name": "Technology", "causes": ["Missing SDK"]},
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["effect"], "Effect")
        groups = state.get("categories", [])
        if not groups:
            raise ValueError("Enter cause categories")
        labels = []
        for row in groups:
            labels.append(name(row["name"], "Category"))
            if not row.get("causes") or any(not isinstance(v, str) or not v.strip() for v in row["causes"]):
                raise ValueError("Each category needs named candidate causes")
        if len(set(labels)) != len(labels):
            raise ValueError("Categories must be distinct")
        return {
            "effect": state["effect"],
            "branches": groups,
            "note": "Branches are possible causes, not established mechanisms.",
        }


class EvidenceMatrix(StructuredMethod):
    id = "evidence_matrix"
    name = "Evidence Matrix"
    category = "Problem Analysis"
    description = "Preserve evidence-to-hypothesis consistency and source reliability."
    example = {
        "hypotheses": ["Pool", "Network"],
        "evidence": [
            {
                "title": "Connection count rose",
                "source": "Telemetry",
                "reliability": 0.8,
                "ratings": {"Pool": "+", "Network": "?"},
            }
        ],
    }

    def calculate(self, state: dict) -> dict:
        hypotheses = [name(v, "Hypothesis") for v in state.get("hypotheses", [])]
        if len(hypotheses) < 2 or len(set(hypotheses)) != len(hypotheses):
            raise ValueError("Enter two or more distinct hypotheses")
        rows = state.get("evidence", [])
        if not rows:
            raise ValueError("Enter evidence")
        contradictions = {h: [] for h in hypotheses}
        for row in rows:
            title = name(row["title"], "Evidence title")
            name(row["source"], "Evidence source")
            probability(row["reliability"], "Reliability")
            if set(row["ratings"]) != set(hypotheses) or any(
                v not in {"+", "-", "0", "?"} for v in row["ratings"].values()
            ):
                raise ValueError("Rate each hypothesis +, -, 0 or ?")
            for h in hypotheses:
                if row["ratings"][h] == "-":
                    contradictions[h].append(title)
        return {
            "evidence": rows,
            "contradictions": contradictions,
            "note": "A consistency rating is user judgment, not proof or a probability.",
        }


for method in (
    BradleyTerryMethod(),
    ValueOfInformation(),
    OpportunityCost(),
    Reversibility(),
    HypothesisTree(),
    AssumptionMapping(),
    RootCause(),
    FiveWhys(),
    Fishbone(),
    EvidenceMatrix(),
):
    register(method)
