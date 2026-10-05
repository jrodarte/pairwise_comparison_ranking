"""Regularized Bradley–Terry ranking and descriptive match statistics.

For each match i vs j, maximize y*log(sigmoid(theta_i-theta_j)) +
(1-y)*log(sigmoid(theta_j-theta_i)), where y is 1, 0 or 0.5.
An L2 penalty of 0.15/2 * sum(theta_i**2) ensures finite estimates for
undefeated, winless and disconnected items. Coordinate Newton updates use
bounded logistic probabilities and are centered each sweep. Display scores
are 100*sigmoid(theta), not percentages or probabilities of winning a match.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .models import Comparison, Item, Outcome


@dataclass
class RankingResult:
    """Relative priority estimate plus transparent observed match statistics."""

    item: Item
    rank: int
    score: float
    wins: int
    losses: int
    ties: int
    points: float

    @property
    def total(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_percentage(self) -> float:
        """Fractional win rate: ties count as half a win."""
        return 100 * self.points / self.total if self.total else 0.0

    @property
    def points_percentage(self) -> float:
        return self.win_percentage


class RankingStrategy(Protocol):
    """Pluggable estimator interface."""

    def calculate(
        self, items: Sequence[Item], comparisons: Sequence[Comparison]
    ) -> list[RankingResult]:
        """Return results in descending priority order."""
        ...


def sigmoid(value: float) -> float:
    """Overflow-safe logistic function."""
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1 + exp_value)


class BradleyTerry:
    """L2-regularized fractional-outcome Bradley–Terry maximum likelihood."""

    def __init__(self, regularization: float = 0.15) -> None:
        if regularization <= 0:
            raise ValueError("Regularization must be positive")
        self.regularization = regularization

    def calculate(
        self, items: Sequence[Item], comparisons: Sequence[Comparison]
    ) -> list[RankingResult]:
        """Estimate strengths with cyclic coordinate Newton steps; ties give 0.5 each."""
        indices = {item.id: index for index, item in enumerate(items)}
        if len(indices) != len(items):
            raise ValueError("Duplicate item IDs")
        wins = [0] * len(items)
        losses = [0] * len(items)
        ties = [0] * len(items)
        matches: list[tuple[int, int, float]] = []
        seen: set[str] = set()
        for comparison in comparisons:
            if comparison.key in seen:
                raise ValueError("Duplicate pair")
            seen.add(comparison.key)
            a, b = indices[comparison.item_a_id], indices[comparison.item_b_id]
            if comparison.outcome == Outcome.A_WINS:
                wins[a] += 1
                losses[b] += 1
                y = 1.0
            elif comparison.outcome == Outcome.B_WINS:
                wins[b] += 1
                losses[a] += 1
                y = 0.0
            else:
                ties[a] += 1
                ties[b] += 1
                y = 0.5
            matches.append((a, b, y))
        by_item: list[list[tuple[int, float]]] = [[] for _ in items]
        for a, b, y in matches:
            by_item[a].append((b, y))
            by_item[b].append((a, 1 - y))
        strengths = [0.0] * len(items)
        for _ in range(2000):
            largest = 0.0
            for i, opponents in enumerate(by_item):
                gradient = -self.regularization * strengths[i]
                curvature = self.regularization
                for j, result in opponents:
                    p = sigmoid(strengths[i] - strengths[j])
                    gradient += result - p
                    curvature += p * (1 - p)
                step = max(-2.0, min(2.0, gradient / curvature))
                strengths[i] += step
                largest = max(largest, abs(step))
            if strengths:
                mean = sum(strengths) / len(strengths)
                strengths = [value - mean for value in strengths]
            if largest < 1e-10:
                break
        ordered = sorted(range(len(items)), key=lambda i: (-strengths[i], items[i].name.casefold()))
        return [
            RankingResult(
                item=items[i],
                rank=rank,
                score=100 * sigmoid(strengths[i]),
                wins=wins[i],
                losses=losses[i],
                ties=ties[i],
                points=wins[i] + ties[i] / 2,
            )
            for rank, i in enumerate(ordered, 1)
        ]


def matchup_groups(
    item: Item, items: Sequence[Item], comparisons: Sequence[Comparison]
) -> dict[str, list[str]]:
    """Group opponents into wins/losses/ties for an item detail view."""
    names = {candidate.id: candidate.name for candidate in items}
    groups: dict[str, list[str]] = {"Beat": [], "Lost to": [], "Tied": []}
    for comparison in comparisons:
        if item.id not in (comparison.item_a_id, comparison.item_b_id):
            continue
        other = comparison.item_b_id if item.id == comparison.item_a_id else comparison.item_a_id
        if comparison.outcome == Outcome.TIE:
            group = "Tied"
        elif (item.id == comparison.item_a_id) == (comparison.outcome == Outcome.A_WINS):
            group = "Beat"
        else:
            group = "Lost to"
        groups[group].append(names[other])
    return groups
