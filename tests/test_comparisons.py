import itertools

import pytest

from pairwise_prioritizer.comparison_engine import (
    create_project,
    decide,
    duplicate,
    next_pair,
    skip,
    undo,
    validate_names,
)
from pairwise_prioritizer.models import Outcome, pair_key


def test_complete_schedule(project):
    expected = {pair_key(a.id, b.id) for a, b in itertools.combinations(project.items, 2)}
    actual = [pair_key(*pair) for pair in project.order]
    assert len(actual) == 6
    assert len(set(actual)) == 6
    assert set(actual) == expected
    assert create_project("Test", project.items, seed=17).order == project.order
    assert create_project("Test", project.items, seed=18).order != project.order


def test_skip_undo_and_complete(project):
    first = next_pair(project)
    skip(project, first)
    assert next_pair(project) != first
    second = next_pair(project)
    decide(project, second, Outcome.TIE)
    assert project.remaining == 5
    undo(project)
    assert project.remaining == 6
    assert next_pair(project) == second
    decide(project, second, Outcome.A_WINS)
    for pair in project.order:
        if pair_key(*pair) not in project.comparisons:
            decide(project, pair, Outcome.B_WINS)
    assert project.status == "Completed"
    assert next_pair(project) is None
    assert len(project.comparisons) == 6
    assert any(event["action"] == "undo" for event in project.audit)


def test_revision_undo(project):
    pair = next_pair(project)
    decide(project, pair, Outcome.A_WINS)
    decide(project, pair, Outcome.B_WINS)
    assert undo(project).outcome == Outcome.A_WINS
    assert project.comparisons[pair_key(*pair)].outcome == Outcome.A_WINS
    undo(project)
    assert next_pair(project) == pair
    assert not project.comparisons


def test_validation_and_duplicate(project):
    with pytest.raises(ValueError, match="Duplicate"):
        validate_names([" Alpha ", "alpha"])
    with pytest.raises(ValueError, match="blank"):
        validate_names(["A", " "])
    with pytest.raises(ValueError, match="two"):
        validate_names(["Only one"])
    with pytest.raises(ValueError):
        pair_key(project.items[0].id, project.items[0].id)
    copy = duplicate(project, "Next quarter")
    assert [i.name for i in copy.items] == [i.name for i in project.items]
    assert {i.id for i in copy.items}.isdisjoint({i.id for i in project.items})
    assert not copy.comparisons
