"""Deterministic staged methods and a real JSON-based TUI/save/export workflow."""

from __future__ import annotations

import copy
import json

import pytest
from textual.widgets import Button, DataTable, Input, Static, TextArea

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.storage import Store


@pytest.mark.asyncio
async def test_library_search_finds_all_staged_methods(tmp_path):
    store = Store(tmp_path / "library.db")
    app = ThinkApp(store=store, initial="methods")
    async with app.run_test() as pilot:
        table = app.screen.query_one("#methods", DataTable)
        assert table.row_count == len(METHODS)
        app.screen.query_one("#method-search", Input).value = "Monte Carlo"
        await pilot.pause()
        assert table.row_count == 1
        assert "Monte Carlo" in str(table.get_row_at(0))
    store.close()


@pytest.mark.asyncio
async def test_matrix_can_start_linked_sensitivity_analysis(tmp_path):
    store = Store(tmp_path / "linked.db")
    project = store.new_project("Choice")
    matrix = Session(project, "matrix", "Vendor choice")
    matrix.method_state = {
        "criteria": [{"name": "Value", "weight": 1}, {"name": "Cost", "weight": 1, "direction": "cost"}],
        "alternatives": [{"name": "Build", "scores": [9, 8]}, {"name": "Buy", "scores": [6, 2]}],
    }
    store.save(matrix)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(matrix)
        await pilot.pause()
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#sensitivity", Button)))
        await pilot.pause()
        assert app.session.method_id == "sensitivity"
        assert app.session.method_state["source_session_id"] == matrix.id
        assert METHODS["sensitivity"].calculate(app.session.method_state)["switch_weight"] == pytest.approx(2 / 3)
        assert store.load(app.session.id).method_id == "sensitivity"
    store.close()


STAGED = (
    "ach",
    "decision_tree",
    "expected_value",
    "sensitivity",
    "ahp",
    "forecasting",
    "reference_class",
    "monte_carlo",
    "scenarios",
    "backcasting",
    "objectives",
    "value_focused",
    "fmea",
    "constraints",
)


@pytest.mark.parametrize("method_id", STAGED)
def test_each_example_is_valid_and_repeatable(method_id):
    method = METHODS[method_id]
    state = copy.deepcopy(method.example)
    assert method.validate(state) == []
    assert method.calculate(state) == method.calculate(state)
    assert isinstance(method.calculate(state), dict)


def test_ach_contradiction_and_unknown():
    method = METHODS["ach"]
    state = {
        "hypotheses": ["H1", "H2"],
        "evidence": [
            {"title": "E1", "reliability": 1, "ratings": {"H1": "--", "H2": "++"}},
            {"title": "E2", "reliability": 0.5, "ratings": {"H1": "?", "H2": "-"}},
        ],
    }
    ranking = method.calculate(state)["ranking"]
    assert ranking[0]["hypothesis"] == "H2"
    assert ranking[0]["inconsistency"] == 0  # unknown is not counted as evidence
    assert ranking[1]["inconsistency"] == 8
    state["evidence"][0]["ratings"]["H1"] = "bad"
    assert method.validate(state)


def test_expected_value_and_decision_tree_validation():
    expected = METHODS["expected_value"].calculate(METHODS["expected_value"].example)
    assert expected["ranking"][0]["expected_value"] == 125
    tree = METHODS["decision_tree"].calculate(METHODS["decision_tree"].example)["analysis"]
    assert tree["expected_value"] == 125
    assert tree["highest_ev_branch"] == "Build"
    invalid = copy.deepcopy(METHODS["decision_tree"].example)
    invalid["tree"]["branches"][0]["node"]["branches"][0]["probability"] = 0.8
    assert "sum to 1" in METHODS["decision_tree"].validate(invalid)[0]
    invalid_ev = copy.deepcopy(METHODS["expected_value"].example)
    invalid_ev["alternatives"][0]["outcomes"][0]["probability"] = 1.1
    assert METHODS["expected_value"].validate(invalid_ev)


def test_sensitivity_known_threshold_and_ahp_consistency():
    result = METHODS["sensitivity"].calculate(METHODS["sensitivity"].example)
    assert result["switch_weight"] == pytest.approx(2 / 3)
    state = copy.deepcopy(METHODS["ahp"].example)
    state["criteria"] = ["A", "B", "C"]
    state["criteria_matrix"] = [[1, 2, 4], [0.5, 1, 2], [0.25, 0.5, 1]]
    state["alternative_matrices"] = {key: [[1, 1], [1, 1]] for key in state["criteria"]}
    result = METHODS["ahp"].calculate(state)
    assert result["criteria"]["weights"] == pytest.approx([4 / 7, 2 / 7, 1 / 7])
    assert result["criteria"]["consistency_ratio"] == pytest.approx(0, abs=1e-9)
    state["criteria_matrix"][0][1] = 3
    assert METHODS["ahp"].validate(state)


def test_forecasting_brier_bins_reference_class_and_monte_carlo():
    result = METHODS["forecasting"].calculate(
        {
            "forecasts": [
                {"question": "A?", "probability": 0.8, "outcome": 1},
                {"question": "B?", "probability": 0.2, "outcome": 0},
                {"question": "C?", "probability": 0.9, "outcome": None},
            ]
        }
    )
    assert result["brier_score"] == pytest.approx(0.04)
    assert result["resolved"] == 2
    assert result["calibration"][1]["observed"] == 1
    assert METHODS["forecasting"].validate({"forecasts": [{"question": "X", "probability": 0.7, "outcome": 2}]})
    reference = METHODS["reference_class"].calculate(METHODS["reference_class"].example)
    assert reference["median_overrun_ratio"] == pytest.approx((5 / 3 + 2) / 2)
    state = {
        "variables": [{"name": "x", "distribution": "uniform", "min": 0, "max": 1}],
        "iterations": 5000,
        "seed": 7,
        "threshold": 0.5,
    }
    sim = METHODS["monte_carlo"].calculate(state)
    assert sim == METHODS["monte_carlo"].calculate(state)
    assert abs(sim["mean"] - 0.5) < 0.03
    assert abs(sim["probability_above_threshold"] - 0.5) < 0.04
    state["variables"][0]["min"] = 2
    assert METHODS["monte_carlo"].validate(state)


def test_strategy_risk_are_structural_not_fabricated():
    scenario = METHODS["scenarios"].calculate(METHODS["scenarios"].example)
    assert len(scenario["scenarios"]) == 4
    assert scenario["scenarios"][0]["poles"] == ["Loose", "Slow"]
    backcast = METHODS["backcasting"].calculate(METHODS["backcasting"].example)
    assert backcast["backward_milestones"][0]["date"] == "2028-06-01"
    assert METHODS["objectives"].calculate(METHODS["objectives"].example)["hierarchy"][0]["children"]
    assert METHODS["value_focused"].calculate(METHODS["value_focused"].example)["alternatives"]
    fmea = METHODS["fmea"].calculate(METHODS["fmea"].example)
    assert fmea["ranking"][0]["rpn"] == 216
    assert "screening" in fmea["warning"]
    assert METHODS["constraints"].calculate(METHODS["constraints"].example)["constraint_hypothesis"]
    invalid = copy.deepcopy(METHODS["fmea"].example)
    invalid["failure_modes"][0]["severity"] = 11
    assert METHODS["fmea"].validate(invalid)
    invalid["scale_max"] = 12
    assert METHODS["fmea"].calculate(invalid)["ranking"][0]["severity"] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_id,field,value",
    [
        ("ach", "hypotheses", ["Network", "Database"]),
        ("decision_tree", "tree", None),
        ("expected_value", "alternatives", None),
        ("sensitivity", "vary", "Cost"),
        ("ahp", "criteria_matrix", [[1, 2], [0.5, 1]]),
        ("forecasting", "forecasts", [{"question": "Resolved?", "probability": 0.6, "outcome": 1}]),
        ("reference_class", "inside_estimate", 7),
        ("monte_carlo", "seed", 9),
        ("scenarios", "question", "Where should our team invest?"),
        ("backcasting", "target_date", "2029-12-31"),
        ("objectives", "nodes", None),
        ("value_focused", "alternatives", ["Pilot", "Delay", "Do nothing"]),
        (
            "fmea",
            "failure_modes",
            [
                {
                    "mode": "Latency",
                    "effect": "Slow response",
                    "cause": "Cache miss",
                    "controls": "Tracing",
                    "severity": 8,
                    "occurrence": 2,
                    "detectability": 4,
                    "action": "Measure",
                    "owner": "Team",
                }
            ],
        ),
        ("constraints", "goal", "Ship more reliable features"),
    ],
)
async def test_staged_method_tui_autosave_resume_export(tmp_path, method_id, field, value):
    store = Store(tmp_path / "stages.db")
    project = store.new_project("Analysis")
    session = Session(project, method_id, "Tradeoff")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        editor = app.screen.query_one("#structured-input", TextArea)
        # The illustrative example cannot silently become project data.
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#structured-calculate", Button)))
        assert store.load(session.id).method_state == {}
        state = copy.deepcopy(METHODS[method_id].example)
        if method_id == "decision_tree":
            value = copy.deepcopy(state["tree"])
            value["branches"][0]["node"]["branches"][0]["node"]["value"] = 240
        elif method_id == "expected_value":
            value = copy.deepcopy(state["alternatives"])
            value[0]["name"] = "Build optimized"
        elif method_id == "objectives":
            value = copy.deepcopy(state["nodes"])
            value[0]["label"] = "User value"
        state[field] = value
        if method_id == "ach":
            state["evidence"][0]["ratings"] = {"Network": "--", "Database": "+"}
        editor.load_text(json.dumps(state))
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#structured-calculate", Button)))
        await pilot.pause(0.5)
        assert store.load(session.id).method_state[field] == value
        text = str(app.screen.query_one("#results", Static).render())
        assert "Calculated locally" in text
        path = tmp_path / "brief.md"
        app.screen.query_one("#export-path", Input).value = str(path)
        await pilot.press("ctrl+e")
        assert "## Analysis" in path.read_text()
        app.open_session(store.load(session.id))
        await pilot.pause(0.5)
        assert json.loads(app.screen.query_one("#structured-input", TextArea).text)[field] == value
    store.close()
