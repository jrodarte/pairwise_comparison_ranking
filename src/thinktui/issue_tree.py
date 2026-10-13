"""Persistent parent-linked issue tree and deterministic traversal helpers."""

from __future__ import annotations

from uuid import uuid4


def nodes_for(state: dict) -> list[dict]:
    """Read existing pre-tree flat sessions as root nodes until their next edit."""
    if "nodes" in state:
        return state["nodes"]
    entries = state.get("entries", [])
    if not isinstance(entries, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("statement"), str) for row in entries
    ):
        raise ValueError("Issue-tree entries must have text statements")
    return [
        {"id": f"legacy-{i}", "parent_id": None, "label": row["statement"], "collapsed": False}
        for i, row in enumerate(entries)
    ]


def _validated(nodes: list[dict]) -> dict[str, dict]:
    if not isinstance(nodes, list):
        raise ValueError("Issue-tree nodes must be a list")
    by_id = {}
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not node["id"]
            or not isinstance(node.get("label"), str)
        ):
            raise ValueError("Issue-tree nodes need text IDs and labels")
        if node["id"] in by_id:
            raise ValueError("Duplicate issue-tree node ID")
        by_id[node["id"]] = node
    for node in nodes:
        parent = node.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or parent not in by_id):
            raise ValueError("Issue-tree node has a missing parent")
    finished = set()
    for node in nodes:
        chain = set()
        parent = node["id"]
        while parent is not None and parent not in finished:
            if parent in chain:
                raise ValueError("Issue-tree cycle detected")
            chain.add(parent)
            parent = by_id[parent].get("parent_id")
        finished.update(chain)
    return by_id


def nested(state: dict) -> list[dict]:
    """Return a complete hierarchy, including collapsed descendants, for export."""
    nodes = nodes_for(state)
    _validated(nodes)

    roots: list[dict] = []
    children = {node["id"]: [] for node in nodes}
    for node in nodes:
        branch = {"id": node["id"], "label": node["label"], "children": children[node["id"]]}
        (roots if node.get("parent_id") is None else children[node["parent_id"]]).append(branch)
    return roots


def visible(state: dict) -> list[tuple[dict, int]]:
    nodes = nodes_for(state)
    _validated(nodes)
    rows: list[tuple[dict, int]] = []

    children: dict[str | None, list[dict]] = {}
    for node in nodes:
        children.setdefault(node.get("parent_id"), []).append(node)
    pending = [(node, 0) for node in reversed(children.get(None, []))]
    while pending:
        node, depth = pending.pop()
        rows.append((node, depth))
        if not node.get("collapsed"):
            pending.extend((child, depth + 1) for child in reversed(children.get(node["id"], [])))
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
