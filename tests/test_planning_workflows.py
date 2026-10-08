"""Rule-based method discovery and explicit, auditable cross-method handoffs."""

from __future__ import annotations

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.planning import GOALS, recommend, transfer
from thinktui.planning_screen import PlanningScreen
from thinktui.screens import DeleteProjectDialog, Home, NewAnalysis, NewProject
from thinktui.storage import Store


def test_recommendations_and_no_invented_judgments():
    assert len(GOALS) >= 7
    for goal in GOALS:
        assert all(key in METHODS and reason for key, reason in recommend(goal))
    source = Session("project", "premortem", "Migration", problem_statement="Migration risks")
    source.method_state["entries"] = [
        {"statement": "Vendor outage", "action": "Plan failover", "likelihood": 60, "impact": 9}
    ]
    assert "fmea" in [method_id for method_id, _ in recommend(source=source)]
    state = transfer(source, "fmea")
    assert state["source_session_id"] == source.id
    assert state["failure_modes"][0]["mode"] == "Vendor outage"
    assert state["failure_modes"][0]["severity"] is None
    assert state["failure_modes"][0]["occurrence"] is None
    assert METHODS["fmea"].validate(state)  # user must supply risk ratings
    source.method_state["entries"][0]["statement"] = "Changed afterward"
    assert state["failure_modes"][0]["mode"] == "Vendor outage"  # snapshot, not opaque memory
    objectives = Session("project", "objectives", "What matters?")
    objectives.method_state["nodes"] = [{"id": "a", "parent_id": None, "label": "Safety", "kind": "fundamental"}]
    matrix = transfer(objectives, "matrix")
    assert matrix["criteria"][0]["name"] == "Safety"
    assert matrix["criteria"][0]["weight"] is None
    assert METHODS["matrix"].validate(matrix)
    scored = Session(
        "project",
        "matrix",
        "Choice",
        method_state={
            "criteria": [{"name": "Value", "weight": 1}, {"name": "Cost", "weight": 1}],
            "alternatives": [{"name": "A", "scores": [8, 2]}, {"name": "B", "scores": [6, 5]}],
        },
    )
    sensitivity = transfer(scored, "sensitivity")
    sensitivity["criteria"][0]["weight"] = 99
    assert scored.method_state["criteria"][0]["weight"] == 1


@pytest.mark.asyncio
async def test_home_help_choose_creates_project_and_method(tmp_path):
    store = Store(tmp_path / "choose.db")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, Home)
        await pilot.press("h")
        assert isinstance(app.screen, PlanningScreen)
        app.screen.query_one("#goal", Select).value = "Forecast an outcome"
        await pilot.pause()
        table = app.screen.query_one("#recommendations", DataTable)
        assert table.row_count == len(recommend("Forecast an outcome"))
        app.screen.start()
        await pilot.pause()
        assert isinstance(app.screen, NewProject)
        assert app.pending_method_id == "fermi"
        app.screen.query_one("#name", Input).value = "Timeline"
        app.screen.create()
        await pilot.pause()
        assert isinstance(app.screen, NewAnalysis)
        assert app.method_id == "fermi"
        app.screen.query_one("#title", Input).value = "Forecast duration"
        app.screen.start()
        await pilot.pause()
        assert app.session.method_id == "fermi"
        assert len(store.projects()) == 1
    store.close()


@pytest.mark.asyncio
async def test_next_method_handoff_and_project_delete_cascade(tmp_path):
    store = Store(tmp_path / "linked.db")
    project = store.new_project("Strategy")
    source = Session(
        project, "premortem", "Launch", problem_statement="What could go wrong?", objective="Avoid outages"
    )
    source.method_state["entries"] = [{"statement": "Vendor outage", "action": "Fail over"}]
    store.save(source)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(source)
        await pilot.pause()
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#plan", Button)))
        await pilot.pause()
        assert isinstance(app.screen, PlanningScreen)
        assert "approved user input" in str(app.screen.query_one(Static).render()) or app.screen.source is source
        app.screen.start()  # first recommendation is FMEA
        await pilot.pause()
        linked = app.session
        assert linked.method_id == "fmea"
        assert linked.project_id == source.project_id
        assert linked.objective == source.objective
        assert linked.method_state["source_session_id"] == source.id
        assert linked.method_state["failure_modes"][0]["mode"] == "Vendor outage"
        assert linked.method_state["failure_modes"][0]["severity"] is None
        assert store.load(linked.id).method_state == linked.method_state
        app.show_project()
        await pilot.pause()
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#delete", Button)))
        assert isinstance(app.screen, DeleteProjectDialog)
        assert app.screen.analysis_count == 2
        await pilot.press("escape")
        assert len(store.sessions(project)) == 2
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#delete", Button)))
        await pilot.pause()
        await pilot.click("#confirm-delete")
        assert store.projects() == []
        assert store.sessions() == []
        assert store.events(source.id) == [] and store.events(linked.id) == []
    store.close()
