"""Indicators, strategy robustness and explicit system models."""

from __future__ import annotations

from .advanced_decisions import StructuredMethod, name, number
from .core import register


class Signposts(StructuredMethod):
    id = "signposts"
    name = "Indicators & Signposts"
    category = "Strategy"
    description = "Track measurable signals and whether user-defined action thresholds have been crossed."
    example = {
        "indicators": [
            {
                "name": "API adoption",
                "scenario": "High growth",
                "unit": "%",
                "direction": "above",
                "threshold": 70,
                "current": 75,
                "action": "Expand capacity",
            }
        ]
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("indicators", [])
        if not rows:
            raise ValueError("Add indicators")
        results = []
        for row in rows:
            label = name(row["name"], "Indicator")
            name(row["scenario"], "Scenario")
            name(row["action"], "Action")
            direction = row["direction"]
            if direction not in {"above", "below"}:
                raise ValueError("Direction must be above or below")
            threshold = number(row["threshold"], "Threshold")
            current = None if row.get("current") is None else number(row["current"], "Current reading")
            triggered = (
                None if current is None else current >= threshold if direction == "above" else current <= threshold
            )
            results.append(
                {
                    "name": label,
                    "scenario": row["scenario"],
                    "unit": row.get("unit", ""),
                    "threshold": threshold,
                    "current": current,
                    "triggered": triggered,
                    "action": row["action"],
                }
            )
        return {"indicators": results, "note": "A threshold crossing is a prompt to investigate, not a prediction."}


class StressTest(StructuredMethod):
    id = "strategy_stress"
    name = "Strategy Stress Test"
    category = "Strategy"
    description = "Expose worst-case user-scored strategy performance across scenarios."
    example = {
        "scenarios": ["Slow", "Fast"],
        "strategies": [
            {"name": "Pilot", "scores": {"Slow": 8, "Fast": 7}},
            {"name": "Scale now", "scores": {"Slow": 2, "Fast": 10}},
        ],
    }

    def calculate(self, state: dict) -> dict:
        scenarios = [name(v, "Scenario") for v in state.get("scenarios", [])]
        if len(scenarios) < 2 or len(set(scenarios)) != len(scenarios):
            raise ValueError("Enter at least two distinct scenarios")
        strategies = state.get("strategies", [])
        if len(strategies) < 2:
            raise ValueError("Compare at least two strategies")
        results = []
        for row in strategies:
            label = name(row["name"], "Strategy")
            if set(row["scores"]) != set(scenarios):
                raise ValueError("Every strategy needs a score for every scenario")
            scores = {key: number(value, "Strategy score", 0) for key, value in row["scores"].items()}
            if any(v > 10 for v in scores.values()):
                raise ValueError("Scores must use a 0–10 scale")
            results.append(
                {"name": label, "scores": scores, "worst_case": min(scores.values()), "best_case": max(scores.values())}
            )
        if len({r["name"] for r in results}) != len(results):
            raise ValueError("Strategy names must be distinct")
        return {
            "strategies": sorted(results, key=lambda r: (-r["worst_case"], r["name"])),
            "note": "Ranked by worst case, not a probability-weighted score; scores are user judgments.",
        }


class CausalLoop(StructuredMethod):
    id = "causal_loop"
    name = "Causal Loop Analysis"
    category = "Systems"
    description = "Find reinforcing/balancing cycles in signed causal links, without simulating dynamics."
    example = {
        "variables": ["Adoption", "Investment", "Capacity"],
        "links": [
            {"from": "Adoption", "to": "Investment", "polarity": 1},
            {"from": "Investment", "to": "Capacity", "polarity": 1},
            {"from": "Capacity", "to": "Adoption", "polarity": 1},
        ],
    }

    def calculate(self, state: dict) -> dict:
        variables = [name(v, "Variable") for v in state.get("variables", [])]
        if not 2 <= len(variables) <= 50 or len(set(variables)) != len(variables):
            raise ValueError("Enter 2–50 distinct variables")
        links = state.get("links", [])
        if not links or len(links) > 300:
            raise ValueError("Enter 1–300 causal links")
        graph: dict[str, list[tuple[str, int]]] = {v: [] for v in variables}
        for row in links:
            source, target = row["from"], row["to"]
            if source not in graph or target not in graph or source == target:
                raise ValueError("Links must connect two distinct listed variables")
            if type(row["polarity"]) is not int or row["polarity"] not in (-1, 1):
                raise ValueError("Polarity must be +1 or -1")
            if any(other == target for other, _ in graph[source]):
                raise ValueError("Duplicate signed link")
            graph[source].append((target, row["polarity"]))
        cycles = []
        visits = 0
        budget = 100_000  # deterministic work cap; avoid blocking Textual on dense graphs
        truncated = False
        for start in sorted(variables):
            if truncated:
                break

            def walk(node: str, path: list[str], sign: int, origin: str = start) -> None:
                nonlocal visits, truncated
                if truncated or len(path) > 12:
                    return
                for target, polarity in graph[node]:
                    visits += 1
                    if visits > budget or len(cycles) >= 100:
                        truncated = True
                        return
                    if target == origin and len(path) >= 2:
                        cycles.append(
                            {"path": [*path, origin], "type": "reinforcing" if sign * polarity > 0 else "balancing"}
                        )
                    elif target > origin and target not in path:
                        walk(target, [*path, target], sign * polarity)
                    if truncated:
                        return

            walk(start, [start], 1)
        return {
            "loops": cycles,
            "truncated": truncated,
            "variables": variables,
            "note": "Polarity is qualitative; loops do not predict stock trajectories. Max 100 loops/12 links reported.",
        }


class Bottleneck(StructuredMethod):
    id = "bottleneck"
    name = "Bottleneck Analysis"
    category = "Systems"
    description = "Find the minimum rated stage capacity and the effect of a proposed capacity change."
    example = {
        "unit": "jobs/day",
        "stages": [
            {"name": "Intake", "capacity": 20},
            {"name": "Review", "capacity": 10},
            {"name": "Ship", "capacity": 16},
        ],
        "proposal": {"stage": "Review", "new_capacity": 18},
    }

    def calculate(self, state: dict) -> dict:
        stages = state.get("stages", [])
        if len(stages) < 2:
            raise ValueError("Enter at least two process stages")
        capacities = {name(row["name"], "Stage"): number(row["capacity"], "Capacity", 0) for row in stages}
        if len(capacities) != len(stages) or any(v == 0 for v in capacities.values()):
            raise ValueError("Stage names must be unique and capacities positive")
        current = min(capacities.values())
        proposal = state.get("proposal")
        after = None
        if proposal:
            if proposal["stage"] not in capacities:
                raise ValueError("Proposal must name a listed stage")
            new_capacity = number(proposal["new_capacity"], "New capacity", 0)
            if new_capacity == 0:
                raise ValueError("Proposed capacity must be positive")
            revised = {**capacities, proposal["stage"]: new_capacity}
            after = min(revised.values())
        return {
            "capacity": current,
            "bottlenecks": [key for key, v in capacities.items() if v == current],
            "proposed_capacity": after,
            "unit": state.get("unit", "user-defined"),
            "note": "Serial, steady-state process model; ignores variability, WIP and parallel routing.",
        }


class StockFlow(StructuredMethod):
    id = "stock_flow"
    name = "Stock-and-Flow Model"
    category = "Systems"
    description = "One deterministic step of a constant-rate conceptual stock/flow model."
    example = {
        "stocks": [{"name": "Backlog", "initial": 20}, {"name": "Done", "initial": 0}],
        "flows": [
            {"name": "Completion", "from": "Backlog", "to": "Done", "rate": 3},
            {"name": "New work", "from": None, "to": "Backlog", "rate": 2},
        ],
        "dt": 1,
        "unit": "items",
    }

    def calculate(self, state: dict) -> dict:
        stocks = state.get("stocks", [])
        if not stocks:
            raise ValueError("Enter stocks")
        levels = {name(row["name"], "Stock"): number(row["initial"], "Initial level", 0) for row in stocks}
        if len(levels) != len(stocks):
            raise ValueError("Stock names must be distinct")
        dt = number(state.get("dt", 1), "Time step", 0)
        if dt == 0:
            raise ValueError("Time step must be positive")
        flows = state.get("flows", [])
        if not flows:
            raise ValueError("Enter flows")
        change = dict.fromkeys(levels, 0.0)
        for row in flows:
            name(row["name"], "Flow")
            source, target = row.get("from"), row.get("to")
            if source is None and target is None or source == target:
                raise ValueError("Flow needs different source/target (one can be outside the system)")
            if source is not None and source not in levels or target is not None and target not in levels:
                raise ValueError("Flow endpoints must be listed stocks or null for outside")
            amount = dt * number(row["rate"], "Flow rate", 0)
            if source is not None:
                change[source] -= amount
            if target is not None:
                change[target] += amount
        after = {key: value + change[key] for key, value in levels.items()}
        if any(value < -1e-9 for value in after.values()):
            raise ValueError("Constant-rate step would make a stock negative; shorten dt or reduce outflow")
        return {
            "after_one_step": after,
            "changes": change,
            "dt": dt,
            "unit": state.get("unit", "user-defined"),
            "note": "One simultaneous step at constant flow rates; no feedback equations or long-run simulation.",
        }


for method in (Signposts(), StressTest(), CausalLoop(), Bottleneck(), StockFlow()):
    register(method)
