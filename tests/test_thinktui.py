"""End-to-end local workspace and deterministic method tests."""

import json

import pytest

from pairwise_prioritizer.comparison_engine import create_project, decide
from pairwise_prioritizer.models import Item, Outcome
from thinktui.ai import AIRequest, FakeAIProvider, context_for
from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.reports import decision_brief, export
from thinktui.storage import Store


def test_matrix_weights_and_costs():
    method = METHODS["matrix"]
    state = {
        "criteria": [{"name": "value", "weight": 3}, {"name": "effort", "weight": 1, "direction": "cost"}],
        "alternatives": [{"name": "A", "scores": [8, 8]}, {"name": "B", "scores": [6, 1]}],
    }
    assert method.calculate(state)["ranking"][0] == {"name": "B", "score": 6.75}
    assert method.calculate(state)["normalized_weights"] == [0.75, 0.25]
    state["criteria"][0]["weight"] = -1
    with pytest.raises(ValueError):
        method.calculate(state)


def test_persistence_export_and_privacy(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    project = store.new_project("Decision")
    session = Session(project, "premortem", "Launch", notes="private notes")
    session.method_state["entries"] = [{"statement": "Vendor outage", "impact": 9, "likelihood": 50, "source": "USER"}]
    store.save(session, "Added risk")
    store.close()
    reopened = Store(tmp_path / "db.sqlite")
    assert reopened.load(session.id).method_state == session.method_state
    assert reopened.events(session.id)[0]["description"] == "Added risk"
    assert "private notes" not in json.dumps(context_for(session))
    destination = tmp_path / "brief.md"
    export(session, destination)
    assert "Vendor outage" in destination.read_text()
    assert "## What Would Change Our Mind?" in decision_brief(session)
    with pytest.raises(ValueError):
        reopened.set_setting("secret", "bad")
    reopened.close()


@pytest.mark.asyncio
async def test_fake_ai_never_modifies_context():
    provider = FakeAIProvider('{"statement":"Check capacity"}')
    session = Session("project", "assumptions", "Check", notes="private")
    context = context_for(session)
    reply = await provider.complete(AIRequest("suggest", context))
    assert json.loads(reply)["statement"] == "Check capacity"
    assert provider.requests[0].context == context
    assert "private" not in json.dumps(context)
    assert session.method_state == {}


def test_pairwise_adapter():
    ranking = create_project("Test", [Item(name="A"), Item(name="B")], seed=1)
    decide(ranking, ranking.order[0], Outcome.TIE)
    result = METHODS["pairwise"].calculate({"ranking": ranking.to_dict()})
    assert result["remaining"] == 0
    assert len(result["ranking"]) == 2


@pytest.mark.asyncio
async def test_tui_create_resume_compare(tmp_path):
    from thinktui.screens import Home, Library, NewAnalysis, NewProject, Workspace

    store = Store(tmp_path / "app.db")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, Home)
        await pilot.press("n")
        assert isinstance(app.screen, NewProject)
        from textual.widgets import Input

        app.screen.query_one("#name", Input).value = "Test project"
        await pilot.press("enter")
        assert app.project_id is not None
        await pilot.press("m")
        assert isinstance(app.screen, Library)
        app.screen.query_one("#method-search", Input).value = "Pairwise"
        await pilot.press("enter")  # focus the filtered results
        await pilot.press("enter")  # choose the method
        assert isinstance(app.screen, NewAnalysis)
        app.screen.query_one("#title", Input).value = "Priorities"
        app.screen.start()
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        from textual.widgets import TextArea

        app.screen.query_one("#items", TextArea).load_text("A\nB")
        from textual.widgets import Button

        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#initialize", Button)))
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        app.screen.compare("tie")
        session_id = app.session.id
        assert store.load(session_id).completed_at is not None
        destination = tmp_path / "decision.md"
        app.screen.query_one("#export-path", Input).value = str(destination)
        await pilot.press("ctrl+e")
        assert "## Analysis" in destination.read_text()
        app.show_project()
        await pilot.pause()
        app.open_session(store.load(session_id))
        await pilot.pause()
        assert app.session.method_state["ranking"]
    store.close()
