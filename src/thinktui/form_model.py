"""Schema-driven editor for structured method states. Examples define shape, never user data."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from .core import METHODS
from .guided_workflow import Field


@dataclass(frozen=True)
class FormField(Field):
    kind: str = "text"
    help: str = "Enter your own information."
    why: str = "This helps explain the result."
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    reference: str = ""
    children: tuple[FormField, ...] = ()
    show_for: tuple[str, ...] = ()  # visible only for these distribution choices


KEYED_GRIDS = {
    ("value_of_information", "actions.payoffs"): "states",
    ("value_of_information", "signals.likelihoods"): "states",
    ("strategy_stress", "strategies.scores"): "scenarios",
    ("evidence_matrix", "evidence.ratings"): "hypotheses",
    ("ach", "evidence.ratings"): "hypotheses",
}

CHOICES = {
    "direction": ("benefit", "cost"),
    "rating": ("++", "+", "0", "-", "--", "?"),
    "operation": ("product", "sum"),
}
MONTE_FIELDS = {
    "uniform": ("min", "max"),
    "triangular": ("min", "mode", "max"),
    "normal": ("mean", "sd"),
    "lognormal": ("mean", "sd"),
    "discrete": ("values", "weights"),
    "samples": ("values",),
}
ENUM_CHOICES = {
    ("monte_carlo", "distribution"): tuple(MONTE_FIELDS),
    ("decision_tree", "type"): ("outcome", "chance", "decision"),
    ("fault_tree", "type"): ("event", "AND", "OR"),
    ("forecasting", "outcome"): ("Unresolved", "No", "Yes"),
    ("causal_loop", "polarity"): ("Reinforcing (+1)", "Balancing (-1)"),
}
KINDS = {
    "objectives": ("fundamental", "means"),
    "value_focused": ("fundamental", "means"),
    "hypothesis_tree": ("hypothesis", "test"),
}
BOUNDS = {
    "confidence": (0, 100),
    "impact": (1, 10),
    "likelihood": (0, 100),
    "severity": (1, 10),
    "occurrence": (1, 10),
    "detectability": (1, 10),
    "probability": (0, 1),
    "reliability": (0, 1),
    "weight": (0, None),
    "score": (0, 10),
    "scores": (0, 10),
}
LONG = {"narrative", "description", "rationale", "why", "evidence", "implications", "indicators"}
HIDDEN = {
    "change_mind",
    "_guided_step",
    "workflow_id",
    "workflow_goal",
    "workflow_steps",
    "workflow_index",
    "source_session_id",
}


def title(key: str) -> str:
    return key.replace("_", " ").capitalize()


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "item"


def monte_variable_fields() -> tuple[FormField, ...]:
    """One declarative union of distribution inputs; the form only shows active fields."""
    shared = (
        FormField("name", "Variable name", help="Name this uncertain input.", why="Names identify model terms."),
        FormField(
            "distribution",
            "Distribution",
            kind="choice",
            choices=ENUM_CHOICES[("monte_carlo", "distribution")],
            help="Choose the shape of uncertainty.",
            why="The chosen distribution determines required judgments.",
        ),
        FormField(
            "coefficient",
            "Coefficient",
            kind="float",
            help="Enter your multiplier (may be negative).",
            why="Multiplies this variable in the linear model.",
        ),
    )
    scalars = tuple(
        FormField(
            key,
            title(key),
            kind="float",
            minimum=0 if key == "sd" else None,
            show_for=tuple(kind for kind, fields in MONTE_FIELDS.items() if key in fields),
            help="Enter your own " + ("nonnegative standard deviation" if key == "sd" else title(key).lower()) + ".",
            why="Defines the spread and center of this distribution.",
        )
        for key in ("min", "mode", "max", "mean", "sd")
    )
    groups = tuple(
        FormField(
            key,
            title(key),
            kind="rows",
            show_for=tuple(kind for kind, fields in MONTE_FIELDS.items() if key in fields),
            children=(
                FormField(
                    "value",
                    "Weight" if key == "weights" else "Value",
                    kind="float",
                    minimum=0 if key == "weights" else None,
                    help="Enter your own " + ("nonnegative weight" if key == "weights" else "numeric outcome") + ".",
                    why="These numbers define your empirical distribution.",
                ),
            ),
            help="Add one numeric " + ("weight per value" if key == "weights" else "value per row") + ".",
            why="All values and weights are user supplied.",
        )
        for key in ("values", "weights")
    )
    return (*shared, *scalars, *groups)


def validate_monte_variable(row: dict) -> str:
    """Cheap, plain-English shape check; never run the simulation while typing."""
    kind = row.get("distribution")
    if kind not in {"discrete", "samples"}:
        return ""
    values = row.get("values", [])
    if not isinstance(values, list) or not values:
        return "Add at least one numeric value."
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return "Each value must be a finite number you enter."
    if kind == "discrete":
        weights = row.get("weights", [])
        if not isinstance(weights, list) or len(weights) != len(values):
            return "Add exactly one weight for each value."
        if any(type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0 for weight in weights):
            return "Weights must be finite, nonnegative numbers you enter."
        if sum(weights) <= 0:
            return "At least one weight must be greater than zero."
    return ""


def conditional_node_fields(method_id: str) -> tuple[FormField, ...]:
    """Fields for every accepted decision/fault-tree node variant, not just an example branch."""
    if method_id == "decision_tree":
        return (
            FormField(
                "type",
                "Node type",
                kind="choice",
                choices=ENUM_CHOICES[(method_id, "type")],
                help="Choose an outcome, chance, or decision node.",
                why="The node type determines which inputs apply.",
            ),
            FormField(
                "value",
                "Outcome value",
                kind="float",
                show_for=("outcome",),
                help="Enter the payoff of this outcome.",
                why="This value enters the rollback calculation.",
            ),
            FormField(
                "branches",
                "Branches",
                kind="rows",
                show_for=("chance", "decision"),
                help="Add each possible branch.",
                why="Branches are compared or probability-weighted.",
                children=(
                    FormField("name", "Branch name", help="Name this branch.", why="Identifies the option or outcome."),
                    FormField(
                        "probability",
                        "Your probability (0–1)",
                        kind="float",
                        minimum=0,
                        maximum=1,
                        show_for=("chance",),
                        help="Enter your chance judgment.",
                        why="Chance branches must sum to one.",
                    ),
                    FormField(
                        "node",
                        "Next node",
                        kind="conditional_node",
                        help="Describe what happens next.",
                        why="Each branch needs a result.",
                    ),
                ),
            ),
        )
    if method_id == "fault_tree":
        return (
            FormField(
                "type",
                "Node type",
                kind="choice",
                choices=ENUM_CHOICES[(method_id, "type")],
                help="Choose a basic event or AND/OR gate.",
                why="Gate type determines probability combination.",
            ),
            FormField(
                "name",
                "Basic event",
                show_for=("event",),
                help="Name the basic event.",
                why="Identifies the source of risk.",
            ),
            FormField(
                "probability",
                "Your probability (0–1)",
                kind="float",
                minimum=0,
                maximum=1,
                show_for=("event",),
                help="Enter your event probability.",
                why="Feeds the fault-tree calculation.",
            ),
            FormField(
                "independent",
                "Independent events?",
                kind="choice",
                choices=("Yes", "No"),
                show_for=("AND", "OR"),
                help="Confirm the events are independent.",
                why="The gate calculation assumes independence.",
            ),
            FormField(
                "children",
                "Gate events",
                kind="rows",
                show_for=("AND", "OR"),
                help="Add two or more child events.",
                why="The gate combines their probabilities.",
                children=(
                    FormField(
                        "value",
                        "Child node",
                        kind="conditional_node",
                        help="Describe a child event or gate.",
                        why="Each child contributes to the gate.",
                    ),
                ),
            ),
        )
    raise ValueError("No conditional node schema for this method")


def schema_for(method_id: str) -> tuple[FormField, ...]:
    """All worksheet methods use their published example *shape*, not its contents."""
    example = METHODS[method_id].example

    def build(key: str, value: Any, path: str) -> FormField:
        label = title(key)
        if method_id in {"decision_tree", "fault_tree"} and path == "tree":
            return FormField(
                key,
                label,
                kind="conditional_node",
                children=conditional_node_fields(method_id),
                help="Describe the first node.",
                why="The tree is calculated from its branches.",
            )
        why = f"{label} is used to check or interpret this analysis."
        help_text = f"Describe {label.lower()} in your own words."
        if key == "id":
            return FormField(key, label, kind="generated", help="Created from the label automatically.", why=why)
        if key == "parent_id":
            return FormField(
                key,
                "Parent objective",
                kind="reference",
                reference="nodes",
                help="Choose a parent or leave blank for a root.",
                why="Parents show how objectives connect.",
            )
        if isinstance(value, list):
            sample = value[0] if value else ""
            if method_id == "monte_carlo" and path == "variables":
                children = monte_variable_fields()
            elif isinstance(sample, dict):
                children = tuple(build(k, v, f"{path}.{k}") for k, v in sample.items())
            elif isinstance(sample, list):
                children = (FormField("value", "Value", kind="text", help="Enter a value.", why=why),)
            else:
                children = (build("value", sample, path),)
            return FormField(
                key, label, kind="rows", children=children, help=f"Add as many {label.lower()} as you need.", why=why
            )
        if isinstance(value, dict):
            if (method_id, path) in KEYED_GRIDS:
                sample = next(iter(value.values()))
                cell = build(key, sample, path + ".value")
                if key == "payoffs":
                    cell = FormField(
                        "value",
                        "Payoff",
                        kind="float",
                        help="Enter your payoff for this state.",
                        why="Payoffs determine expected value; losses may be negative.",
                    )
                if key == "likelihoods":
                    cell = FormField(
                        "value",
                        "Likelihood",
                        kind="float",
                        minimum=0,
                        maximum=1,
                        help="Enter your conditional likelihood, 0–1.",
                        why="Likelihoods determine how the signal updates each state.",
                    )
                elif key == "ratings":
                    cell = FormField(
                        "value",
                        "Consistency",
                        kind="choice",
                        choices=("+", "-", "0", "?")
                        if method_id == "evidence_matrix"
                        else ("++", "+", "0", "-", "--", "?"),
                        help="Choose how this evidence relates to the hypothesis.",
                        why="Contradictions are surfaced for review, not inferred by AI.",
                    )
                elif key == "scores":
                    cell = FormField(
                        "value",
                        "Score",
                        kind="float",
                        minimum=0,
                        maximum=10,
                        help="Enter your score, 0–10.",
                        why="Scores show how the strategy performs in each scenario.",
                    )
                return FormField(
                    key,
                    label,
                    kind="keyed_grid",
                    reference=KEYED_GRIDS[(method_id, path)],
                    children=(cell,),
                    help="Enter one judgment for each named " + KEYED_GRIDS[(method_id, path)][:-1] + ".",
                    why="Every named row needs its own user-supplied judgment.",
                )
            return FormField(
                key,
                label,
                kind="object",
                children=tuple(build(k, v, f"{path}.{k}") for k, v in value.items()),
                help=help_text,
                why=why,
            )
        choices = (
            KINDS[method_id]
            if key == "kind" and method_id in KINDS
            else ENUM_CHOICES.get((method_id, key), CHOICES.get(key, ()))
        )
        if method_id == "bradley_terry" and key == "outcome":
            choices = ("a_wins", "b_wins", "tie")
        if key == "direction" and method_id == "signposts":
            choices = ("above", "below")
        if choices or isinstance(value, bool):
            kind = "choice"
            if isinstance(value, bool):
                choices = ("Yes", "No")
        elif key.endswith("date") or key == "date":
            kind = "date"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            kind = "int" if isinstance(value, int) else "float"
        else:
            kind = "long_text" if key in LONG else "text"
        low, high = BOUNDS.get(key, (None, None))
        if key == "confidence" and isinstance(value, float):
            high = 1
        if key in {"likelihood", "impact"} and method_id == "risk_matrix":
            low, high = 1, 10
        if key == "scores":
            kind = "float"
        return FormField(
            key,
            label,
            kind=kind,
            multiline=kind == "long_text",
            help=help_text
            if kind not in {"int", "float", "date"}
            else ("Use YYYY-MM-DD." if kind == "date" else "Enter your own numeric judgment."),
            why=why,
            minimum=low,
            maximum=high,
            choices=choices,
        )

    return tuple(build(key, value, key) for key, value in example.items() if key not in HIDDEN)


def blank(field: FormField) -> Any:
    if field.kind == "rows":
        return []
    if field.kind == "keyed_grid":
        return {}
    if field.kind == "conditional_node":
        return {"type": ""}
    if field.kind == "object":
        return {child.key: blank(child) for child in field.children if child.kind != "generated"}
    return ""


def parse(field: FormField, raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None if field.kind == "reference" else ""
    if field.kind in {"int", "float"}:
        try:
            result = int(value) if field.kind == "int" else float(value)
        except ValueError:
            raise ValueError(f"{field.label}: enter a {'whole' if field.kind == 'int' else 'finite'} number") from None
        import math

        if (
            not math.isfinite(result)
            or field.minimum is not None
            and result < field.minimum
            or field.maximum is not None
            and result > field.maximum
        ):
            raise ValueError(
                f"{field.label}: enter a number between {field.minimum if field.minimum is not None else 'any'} and {field.maximum if field.maximum is not None else 'any'}"
            )
        return result
    if field.kind == "date":
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError(f"{field.label}: use YYYY-MM-DD") from None
    if field.kind == "choice" and value not in field.choices:
        raise ValueError(f"{field.label}: choose {', '.join(field.choices)}")
    if field.choices == ("Yes", "No"):
        return value == "Yes"
    if field.choices == ENUM_CHOICES[("forecasting", "outcome")]:
        return {"Unresolved": None, "No": 0, "Yes": 1}[value]
    if field.choices == ENUM_CHOICES[("causal_loop", "polarity")]:
        return {"Reinforcing (+1)": 1, "Balancing (-1)": -1}[value]
    return value


def normalize_ids(state: dict) -> dict:
    """Make objective identifiers stable, unique, and invisible without breaking saved links."""
    nodes = state.get("nodes", [])
    if not isinstance(nodes, list):
        return state
    used = {node.get("id") for node in nodes if isinstance(node, dict) and node.get("id")}
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") or not str(node.get("label", "")).strip():
            continue
        base = slug(str(node.get("label", "")))
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}-{index}"
            index += 1
        node["id"] = candidate
        used.add(candidate)
    return state


def rename_grid_label(state: dict, method_id: str, source: str, old: str, new: str) -> None:
    """Carry existing judgments through a label edit without overwriting collisions.

    The unused key remains visible in the form when a rename collides, so a human
    can resolve it instead of silently losing a score.
    """
    if not old or not new or old == new:
        return
    for (method, path), linked in KEYED_GRIDS.items():
        if method != method_id or linked != source:
            continue
        group, key = path.split(".")
        for row in state.get(group, []):
            values = row.get(key) if isinstance(row, dict) else None
            if isinstance(values, dict) and old in values and new not in values:
                values[new] = values.pop(old)


def draft_from_example(method_id: str) -> dict:
    """Only invoked after the user explicitly chooses Load example."""
    return deepcopy(METHODS[method_id].example)
