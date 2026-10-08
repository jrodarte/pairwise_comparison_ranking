"""Regressions for numeric AI prose and analysis-title collisions."""

from __future__ import annotations

import json

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static, TextArea

from thinktui import field_ai, form_screen, screens
from thinktui.ai import FakeAIProvider, ProviderConfig
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.field_ai import text_only
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.screens import AnalysisDialog, MoveAnalysisDialog, ProjectView, Workspace
from thinktui.storage import Store


@pytest.mark.parametrize(
    "judgment",
    [
        "Confidence is 30 percent",
        "Risk is 8",
        "Rating is 4 out of 5",
        "Deadline is 12 October 2026",
        "Probability is 0.3",
        "Cost: 25",
        "10 percent",
        "8 out of 10",
        "October 2026",
        "2026-10-12",
    ],
)
def test_ai_generated_numeric_judgment_is_removed(judgment):
    assert text_only(judgment) == ""
    assert text_only(f"Phase 2\n{judgment}\nReview in Q3") == "Phase 2\nReview in Q3"


@pytest.mark.asyncio
async def test_form_ai_stream_filters_numeric_prose_but_accepts_user_edited_text(tmp_path, monkeypatch):
    store = Store(tmp_path / "form.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Study"), "backcasting", "Future")
    store.save(session)
    fake = FakeAIProvider(
        "Confidence is 30 percent\nRisk is 8\nRating is 4 out of 5\nDeadline is 12 October 2026\nPhase 2"
    )

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(form_screen, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        ident = next(i for i, (path, _) in screen.fields.items() if path == ("future_state",))
        screen.suggest(ident)
        await screen.workers.wait_for_complete()
        assert screen.query_one("#form-preview", TextArea).text == "Phase 2"
        assert store.load(session.id).method_state == {}
        screen.query_one("#form-preview", TextArea).load_text("Risk is 8 — my own wording")
        screen.accept()
        await pilot.pause()
        assert store.load(session.id).method_state["future_state"] == "Risk is 8 — my own wording"
    store.close()


@pytest.mark.asyncio
async def test_guided_draft_filters_numeric_prose_and_preserves_user_edits(tmp_path, monkeypatch):
    store = Store(tmp_path / "guided.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Study"), "matrix", "Options")
    store.save(session)
    fake = FakeAIProvider("Risk is 8\nPhase 2\nDeadline is 12 October 2026\nQ3")

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(field_ai, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GuidedScreen)
        screen.query_one("#help-suggest-alternatives", Button).press()
        await pilot.pause()
        await screen.workers.wait_for_complete()
        assert screen.query_one("#field-help-preview", TextArea).text == "Phase 2\nQ3", str(
            screen.query_one("#field-help-status", Static).content
        )
        assert store.load(session.id).method_state == {}
        screen.query_one("#field-help-preview", TextArea).load_text("Rating is 4 out of 5 — my own wording")
        screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert screen.query_one("#field-alternatives", TextArea).text == "Rating is 4 out of 5 — my own wording"
        assert store.load(session.id).method_state == {}
    store.close()


@pytest.mark.asyncio
async def test_assumption_suggestion_and_challenge_filter_numeric_prose(tmp_path, monkeypatch):
    store = Store(tmp_path / "workspace.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Study"), "assumptions", "Hypotheses")
    store.save(session)
    fake = FakeAIProvider(json.dumps({"statement": "Risk is 8\nPhase 2"}))

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(screens, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Workspace)
        screen.query_one("#suggest", Button).press()
        await pilot.pause()
        await screen.workers.wait_for_complete()
        assert screen.query_one("#suggestion", Input).value == "Phase 2", str(
            screen.query_one("#ai-response", Static).content
        )
        assert store.load(session.id).method_state == {}
        fake.answer = "Risk is 8\nRating is 4 out of 5\nDeadline is 12 October 2026\nReview in Q3"
        screen.query_one("#challenge", Button).press()
        await pilot.pause()
        await screen.workers.wait_for_complete()
        message = str(screen.query_one("#ai-response", Static).content)
        assert "Review in Q3" in message
        assert all(judgment not in message for judgment in ("Risk is 8", "Rating is 4", "Deadline is 12"))
        assert store.load(session.id).method_state == {}
    store.close()


@pytest.mark.asyncio
async def test_duplicate_f2_rename_warns_without_dismissing_or_changing_data(tmp_path, monkeypatch):
    store = Store(tmp_path / "rename.db")
    project = store.new_project("Study")
    first, second = Session(project, "issue_tree", "First"), Session(project, "issue_tree", "Second")
    store.save(first)
    store.save(second)
    app = ThinkApp(store=store)
    notifications = []
    original_notify = app.notify

    def notify(message, **kwargs):
        notifications.append((message, kwargs.get("severity")))
        return original_notify(message, **kwargs)

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test() as pilot:
        app.project_id = project
        app.show_project()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProjectView)
        table = screen.query_one("#analyses", DataTable)
        table.move_cursor(row=screen.analysis_rows.index(first.id))
        table.focus()
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, AnalysisDialog)
        app.screen.query_one("#new-name", Input).value = "second"  # case-insensitive conflict
        events_before = len(store.events(first.id))
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, AnalysisDialog)
        assert app.screen.query_one("#new-name", Input).value == "second"
        assert store.load(first.id).title == "First"
        assert store.load(second.id).title == "Second"
        assert len(store.events(first.id)) == events_before
        assert any("already has this title" in text and severity == "warning" for text, severity in notifications)
        app.screen.query_one("#new-name", Input).value = "Distinct"
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        assert store.load(first.id).title == "Distinct"
    store.close()


@pytest.mark.asyncio
async def test_move_title_collision_warns_without_moving_or_overwriting(tmp_path, monkeypatch):
    store = Store(tmp_path / "move.db")
    source, target = store.new_project("Source"), store.new_project("Destination")
    moving = Session(source, "issue_tree", "Analysis")
    existing = Session(target, "issue_tree", "analysis")
    historical_duplicate = Session(target, "issue_tree", "analysis")
    store.save(moving)
    store.save(existing)
    store.save(historical_duplicate)  # preexisting duplicate titles remain readable, not migrated or renamed
    original_events = len(store.events(moving.id))
    with pytest.raises(ValueError, match="already has an analysis"):
        store.move_session(moving.id, target)
    assert store.load(moving.id).project_id == source
    assert len(store.events(moving.id)) == original_events
    app = ThinkApp(store=store)
    notifications = []
    original_notify = app.notify

    def notify(message, **kwargs):
        notifications.append((message, kwargs.get("severity")))
        return original_notify(message, **kwargs)

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test() as pilot:
        app.project_id = source
        app.show_project()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ProjectView)
        screen.query_one("#analyses", DataTable).focus()
        await pilot.press("ctrl+m")
        await pilot.pause()
        assert isinstance(app.screen, MoveAnalysisDialog)
        assert app.screen.query_one("#destination", Select).value == target
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, MoveAnalysisDialog)
        assert store.load(moving.id).project_id == source
        assert store.load(existing.id).project_id == target
        assert store.load(historical_duplicate.id).title == "analysis"
        assert len(store.sessions(target)) == 2
        assert len(store.events(moving.id)) == original_events
        assert any("already has an analysis" in text and severity == "warning" for text, severity in notifications)
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
    store.close()
