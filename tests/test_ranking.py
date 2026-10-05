import math
from itertools import combinations

from pairwise_prioritizer.models import Comparison, Item, Outcome
from pairwise_prioritizer.ranking import BradleyTerry, matchup_groups


def test_dominance_and_statistics():
    items = [Item(name=name) for name in "ABCD"]
    matches = [
        Comparison(a.id, b.id, Outcome.A_WINS, sequence=i)
        for i, (a, b) in enumerate(combinations(items, 2), 1)
    ]
    results = BradleyTerry().calculate(items, matches)
    assert [r.item.name for r in results] == list("ABCD")
    assert [(r.wins, r.losses, r.ties) for r in results] == [
        (3, 0, 0),
        (2, 1, 0),
        (1, 2, 0),
        (0, 3, 0),
    ]
    assert all(0 < row.score < 100 for row in results)
    assert matchup_groups(items[0], items, matches)["Beat"] == list("BCD")


def test_ties_and_cycle_are_finite():
    items = [Item(name=name) for name in "ABC"]
    a, b, c = items
    cycle = [
        Comparison(a.id, b.id, Outcome.A_WINS, 1),
        Comparison(b.id, c.id, Outcome.A_WINS, 2),
        Comparison(c.id, a.id, Outcome.A_WINS, 3),
    ]
    results = BradleyTerry().calculate(items, cycle)
    assert all(math.isfinite(row.score) for row in results)
    assert all(abs(row.score - 50) < 1e-6 for row in results)
    ties = [Comparison(a.id, b.id, Outcome.TIE, 1)]
    rows = BradleyTerry().calculate(items, ties)
    assert rows[0].score == 50
    tied = next(row for row in rows if row.item.id == a.id)
    assert (tied.ties, tied.points, tied.win_percentage, tied.total) == (1, 0.5, 50, 1)


def test_unplayed_and_perfect_separation():
    items = [Item(name=str(n)) for n in range(30)]
    matches = [
        Comparison(items[0].id, item.id, Outcome.A_WINS, i) for i, item in enumerate(items[1:], 1)
    ]
    rows = BradleyTerry().calculate(items, matches)
    assert rows[0].item.id == items[0].id
    assert all(math.isfinite(row.score) for row in rows)
    assert all(row.score == 50 for row in BradleyTerry().calculate(items, []))
