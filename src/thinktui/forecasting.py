"""V0.3 forecasting calculations; no AI or external reference data."""

from __future__ import annotations

import math
import random
import statistics

from .advanced_decisions import StructuredMethod, number, probability
from .core import register


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    location = (len(ordered) - 1) * p
    lower = int(location)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (location - lower)


class ForecastingJournal(StructuredMethod):
    id = "forecasting"
    name = "Probability Forecast Journal"
    category = "Forecasting"
    description = "Track forecasts, Brier scores and observed frequency by probability bin."
    example = {
        "forecasts": [
            {
                "question": "Will X ship?",
                "probability": 0.7,
                "outcome": 1,
                "resolution_date": "2027-01-01",
                "rationale": "User estimate",
            },
            {"question": "Will Y ship?", "probability": 0.3, "outcome": 0},
        ]
    }

    def calculate(self, state: dict) -> dict:
        rows = state.get("forecasts", [])
        if not rows:
            raise ValueError("Add at least one forecast")
        bins: dict[int, list[tuple[float, int]]] = {}
        resolved = []
        for row in rows:
            if not isinstance(row.get("question"), str) or not row["question"].strip():
                raise ValueError("Each forecast needs a question")
            p = probability(row["probability"], "Forecast probability")
            outcome = row.get("outcome")
            if outcome is None:
                continue
            if type(outcome) is not int or outcome not in (0, 1):
                raise ValueError("Resolved outcome must be 0 (no) or 1 (yes)")
            resolved.append((p - outcome) ** 2)
            bins.setdefault(min(int(p * 10), 9), []).append((p, outcome))
        calibration = [
            {
                "range": f"{i * 10}–{100 if i == 9 else i * 10 + 9}%",
                "count": len(data),
                "mean_prediction": statistics.mean(p for p, _ in data),
                "observed": statistics.mean(o for _, o in data),
            }
            for i, data in sorted(bins.items())
        ]
        return {
            "count": len(rows),
            "resolved": len(resolved),
            "brier_score": statistics.mean(resolved) if resolved else None,
            "calibration": calibration,
            "note": "Only resolved questions enter Brier/calibration; small bins are noisy.",
        }


class ReferenceClass(StructuredMethod):
    id = "reference_class"
    name = "Reference-Class Forecasting"
    category = "Forecasting"
    description = "Compare an inside estimate against actual/estimated ratios from user-entered cases."
    example = {
        "cases": [{"name": "Project A", "estimate": 3, "actual": 5}, {"name": "Project B", "estimate": 4, "actual": 8}],
        "inside_estimate": 6,
    }

    def calculate(self, state: dict) -> dict:
        cases = state.get("cases", [])
        if not cases:
            raise ValueError("Enter historical cases; ThinkTUI never invents them")
        ratios = []
        for row in cases:
            estimate = number(row["estimate"], "Case estimate", 0)
            actual = number(row["actual"], "Case actual", 0)
            if estimate == 0:
                raise ValueError("Case estimate must be positive")
            ratios.append(actual / estimate)
        inside = number(state["inside_estimate"], "Inside estimate", 0)
        return {
            "cases": len(cases),
            "mean_overrun_ratio": statistics.mean(ratios),
            "median_overrun_ratio": statistics.median(ratios),
            "p10_ratio": percentile(ratios, 0.1),
            "p90_ratio": percentile(ratios, 0.9),
            "outside_view_median": inside * statistics.median(ratios),
            "outside_view_p10": inside * percentile(ratios, 0.1),
            "outside_view_p90": inside * percentile(ratios, 0.9),
            "note": "Only user-supplied cases; validity depends on reference-class comparability.",
        }


def draw(rng: random.Random, spec: dict) -> float:
    kind = spec["distribution"]
    if kind == "uniform":
        low, high = number(spec["min"], "Minimum"), number(spec["max"], "Maximum")
        if low >= high:
            raise ValueError("Uniform min must be below max")
        return rng.uniform(low, high)
    if kind == "triangular":
        low, mode, high = (number(spec[k], k) for k in ("min", "mode", "max"))
        if not low <= mode <= high or low == high:
            raise ValueError("Triangular requires min <= mode <= max and min < max")
        return rng.triangular(low, high, mode)
    if kind in {"normal", "lognormal"}:
        mean = number(spec["mean"], "Mean")
        sd = number(spec["sd"], "Standard deviation", 0)
        return rng.gauss(mean, sd) if kind == "normal" else rng.lognormvariate(mean, sd)
    if kind == "discrete":
        values = [number(v, "Discrete value") for v in spec["values"]]
        weights = [number(w, "Discrete weight", 0) for w in spec["weights"]]
        if not values or len(values) != len(weights) or sum(weights) <= 0:
            raise ValueError("Discrete values need matching nonnegative weights with positive sum")
        return rng.choices(values, weights=weights)[0]
    if kind == "samples":
        values = [number(v, "Sample") for v in spec["values"]]
        if not values:
            raise ValueError("At least one sample is required")
        return rng.choice(values)
    raise ValueError("Unknown distribution")


class MonteCarlo(StructuredMethod):
    id = "monte_carlo"
    name = "Monte Carlo Simulation"
    category = "Forecasting"
    description = "Reproducible simulation of a linear model with uncertain inputs."
    example = {
        "variables": [
            {"name": "benefit", "distribution": "triangular", "min": 10, "mode": 20, "max": 30, "coefficient": 1},
            {"name": "cost", "distribution": "uniform", "min": 5, "max": 15, "coefficient": -1},
        ],
        "constant": 0,
        "threshold": 0,
        "iterations": 2000,
        "seed": 42,
    }

    def calculate(self, state: dict) -> dict:
        variables = state.get("variables", [])
        if not variables or len(variables) > 30:
            raise ValueError("Enter 1–30 uncertain variables")
        labels = [spec.get("name") for spec in variables]
        if any(not isinstance(v, str) or not v.strip() for v in labels) or len(set(labels)) != len(labels):
            raise ValueError("Variables need unique names")
        iterations = state.get("iterations", 2000)
        seed = state.get("seed", 0)
        if type(iterations) is not int or not 100 <= iterations <= 50000:
            raise ValueError("Iterations must be an integer from 100 to 50000")
        if type(seed) is not int:
            raise ValueError("Seed must be an integer")
        constant = number(state.get("constant", 0), "Constant")
        threshold = number(state.get("threshold", 0), "Threshold")
        coefficients = [number(v.get("coefficient", 1), "Coefficient") for v in variables]
        rng = random.Random(seed)
        results = [
            constant + sum(c * draw(rng, spec) for c, spec in zip(coefficients, variables, strict=True))
            for _ in range(iterations)
        ]
        if not all(math.isfinite(v) for v in results):
            raise ValueError("Simulated result is not finite")
        return {
            "iterations": iterations,
            "seed": seed,
            "mean": statistics.mean(results),
            "p10": percentile(results, 0.1),
            "p50": percentile(results, 0.5),
            "p90": percentile(results, 0.9),
            "probability_above_threshold": sum(v > threshold for v in results) / iterations,
            "note": "Outputs use the units of your linear model; input distributions are user estimates.",
        }


for method in (ForecastingJournal(), ReferenceClass(), MonteCarlo()):
    register(method)
