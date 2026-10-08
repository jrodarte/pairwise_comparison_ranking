"""V0.4 qualitative strategy and risk workflows with explicit user-supplied inputs."""

from __future__ import annotations

from datetime import date

from .advanced_decisions import StructuredMethod, name, number
from .core import register
from .issue_tree import nested, nodes_for


class Scenarios(StructuredMethod):
    id = "scenarios"
    name = "Scenario Planning"
    category = "Strategy"
    description = "Two uncertainties, four user-written futures, implications and signposts."
    example = {
        "question": "How should we invest?",
        "drivers": ["Regulation", "Adoption"],
        "axes": [
            {"name": "Regulation", "low": "Loose", "high": "Strict"},
            {"name": "Adoption", "low": "Slow", "high": "Fast"},
        ],
        "scenarios": {
            key: {
                "name": key,
                "narrative": "User-supplied story",
                "implications": ["What changes?"],
                "indicators": ["Observable signal"],
            }
            for key in ("low_low", "low_high", "high_low", "high_high")
        },
        "strategies": [
            {
                "name": "Pilot first",
                "actions": {
                    key: "User-defined action for this future"
                    for key in ("low_low", "low_high", "high_low", "high_high")
                },
            }
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["question"], "Strategic question")
        drivers = state.get("drivers", [])
        if len(drivers) < 2 or len({name(driver, "Driving force") for driver in drivers}) != len(drivers):
            raise ValueError("Enter at least two distinct driving forces")
        axes = state.get("axes", [])
        if len(axes) != 2 or len({name(a["name"], "Axis") for a in axes}) != 2:
            raise ValueError("Enter two distinct uncertainty axes")
        for axis in axes:
            if name(axis["low"], "Low pole") == name(axis["high"], "High pole"):
                raise ValueError("An axis must have distinct poles")
        keys = ("low_low", "low_high", "high_low", "high_high")
        scenarios = state.get("scenarios", {})
        if set(scenarios) != set(keys):
            raise ValueError("Describe all four scenarios: low_low, low_high, high_low, high_high")
        futures = []
        for key in keys:
            row = scenarios[key]
            futures.append(
                {
                    "quadrant": key,
                    "name": name(row["name"], "Scenario"),
                    "narrative": name(row["narrative"], "Narrative"),
                    "implications": row.get("implications", []),
                    "indicators": row.get("indicators", []),
                    "poles": [axes[i][level] for i, level in enumerate(key.split("_"))],
                }
            )
        strategies = state.get("strategies", [])
        if not strategies:
            raise ValueError("Describe at least one strategy across all four futures")
        for strategy in strategies:
            name(strategy["name"], "Strategy")
            if set(strategy["actions"]) != set(keys):
                raise ValueError("Each strategy needs an action in every scenario")
            for action in strategy["actions"].values():
                name(action, "Strategy action")
        return {
            "drivers": state.get("drivers", []),
            "scenarios": futures,
            "strategies": strategies,
            "note": "Scenario stories and indicators are user supplied, not forecasts or probabilities.",
        }


class Backcasting(StructuredMethod):
    id = "backcasting"
    name = "Backcasting"
    category = "Strategy"
    description = "Work backward from a desired outcome to dated prerequisites."
    example = {
        "future_state": "Automated lineage",
        "target_date": "2028-12-31",
        "milestones": [
            {"date": "2028-06-01", "requirement": "APIs live", "owner": "Platform"},
            {"date": "2027-01-01", "requirement": "Pilot", "owner": "Team"},
        ],
    }

    def calculate(self, state: dict) -> dict:
        name(state["future_state"], "Future state")
        try:
            target = date.fromisoformat(state["target_date"])
        except (TypeError, ValueError):
            raise ValueError("Target date must be YYYY-MM-DD") from None
        milestones = state.get("milestones", [])
        if not milestones:
            raise ValueError("Add at least one prerequisite milestone")
        dates = []
        for row in milestones:
            name(row["requirement"], "Requirement")
            try:
                milestone = date.fromisoformat(row["date"])
            except (TypeError, ValueError):
                raise ValueError("Milestone date must be YYYY-MM-DD") from None
            if milestone >= target:
                raise ValueError("Milestones must precede the target date")
            dates.append(milestone)
        return {
            "future_state": state["future_state"],
            "target_date": target.isoformat(),
            "backward_milestones": [
                row for _, row in sorted(zip(dates, milestones, strict=True), reverse=True, key=lambda pair: pair[0])
            ],
            "note": "Dependencies and feasibility require human review.",
        }


class Objectives(StructuredMethod):
    id = "objectives"
    name = "Objectives Hierarchy"
    category = "Strategy"
    description = "Distinguish fundamental objectives from means in a hierarchy."
    example = {
        "nodes": [
            {"id": "value", "parent_id": None, "label": "Customer value", "kind": "fundamental"},
            {"id": "onboarding", "parent_id": "value", "label": "Fast onboarding", "kind": "means"},
        ]
    }

    def calculate(self, state: dict) -> dict:
        nodes = nodes_for(state)
        if not nodes:
            raise ValueError("Add at least one objective")
        if any(node.get("kind") not in {"fundamental", "means"} for node in nodes):
            raise ValueError("Each objective must have kind fundamental or means")
        if not any(node["kind"] == "fundamental" for node in nodes):
            raise ValueError("Identify at least one fundamental objective")
        return {
            "hierarchy": nested(state),
            "kinds": {node["id"]: node["kind"] for node in nodes},
            "note": "Means are not automatically criteria; user determines what matters.",
        }


class ValueFocused(StructuredMethod):
    id = "value_focused"
    name = "Value-Focused Thinking"
    category = "Strategy"
    description = "Clarify measurable fundamental objectives before generating alternatives."
    example = {
        "objectives": [
            {"name": "Reduce onboarding time", "kind": "fundamental", "measure": "Median days", "why": "Faster value"}
        ],
        "alternatives": ["Pilot", "Process change", "Do nothing"],
    }

    def calculate(self, state: dict) -> dict:
        objectives = state.get("objectives", [])
        if not objectives:
            raise ValueError("Enter objectives")
        labels = [name(o["name"], "Objective") for o in objectives]
        if len(set(labels)) != len(labels):
            raise ValueError("Objective names must be distinct")
        if not any(o.get("kind") == "fundamental" for o in objectives):
            raise ValueError("Identify a fundamental objective")
        for row in objectives:
            if row.get("kind") not in {"fundamental", "means"}:
                raise ValueError("Objectives must be fundamental or means")
            name(row["measure"], "Measure")
        return {
            "objectives": objectives,
            "alternatives": state.get("alternatives", []),
            "note": "Measurements are definitions, not observed evidence.",
        }


class FMEA(StructuredMethod):
    id = "fmea"
    name = "Failure Mode and Effects Analysis"
    category = "Risk"
    description = "Display severity, occurrence, detectability and a screening RPN."
    example = {
        "failure_modes": [
            {
                "mode": "API outage",
                "effect": "No service",
                "cause": "Dependency",
                "controls": "Retry",
                "severity": 9,
                "occurrence": 4,
                "detectability": 6,
                "action": "Add failover",
                "owner": "Team",
            }
        ]
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("failure_modes", [])
        if not rows:
            raise ValueError("Add at least one failure mode")
        scale = state.get("scale_max", 10)
        if type(scale) is not int or not 2 <= scale <= 20:
            raise ValueError("Scale maximum must be a whole number from 2 to 20")
        ranked = []
        for row in rows:
            name(row["mode"], "Failure mode")
            for field in ("effect", "cause", "controls", "action", "owner"):
                name(row[field], field)
            scores = {}
            for key in ("severity", "occurrence", "detectability"):
                value = row[key]
                if type(value) is not int or not 1 <= value <= scale:
                    raise ValueError(f"{key} must be a whole number from 1 to {scale}")
                scores[key] = value
            ranked.append({**row, "rpn": scores["severity"] * scores["occurrence"] * scores["detectability"]})
        return {
            "scale_max": scale,
            "ranking": sorted(ranked, key=lambda r: (-r["rpn"], r["mode"])),
            "warning": "RPN is a screening heuristic. Review severity, occurrence and detectability separately.",
        }


class Constraints(StructuredMethod):
    id = "constraints"
    name = "Theory of Constraints"
    category = "Systems"
    description = "Record system goal, bottleneck hypothesis and exploit/subordinate/elevate plan."
    example = {
        "goal": "Ship reliable features",
        "constraint": "Test environment throughput",
        "evidence": ["Queue length increased"],
        "throughput": {"unit": "deployments/week", "current": 4, "target": 8},
        "exploit": "Schedule capacity",
        "subordinate": "Limit upstream WIP",
        "elevate": "Add workers",
        "reassess": "Measure queue after change",
    }

    def calculate(self, state: dict) -> dict:
        for key in ("goal", "constraint", "exploit", "subordinate", "elevate", "reassess"):
            name(state[key], key)
        throughput = state.get("throughput")
        if throughput:
            name(throughput["unit"], "Throughput unit")
            for field in ("current", "target"):
                number(throughput[field], f"Throughput {field}", 0)
        return {
            "goal": state["goal"],
            "constraint_hypothesis": state["constraint"],
            "evidence": state.get("evidence", []),
            "throughput": throughput,
            "steps": {key: state[key] for key in ("exploit", "subordinate", "elevate", "reassess")},
            "note": "A bottleneck is a hypothesis until system throughput evidence supports it.",
        }


for method in (Scenarios(), Backcasting(), Objectives(), ValueFocused(), FMEA(), Constraints()):
    register(method)
