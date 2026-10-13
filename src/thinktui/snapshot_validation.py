"""Shape checks for imported *drafts* as well as completed analyses.

Validation of a completed calculation is not enough here: a draft may lack required
judgments but must never contain a malformed container or an unsafe value that will
crash the editor when it is opened. Examples describe fields, not imported evidence.
"""

from __future__ import annotations

import math
import re
from datetime import date

from .core import ASSUMPTION_STATUSES, METHODS
from .form_model import FormField, conditional_node_fields, schema_for

# Decision Journal fields (spec §36); the editor stores every one as text.
JOURNAL_TEXT_KEYS = (
    "decision",
    "decision_date",
    "context",
    "alternatives",
    "chosen",
    "expected_outcome",
    "assumptions",
    "risks",
    "rationale",
    "review_date",
    "actual_outcome",
    "lessons",
)


def _bad(path: str, expected: str) -> None:
    raise ValueError(f"Snapshot {path} must be {expected}")


def _number(value: object, path: str) -> float:
    if type(value) not in (int, float):
        _bad(path, "a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        _bad(path, "a finite number")
    if not math.isfinite(result):
        _bad(path, "a finite number")
    return result


def _matrix(value: object, path: str) -> None:
    if not isinstance(value, list):
        _bad(path, "an array of judgment rows")
    for index, row in enumerate(value):
        if not isinstance(row, list):
            _bad(f"{path}[{index}]", "an array")
        for column, cell in enumerate(row):
            if cell != "":
                _number(cell, f"{path}[{index}][{column}]")


def _fields(value: object, specs: tuple[FormField, ...], path: str) -> None:
    if not isinstance(value, dict):
        _bad(path, "an object")
    known = {spec.key for spec in specs}
    for key in value.keys() - known:
        if key == "source" and re.fullmatch(r"ach\.evidence\[\d+\]", path):
            if not isinstance(value[key], str):
                _bad(path + ".source", "text")
        else:
            _bad(path + "." + key, "a recognized field")
    for spec in specs:
        if spec.key in value:
            _field(value[spec.key], spec, f"{path}.{spec.key}")


def _field(value: object, spec: FormField, path: str) -> None:
    kind = spec.kind
    if kind == "generated":
        if not isinstance(value, str):
            _bad(path, "text")
    elif kind in {"object", "conditional_node"}:
        children = spec.children or (conditional_node_fields(path.split(".")[0]) if kind == "conditional_node" else ())
        _fields(value, children, path)
    elif kind == "keyed_grid":
        if not isinstance(value, dict):
            _bad(path, "an object of keyed judgments")
        for key, cell in value.items():
            _field(cell, spec.children[0], f"{path}.{key}")
    elif kind == "rows":
        if not isinstance(value, list):
            _bad(path, "an array")
        single = len(spec.children) == 1 and spec.children[0].key == "value"
        for index, row in enumerate(value):
            if single:
                _field(row, spec.children[0], f"{path}[{index}]")
            else:
                _fields(row, spec.children, f"{path}[{index}]")
    elif value == "" and type(value) is str:
        pass  # a blank editor value is a legitimate unfinished judgment
    elif value is None and spec.optional:
        pass  # the form saves a cleared optional choice or number as null
    elif kind in {"int", "float"}:
        n = _number(value, path)
        if kind == "int" and type(value) is not int:
            _bad(path, "a whole number")
        if spec.minimum is not None and n < spec.minimum or spec.maximum is not None and n > spec.maximum:
            _bad(path, "within the field's permitted range")
    elif kind == "date":
        if not isinstance(value, str):
            _bad(path, "an ISO date or blank text")
        try:
            if date.fromisoformat(value).isoformat() != value:
                _bad(path, "an ISO date")
        except ValueError:
            _bad(path, "an ISO date")
    elif kind == "reference":
        if value is not None and not isinstance(value, str):
            _bad(path, "text or null")
    elif kind == "choice":
        if spec.choices == ("Yes", "No"):
            if type(value) is not bool:
                _bad(path, "a yes/no judgment")
        elif spec.key == "outcome" and path.startswith("forecasting."):
            if value is not None and type(value) is not int or type(value) is int and value not in (0, 1):
                _bad(path, "yes, no or unresolved")
        elif spec.key == "polarity" and path.startswith("causal_loop."):
            if type(value) is not int or value not in (-1, 1):
                _bad(path, "+1 or -1")
        elif not isinstance(value, str) or value not in spec.choices:
            _bad(path, "one of the listed choices")
    elif not isinstance(value, str):
        _bad(path, "text")


def validate_state(method_id: str, state: dict) -> None:
    """Reject malformed present fields, not missing fields in a genuine draft."""
    if method_id == "issue_tree":
        from .issue_tree import _validated, nodes_for

        _validated(nodes_for(state))
    elif method_id == "pairwise":
        if "ranking" in state:
            from pairwise_prioritizer.models import Project

            try:
                Project.from_dict(state["ranking"])
            except Exception as exc:
                raise ValueError("Snapshot ranking has invalid items or comparisons") from exc
    elif method_id in {"assumptions", "premortem"}:
        entries = state.get("entries", [])
        if not isinstance(entries, list):
            _bad(method_id + ".entries", "an array")
        for index, row in enumerate(entries):
            if not isinstance(row, dict):
                _bad(f"{method_id}.entries[{index}]", "an object")
            for key in ("statement", *METHODS[method_id].TEXT_FIELDS, "status"):
                if key in row and not isinstance(row[key], str):
                    _bad(f"{method_id}.entries[{index}].{key}", "text")
            if method_id == "assumptions" and row.get("status") not in (None, "", *ASSUMPTION_STATUSES):
                _bad(f"assumptions.entries[{index}].status", "a known validation status")
            for key in ("confidence", "impact") if method_id == "assumptions" else ("likelihood", "impact"):
                if key in row and row[key] != "":
                    _number(row[key], f"{method_id}.entries[{index}].{key}")
    elif method_id == "journal":
        for key in JOURNAL_TEXT_KEYS:
            if key in state and not isinstance(state[key], str):
                _bad(f"journal.{key}", "text")
    elif method_id == "matrix":
        for key in ("criteria", "alternatives"):
            if key in state:
                if not isinstance(state[key], list):
                    _bad("matrix." + key, "an array")
                for index, row in enumerate(state[key]):
                    if not isinstance(row, dict):
                        _bad(f"matrix.{key}[{index}]", "an object")
                    if "name" in row and not isinstance(row["name"], str):
                        _bad(f"matrix.{key}[{index}].name", "text")
                    if "weight" in row and row["weight"] not in ("", None):
                        _number(row["weight"], f"matrix.{key}[{index}].weight")
                    if "scores" in row:
                        if not isinstance(row["scores"], list):
                            _bad(f"matrix.{key}[{index}].scores", "an array")
                        for j, score in enumerate(row["scores"]):
                            if score != "":
                                _number(score, f"matrix.{key}[{index}].scores[{j}]")
    else:
        # AHP's dynamic named matrices are not described by the example's two keys.
        if method_id == "ahp":
            if "criteria_matrix" in state:
                _matrix(state["criteria_matrix"], "ahp.criteria_matrix")
            if "alternative_matrices" in state:
                matrices = state["alternative_matrices"]
                if not isinstance(matrices, dict):
                    _bad("ahp.alternative_matrices", "an object")
                for key, matrix in matrices.items():
                    _matrix(matrix, "ahp.alternative_matrices." + key)
        specs = tuple(
            field
            for field in schema_for(method_id)
            if method_id != "ahp" or field.key not in {"criteria_matrix", "alternative_matrices"}
        )
        _fields({field.key: state[field.key] for field in specs if field.key in state}, specs, method_id)
        if method_id == "monte_carlo":
            for index, row in enumerate(state.get("variables", [])):
                kind = row.get("distribution")
                if kind and kind not in {"uniform", "triangular", "normal", "lognormal", "discrete", "samples"}:
                    _bad(f"monte_carlo.variables[{index}].distribution", "a known distribution")
                if kind == "lognormal" and row.get("mean") not in (None, ""):
                    mean = _number(row["mean"], f"monte_carlo.variables[{index}].mean")
                    sd = (
                        _number(row["sd"], f"monte_carlo.variables[{index}].sd")
                        if row.get("sd") not in (None, "")
                        else 0
                    )
                    if mean + 6 * sd > 700:
                        _bad(f"monte_carlo.variables[{index}].mean", "a safe log-scale parameter")
    meta = {
        "change_mind",
        "source_session_id",
        "workflow_id",
        "workflow_goal",
        "workflow_steps",
        "workflow_index",
        "_guided_step",
        "_draft",
        "_draft_fields",
        "_forecast_edit_index",
        "_text_row_drafts",
        "_example_loaded",
    }
    if method_id in {"issue_tree", "assumptions", "premortem"}:
        known = {"nodes", "entries"}
    elif method_id == "journal":
        known = {*JOURNAL_TEXT_KEYS, "confidence"}
    elif method_id == "pairwise":
        known = {"ranking"}
    elif method_id == "matrix":
        known = {"criteria", "alternatives"}
    else:
        known = {field.key for field in schema_for(method_id)}
    for key in state.keys() - known - meta:
        _bad(method_id + "." + key, "a recognized field")
    for key in ("change_mind", "source_session_id", "workflow_id", "workflow_goal"):
        if key in state and not isinstance(state[key], str):
            _bad(method_id + "." + key, "text")
    for key in ("_guided_step", "workflow_index", "_forecast_edit_index"):
        if key in state and (type(state[key]) is not int or state[key] < 0):
            _bad(method_id + "." + key, "a nonnegative step index")
    for key in ("workflow_steps", "_text_row_drafts"):
        if key in state and (not isinstance(state[key], list) or any(not isinstance(v, str) for v in state[key])):
            _bad(method_id + "." + key, "a list of text")
    if any(key in state for key in ("workflow_id", "workflow_goal", "workflow_steps", "workflow_index")):
        steps = state.get("workflow_steps")
        index = state.get("workflow_index")
        if (
            not isinstance(steps, list)
            or not steps
            or any(step not in METHODS for step in steps)
            or type(index) is not int
            or not 0 <= index < len(steps)
            or steps[index] != method_id
        ):
            _bad(method_id + ".workflow_steps", "a valid plan whose current step matches the analysis method")
    if "_example_loaded" in state and type(state["_example_loaded"]) is not bool:
        _bad(method_id + "._example_loaded", "yes or no")
    for key in ("_draft", "_draft_fields"):
        if key in state and (
            not isinstance(state[key], dict) or any(not isinstance(v, str) for v in state[key].values())
        ):
            _bad(method_id + "." + key, "a text-only draft")
