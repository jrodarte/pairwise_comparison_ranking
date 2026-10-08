"""Schema-driven editor for structured method states. Examples define shape, never user data."""

from __future__ import annotations

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


KEYED_GRIDS = {
    ("value_of_information", "actions.payoffs"): "states",
    ("value_of_information", "signals.likelihoods"): "states",
    ("strategy_stress", "strategies.scores"): "scenarios",
}

CHOICES = {
    "direction": ("benefit", "cost"),
    "rating": ("++", "+", "0", "-", "--", "?"),
    "operation": ("product", "sum"),
}
KINDS = {
    "objectives": ("fundamental", "means"),
    "value_focused": ("fundamental", "means"),
    "hypothesis_tree": ("hypothesis", "test"),
    "decision_tree": ("chance", "decision"),
    "fault_tree": ("AND", "OR"),
    "monte_carlo": ("normal", "lognormal", "uniform", "triangular"),
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


def schema_for(method_id: str) -> tuple[FormField, ...]:
    """All worksheet methods use their published example *shape*, not its contents."""
    example = METHODS[method_id].example

    def build(key: str, value: Any, path: str) -> FormField:
        label = title(key)
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
            if isinstance(sample, dict):
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
        choices = KINDS[method_id] if key == "kind" and method_id in KINDS else CHOICES.get(key, ())
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
