"""Explicit multi-stage orchestration, judgments, export and restored audit trail."""

from __future__ import annotations

import json

import pytest
from textual.widgets import Button, Input, Select, TextArea

from thinktui.app import ThinkApp
from thinktui.core import METHODS
from thinktui.guided_screen import GuidedScreen
from thinktui.planning import begin_workflow, continue_workflow, planned_next, transfer
from thinktui.planning_screen import PlanningScreen
from thinktui.screens import Workspace
from thinktui.storage import Store
from thinktui.text_field import TextField


def test_plan_is_sequential_and_cannot_invent_judgments():
    first = begin_workflow("project", "Choose between options", "Choose a service")
    assert first.method_id == "matrix"
    assert planned_next(first) == "ahp"
    with pytest.raises(ValueError, match="Finish and validate"):
        continue_workflow(first)
    first.method_state.update(
        {
            "criteria": [
                {"name": "Value", "weight": 3, "direction": "benefit"},
                {"name": "Cost", "weight": 1, "direction": "cost"},
            ],
            "alternatives": [{"name": "A", "scores": [8, 7]}, {"name": "B", "scores": [4, 2]}],
        }
    )
    first.completed_at = "2026-01-01"
    second = continue_workflow(first)
    assert second.method_state["criteria"] == ["Value", "Cost"]
    assert second.method_state["alternatives"] == ["A", "B"]
    assert "criteria_matrix" not in second.method_state
    assert "alternative_matrices" not in second.method_state
    assert second.method_state["workflow_index"] == 1
    assert second.method_state["source_session_id"] == first.id
    assert transfer(first, "ahp")["alternatives"] == ["A", "B"]
    assert not METHODS["ahp"].validate(second.method_state) == []


def put(screen, values):
    for key, value in values.items():
        widget = screen.query_one(f"#field-{key}")
        if isinstance(widget, TextArea):
            widget.load_text(value)
        else:
            widget.value = value


@pytest.mark.asyncio
async def test_linked_matrix_ahp_finish_and_export(tmp_path):
    store = Store(tmp_path / "workflow.db")
    project = store.new_project("Purchasing")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.project_id = project
        app.switch_screen(PlanningScreen())
        await pilot.pause()
        planning = app.screen
        planning.query_one("#goal", Select).value = "Choose between options"
        planning.query_one("#workflow-problem", TextField).value = "Which provider should we choose?"
        planning.query_one("#workflow", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        first = app.session
        matrix = app.screen
        put(matrix, {"alternatives": "In-house\nContractor"})
        await pilot.press("f8")
        put(matrix, {"criteria": "Value | 3 | benefit\nCost | 1 | cost"})
        await pilot.press("f8")
        put(matrix, {"score_0_0": "9", "score_0_1": "8", "score_1_0": "6", "score_1_1": "2"})
        await pilot.press("f8")
        assert "In-house" in str(matrix.query_one("#guided-results").content)
        # The handoff is visible but is forbidden before explicit completion.
        matrix.query_one("#plan", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, PlanningScreen)
        assert app.screen.options[0] == "ahp"
        app.screen.start()
        assert isinstance(app.screen, PlanningScreen)
        app.screen.action_back()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        await pilot.press("f8")  # Finish/approve the matrix stage
        assert store.load(first.id).completed_at
        app.screen.query_one("#plan", Button).press()
        await pilot.pause()
        app.screen.start()  # explicit linked handoff to AHP
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        second = app.session
        assert second.method_id == "ahp"
        assert second.method_state["source_session_id"] == first.id
        assert "criteria_matrix" not in second.method_state
        ahp = app.screen
        await pilot.press("f8")  # user reviews copied criteria and alternatives
        await pilot.press("f8")
        put(ahp, {"pair_0_1": "3"})
        await pilot.press("f8")
        put(ahp, {"pair_0_1": "2"})
        await pilot.press("f8")
        put(ahp, {"pair_0_1": "1/2"})
        await pilot.press("f8")
        assert "Consistency ratio" in str(ahp.query_one("#guided-results").content)
        await pilot.press("f8")
        assert store.load(second.id).completed_at
        destination = tmp_path / "decision.md"
        ahp.query_one("#guided-export-path", Input).value = str(destination)
        ahp.action_export()
        assert "Analytic Hierarchy Process" in destination.read_text()
        assert first.title in destination.read_text()
        # Restore creates new project/session IDs throughout audit changes and links.
        imported = store.import_snapshot(store.snapshot(project))
        restored = {s.method_id: s for s in store.sessions(imported)}
        assert restored["ahp"].method_state["source_session_id"] == restored["matrix"].id
        assert second.id not in json.dumps([dict(event) for event in store.events(restored["ahp"].id)])
        assert first.id not in json.dumps([dict(event) for event in store.events(restored["ahp"].id)])
        assert planned_next(restored["ahp"]) == "premortem"
        app.switch_screen(PlanningScreen(first))
        await pilot.pause()
        app.screen.start()  # repeated confirmation resumes, not a duplicate analysis
        await pilot.pause()
        assert app.session.id == second.id
        assert len(store.sessions(project)) == 2
    store.close()


@pytest.mark.asyncio
async def test_plan_from_worksheet_to_next_stage(tmp_path):
    store = Store(tmp_path / "steps.db")
    project = store.new_project("Study")
    first = begin_workflow(project, "Rank alternatives", "Select provider")
    first.method_state.update(
        {
            "criteria": [{"name": "Value", "weight": 1}, {"name": "Cost", "weight": 1}],
            "alternatives": [{"name": "A", "scores": [9, 8]}, {"name": "B", "scores": [6, 2]}],
        }
    )
    first.completed_at = "2026-01-01"
    store.save(first)
    worksheet = continue_workflow(first)
    store.save(worksheet, "Linked from analysis " + first.id)
    assert worksheet.method_id == "sensitivity"
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(worksheet)  # dedicated worksheet for sensitivity
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        assert worksheet.method_state["source_session_id"] == first.id
        app.screen.query_one("#structured-calculate", Button).press()
        await pilot.pause()
        assert store.load(worksheet.id).completed_at
        app.screen.query_one("#plan", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, PlanningScreen)
        assert app.screen.options[0] == "premortem"
        app.screen.start()
        await pilot.pause()
        assert app.session.method_id == "premortem"
        assert app.session.method_state["workflow_index"] == 2
        assert app.session.method_state["source_session_id"] == worksheet.id
        final = app.session
        app.screen.query_one("#entry", TextField).value = "Provider might fail"
        app.screen.query_one("#action", TextField).value = "Test the fallback"
        app.screen.query_one("#add", Button).press()
        await pilot.pause()
        assert not store.load(final.id).method_state.get("entries")  # no invented ratings
        app.screen.query_one("#confidence", Input).value = "70"
        app.screen.query_one("#impact", Input).value = "8"
        app.screen.query_one("#add", Button).press()
        await pilot.pause()
        assert store.load(final.id).method_state["entries"][0]["impact"] == 8
        app.screen.query_one("#finish-stage", Button).press()
        await pilot.pause()
        assert store.load(final.id).completed_at
        app.show_project()
        await pilot.pause()
        assert len(store.sessions(project)) == 3
    store.close()
