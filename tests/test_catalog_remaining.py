"""All 40 catalog entries have deterministic validation, calculation and a TUI path."""

from __future__ import annotations

import copy
import json

import pytest
from textual.widgets import Button, Input, Static, TextArea

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.storage import Store

REMAINING = (
    "bradley_terry",
    "value_of_information",
    "opportunity_cost",
    "reversibility",
    "hypothesis_tree",
    "assumption_mapping",
    "root_cause",
    "five_whys",
    "fishbone",
    "evidence_matrix",
    "risk_matrix",
    "fault_tree",
    "bow_tie",
    "fermi",
    "bayesian_update",
    "signposts",
    "strategy_stress",
    "causal_loop",
    "bottleneck",
    "stock_flow",
)


@pytest.mark.parametrize("method_id", REMAINING)
def test_remaining_method_example_and_determinism(method_id):
    method = METHODS[method_id]
    state = copy.deepcopy(method.example)
    assert method.validate(state) == []
    assert method.calculate(state) == method.calculate(state)
    assert isinstance(method.calculate(state), dict)
    assert method.validate({})  # no method silently invents missing input


def test_value_of_information_probability_and_cost():
    method = METHODS["value_of_information"]
    result = method.calculate(method.example)
    assert result["best_without_information"] == pytest.approx(40)
    assert result["perfect_information_value"] == pytest.approx(20)
    assert result["sample_information_value"] == pytest.approx(4)
    assert result["net_sample_information_value"] == pytest.approx(-1)
    state = copy.deepcopy(method.example)
    state["signals"][0]["likelihoods"]["Demand"] = 0.7
    assert "sum to 1" in method.validate(state)[0]


def test_bayes_fault_tree_fermi_and_systems_math():
    posterior = METHODS["bayesian_update"].calculate(METHODS["bayesian_update"].example)
    assert posterior["posterior"] == pytest.approx(0.75)
    fault = METHODS["fault_tree"].calculate(METHODS["fault_tree"].example)
    assert fault["result"]["probability"] == pytest.approx(0.28)
    invalid = copy.deepcopy(METHODS["fault_tree"].example)
    invalid["tree"]["independent"] = False
    assert "independent" in METHODS["fault_tree"].validate(invalid)[0]
    estimate = METHODS["fermi"].calculate(METHODS["fermi"].example)
    assert (estimate["low_case"], estimate["estimate"], estimate["high_case"]) == (640, 1000, 1440)
    bottleneck = METHODS["bottleneck"].calculate(METHODS["bottleneck"].example)
    assert bottleneck["capacity"] == 10 and bottleneck["proposed_capacity"] == 16
    stock = METHODS["stock_flow"].calculate(METHODS["stock_flow"].example)
    assert stock["after_one_step"] == {"Backlog": 19, "Done": 3}
    loop = METHODS["causal_loop"].calculate(METHODS["causal_loop"].example)
    assert len(loop["loops"]) == 1 and loop["loops"][0]["type"] == "reinforcing"
    invalid = copy.deepcopy(METHODS["stock_flow"].example)
    invalid["flows"][0]["rate"] = 30
    assert "negative" in METHODS["stock_flow"].validate(invalid)[0]
    mixed = copy.deepcopy(METHODS["causal_loop"].example)
    mixed["links"][0]["polarity"] = -1
    assert METHODS["causal_loop"].calculate(mixed)["loops"][0]["type"] == "balancing"
    invalid = copy.deepcopy(METHODS["bayesian_update"].example)
    invalid["prior"] = 1.5
    assert METHODS["bayesian_update"].validate(invalid)


def test_qualitative_methods_do_not_invent_scores():
    for method_id in ("reversibility", "hypothesis_tree", "root_cause", "five_whys", "fishbone", "bow_tie"):
        result = METHODS[method_id].calculate(METHODS[method_id].example)
        assert "probability" not in result and "score" not in result
    matrix = METHODS["evidence_matrix"].calculate(METHODS["evidence_matrix"].example)
    assert matrix["contradictions"] == {"Pool": [], "Network": []}
    risk = METHODS["risk_matrix"].calculate(METHODS["risk_matrix"].example)
    assert risk["risks"][0]["likelihood"] == 3
    assert "heuristic" in risk["warning"]
    strategy = METHODS["strategy_stress"].calculate(METHODS["strategy_stress"].example)
    assert strategy["strategies"][0]["name"] == "Pilot"
    assert strategy["strategies"][0]["worst_case"] == 7
    signposts = METHODS["signposts"].calculate(METHODS["signposts"].example)
    assert signposts["indicators"][0]["triggered"] is True


def changed_example(method_id: str) -> dict:
    state = copy.deepcopy(METHODS[method_id].example)
    if method_id == "bradley_terry":
        state["items"].append("Gamma")
    elif method_id == "value_of_information":
        state["research_cost"] = 6
    elif method_id == "opportunity_cost":
        state["chosen"] = "Buy"
    elif method_id == "reversibility":
        state["alternatives"][0]["rollback_cost"] = 9
    elif method_id == "hypothesis_tree":
        state["question"] = "Why are requests slow?"
    elif method_id == "assumption_mapping":
        state["assumptions"][0]["confidence"] = 0.4
    elif method_id in {"root_cause", "five_whys"}:
        state["problem"] = "Investigate observed delays"
    elif method_id == "fishbone":
        state["effect"] = "Slow onboarding"
    elif method_id == "evidence_matrix":
        state["evidence"][0]["reliability"] = 0.9
    elif method_id == "risk_matrix":
        state["scale_max"] = 6
    elif method_id == "fault_tree":
        state["tree"]["children"][0]["probability"] = 0.15
    elif method_id == "bow_tie":
        state["top_event"] = "Vendor API down"
    elif method_id == "fermi":
        state["factors"][0]["estimate"] = 101
    elif method_id == "bayesian_update":
        state["prior"] = 0.5
    elif method_id == "signposts":
        state["indicators"][0]["current"] = 76
    elif method_id == "strategy_stress":
        state["strategies"][0]["scores"]["Slow"] = 9
    elif method_id == "causal_loop":
        state["links"][0]["polarity"] = -1
    elif method_id == "bottleneck":
        state["proposal"]["new_capacity"] = 14
    elif method_id == "stock_flow":
        state["dt"] = 2
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", REMAINING)
async def test_remaining_method_tui_save_resume_and_export(tmp_path, method_id):
    store = Store(tmp_path / "catalog.db")
    project = store.new_project("Analysis")
    session = Session(project, method_id, "Test")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        editor = app.screen.query_one("#structured-input", TextArea)
        button = app.screen.query_one("#structured-calculate", Button)
        app.screen.on_button_pressed(Button.Pressed(button))  # never save illustrative examples
        assert store.load(session.id).method_state == {}
        state = changed_example(method_id)
        editor.load_text(json.dumps(state))
        app.screen.on_button_pressed(Button.Pressed(button))
        assert all(store.load(session.id).method_state[key] == value for key, value in state.items())
        assert "Calculated locally" in str(app.screen.query_one("#results", Static).render())
        destination = tmp_path / "analysis.md"
        app.screen.query_one("#export-path", Input).value = str(destination)
        await pilot.press("ctrl+e")
        assert "## Analysis" in destination.read_text()
        app.open_session(store.load(session.id))
        await pilot.pause()
        assert all(
            json.loads(app.screen.query_one("#structured-input", TextArea).text)[key] == value
            for key, value in state.items()
        )
    store.close()
