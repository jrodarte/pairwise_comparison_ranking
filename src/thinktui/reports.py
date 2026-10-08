"""Auditable local reports; no credentials or unapproved AI suggestions."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .core import METHODS, Session


def plain_result(result: dict) -> str:
    """Readable local calculation output for non-technical review screens."""
    lines: list[str] = []

    def show(value: object, depth: int = 0) -> None:
        indent = "  " * depth
        if isinstance(value, dict):
            for key, entry in value.items():
                label = key.replace("_", " ").capitalize()
                if isinstance(entry, (dict, list)):
                    lines.append(indent + label + ":")
                    show(entry, depth + 1)
                else:
                    lines.append(f"{indent}{label}: {entry}")
        elif isinstance(value, list):
            for index, entry in enumerate(value, 1):
                if isinstance(entry, (dict, list)):
                    lines.append(f"{indent}{index}.")
                    show(entry, depth + 1)
                else:
                    lines.append(f"{indent}{index}. {entry}")

    show(result)
    return "\n".join(lines)


def decision_brief(session: Session, source_title: str = "") -> str:
    method = METHODS[session.method_id]
    state = session.method_state
    try:
        result = method.calculate(state)
    except (ValueError, KeyError, TypeError):
        result = {"status": "Incomplete"}
    sections: list[tuple[str, str]] = [
        ("Decision", state.get("decision", session.title) if session.method_id == "journal" else session.title),
        ("Objective", session.objective),
        ("Context", "\n".join(filter(None, (session.problem_statement, session.context)))),
        ("Linked Source Analysis", source_title or state.get("source_session_id", "")),
    ]
    if session.method_id in {"matrix", "sensitivity"}:
        criteria = state.get("criteria", [])
        if criteria:
            sections.append(
                (
                    "Criteria",
                    "| Criterion | Weight | Direction |\n| --- | ---: | --- |\n"
                    + "\n".join(
                        f"| {row.get('name', '')} | {row.get('weight', '')} | {row.get('direction', 'benefit')} |"
                        for row in criteria
                    ),
                )
            )
        options = state.get("alternatives", [])
        if options:
            sections.append(
                (
                    "Alternatives and scores",
                    "| Option | "
                    + " | ".join(row.get("name", "") for row in criteria)
                    + " |\n| --- | "
                    + " | ".join("---:" for _ in criteria)
                    + " |\n"
                    + "\n".join(
                        "| " + str(row.get("name", "")) + " | " + " | ".join(map(str, row.get("scores", []))) + " |"
                        for row in options
                    ),
                )
            )
    else:
        inputs = {
            k: v
            for k, v in state.items()
            if k not in {"change_mind", "_guided_step"} and not k.startswith("workflow_") and k != "source_session_id"
        }
        if inputs:
            sections.append(("Method inputs (user-supplied)", plain_result(inputs)))
    sections += [
        ("Analysis (calculated locally)", plain_result(result)),
        ("Uncertainty", "Judgments and estimates are user-supplied; scores are relative."),
        ("Why", state.get("rationale", "") if session.method_id == "journal" else session.notes),
        ("Expected outcome", state.get("expected_outcome", "")),
        ("Actual outcome", state.get("actual_outcome", "")),
        ("Lessons learned", state.get("lessons", "")),
        ("What would change our mind?", state.get("change_mind", "")),
        ("Review date", state.get("review_date", "")),
    ]
    return (
        "# Decision Brief\n\n"
        + f"Method: {method.name}  |  Updated: {session.updated_at}\n\n"
        + "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections if body not in ("", None))
        + "\n"
    )


def export(session: Session, destination: Path, *, store=None) -> None:
    if destination.suffix.lower() not in {".md", ".json"}:
        raise ValueError("Use a .md or .json filename")
    if destination.suffix.lower() == ".md":
        source_title = ""
        source_id = session.method_state.get("source_session_id")
        if source_id and store is not None:
            try:
                source_title = store.load(source_id).title
            except KeyError:
                pass
        content = decision_brief(session, source_title)
    else:
        content = json.dumps(asdict(session), indent=2, ensure_ascii=False)
    # Compose first, then create exclusively: a repeated export never destroys an earlier report.
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(content)
