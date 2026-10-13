"""Explicit, validated steps for five high-value methods; no AI-created judgments."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass

from .advanced_decisions import name, number, probability
from .core import METHODS

GUIDED = frozenset({"matrix", "ahp", "ach", "forecasting", "scenarios"})
QUADRANTS = ("low_low", "low_high", "high_low", "high_high")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    value: str = ""
    multiline: bool = False
    help: str = ""
    why: str = ""


@dataclass(frozen=True)
class Step:
    title: str
    help: str
    fields: tuple[Field, ...] = ()
    review: bool = False


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def distinct(values: list[str], label: str, minimum: int = 2) -> list[str]:
    if len(values) < minimum or len(values) != len({v.casefold() for v in values}):
        raise ValueError(f"Enter at least {minimum} distinct {label}")
    return values


def ratio(text: str) -> float:
    try:
        parts = text.strip().split("/")
        value = float(parts[0]) if len(parts) == 1 else float(parts[0]) / float(parts[1]) if len(parts) == 2 else 0
    except (ValueError, ZeroDivisionError):
        raise ValueError("Judgment must be a decimal or fraction such as 1/3") from None
    if not math.isfinite(value) or not 1 / 9 - 1e-9 <= value <= 9 + 1e-9:
        raise ValueError("Pairwise judgment must be from 1/9 to 9")
    return value


def matrix_from_pairs(size: int, values: dict[str, str]) -> list[list[float]]:
    matrix = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for i in range(size):
        for j in range(i + 1, size):
            value = ratio(values[f"pair_{i}_{j}"])
            matrix[i][j], matrix[j][i] = value, 1 / value
    return matrix


def pair_fields(labels: list[str], existing: list | None = None) -> tuple[Field, ...]:
    return tuple(
        Field(f"pair_{i}_{j}", f"{a} compared with {b} (1/9–9; 1 = equal)", str(existing[i][j]) if existing else "")
        for i, a in enumerate(labels)
        for j, b in enumerate(labels)
        if i < j
    )


def definition(method: str, state: dict, index: int) -> Step:
    if method == "matrix":
        if index == 0:
            return Step(
                "Choose options to compare",
                "Name at least two distinct choices below. Include 'do nothing' if it is a real option. "
                "Add or remove rows as needed; bulk paste is optional.",
                (Field("alternatives", "Options", "\n".join(a["name"] for a in state.get("alternatives", [])), True),),
            )
        if index == 1:
            criteria = "\n".join(
                f"{c['name']} | {'' if c.get('weight') is None else c['weight']} | {c.get('direction', 'benefit')}"
                for c in state.get("criteria", [])
            )
            return Step(
                "Choose what matters",
                "Add each criterion, give it your relative weight, and choose whether higher or lower scores "
                "are better. No need to make weights add up to 100.",
                (Field("criteria", "Criteria, weights, directions", criteria, True),),
            )
        if index == 2:
            criteria = state.get("criteria", [])
            fields = tuple(
                Field(
                    f"score_{i}_{j}",
                    f"{alt['name']} · {c['name']} (0–10)",
                    str(alt["scores"][j]) if j < len(alt.get("scores", [])) else "",
                )
                for i, alt in enumerate(state.get("alternatives", []))
                for j, c in enumerate(criteria)
            )
            return Step(
                "Score options · converge",
                "Enter *your* 0–10 judgments. For cost criteria, larger means more costly.",
                fields,
            )
        return Step(
            "Review decision matrix",
            "Review normalized weights, benefit/cost transformations and ranking; user decides.",
            review=True,
        )
    if method == "ahp":
        criteria = state.get("criteria", [])
        alternatives = state.get("alternatives", [])
        if index == 0:
            return Step(
                "Goal & criteria",
                "The goal is the problem statement. Enter 1–10 criteria, one per line.",
                (Field("criteria", "Criteria", "\n".join(criteria), True),),
            )
        if index == 1:
            return Step(
                "Alternatives",
                "Enter 2–10 distinct alternatives, one per line.",
                (Field("alternatives", "Alternatives", "\n".join(alternatives), True),),
            )
        if index == 2:
            return Step(
                "Compare criteria",
                "Enter A/B ratios: 3 means A has three times the priority of B; 1/3 means B has three times the priority.",
                pair_fields(criteria, state.get("criteria_matrix")),
            )
        if index < 3 + len(criteria):
            c = criteria[index - 3]
            return Step(
                f"Compare alternatives · {c}",
                f"How do alternatives compare on {c}? Enter ratios; the reverse comparison is calculated.",
                pair_fields(alternatives, state.get("alternative_matrices", {}).get(c)),
            )
        return Step(
            "Review AHP priorities",
            "Check consistency ratios (CR > 0.1 warrants review). No judgments are auto-corrected.",
            review=True,
        )
    if method == "ach":
        if index == 0:
            return Step(
                "Competing hypotheses",
                "Diverge: enter at least two distinct explanations, one per line.",
                (Field("hypotheses", "Hypotheses", "\n".join(state.get("hypotheses", [])), True),),
            )
        if index == 1:
            fields = [
                Field("title", "One evidence item / observation"),
                Field("source", "Source / provenance (optional)"),
                Field("reliability", "Source reliability (0–1)"),
            ]
            fields.extend(
                Field(f"rating_{i}", f"Consistency with {h} (++,+,0,-,--,?)")
                for i, h in enumerate(state.get("hypotheses", []))
            )
            return Step(
                "Assess one evidence item",
                "Enter observed evidence, not a model-generated fact. Rate ALL hypotheses; '?' is unknown.",
                tuple(fields),
            )
        return Step(
            "Review contradictions",
            "Lower weighted inconsistency is not a posterior probability. Add more evidence or review the record.",
            review=True,
        )
    if method == "forecasting":
        draft = state.get("_draft", {})
        if index == 0:
            return Step(
                "Forecast question",
                "State a resolvable yes/no question; define the resolution date and rationale.",
                (
                    Field("question", "Question", draft.get("question", "")),
                    Field(
                        "resolution_date", "Resolution date (YYYY-MM-DD, optional)", draft.get("resolution_date", "")
                    ),
                    Field("rationale", "Rationale / reference class (if known)", draft.get("rationale", ""), True),
                ),
            )
        if index == 1:
            return Step(
                "Make your probability judgment",
                "Enter a probability from 0–100%. Think about base rates if available.",
                (Field("probability", "Your probability, percent (0–100)", draft.get("probability", "")),),
            )
        if index == 2:
            value = state["forecasts"][-1].get("outcome")
            return Step(
                "Resolve when known",
                "Type yes, no or ? (unresolved). This can be updated later.",
                (Field("outcome", "Outcome", "?" if value is None else "yes" if value == 1 else "no"),),
            )
        return Step(
            "Brier score & calibration",
            "Only resolved forecasts count; add another forecast to improve the sample.",
            review=True,
        )
    if method == "scenarios":
        if index == 0:
            return Step(
                "Strategic question & driving forces",
                "Separate what is known from critical uncertainties.",
                (
                    Field("question", "Strategic question", state.get("question", "")),
                    Field(
                        "drivers",
                        "Driving forces, one per line (at least two)",
                        "\n".join(state.get("drivers", [])),
                        True,
                    ),
                ),
            )
        if index == 1:
            axes = state.get("axes", [{}, {}])
            fields = tuple(
                Field(
                    f"axis_{i}_{part}", f"Uncertainty {i + 1} · {part}", axes[i].get(part, "") if i < len(axes) else ""
                )
                for i in range(2)
                for part in ("name", "low", "high")
            )
            return Step("Select two uncertainty axes", "Name each axis and its distinct low/high poles.", fields)
        if index in (2, 3, 4, 5):
            quadrant = QUADRANTS[index - 2]
            row = state.get("scenarios", {}).get(quadrant, {})
            return Step(
                f"Scenario · {quadrant}",
                "Write your own plausible narrative, implications and observable signposts.",
                (
                    Field("name", "Scenario name", row.get("name", "")),
                    Field("narrative", "Narrative", row.get("narrative", ""), True),
                    Field("implications", "Implications, one per line", "\n".join(row.get("implications", [])), True),
                    Field(
                        "indicators", "Indicators/signposts, one per line", "\n".join(row.get("indicators", [])), True
                    ),
                ),
            )
        if index == 6:
            fields = [Field("name", "Strategy name")]
            fields.extend(Field(f"action_{key}", f"Action in {state['scenarios'][key]['name']}") for key in QUADRANTS)
            return Step(
                "Strategy across futures",
                "Enter at least one strategy with a user-approved action for EACH future.",
                tuple(fields),
            )
        return Step(
            "Review scenarios & strategies",
            "Scenarios are plausible narratives, not probability forecasts. Add another strategy or export.",
            review=True,
        )
    raise ValueError("No guided workflow for this method")


class LabelMappingRequired(ValueError):
    """Guided AHP/ACH labels have saved judgments needing an explicit mapping."""

    def __init__(self, method: str, index: int, previous: list[str], proposed: list[str]) -> None:
        super().__init__("Confirm which old judgments belong to each edited label")
        self.method, self.index, self.previous, self.proposed = method, index, previous, proposed


class ScenarioMappingRequired(ValueError):
    """Saved narratives must be mapped to edited axis poles explicitly."""

    method = "scenarios"
    index = 1

    def __init__(self, previous_axes: list[dict], proposed_axes: list[dict]) -> None:
        super().__init__("Confirm where each saved scenario and strategy action belongs on the revised axes")
        self.previous = [
            f"{q}: {previous_axes[0][a]}, {previous_axes[1][b]}"
            for q, a, b in (
                ("low_low", "low", "low"),
                ("low_high", "low", "high"),
                ("high_low", "high", "low"),
                ("high_high", "high", "high"),
            )
        ]
        self.proposed = [
            f"{q}: {proposed_axes[0][a]}, {proposed_axes[1][b]}"
            for q, a, b in (
                ("low_low", "low", "low"),
                ("low_high", "low", "high"),
                ("high_low", "high", "low"),
                ("high_high", "high", "high"),
            )
        ]


class MatrixMappingRequired(ValueError):
    """A scored matrix needs an explicit old-to-new judgment mapping."""

    def __init__(self, index: int, previous: list[str], proposed: list[str]) -> None:
        super().__init__("Confirm which existing scores belong to each edited label before continuing")
        self.index, self.previous, self.proposed = index, previous, proposed


def checked_label_mapping(
    previous: list[str], proposed: list[str], mapping: list[int | None], *, discard_judgments: bool = False
) -> None:
    """Never drop an unmapped ACH/AHP judgment without named, explicit consent."""
    if len(mapping) != len(proposed) or any(
        source is not None and (type(source) is not int or not 0 <= source < len(previous)) for source in mapping
    ):
        raise ValueError("Map each label to an old label or choose a new blank label")
    retained = [source for source in mapping if source is not None]
    if len(retained) != len(set(retained)):
        raise ValueError("Each saved label can be mapped only once")
    lost = [label for i, label in enumerate(previous) if i not in retained]
    if lost and not discard_judgments:
        raise ValueError("Confirm discarding saved judgments for: " + ", ".join(lost))


def remap_judgments(matrix: list[list[float]], mapping: list[int | None]) -> list[list[float | str]]:
    """Retain the original submatrix and leave all *new* pairwise judgments blank."""
    return [
        [
            matrix[left][right] if left is not None and right is not None else 1.0 if i == j else ""
            for j, right in enumerate(mapping)
        ]
        for i, left in enumerate(mapping)
    ]


def complete_judgments(matrix: object, size: int) -> bool:
    return (
        isinstance(matrix, list)
        and len(matrix) == size
        and all(
            isinstance(row, list)
            and len(row) == size
            and all(type(value) in (int, float) and math.isfinite(value) and value > 0 for value in row)
            for row in matrix
        )
    )


def matrix_score_present(value: object) -> bool:
    """Treat even malformed, nonblank legacy inputs as judgments, never silent trash."""
    return value is not None and value != ""


def matrix_has_scores(state: dict) -> bool:
    return any(matrix_score_present(score) for row in state.get("alternatives", []) for score in row.get("scores", []))


def matrix_mapping(before: list[str], after: list[str]) -> list[int | None]:
    """Propose exact-name matches only; a rename is a new row until confirmed."""
    return [before.index(label) if label in before else None for label in after]


def checked_mapping(previous: list[str], proposed: list[str], mapping: list[int | None]) -> None:
    if len(mapping) != len(proposed) or any(
        source is not None and (type(source) is not int or not 0 <= source < len(previous)) for source in mapping
    ):
        raise ValueError("Choose one existing row or a new blank row for every label")
    selected = [source for source in mapping if source is not None]
    if len(selected) != len(set(selected)):
        raise ValueError("Each existing scored row can map to only one new label")


def reachable_index(method: str, state: dict) -> int:
    """A stale/malformed saved cursor cannot bypass missing prior steps."""
    if method == "matrix":
        if len(state.get("alternatives", [])) < 2:
            return 0
        if not state.get("criteria"):
            return 1
        if any(
            len(row.get("scores", [])) != len(state["criteria"])
            or any(
                type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 10
                for score in row.get("scores", [])
            )
            for row in state["alternatives"]
        ):
            return 2
        return 3
    if method == "ahp":
        criteria = state.get("criteria", [])
        if not criteria:
            return 0
        if len(state.get("alternatives", [])) < 2:
            return 1
        if not complete_judgments(state.get("criteria_matrix"), len(criteria)):
            return 2
        alternatives_matrices = state.get("alternative_matrices", {})
        if not isinstance(alternatives_matrices, dict):
            return 3
        for index, criterion in enumerate(criteria):
            if not complete_judgments(alternatives_matrices.get(criterion), len(state["alternatives"])):
                return 3 + index
        return 3 + len(criteria)
    if method == "ach":
        hypotheses = state.get("hypotheses", [])
        if len(hypotheses) < 2:
            return 0
        evidence = state.get("evidence", [])
        if not evidence or any(
            not isinstance(row.get("ratings"), dict)
            or set(row["ratings"]) != set(hypotheses)
            or any(value not in {"++", "+", "0", "-", "--", "?"} for value in row["ratings"].values())
            for row in evidence
        ):
            return 1
        return 2
    if method == "forecasting":
        return 3 if state.get("forecasts") else 1 if state.get("_draft") else 0
    if method == "scenarios":
        if not state.get("question") or not state.get("drivers"):
            return 0
        if len(state.get("axes", [])) < 2:
            return 1
        for index, key in enumerate(QUADRANTS):
            if key not in state.get("scenarios", {}):
                return 2 + index
        return 7 if state.get("strategies") else 6
    raise ValueError("No guided workflow for this method")


def next_index(method: str, state: dict, index: int) -> int:
    return min(index + 1, final_index(method, state))


def final_index(method: str, state: dict) -> int:
    return {"matrix": 3, "ach": 2, "forecasting": 3, "scenarios": 7}.get(method, 3 + len(state.get("criteria", [])))


def advance(
    method: str,
    state: dict,
    index: int,
    values: dict[str, str],
    *,
    mapping: list[int | None] | None = None,
    discard_scores: bool = False,
    discard_judgments: bool = False,
) -> dict:
    """Return a fresh state after one validated step. Failure cannot mutate persisted data."""
    data = deepcopy(state)
    if index == final_index(method, data):
        issues = METHODS[method].validate(data)
        if issues:
            raise ValueError(" ".join(issues))
        return data
    if method == "matrix":
        if index == 0:
            names = distinct(lines(values["alternatives"]), "alternatives")
            existing = data.get("alternatives", [])
            before = [row["name"] for row in existing]
            if before != names:
                if matrix_has_scores(data) and mapping is None:
                    raise MatrixMappingRequired(index, before, names)
                if mapping is not None:
                    checked_mapping(before, names, mapping)
                    lost = [
                        row["name"]
                        for i, row in enumerate(existing)
                        if i not in mapping and any(matrix_score_present(s) for s in row.get("scores", []))
                    ]
                    if lost and not discard_scores:
                        raise ValueError("Confirm discarding scores for: " + ", ".join(lost))
                sources = mapping if mapping is not None else matrix_mapping(before, names)
                data["alternatives"] = [
                    {**existing[source], "name": label, "scores": list(existing[source].get("scores", []))}
                    if source is not None
                    else {"name": label, "scores": []}
                    for label, source in zip(names, sources, strict=True)
                ]
        elif index == 1:
            rows = []
            for line in lines(values["criteria"]):
                parts = [part.strip() for part in line.split("|")]
                if len(parts) != 3:
                    raise ValueError("Use Name | weight | benefit or cost on every line")
                label = name(parts[0], "Criterion")
                weight = number(parts[1], "Weight", 0)
                if parts[2] not in {"benefit", "cost"}:
                    raise ValueError("Direction must be benefit or cost")
                rows.append({"name": label, "weight": weight, "direction": parts[2]})
            distinct([r["name"] for r in rows], "criteria", 1)
            if sum(r["weight"] for r in rows) <= 0:
                raise ValueError("Total weight must be positive")
            old_criteria = data.get("criteria", [])
            before = [criterion["name"] for criterion in old_criteria]
            after = [criterion["name"] for criterion in rows]
            if before != after:
                if matrix_has_scores(data) and mapping is None:
                    raise MatrixMappingRequired(index, before, after)
                if mapping is not None:
                    checked_mapping(before, after, mapping)
                    lost = [
                        old_criteria[j]["name"]
                        for j in range(len(old_criteria))
                        if j not in mapping
                        and any(
                            j < len(alt.get("scores", [])) and matrix_score_present(alt["scores"][j])
                            for alt in data.get("alternatives", [])
                        )
                    ]
                    if lost and not discard_scores:
                        raise ValueError("Confirm discarding scores for: " + ", ".join(lost))
                sources = mapping if mapping is not None else matrix_mapping(before, after)
                for alternative in data.get("alternatives", []):
                    prior = alternative.get("scores", [])
                    alternative["scores"] = (
                        [prior[j] if j is not None and j < len(prior) else "" for j in sources] if prior else []
                    )
            data["criteria"] = rows
        elif index == 2:
            for i, alt in enumerate(data["alternatives"]):
                scores = [number(values[f"score_{i}_{j}"], "Score", 0) for j in range(len(data["criteria"]))]
                if any(value > 10 for value in scores):
                    raise ValueError("Scores must be between 0 and 10")
                alt["scores"] = scores
    elif method == "ahp":
        if index in (0, 1):
            key = "criteria" if index == 0 else "alternatives"
            labels = distinct(lines(values[key]), key, 1 if index == 0 else 2)
            if len(labels) > 10:
                raise ValueError("AHP supports at most ten labels per level")
            if (
                data.get(key)
                and data[key] != labels
                and (
                    data.get("criteria_matrix") or data.get("alternative_matrices")
                    if index == 0
                    else data.get("alternative_matrices")
                )
            ):
                before = data[key]
                if mapping is None:
                    raise LabelMappingRequired("ahp", index, before, labels)
                checked_label_mapping(before, labels, mapping, discard_judgments=discard_judgments)
                if index == 0:
                    matrix = data.get("criteria_matrix")
                    if matrix:
                        data["criteria_matrix"] = remap_judgments(matrix, mapping)
                    old_alternatives = data.get("alternative_matrices", {})
                    data["alternative_matrices"] = {
                        label: old_alternatives[before[source]]
                        for label, source in zip(labels, mapping, strict=True)
                        if source is not None and before[source] in old_alternatives
                    }
                else:
                    for criterion, matrix in data.get("alternative_matrices", {}).items():
                        data["alternative_matrices"][criterion] = remap_judgments(matrix, mapping)
            data[key] = labels
        elif index == 2:
            data["criteria_matrix"] = matrix_from_pairs(len(data["criteria"]), values)
        else:
            criterion = data["criteria"][index - 3]
            data.setdefault("alternative_matrices", {})[criterion] = matrix_from_pairs(
                len(data["alternatives"]), values
            )
    elif method == "ach":
        if index == 0:
            labels = distinct(lines(values["hypotheses"]), "hypotheses")
            if data.get("evidence") and data.get("hypotheses") != labels:
                before = data["hypotheses"]
                if mapping is None:
                    raise LabelMappingRequired("ach", index, before, labels)
                checked_label_mapping(before, labels, mapping, discard_judgments=discard_judgments)
                for entry in data["evidence"]:
                    entry["ratings"] = {
                        label: entry["ratings"].get(before[source], "") if source is not None else ""
                        for label, source in zip(labels, mapping, strict=True)
                    }
            data["hypotheses"] = labels
        elif index == 1:
            entry = {
                "title": name(values["title"], "Evidence"),
                "source": values.get("source", "").strip(),
                "reliability": probability(values["reliability"], "Reliability"),
                "ratings": {h: values[f"rating_{i}"].strip() for i, h in enumerate(data["hypotheses"])},
            }
            if any(r not in {"++", "+", "0", "-", "--", "?"} for r in entry["ratings"].values()):
                raise ValueError("Rate all hypotheses ++, +, 0, -, -- or ?")
            evidence = data.setdefault("evidence", [])
            if "edit_index" in values:
                selected = int(values["edit_index"])
                if not 0 <= selected < len(evidence):
                    raise ValueError("Choose a saved evidence item")
                evidence[selected] = entry
            else:
                evidence.append(entry)
    elif method == "forecasting":
        if index == 0:
            draft = {
                "question": name(values["question"], "Forecast question"),
                "resolution_date": values["resolution_date"].strip(),
                "rationale": values["rationale"].strip(),
            }
            # Reuse the method's date semantics if specified.
            if draft["resolution_date"]:
                from datetime import date

                try:
                    if date.fromisoformat(draft["resolution_date"]).isoformat() != draft["resolution_date"]:
                        raise ValueError
                except ValueError:
                    raise ValueError("Resolution date must be YYYY-MM-DD") from None
            data["_draft"] = draft
        elif index == 1:
            percent = number(values["probability"], "Probability", 0)
            if percent > 100:
                raise ValueError("Probability must be 0–100%")
            draft = data.get("_draft")
            if not isinstance(draft, dict) or not draft.get("question"):
                raise ValueError("Return to the forecast question before setting its probability")
            forecasts = data.setdefault("forecasts", [])
            selected = data.get("_forecast_edit_index")
            entry = {**draft, "probability": percent / 100, "outcome": None}
            if type(selected) is int and 0 <= selected < len(forecasts):
                forecasts[selected] = entry
            else:
                forecasts.append(entry)
                data["_forecast_edit_index"] = len(forecasts) - 1
        elif index == 2:
            response = values["outcome"].strip().casefold()
            if response not in {"yes", "no", "?", ""}:
                raise ValueError("Outcome must be yes, no or ?")
            selected = values.get("forecast_index", len(data["forecasts"]) - 1)
            try:
                selected = int(selected)
            except (ValueError, TypeError):
                raise ValueError("Choose a saved forecast to resolve") from None
            if not 0 <= selected < len(data["forecasts"]):
                raise ValueError("Choose a saved forecast to resolve")
            data["forecasts"][selected]["outcome"] = {"yes": 1, "no": 0, "?": None, "": None}[response]
    elif method == "scenarios":
        if index == 0:
            data["question"] = name(values["question"], "Strategic question")
            data["drivers"] = distinct(lines(values["drivers"]), "driving forces")
        elif index == 1:
            axes = [
                {part: name(values[f"axis_{i}_{part}"], part) for part in ("name", "low", "high")} for i in range(2)
            ]
            if len({a["name"].casefold() for a in axes}) < 2 or any(a["low"] == a["high"] for a in axes):
                raise ValueError("Choose two distinct axes with distinct low/high poles")
            if data.get("scenarios") and data.get("axes") != axes:
                if mapping is None:
                    raise ScenarioMappingRequired(data["axes"], axes)
                checked_label_mapping(list(QUADRANTS), list(QUADRANTS), mapping)
                prior = data["scenarios"]
                data["scenarios"] = {
                    q: prior[QUADRANTS[source]]
                    for q, source in zip(QUADRANTS, mapping, strict=True)
                    if QUADRANTS[source] in prior
                }
                for strategy in data.get("strategies", []):
                    old_actions = strategy["actions"]
                    strategy["actions"] = {
                        q: old_actions[QUADRANTS[source]]
                        for q, source in zip(QUADRANTS, mapping, strict=True)
                        if QUADRANTS[source] in old_actions
                    }
            data["axes"] = axes
        elif 2 <= index <= 5:
            key = QUADRANTS[index - 2]
            data.setdefault("scenarios", {})[key] = {
                "name": name(values["name"], "Scenario"),
                "narrative": name(values["narrative"], "Narrative"),
                "implications": lines(values["implications"]),
                "indicators": lines(values["indicators"]),
            }
        elif index == 6:
            strategy = {
                "name": name(values["name"], "Strategy"),
                "actions": {key: name(values[f"action_{key}"], f"Action in {key}") for key in QUADRANTS},
            }
            strategies = data.setdefault("strategies", [])
            selected = int(values["edit_index"]) if "edit_index" in values else None
            if any(
                row["name"].casefold() == strategy["name"].casefold()
                for i, row in enumerate(strategies)
                if i != selected
            ):
                raise ValueError("Strategy names must be distinct")
            if selected is None:
                strategies.append(strategy)
            elif 0 <= selected < len(strategies):
                strategies[selected] = strategy
            else:
                raise ValueError("Choose a saved strategy")
    return data
