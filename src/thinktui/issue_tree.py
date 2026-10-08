"""Persistent parent-linked issue tree and deterministic traversal helpers."""

from __future__ import annotations

from uuid import uuid4


def nodes_for(state: dict) -> list[dict]:
    """Read existing pre-tree flat sessions as root nodes until their next edit."""
    if "nodes" in state:
        return state["nodes"]
    return [
        {"id": f"legacy-{i}", "parent_id": None, "label": row["statement"], "collapsed": False}
        for i, row in enumerate(state.get("entries", []))
    ]


def _validated(nodes: list[dict]) -> dict[str, dict]:
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("Duplicate issue-tree node ID")
    for node in nodes:
        parent = node["parent_id"]
        if parent is not None and parent not in by_id:
            raise ValueError("Issue-tree node has a missing parent")
        seen = {node["id"]}
        while parent is not None:
            if parent in seen:
                raise ValueError("Issue-tree cycle detected")
            seen.add(parent)
            parent = by_id[parent]["parent_id"]
    return by_id


def nested(state: dict) -> list[dict]:
    """Return a complete hierarchy, including collapsed descendants, for export."""
    nodes = nodes_for(state)
    _validated(nodes)

    def children(parent_id: str | None) -> list[dict]:
        return [
            {"id": node["id"], "label": node["label"], "children": children(node["id"])}
            for node in nodes
            if node["parent_id"] == parent_id
        ]

    return children(None)


def visible(state: dict) -> list[tuple[dict, int]]:
    nodes = nodes_for(state)
    _validated(nodes)
    rows: list[tuple[dict, int]] = []

    def visit(parent_id: str | None, depth: int) -> None:
        for node in nodes:
            if node["parent_id"] == parent_id:
                rows.append((node, depth))
                if not node.get("collapsed"):
                    visit(node["id"], depth + 1)

    visit(None, 0)
    return rows


def writable_nodes(state: dict) -> list[dict]:
    """Migrate old flat entries on first edit without dropping their labels."""
    if "nodes" not in state:
        nodes = nodes_for(state)
        _validated(nodes)
        state["nodes"] = nodes
        state.pop("entries", None)
    return state["nodes"]


def add(state: dict, label: str, parent_id: str | None = None, after_id: str | None = None) -> str:
    label = label.strip()
    if not label:
        raise ValueError("Enter a branch name")
    nodes = writable_nodes(state)
    by_id = _validated(nodes)
    if parent_id is not None and parent_id not in by_id:
        raise ValueError("Parent not found")
    if after_id is not None and (after_id not in by_id or by_id[after_id]["parent_id"] != parent_id):
        raise ValueError("Sibling not found")
    node_id = str(uuid4())
    node = {"id": node_id, "parent_id": parent_id, "label": label, "collapsed": False}
    if parent_id is None and after_id is None:
        nodes.append(node)
    else:
        # Insert after the parent's existing subtree or the selected sibling's subtree.
        anchor = after_id or parent_id
        index = nodes.index(by_id[anchor]) + 1
        descendants = {anchor}
        while index < len(nodes) and nodes[index]["parent_id"] in descendants:
            descendants.add(nodes[index]["id"])
            index += 1
        nodes.insert(index, node)
    return node_id


def edit(state: dict, node_id: str, label: str) -> None:
    label = label.strip()
    if not label:
        raise ValueError("Enter a branch name")
    nodes = writable_nodes(state)
    _validated(nodes)[node_id]["label"] = label


def delete(state: dict, node_id: str) -> None:
    nodes = writable_nodes(state)
    if node_id not in _validated(nodes):
        raise ValueError("Node not found")
    removed = {node_id}
    changed = True
    while changed:
        before = len(removed)
        removed.update(node["id"] for node in nodes if node["parent_id"] in removed)
        changed = len(removed) != before
    state["nodes"] = [node for node in nodes if node["id"] not in removed]


def toggle(state: dict, node_id: str) -> None:
    nodes = writable_nodes(state)
    node = _validated(nodes)[node_id]
    node["collapsed"] = not node.get("collapsed", False)
