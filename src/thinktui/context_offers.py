"""Optional text-only handoffs from earlier analyses; never copy numerical judgments."""

from __future__ import annotations

from .core import Session
from .issue_tree import nodes_for


def offers(method_id: str, sessions: list[Session], current_id: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for session in sessions:  # newest first; only a previous finished analysis
        if session.id == current_id or not session.completed_at:
            continue
        state = session.method_state
        if method_id == "matrix" and session.method_id == "value_focused":
            for key, values in (
                ("alternatives", state.get("alternatives", [])),
                (
                    "criteria",
                    [row.get("measure", "") for row in state.get("objectives", []) if row.get("kind") == "fundamental"],
                ),
            ):
                result.setdefault(key, [])
                result[key].extend(v.strip() for v in values if isinstance(v, str) and v.strip())
        if method_id == "assumptions" and session.method_id == "issue_tree":
            nodes = nodes_for(state)
            parent_ids = {node.get("parent_id") for node in nodes}
            result.setdefault("statements", []).extend(
                node["label"].strip()
                for node in nodes
                if node["id"] not in parent_ids and node.get("label", "").strip().endswith("?")
            )
    return {key: list(dict.fromkeys(values)) for key, values in result.items() if values}
