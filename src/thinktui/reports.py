"""Auditable local reports; no credentials or unapproved AI suggestions."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .core import METHODS, Session


def decision_brief(session: Session) -> str:
    method = METHODS[session.method_id]
    try:
        result = method.calculate(session.method_state)
    except (ValueError, KeyError):
        result = {"status": "Incomplete"}
    sections = {
        "Decision": session.method_state.get("decision", session.title)
        if session.method_id == "journal"
        else session.title,
        "Objective": session.objective,
        "Linked Source Analysis": session.method_state.get("source_session_id", ""),
        "Context": session.problem_statement + "\n" + session.context,
        "Alternatives": (
            session.method_state.get("alternatives", "")
            if session.method_id == "journal"
            else json.dumps(session.method_state.get("alternatives", []), indent=2)
        ),
        "Criteria": json.dumps(session.method_state.get("criteria", []), indent=2),
        "Assumptions": json.dumps(
            session.assumptions + session.method_state.get("entries", [])
            if session.method_id == "assumptions"
            else session.assumptions,
            indent=2,
        ),
        "Evidence": json.dumps(session.evidence, indent=2),
        "Method Inputs (user-supplied)": json.dumps(session.method_state, indent=2, ensure_ascii=False),
        "Analysis": json.dumps(result, indent=2),
        "Risks": (
            session.method_state.get("risks", "")
            if session.method_id == "journal"
            else json.dumps(
                session.method_state.get("entries", []) if session.method_id == "premortem" else [],
                indent=2,
            )
        ),
        "Uncertainty": "Judgments and estimates are user-supplied; scores are relative.",
        "Chosen Option": session.method_state.get("chosen", "") if session.method_id == "journal" else "",
        "Expected Outcome": session.method_state.get("expected_outcome", "") if session.method_id == "journal" else "",
        "Confidence": str(session.method_state.get("confidence", "")) if session.method_id == "journal" else "",
        "Why": session.method_state.get("rationale", "") if session.method_id == "journal" else session.notes,
        "Actual Outcome": session.method_state.get("actual_outcome", "") if session.method_id == "journal" else "",
        "Lessons Learned": session.method_state.get("lessons", "") if session.method_id == "journal" else "",
        "What Would Change Our Mind?": session.method_state.get("change_mind", ""),
        "Next Actions": "\n".join(d.get("action", "") for d in session.decisions),
        "Review Date": session.method_state.get("review_date", ""),
    }
    return (
        "# Decision Brief\n\n"
        + f"Method: {method.name}  |  Updated: {session.updated_at}\n\n"
        + "\n\n".join(f"## {heading}\n\n{body or '—'}" for heading, body in sections.items())
        + "\n"
    )


def export(session: Session, destination: Path) -> None:
    if destination.suffix.lower() == ".md":
        destination.write_text(decision_brief(session), encoding="utf-8")
    elif destination.suffix.lower() == ".json":
        destination.write_text(json.dumps(asdict(session), indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        raise ValueError("Use a .md or .json filename")
