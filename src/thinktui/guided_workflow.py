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
                "Alternatives · diverge",
                "List at least two distinct options, one per line. Include 'do nothing' if relevant.",
                (Field("alternatives", "Options", "\n".join(a["name"] for a in state.get("alternatives", [])), True),),
            )
        if index == 1:
            criteria = "\n".join(
                f"{c['name']} | {c.get('weight') or ''} | {c.get('direction', 'benefit')}"
                for c in state.get("criteria", [])
            )
            return Step(
                "Criteria & weights",
                "One per line: Name | nonnegative weight | benefit or cost. Weights are normalized at calculation.",
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


def reachable_index(method: str, state: dict) -> int:
    """A stale/malformed saved cursor cannot bypass missing prior steps."""
    if method == "matrix":
        if len(state.get("alternatives", [])) < 2:
            return 0
        if not state.get("criteria"):
            return 1
        if any(len(row.get("scores", [])) != len(state["criteria"]) for row in state["alternatives"]):
            return 2
        return 3
    if method == "ahp":
        criteria = state.get("criteria", [])
        if not criteria:
            return 0
        if len(state.get("alternatives", [])) < 2:
            return 1
        if not state.get("criteria_matrix"):
            return 2
        for index, criterion in enumerate(criteria):
            if criterion not in state.get("alternative_matrices", {}):
                return 3 + index
        return 3 + len(criteria)
    if method == "ach":
        return 0 if len(state.get("hypotheses", [])) < 2 else 1 if not state.get("evidence") else 2
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


def advance(method: str, state: dict, index: int, values: dict[str, str]) -> dict:
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
            before = [row["name"] for row in data.get("alternatives", [])]
            if before and before != names and data.get("criteria"):
                raise ValueError("Scores exist; use Advanced JSON to revise alternatives without losing judgments")
            if before != names:
                data["alternatives"] = [{"name": n, "scores": []} for n in names]
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
            previous = [(c["name"], c.get("direction")) for c in data.get("criteria", [])]
            if (
                previous
                and previous != [(c["name"], c["direction"]) for c in rows]
                and any(alt.get("scores") for alt in data.get("alternatives", []))
            ):
                raise ValueError("Scores exist; use Advanced JSON to revise criteria without losing judgments")
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
                and (data.get("criteria_matrix") or data.get("alternative_matrices"))
            ):
                raise ValueError("Judgments exist; use Advanced JSON to revise labels without losing comparisons")
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
                raise ValueError("Evidence is rated; use Advanced JSON to revise hypotheses without losing ratings")
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
            data.setdefault("evidence", []).append(entry)
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
            draft = data.pop("_draft")
            data.setdefault("forecasts", []).append({**draft, "probability": percent / 100, "outcome": None})
        elif index == 2:
            response = values["outcome"].strip().casefold()
            if response not in {"yes", "no", "?", ""}:
                raise ValueError("Outcome must be yes, no or ?")
            data["forecasts"][-1]["outcome"] = {"yes": 1, "no": 0, "?": None, "": None}[response]
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
                raise ValueError("Narratives exist; use Advanced JSON to revise axes without losing quadrant meaning")
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
            if any(row["name"].casefold() == strategy["name"].casefold() for row in data.get("strategies", [])):
                raise ValueError("Strategy names must be distinct")
            data.setdefault("strategies", []).append(strategy)
    return data
