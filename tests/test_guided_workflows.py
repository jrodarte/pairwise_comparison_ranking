"""Keyboard-first flagship workflows and audited, deterministic results."""

from __future__ import annotations

import pytest
from textual.widgets import Button, Checkbox, Select, Static, TextArea

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.guided_screen import GuidedScreen
from thinktui.guided_workflow import MatrixMappingRequired, advance, definition, final_index, reachable_index
from thinktui.matrix_mapping_screen import MatrixMappingDialog
from thinktui.reports import decision_brief
from thinktui.storage import Store


def test_matrix_steps_validate_without_losing_judgments():
    state = advance("matrix", {}, 0, {"alternatives": "Build\nBuy"})
    state = advance("matrix", state, 1, {"criteria": "Value | 3 | benefit\nCost | 1 | cost"})
    old = state.copy()
    with pytest.raises(ValueError, match="Score"):
        advance("matrix", state, 2, {"score_0_0": "9", "score_0_1": "", "score_1_0": "6", "score_1_1": "2"})
    assert state == old
    state = advance("matrix", state, 2, {"score_0_0": "9", "score_0_1": "8", "score_1_0": "6", "score_1_1": "2"})
    assert METHODS["matrix"].calculate(state)["ranking"][0]["name"] == "Build"
    with pytest.raises(MatrixMappingRequired):
        advance("matrix", state, 0, {"alternatives": "Other\nBuy"})
    renamed = advance("matrix", state, 0, {"alternatives": "Other\nBuy"}, mapping=[0, 1])
    assert renamed["alternatives"][0]["scores"] == [9, 8]
    assert state["alternatives"][0]["name"] == "Build"  # mapping never mutates the source
    reordered = advance("matrix", state, 0, {"alternatives": "Buy\nBuild"}, mapping=[1, 0])
    assert reordered["alternatives"][0]["scores"] == [6, 2]
    extended = advance("matrix", state, 0, {"alternatives": "Build\nBuy\nTrial"}, mapping=[0, 1, None])
    assert [row["scores"] for row in extended["alternatives"]] == [[9, 8], [6, 2], []]
    assert reachable_index("matrix", extended) == 2
    with pytest.raises(ValueError, match="discarding scores"):
        advance("matrix", state, 0, {"alternatives": "Other\nBuy"}, mapping=[None, 1])
    blank = advance("matrix", state, 0, {"alternatives": "Other\nBuy"}, mapping=[None, 1], discard_scores=True)
    assert blank["alternatives"][0]["scores"] == []
    with pytest.raises(ValueError, match="only one"):
        advance("matrix", state, 0, {"alternatives": "Other\nBuy"}, mapping=[0, 0])
    with pytest.raises(MatrixMappingRequired):
        advance("matrix", state, 1, {"criteria": "Price | 3 | benefit\nCost | 1 | cost"})
    revised = advance("matrix", state, 1, {"criteria": "Cost | 1 | cost\nBenefit | 3 | benefit"}, mapping=[1, 0])
    assert revised["alternatives"][0]["scores"] == [8, 9]
    assert revised["alternatives"][1]["scores"] == [2, 6]
    with pytest.raises(ValueError, match="discarding scores"):
        advance("matrix", state, 1, {"criteria": "Value | 3 | benefit"}, mapping=[0])
    added = advance(
        "matrix",
        state,
        1,
        {"criteria": "Cost | 1 | cost\nValue | 3 | benefit\nEase | 2 | benefit"},
        mapping=[1, 0, None],
    )
    assert added["alternatives"][0]["scores"] == [8, 9, ""]
    assert reachable_index("matrix", added) == 2
    same = advance("matrix", state, 0, {"alternatives": "Build\nBuy"})
    assert same["alternatives"][0]["scores"] == [9, 8]
    legacy = {**state, "alternatives": [{"name": "Build", "scores": ["9", "8"]}, state["alternatives"][1]]}
    with pytest.raises(MatrixMappingRequired):
        advance("matrix", legacy, 0, {"alternatives": "Other\nBuy"})


def test_unscored_matrix_labels_change_after_handoff_without_mapping():
    state = {
        "alternatives": [{"name": "Pilot", "scores": []}, {"name": "Wait", "scores": []}],
        "criteria": [{"name": "Response time", "weight": None, "direction": "benefit"}],
    }
    changed = advance("matrix", state, 0, {"alternatives": "Trial\nWait"})
    assert [row["name"] for row in changed["alternatives"]] == ["Trial", "Wait"]
    assert changed["criteria"] == state["criteria"]
    assert state["alternatives"][0]["name"] == "Pilot"


@pytest.mark.asyncio
async def test_matrix_handoff_can_edit_alternatives_before_scoring(tmp_path):
    store = Store(tmp_path / "handoff.db")
    project = store.new_project("Plan")
    source = Session(
        project,
        "value_focused",
        "Values",
        completed_at="reviewed",
        method_state={
            "objectives": [{"name": "Fast onboarding", "kind": "fundamental", "measure": "Speed"}],
            "alternatives": ["Pilot", "Wait"],
        },
    )
    store.save(source)
    session = Session(project, "matrix", "Compare")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#use-offer", Button).press()
        await pilot.pause()
        assert session.method_state["criteria"][0]["name"] == "Speed"
        app.screen.query_one("#field-alternatives", TextArea).load_text("Trial\nWait")
        await app.screen.action_next()
        assert isinstance(app.screen, GuidedScreen)
        assert app.screen.index == 1
        assert [row["name"] for row in session.method_state["alternatives"]] == ["Trial", "Wait"]
        assert all(row["scores"] == [] for row in session.method_state["alternatives"])
        assert session.method_state["criteria"][0]["name"] == "Speed"


@pytest.mark.asyncio
async def test_scored_matrix_reopen_maps_option_and_criterion_without_json(tmp_path):
    store = Store(tmp_path / "scored.db")
    project = store.new_project("Plan")
    state = {
        "criteria": [
            {"name": "Quality", "weight": 2, "direction": "benefit"},
            {"name": "Cost", "weight": 1, "direction": "cost"},
        ],
        "alternatives": [{"name": "North", "scores": [9, 8]}, {"name": "South", "scores": [6, 2]}],
    }
    session = Session(project, "matrix", "Choice", method_state=state, completed_at="reviewed")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(store.load(session.id), guided=True)
        await pilot.pause()
        screen = app.screen
        assert screen.index == 3
        for _ in range(3):
            await screen.action_previous()
        screen.query_one("#field-alternatives", TextArea).load_text("South\nTrial")
        await screen.action_next()
        await pilot.pause()
        assert isinstance(app.screen, MatrixMappingDialog)
        assert store.load(session.id).method_state["alternatives"] == state["alternatives"]
        assert app.screen.query_one("#matrix-source-0", Select).value == 1  # exact name
        app.screen.query_one("#matrix-source-1", Select).value = 0  # confirm rename
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert [row["scores"] for row in app.session.method_state["alternatives"]] == [[6, 2], [9, 8]]
        assert app.session.completed_at is None
        screen.query_one("#field-criteria", TextArea).load_text("Cost | 1 | cost\nBenefit | 2 | benefit")
        await screen.action_next()
        await pilot.pause()
        assert isinstance(app.screen, MatrixMappingDialog)
        app.screen.query_one("#matrix-source-1", Select).value = 0
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        saved = store.load(session.id).method_state
        assert [criterion["name"] for criterion in saved["criteria"]] == ["Cost", "Benefit"]
        assert [row["scores"] for row in saved["alternatives"]] == [[2, 6], [8, 9]]
        assert not METHODS["matrix"].validate(saved)
        await screen.action_next()  # score grid retains confirmed mappings
        await screen.action_next()  # review completion
        assert store.load(session.id).completed_at is not None


@pytest.mark.asyncio
async def test_scored_matrix_requires_explicit_discard_confirmation(tmp_path):
    store = Store(tmp_path / "discard.db")
    session = Session(
        store.new_project("Plan"),
        "matrix",
        "Choice",
        completed_at="reviewed",
        method_state={
            "criteria": [
                {"name": "Quality", "weight": 2, "direction": "benefit"},
                {"name": "Cost", "weight": 1, "direction": "cost"},
            ],
            "alternatives": [{"name": "North", "scores": [9, 8]}, {"name": "South", "scores": [6, 2]}],
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        await app.screen.action_previous()
        await app.screen.action_previous()
        app.screen.query_one("#field-criteria", TextArea).load_text("Quality | 2 | benefit")
        await app.screen.action_next()
        await pilot.pause()
        assert isinstance(app.screen, MatrixMappingDialog)
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert "discarding scores" in str(app.screen.query_one("#matrix-mapping-error", Static).content)
        assert len(store.load(session.id).method_state["criteria"]) == 2
        app.screen.query_one("#matrix-discard", Checkbox).value = True
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert [row["scores"] for row in store.load(session.id).method_state["alternatives"]] == [[9], [6]]


def test_simple_guided_name_lists_round_trip_without_structured_row_syntax():
    # These are plain names, unlike matrix criteria: one line is exactly one label.
    ahp = {"criteria": ["Value | impact", "0"], "alternatives": ["Build", "Wait"]}
    for index, key in ((0, "criteria"), (1, "alternatives")):
        text = definition("ahp", ahp, index).fields[0].value
        assert text.splitlines() == ahp[key]
        assert advance("ahp", ahp, index, {key: text})[key] == ahp[key]
    ach = {"hypotheses": ["Network", "0"]}
    text = definition("ach", ach, 0).fields[0].value
    assert advance("ach", ach, 0, {"hypotheses": text})["hypotheses"] == ach["hypotheses"]
    scenarios = {"question": "Which approach?", "drivers": ["Demand | timing", "0"]}
    question, drivers = definition("scenarios", scenarios, 0).fields
    assert (
        advance("scenarios", scenarios, 0, {"question": question.value, "drivers": drivers.value})["drivers"]
        == scenarios["drivers"]
    )


def test_ahp_steps_recips_and_consistency():
    state = advance("ahp", {}, 0, {"criteria": "Value\nCost"})
    state = advance("ahp", state, 1, {"alternatives": "A\nB"})
    with pytest.raises(ValueError):
        advance("ahp", state, 2, {"pair_0_1": "11"})
    state = advance("ahp", state, 2, {"pair_0_1": "3"})
    state = advance("ahp", state, 3, {"pair_0_1": "2"})
    state = advance("ahp", state, 4, {"pair_0_1": "1/2"})
    assert state["alternative_matrices"]["Cost"][0][1] == pytest.approx(0.5)
    assert METHODS["ahp"].calculate(state)["criteria"]["consistency_ratio"] == 0
    assert final_index("ahp", state) == 5
    assert definition("ahp", state, 5).review
    assert advance("ahp", state, 5, {}) == state


def test_ach_forecast_scenario_steps():
    state = advance("ach", {}, 0, {"hypotheses": "Pool\nNetwork"})
    state = advance(
        "ach",
        state,
        1,
        {
            "title": "Connection count rose",
            "source": "Operator log",
            "reliability": "0.8",
            "rating_0": "--",
            "rating_1": "+",
        },
    )
    assert METHODS["ach"].calculate(state)["ranking"][0]["hypothesis"] == "Network"
    assert METHODS["ach"].calculate(state)["evidence"][0]["source"] == "Operator log"
    report = decision_brief(Session("project", "ach", "Case", method_state=state))
    assert "Source: Operator log" in report and "Pool: --" in report
    with pytest.raises(ValueError, match="Confirm which old judgments"):
        advance("ach", state, 0, {"hypotheses": "Pool\nTraffic"})
    forecast = advance(
        "forecasting", {}, 0, {"question": "Ship by Q4?", "resolution_date": "", "rationale": "User estimate"}
    )
    forecast = advance("forecasting", forecast, 1, {"probability": "70"})
    forecast = advance("forecasting", forecast, 2, {"outcome": "yes"})
    assert METHODS["forecasting"].calculate(forecast)["brier_score"] == pytest.approx(0.09)
    scenario = advance("scenarios", {}, 0, {"question": "Invest where?", "drivers": "Regulation\nAdoption"})
    scenario = advance(
        "scenarios",
        scenario,
        1,
        {
            "axis_0_name": "Regulation",
            "axis_0_low": "Loose",
            "axis_0_high": "Strict",
            "axis_1_name": "Adoption",
            "axis_1_low": "Slow",
            "axis_1_high": "Fast",
        },
    )
    for index in range(2, 6):
        scenario = advance(
            "scenarios",
            scenario,
            index,
            {
                "name": f"Future {index}",
                "narrative": "User narrative",
                "implications": "Supply risk",
                "indicators": "Adoption rate",
            },
        )
    scenario = advance(
        "scenarios",
        scenario,
        6,
        {
            "name": "Pilot",
            "action_low_low": "Test",
            "action_low_high": "Scale",
            "action_high_low": "Pause",
            "action_high_high": "Prepare",
        },
    )
    assert len(METHODS["scenarios"].calculate(scenario)["scenarios"]) == 4
    assert definition("scenarios", scenario, 7).review
    with pytest.raises(ValueError, match="Confirm where each saved scenario"):
        advance(
            "scenarios",
            scenario,
            1,
            {
                "axis_0_name": "Regulation",
                "axis_0_low": "Loose",
                "axis_0_high": "Changed",
                "axis_1_name": "Adoption",
                "axis_1_low": "Slow",
                "axis_1_high": "Fast",
            },
        )
    assert reachable_index("scenarios", {"question": "Q", "drivers": ["A", "B"], "axes": scenario["axes"]}) == 2
    assert reachable_index("ahp", {"criteria": ["A", "B"], "alternatives": ["X", "Y"]}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_id,first,second",
    [
        ("matrix", {"alternatives": "Build\nBuy"}, {"criteria": "Value | 3 | benefit\nCost | 1 | cost"}),
        ("ahp", {"criteria": "Value\nCost"}, {"alternatives": "A\nB"}),
        (
            "ach",
            {"hypotheses": "Pool\nNetwork"},
            {"title": "Latency rose", "reliability": "0.8", "rating_0": "-", "rating_1": "+"},
        ),
        ("forecasting", {"question": "Ship?", "resolution_date": "", "rationale": "Estimate"}, {"probability": "72"}),
        (
            "scenarios",
            {"question": "Invest?", "drivers": "Adoption\nRegulation"},
            {
                "axis_0_name": "Adoption",
                "axis_0_low": "Slow",
                "axis_0_high": "Fast",
                "axis_1_name": "Regulation",
                "axis_1_low": "Loose",
                "axis_1_high": "Strict",
            },
        ),
    ],
)
async def test_guided_keyboard_save_resume_and_advanced(tmp_path, method_id, first, second):
    store = Store(tmp_path / "guided.db")
    project = store.new_project("Project")
    session = Session(project, method_id, "Analysis")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GuidedScreen)
        for key, value in first.items():
            widget = screen.query_one(f"#field-{key}")
            if isinstance(widget, TextArea):
                widget.load_text(value)
            else:
                widget.value = value
        await pilot.press("f8")
        assert app.session.method_state["_guided_step"] == 1
        assert store.load(session.id).method_state["_guided_step"] == 1
        for key, value in second.items():
            widget = screen.query_one(f"#field-{key}")
            if isinstance(widget, TextArea):
                widget.load_text(value)
            else:
                widget.value = value
        await pilot.press("f8")
        assert store.load(session.id).method_state["_guided_step"] == 2
        app.show_project()
        await pilot.pause()
        from textual.widgets import DataTable

        table = app.screen.query_one("#analyses", DataTable)
        table.focus()
        await pilot.press("enter")  # resume defaults to guided, not the JSON worksheet
        assert isinstance(app.screen, GuidedScreen)
        assert app.screen.index == 2
        await pilot.press("f6")
        from thinktui.screens import Workspace

        assert isinstance(app.screen, Workspace)
        assert app.session.method_state["_guided_step"] == 2
    store.close()
