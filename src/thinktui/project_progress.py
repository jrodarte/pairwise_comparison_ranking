"""A lightweight project-level planning checklist, not a claim of completeness."""

from __future__ import annotations

from .core import Session

STEPS = (
    ("Why", ("objectives", "value_focused"), "objectives"),
    ("Who", ("issue_tree", "scenarios"), "issue_tree"),
    ("What", ("value_focused", "matrix"), "value_focused"),
    ("Where", ("issue_tree", "causal_loop"), "issue_tree"),
    ("When", ("backcasting", "forecasting"), "backcasting"),
    ("How", ("premortem", "fmea"), "premortem"),
)


def checklist(sessions: list[Session]) -> tuple[list[str], str | None]:
    lines = []
    next_method = None
    for question, methods, recommendation in STEPS:
        finished = [s for s in sessions if s.method_id in methods and s.completed_at]
        drafts = [s for s in sessions if s.method_id in methods and not s.completed_at]
        status = "✓ Reviewed" if finished else "◌ In progress" if drafts else "○ Not started"
        lines.append(f"{question}: {status} · {', '.join(methods).replace('_', ' ')}")
        if next_method is None and not finished:
            next_method = drafts[0].method_id if drafts else recommendation
    return lines, next_method
