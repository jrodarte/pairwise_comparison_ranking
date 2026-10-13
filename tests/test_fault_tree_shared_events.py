"""Shared basic event leaves are one Bernoulli variable, not independent samples."""

from itertools import product

import pytest

from thinktui import methods as _methods  # noqa: F401 - register the full method catalog
from thinktui.core import METHODS


def leaf(name, p=0.5):
    return {"type": "event", "name": name, "probability": p}


def gate(kind, *children):
    return {"type": kind, "independent": True, "children": list(children)}


def independent_reference(tree, probabilities):
    """Enumerate truth assignments to distinct *names* for small reference cases."""
    names = list(probabilities)

    def active(node, outcome):
        if node["type"] == "event":
            return outcome[node["name"]]
        results = [active(child, outcome) for child in node["children"]]
        return all(results) if node["type"] == "AND" else any(results)

    total = 0.0
    for assignment in product((False, True), repeat=len(names)):
        outcome = dict(zip(names, assignment, strict=True))
        weight = 1.0
        for name in names:
            p = probabilities[name]
            weight *= p if outcome[name] else 1 - p
        total += weight * active(tree, outcome)
    return total


def test_shared_basic_event_is_not_counted_independently():
    tree = gate("OR", gate("AND", leaf("A"), leaf("B")), gate("AND", leaf("A"), leaf("C")))
    result = METHODS["fault_tree"].calculate({"top_event": "Outage", "tree": tree})
    assert result["result"]["probability"] == pytest.approx(0.375)
    assert result["result"]["probability"] == independent_reference(tree, {"A": 0.5, "B": 0.5, "C": 0.5})
    assert result["result"]["children"][0]["probability"] == pytest.approx(0.25)
    assert METHODS["fault_tree"].calculate({"top_event": "Outage", "tree": gate("OR", leaf("A"), leaf("A"))})["result"][
        "probability"
    ] == pytest.approx(0.5)


@pytest.mark.parametrize(
    "tree, probabilities",
    [
        (gate("AND", leaf("A", 0.3), leaf("B", 0.4)), {"A": 0.3, "B": 0.4}),
        (gate("OR", leaf("A", 0.3), leaf("B", 0.4)), {"A": 0.3, "B": 0.4}),
        (
            gate("AND", gate("OR", leaf("A", 0.2), leaf("B", 0.6)), gate("OR", leaf("B", 0.6), leaf("C", 0.7))),
            {"A": 0.2, "B": 0.6, "C": 0.7},
        ),
    ],
)
def test_fault_tree_matches_exhaustive_reference(tree, probabilities):
    result = METHODS["fault_tree"].calculate({"top_event": "Failure", "tree": tree})
    assert result["result"]["probability"] == pytest.approx(independent_reference(tree, probabilities))


def test_conflicting_probabilities_for_one_event_are_rejected():
    state = {"top_event": "Failure", "tree": gate("OR", leaf("A", 0.2), leaf("A", 0.5))}
    with pytest.raises(ValueError, match="conflicting probabilities"):
        METHODS["fault_tree"].calculate(state)
    assert METHODS["fault_tree"].validate(state)
