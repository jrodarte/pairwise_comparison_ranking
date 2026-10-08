"""Transparent rule-based method discovery, next-method recommendations and approved handoffs."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from .core import METHODS, Session

GOALS: dict[str, tuple[str, ...]] = {
    "Rank alternatives": ("pairwise", "matrix", "sensitivity"),
    "Choose between options": ("objectives", "value_focused", "matrix", "sensitivity", "premortem", "journal"),
    "Understand a problem": ("issue_tree", "hypothesis_tree", "ach", "root_cause", "five_whys"),
    "Identify risks": ("premortem", "risk_matrix", "fmea", "fault_tree", "bow_tie"),
    "Forecast an outcome": ("fermi", "reference_class", "forecasting", "bayesian_update", "monte_carlo"),
    "Plan for uncertainty": ("scenarios", "signposts", "strategy_stress", "backcasting"),
    "Explore a complex system": ("stock_flow", "causal_loop", "bottleneck", "constraints"),
    "Challenge a plan": ("assumption_mapping", "reversibility", "premortem", "value_of_information"),
}

# Curated, sequential plans; methods are never executed or judged automatically.
WORKFLOWS: dict[str, tuple[str, ...]] = {
    "Rank alternatives": ("matrix", "sensitivity", "premortem"),
    "Choose between options": ("matrix", "ahp", "premortem", "journal"),
    "Understand a problem": ("ach", "root_cause", "journal"),
    "Forecast an outcome": ("forecasting", "scenarios", "signposts"),
    "Plan for uncertainty": ("scenarios", "signposts", "strategy_stress"),
    "Identify risks": ("premortem", "fmea", "bow_tie"),
    "Challenge a plan": ("assumption_mapping", "premortem", "value_of_information"),
    "Explore a complex system": ("causal_loop", "bottleneck", "constraints"),
}


def planned_next(source: Session) -> str | None:
    steps = source.method_state.get("workflow_steps", [])
    index = source.method_state.get("workflow_index")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not isinstance(steps, list)
        or not 0 <= index < len(steps)
        or steps[index] != source.method_id
    ):
        return None
    return steps[index + 1] if index + 1 < len(steps) else None


def begin_workflow(project_id: str, goal: str, problem: str) -> Session:
    """Create only the first draft; each subsequent handoff requires user confirmation."""
    if goal not in WORKFLOWS or not problem.strip():
        raise ValueError("Select a goal and enter the problem to start a workflow")
    steps = WORKFLOWS[goal]
    return Session(
        project_id=project_id,
        method_id=steps[0],
        title=f"{goal} · {METHODS[steps[0]].name}",
        problem_statement=problem.strip(),
        objective=goal,
        method_state={
            "workflow_id": str(uuid4()),
            "workflow_goal": goal,
            "workflow_steps": list(steps),
            "workflow_index": 0,
        },
    )


def continue_workflow(source: Session) -> Session:
    """Prepare exactly the next linked draft, never creating missing method judgments."""
    method_id = planned_next(source)
    if method_id is None:
        raise ValueError("No planned next step")
    if source.completed_at is None or METHODS[source.method_id].validate(source.method_state):
        raise ValueError("Finish and validate this analysis before continuing the workflow")
    state = (
        sensitivity_from_matrix(source).method_state
        if source.method_id == "matrix" and method_id == "sensitivity"
        else transfer(source, method_id)
    )
    state.update(
        {key: deepcopy(source.method_state[key]) for key in ("workflow_id", "workflow_goal", "workflow_steps")}
    )
    state["workflow_index"] = source.method_state["workflow_index"] + 1
    return Session(
        project_id=source.project_id,
        method_id=method_id,
        title=source.title.split(" · ")[0] + " · " + METHODS[method_id].name,
        problem_statement=source.problem_statement,
        objective=source.objective,
        method_state=state,
    )


NEXT: dict[str, tuple[str, ...]] = {
    "pairwise": ("matrix", "assumption_mapping"),
    "objectives": ("matrix", "value_focused"),
    "value_focused": ("matrix",),
    "matrix": ("sensitivity", "premortem", "journal"),
    "sensitivity": ("premortem", "journal"),
    "issue_tree": ("hypothesis_tree", "ach"),
    "hypothesis_tree": ("ach", "evidence_matrix"),
    "ach": ("root_cause", "evidence_matrix"),
    "five_whys": ("root_cause", "fishbone"),
    "premortem": ("fmea", "risk_matrix", "bow_tie"),
    "risk_matrix": ("bow_tie", "fault_tree"),
    "scenarios": ("signposts", "strategy_stress", "backcasting"),
    "signposts": ("strategy_stress",),
    "fermi": ("reference_class", "monte_carlo"),
    "forecasting": ("reference_class", "monte_carlo"),
    "reference_class": ("monte_carlo",),
    "causal_loop": ("bottleneck", "constraints"),
    "bottleneck": ("constraints",),
}


def recommend(goal: str | None = None, source: Session | None = None) -> list[tuple[str, str]]:
    """Each suggestion explains why it fits; recommendations are never AI judgments."""
    choices = NEXT.get(source.method_id, ("journal", "assumption_mapping")) if source else GOALS.get(goal or "", ())
    options = [(method_id, METHODS[method_id].description) for method_id in choices]
    planned = planned_next(source) if source else None
    if planned:
        options = [(planned, "Planned next step · " + METHODS[planned].description)] + [
            option for option in options if option[0] != planned
        ]
    return options


def transfer(source: Session, target_id: str) -> dict:
    """Only copy approved user input; no fabricated weights, scores, probabilities or observations."""
    if target_id not in METHODS:
        raise ValueError("Unknown method")
    state: dict = {"source_session_id": source.id}
    src = source.method_state
    if target_id == "matrix":
        if source.method_id == "pairwise" and "ranking" in src:
            from pairwise_prioritizer.models import Project

            state["alternatives"] = [
                {"name": item.name, "scores": []} for item in Project.from_dict(src["ranking"]).items
            ]
            state["criteria"] = []
        elif source.method_id == "objectives":
            state["criteria"] = [
                {"name": node["label"], "weight": None}
                for node in src.get("nodes", [])
                if node.get("kind") == "fundamental"
            ]
            state["alternatives"] = []
    elif target_id == "ahp" and source.method_id == "matrix":
        state["criteria"] = [row["name"] for row in src.get("criteria", [])]
        state["alternatives"] = [row["name"] for row in src.get("alternatives", [])]
        # Numerical scores and criterion weights are NOT pairwise AHP judgments.
    elif target_id == "sensitivity" and source.method_id == "matrix":
        return sensitivity_from_matrix(source).method_state
    elif target_id == "fmea" and source.method_id == "premortem":
        state["failure_modes"] = [
            {
                "mode": row["statement"],
                "cause": "",  # a failure mode does not establish its cause
                "action": row.get("action", ""),
                "effect": "",
                "controls": "",
                "owner": "",
                "severity": None,
                "occurrence": None,
                "detectability": None,
            }
            for row in src.get("entries", [])
        ]
    elif target_id == "strategy_stress" and source.method_id == "scenarios":
        scenarios = src.get("scenarios", {})
        state["scenarios"] = [row.get("name", key) for key, row in scenarios.items()]
        state["strategies"] = [{"name": row["name"], "scores": {}} for row in src.get("strategies", [])]
    elif target_id == "signposts" and source.method_id == "scenarios":
        state["indicators"] = [
            {
                "name": indicator,
                "scenario": row.get("name", key),
                "unit": "",
                "direction": "",
                "threshold": None,
                "current": None,
                "action": "",
            }
            for key, row in src.get("scenarios", {}).items()
            for indicator in row.get("indicators", [])
        ]
    return state


def sensitivity_pair(source: Session) -> tuple[int, int]:
    """Suggest the two highest-ranked options, without committing a comparison."""
    state = source.method_state
    if source.method_id != "matrix" or METHODS["matrix"].validate(state):
        raise ValueError("Calculate the decision matrix before testing sensitivity")
    if len(state["criteria"]) < 2:
        raise ValueError("Sensitivity needs at least two criteria")
    ranking = METHODS["matrix"].calculate(state)["ranking"]
    available = list(range(len(state["alternatives"])))
    selected = []
    for row in ranking[:2]:
        index = next(i for i in available if state["alternatives"][i]["name"] == row["name"])
        selected.append(index)
        available.remove(index)
    return selected[0], selected[1]


def sensitivity_from_matrix(source: Session, pair: tuple[int, int] | None = None) -> Session:
    """Prepare a linked draft with only the explicitly selected matrix judgments."""
    if source.method_id != "matrix" or METHODS["matrix"].validate(source.method_state):
        raise ValueError("Calculate the decision matrix before testing sensitivity")
    state = source.method_state
    if len(state["criteria"]) < 2:
        raise ValueError("Sensitivity needs at least two criteria")
    if pair is None:
        pair = sensitivity_pair(source)
    if (
        not isinstance(pair, tuple)
        or len(pair) != 2
        or any(type(i) is not int or not 0 <= i < len(state["alternatives"]) for i in pair)
        or pair[0] == pair[1]
    ):
        raise ValueError("Choose two different matrix options to compare")
    copied = {
        "criteria": [
            {key: deepcopy(value) for key, value in criterion.items() if key in ("name", "weight", "direction")}
            for criterion in state["criteria"]
        ],
        "alternatives": [
            {"name": state["alternatives"][i]["name"], "scores": deepcopy(state["alternatives"][i]["scores"])}
            for i in pair
        ],
        "vary": state["criteria"][0]["name"],
        "range": [0, 1],
        "source_session_id": source.id,
    }
    if issues := METHODS["sensitivity"].validate(copied):
        raise ValueError("Matrix cannot feed sensitivity: " + " ".join(issues))
    return Session(
        project_id=source.project_id,
        method_id="sensitivity",
        title=source.title + " · Sensitivity",
        problem_statement=source.problem_statement,
        objective=source.objective,
        method_state=copied,
    )
