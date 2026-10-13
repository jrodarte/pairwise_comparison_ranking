"""Schema-driven editor for structured method states. Examples define shape, never user data."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from .core import ASSUMPTION_STATUSES, METHODS
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
    optional: bool = False
    children: tuple[FormField, ...] = ()
    show_for: tuple[str, ...] = ()  # visible only for these distribution choices
    item_label: str = ""  # singular name of one row, e.g. "Hypothesis" for a Hypotheses list


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
    ("assumption_mapping", "status"): ASSUMPTION_STATUSES,
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
# Example integers describe shape, not whether a measured quantity must be whole.
# Keep counts/seeds as integers; these judgments accept finite fractional values.
DECIMAL_PATHS = {
    "fermi": {"factors.low", "factors.estimate", "factors.high"},
    "reference_class": {"cases.estimate", "cases.actual", "inside_estimate"},
    "signposts": {"indicators.threshold", "indicators.current"},
    "monte_carlo": {"constant", "threshold"},
}
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


# Plain-language labels where a field key alone is cryptic ("Dt", "Sd", "P if true").
KEY_LABELS = {
    "dt": "Time step (dt)",
    "sd": "Standard deviation",
    "p_if_true": "P(evidence | hypothesis true), 0–1",
    "p_if_false": "P(evidence | hypothesis false), 0–1",
    "scale_max": "Scale maximum",
    "rollback_cost": "Cost to reverse",
    "rollback_days": "Days to reverse",
    "trigger": "Reversal trigger",
    "research_cost": "Cost of the research or information",
    "inside_estimate": "Your inside-view estimate",
    "adjusted_estimate": "Your adjusted forecast",
    "reference_class": "Reference class",
    "new_capacity": "Proposed new capacity",
    "root_test": "Test of the root cause",
    "future_state": "Desired future state",
    "target_date": "Target date",
    "depends_on": "Depends on",
    "change_mind": "What would change your mind?",
    "basis": "Why do you believe it?",
    "criteria_matrix": "Criteria comparison matrix",
    "alternative_matrices": "Alternative comparison matrices",
    "vary": "Criterion to vary",
    "a": "Item A",
    "b": "Item B",
    "low": "Low pole",
    "high": "High pole",
    "low_low": "Scenario · axis 1 low, axis 2 low",
    "low_high": "Scenario · axis 1 low, axis 2 high",
    "high_low": "Scenario · axis 1 high, axis 2 low",
    "high_high": "Scenario · axis 1 high, axis 2 high",
}
# (method, dotted path) → (label, help). Help says what to enter; "why" stays generic.
PATH_LABELS = {
    ("assumption_mapping", "assumptions.statement"): ("Assumption", "One testable claim your plan depends on."),
    ("assumption_mapping", "assumptions.basis"): (
        "Why do you believe it?",
        "Current basis or evidence; separates an assumption from a known fact.",
    ),
    ("assumption_mapping", "assumptions.confidence"): ("Confidence (0–1)", "How sure you are it holds, 0–1."),
    ("assumption_mapping", "assumptions.impact"): ("Impact if wrong (1–10)", "Consequence if it proves false."),
    ("assumption_mapping", "assumptions.test"): ("Validation test", "How you will check this assumption."),
    ("assumption_mapping", "assumptions.change_mind"): (
        "Disproved if…",
        "The test result that would show this assumption is wrong. Decide it before you test.",
    ),
    ("assumption_mapping", "assumptions.status"): (
        "Test result",
        "Untested = not yet tested; Supported = held; Weak = mixed result; Falsified = disproved.",
    ),
    ("ach", "evidence.source"): ("Source / provenance", "Where this evidence came from."),
    ("evidence_matrix", "evidence.source"): ("Source / provenance", "Where this evidence came from."),
    ("ach", "evidence.reliability"): ("Reliability (0–1)", "How much you trust this evidence, 0–1."),
    ("evidence_matrix", "evidence.reliability"): ("Reliability (0–1)", "How much you trust this evidence, 0–1."),
    ("expected_value", "alternatives.outcomes.name"): ("Outcome", "Name what happens, e.g. Adopted."),
    ("expected_value", "alternatives.outcomes.probability"): (
        "Probability (0–1)",
        "Your chance judgment; each alternative's outcomes sum to 1.",
    ),
    ("expected_value", "alternatives.outcomes.value"): ("Payoff", "Value of this outcome in a shared unit."),
    ("risk_matrix", "risks.owner"): ("Owner", "Who manages this risk."),
    ("reference_class", "question"): ("Forecast question", "What quantity are you forecasting?"),
    ("reference_class", "reference_class"): (
        "Reference class",
        "Which comparable past cases form the outside view, and why they are comparable.",
    ),
    ("reference_class", "cases.estimate"): ("Original estimate", "What was estimated at the start."),
    ("reference_class", "cases.actual"): ("Actual result", "What actually happened, in the same unit."),
    ("reference_class", "adjusted_estimate"): (
        "Your adjusted forecast",
        "Your final forecast after comparing the inside and outside views.",
    ),
    ("backcasting", "milestones.requirement"): ("What must be true by then?", "A prerequisite for the future state."),
    ("backcasting", "milestones.depends_on"): ("Depends on", "Earlier milestones this one needs."),
    ("five_whys", "chain.why"): ("Why?", "Ask why the previous answer happened."),
    ("five_whys", "chain.answer"): ("Because…", "Your answer to this why."),
    ("root_cause", "causes.claim"): ("Candidate cause", "One possible cause, stated as a claim."),
    ("root_cause", "causes.test"): ("Test", "How to confirm or rule out this cause."),
    ("fmea", "failure_modes.mode"): ("Failure mode", "How it can fail."),
    ("fmea", "failure_modes.controls"): ("Existing controls", "Controls already in place."),
    ("fmea", "failure_modes.action"): ("Recommended action", "What you will do to reduce the risk."),
    ("hypothesis_tree", "nodes.label"): ("Hypothesis or test", "State the hypothesis or the test."),
    ("value_focused", "objectives.why"): ("Why does it matter?", "The deeper value this objective serves."),
    ("signposts", "indicators.current"): ("Current reading", "Latest observed value, if known."),
}
# Optional fields: blank is accepted and the label says so.
OPTIONAL_PATHS = {
    ("assumption_mapping", "assumptions.basis"),
    ("assumption_mapping", "assumptions.change_mind"),
    ("assumption_mapping", "assumptions.status"),
    ("ach", "evidence.source"),
    ("evidence_matrix", "evidence.source"),
    ("expected_value", "alternatives.outcomes.name"),
    ("risk_matrix", "risks.owner"),
    ("reference_class", "question"),
    ("reference_class", "reference_class"),
    ("reference_class", "adjusted_estimate"),
    ("backcasting", "milestones.owner"),
    ("backcasting", "milestones.depends_on"),
    ("forecasting", "forecasts.resolution_date"),
    ("forecasting", "forecasts.rationale"),
    ("value_focused", "objectives.why"),
}
SINGULAR = {
    "hypotheses": "Hypothesis",
    "axes": "Axis",
    "criteria": "Criterion",
    "alternatives": "Alternative",
    "items": "Item",
    "comparisons": "Comparison",
    "drivers": "Driving force",
    "variables": "Variable",
    "evidence": "Evidence item",
    "implications": "Implication",
    "indicators": "Indicator",
    "causes": "Cause",
    "supporting": "Supporting evidence",
    "contradicting": "Contradicting evidence",
    "preventive_controls": "Preventive control",
    "mitigating_controls": "Mitigating control",
    "categories": "Category",
    "chain": "Why",
    "scenarios": "Scenario",
    "strategies": "Strategy",
    "nodes": "Node",
    "branches": "Branch",
    "children": "Child event",
    "factors": "Factor",
    "cases": "Case",
    "forecasts": "Forecast",
    "milestones": "Milestone",
    "objectives": "Objective",
    "failure_modes": "Failure mode",
    "assumptions": "Assumption",
    "risks": "Risk",
    "threats": "Threat",
    "consequences": "Consequence",
    "states": "State",
    "actions": "Action",
    "signals": "Signal",
    "outcomes": "Outcome",
    "links": "Link",
    "stages": "Stage",
    "stocks": "Stock",
    "flows": "Flow",
    "values": "Value",
    "weights": "Weight",
    "scores": "Score",
    "range": "Bound",
}


def singular(key: str) -> str:
    return SINGULAR.get(key, title(key).removesuffix("s") or title(key))


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
            help=(
                "Enter the log-scale mean (not the real-space average) for lognormal; ordinary mean for normal."
                if key == "mean"
                else "Enter your own " + ("nonnegative standard deviation" if key == "sd" else title(key).lower()) + "."
            ),
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
    if method_id == "fmea":
        example = {**example, "scale_max": 10}

    def merge_rows(rows: list) -> dict:
        """An example's first row is not a schema: later rows may have optional keys."""
        merged: dict = {}
        for row in rows:
            if isinstance(row, dict):
                for key, value in row.items():
                    if key not in merged:
                        merged[key] = value
                    elif isinstance(value, dict) and isinstance(merged[key], dict):
                        merged[key] = {**merged[key], **value}
        return merged

    def build(key: str, value: Any, path: str) -> FormField:
        # A scalar list's "value" child is one item of its parent, e.g. one Hypothesis.
        label = singular(path.rsplit(".", 1)[-1]) if key == "value" else KEY_LABELS.get(key, title(key))
        label, custom_help = PATH_LABELS.get((method_id, path), (label, ""))
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
            noun = "objective" if method_id == "objectives" else "node"
            return FormField(
                key,
                f"Parent {noun}",
                kind="reference",
                reference="nodes",
                help=f"Leave blank for a top-level {noun}. Label another {noun} before choosing it as a parent.",
                why="Parents connect nodes within the hierarchy, not the analysis decision purpose.",
            )
        if isinstance(value, list):
            sample = merge_rows(value) if value and isinstance(value[0], dict) else value[0] if value else ""
            if method_id == "monte_carlo" and path == "variables":
                children = monte_variable_fields()
            elif isinstance(sample, dict):
                children = tuple(build(k, v, f"{path}.{k}") for k, v in sample.items())
                if method_id == "objectives" and path == "nodes":
                    children += (
                        FormField(
                            "change_mind",
                            "What would change your mind about this objective? (optional)",
                            optional=True,
                            help="Name an observation that would make you reconsider this outcome or means.",
                            why="Keeps the test tied to this objective rather than the hierarchy as a whole.",
                        ),
                    )
            elif isinstance(sample, list):
                children = (FormField("value", "Value", kind="text", help="Enter a value.", why=why),)
                if method_id == "sensitivity" and path == "alternatives.scores":
                    children = (
                        FormField(
                            "value",
                            "Score",
                            kind="float",
                            minimum=0,
                            maximum=10,
                            help="Enter a score from 0 to 10.",
                            why="Scores are aligned with the criterion in the same position.",
                        ),
                    )
            else:
                children = (build("value", sample, path),)
            return FormField(
                key,
                label,
                kind="rows",
                children=children,
                help=f"Add as many {label.lower()} as you need.",
                why=why,
                item_label=singular(key),
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
        references = {
            ("sensitivity", "vary"): "criteria",
            ("opportunity_cost", "chosen"): "alternatives",
            ("bradley_terry", "a"): "items",
            ("bradley_terry", "b"): "items",
            ("causal_loop", "from"): "variables",
            ("causal_loop", "to"): "variables",
            ("stock_flow", "from"): "stocks",
            ("stock_flow", "to"): "stocks",
            ("bottleneck", "stage"): "stages",
        }
        reference = references.get((method_id, key), "") if key != "stage" or path == "proposal.stage" else ""
        if reference:
            kind = "reference"
        elif choices or isinstance(value, bool):
            kind = "choice"
            if isinstance(value, bool):
                choices = ("Yes", "No")
        elif key.endswith("date") or key == "date":
            kind = "date"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            kind = (
                "int"
                if key in {"iterations", "seed", "scale_max", "trials", "sample_size"}
                or method_id in {"fmea", "risk_matrix"}
                and key in {"severity", "occurrence", "detectability", "likelihood", "impact"}
                else "float"
            )
        else:
            kind = "long_text" if key in LONG else "text"
        low, high = BOUNDS.get(key, (None, None))
        if key == "confidence" and isinstance(value, float):
            high = 1
        if key in {"likelihood", "impact"} and method_id == "risk_matrix":
            low, high = 1, 10  # enforce the user's scale_max in the form as well
        if method_id == "fmea" and key in {"severity", "occurrence", "detectability"}:
            low, high = 1, 20
        if key == "scale_max":
            low, high = 2, 20 if method_id == "fmea" else 10
        if method_id == "bayesian_update" and key in {"prior", "p_if_true", "p_if_false"}:
            low, high = 0, 1
        if method_id == "monte_carlo" and key == "iterations":
            low, high = 100, 50000
        if method_id in {"fermi", "reference_class"} and key in {"low", "estimate", "high", "actual"}:
            low = 0
        sensitivity_score = method_id == "sensitivity" and path == "alternatives.scores" and key == "value"
        sensitivity_bound = method_id == "sensitivity" and path == "range" and key == "value"
        if key == "scores" or sensitivity_score or sensitivity_bound or path in DECIMAL_PATHS.get(method_id, ()):
            kind = "float"
        if sensitivity_score:
            low, high = 0, 10
            help_text = "Enter your score from 0 to 10 (decimals allowed)."
        if sensitivity_bound:
            low, high = 0, 1
            help_text = "Enter a bound between 0 and 1 (decimals allowed)."
        optional = (
            (method_id, path) in OPTIONAL_PATHS
            or (method_id == "signposts" and path == "indicators.current")
            or (method_id == "bottleneck" and path.startswith("proposal."))
            or (method_id == "constraints" and path.startswith("throughput."))
        )
        if custom_help:
            help_text = custom_help
        elif kind in {"int", "float", "date"} and not (sensitivity_bound or sensitivity_score):
            help_text = "Use YYYY-MM-DD." if kind == "date" else "Enter your own numeric judgment."
        return FormField(
            key,
            label + (" (optional)" if optional else ""),
            kind=kind,
            multiline=kind == "long_text",
            help=help_text,
            why=why,
            minimum=low,
            maximum=high,
            choices=choices,
            reference=reference,
            optional=optional,
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
        return None if (field.kind == "reference" or field.optional and field.kind not in {"text", "long_text"}) else ""
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
