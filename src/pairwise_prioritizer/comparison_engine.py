"""Complete round-robin pair scheduling and reversible decisions."""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence
from itertools import combinations

from .models import Change, Comparison, Item, Outcome, Project, now, pair_key


def validate_names(names: Sequence[str]) -> list[str]:
    """Normalize names and reject empty or case-insensitive duplicates."""
    cleaned = [name.strip() for name in names]
    if any(not name for name in cleaned):
        raise ValueError("Remove blank item names before starting")
    if len(cleaned) < 2:
        raise ValueError("Add at least two items")
    if len({name.casefold() for name in cleaned}) != len(cleaned):
        raise ValueError("Duplicate names detected (ignoring case); remove duplicates first")
    return cleaned


def create_project(
    name: str, items: Sequence[Item], description: str = "", seed: int | None = None
) -> Project:
    """Create a complete, reproducibly shuffled schedule with independently flipped sides."""
    if not name.strip():
        raise ValueError("Enter a project name")
    validate_names([item.name for item in items])
    if len({item.id for item in items}) != len(items):
        raise ValueError("Duplicate item IDs")
    seed = secrets.randbits(64) if seed is None else seed
    rng = random.Random(seed)
    order = list(combinations((item.id for item in items), 2))
    rng.shuffle(order)
    order = [(b, a) if rng.getrandbits(1) else (a, b) for a, b in order]
    return Project(
        name=name.strip(),
        description=description.strip(),
        items=list(items),
        seed=seed,
        order=order,
    )


def next_pair(project: Project) -> tuple[str, str] | None:
    """Return the next outstanding pair; deferred pairs appear after normal pairs."""
    indexed = {pair_key(*pair): pair for pair in project.order}
    for key in project.pending:
        if key not in project.comparisons:
            return indexed[key]
    for pair in project.order:
        key = pair_key(*pair)
        if key not in project.comparisons and key not in project.skipped:
            return pair
    for key in project.skipped:
        if key not in project.comparisons:
            return indexed[key]
    return None


def decide(project: Project, pair: tuple[str, str], outcome: Outcome) -> None:
    """Record a decision or revision, retaining its previous state for undo."""
    key = pair_key(*pair)
    if key not in {pair_key(*candidate) for candidate in project.order}:
        raise ValueError("Pair does not belong to project")
    previous = project.comparisons.get(key)
    comparison = Comparison(pair[0], pair[1], outcome, len(project.audit) + 1)
    project.comparisons[key] = comparison
    project.skipped = [value for value in project.skipped if value != key]
    project.pending = [value for value in project.pending if value != key]
    project.undo_stack.append(
        Change(key, previous.to_dict() if previous else None, comparison.to_dict())
    )
    project.audit.append(
        {
            "action": "revise" if previous else "decide",
            "at": now(),
            "comparison": comparison.to_dict(),
            "previous": previous.to_dict() if previous else None,
        }
    )
    project.modified_at = now()


def skip(project: Project, pair: tuple[str, str]) -> None:
    """Defer a pair until the rest of the schedule has been processed."""
    key = pair_key(*pair)
    if key in project.comparisons or key not in {pair_key(*p) for p in project.order}:
        raise ValueError("Cannot skip this pair")
    project.pending = [value for value in project.pending if value != key]
    project.skipped = [value for value in project.skipped if value != key] + [key]
    project.audit.append({"action": "skip", "pair": key, "at": now()})
    project.modified_at = now()


def undo(project: Project) -> Comparison | None:
    """Reverse the most recent decision; return restored decision, if any."""
    if not project.undo_stack:
        raise ValueError("No previous decision to undo")
    change = project.undo_stack.pop()
    if change.before is None:
        project.comparisons.pop(change.key)
        project.pending = [change.key] + [key for key in project.pending if key != change.key]
        restored = None
    else:
        restored = Comparison.from_dict(change.before)
        project.comparisons[change.key] = restored
    project.audit.append(
        {"action": "undo", "pair": change.key, "reversed": change.after, "at": now()}
    )
    project.modified_at = now()
    return restored


def duplicate(project: Project, name: str) -> Project:
    """Start a fresh schedule with copies of the items but no previous decisions."""
    items = [
        Item(name=item.name, description=item.description, metadata=item.metadata.copy())
        for item in project.items
    ]
    return create_project(name, items, project.description)
