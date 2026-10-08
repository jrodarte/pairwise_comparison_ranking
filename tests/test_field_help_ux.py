"""Text-only suggestions across the six no-JSON workflows (never AI numeric judgments)."""

import pytest
from textual.widgets import Button, Input, Static, TextArea

from thinktui import field_ai
from thinktui.ai import FakeAIProvider, ProviderConfig
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.guided_screen import GuidedScreen
from thinktui.screens import Workspace
from thinktui.storage import Store


@pytest.mark.asyncio
async def test_guided_matrix_suggests_editable_rows_without_weights_or_scores(tmp_path, monkeypatch):
    store = Store(tmp_path / "matrix.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Plan"), "matrix", "Choose", problem_statement="What should we try?")
    session.notes = "private note"
    store.save(session)
    fake = FakeAIProvider("Pilot\nDo nothing")

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(field_ai, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        app.screen.query_one("#help-suggest-alternatives", Button).press()
        await pilot.pause()
        assert session.method_state == {}
        assert fake.requests[0].context["problem"] == "What should we try?"
        assert "notes" not in fake.requests[0].context
        app.screen.query_one("#field-help-preview", TextArea).load_text("Local trial\nWait")
        app.screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert app.screen.query_one("#field-alternatives", TextArea).text == "Local trial\nWait"
        assert session.method_state == {}  # still only a draft until Validate & next
        await app.screen.action_next()
        assert [row["name"] for row in session.method_state["alternatives"]] == ["Local trial", "Wait"]
        assert all(row["scores"] == [] for row in session.method_state["alternatives"])
        fake.answer = "Quality\nCost"
        app.screen.query_one("#help-suggest-criteria", Button).press()
        await pilot.pause()
        app.screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert "weight" in str(app.screen.query_one("#guided-error-criteria", Static).content).lower()
        app.screen.query_one("#field-criteria", TextArea).load_text("Quality | 3 | benefit\nCost | 2 | cost")
        await pilot.pause()
        assert not str(app.screen.query_one("#guided-error-criteria", Static).content)
        await app.screen.action_next()
        assert [row["weight"] for row in session.method_state["criteria"]] == [3, 2]
        assert not app.screen.query("#help-suggest-score_0_0")
        assert any("Why:" in str(widget.content) for widget in app.screen.query(Static))


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", ["assumptions", "premortem"])
async def test_dedicated_fields_and_rows_require_accept_and_user_ratings(tmp_path, monkeypatch, method_id):
    store = Store(tmp_path / f"{method_id}.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Plan"), method_id, "Risk")
    store.save(session)
    fake = FakeAIProvider("Try a small pilot")

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(field_ai, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        app.screen.query_one("#help-entry", Button).press()
        await pilot.pause()
        assert not session.method_state.get("entries")
        assert app.screen.query_one("#entry", Input).value == ""
        app.screen.query_one("#field-help-preview", TextArea).load_text("Test if demand persists")
        app.screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert app.screen.query_one("#entry", Input).value == "Test if demand persists"
        assert not app.screen.query_one("#confidence", Input).value
        app.screen.query_one("#confidence", Input).value = "130"
        await pilot.pause()
        assert "0 to 100" in str(app.screen.query_one("#dedicated-feedback", Static).content)
        app.screen.query_one("#confidence", Input).value = "40"
        app.screen.query_one("#impact", Input).value = "8"
        await pilot.pause()
        assert "Local risk priority preview" in str(app.screen.query_one("#dedicated-feedback", Static).content)
        assert app.screen.add_entry()
        saved = store.load(session.id).method_state["entries"][0]
        assert saved["statement"] == "Test if demand persists"
        assert saved["impact"] == 8 and saved["confidence"] == 40
        assert saved["source"] == "AI_ACCEPTED"
        assert not app.screen.query_one("#confidence", Input).value  # no rating carried to next row
        fake.answer = "Review supply\nCheck throughput"
        app.screen.query_one("#help-rows", Button).press()
        await pilot.pause()
        app.screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert app.screen.query_one("#entry", Input).value == "Review supply"
        assert app.screen.pending_ai_rows == ["Review supply", "Check throughput"]
        assert len(store.load(session.id).method_state["entries"]) == 1
        assert store.load(session.id).method_state["_text_row_drafts"] == ["Review supply", "Check throughput"]
        app.open_session(store.load(session.id))
        await pilot.pause()
        assert app.screen.query_one("#entry", Input).value == "Review supply"
        app.screen.query_one("#confidence", Input).value = "20"
        app.screen.query_one("#impact", Input).value = "7"
        assert app.screen.add_entry()
        assert app.screen.query_one("#entry", Input).value == "Check throughput"
        assert app.screen.query_one("#confidence", Input).value == ""
        assert store.load(session.id).method_state["_text_row_drafts"] == ["Check throughput"]
        fake.answer = "Score 90"
        app.screen.query_one("#help-action", Button).press()
        await pilot.pause()
        assert "numeric" in str(app.screen.query_one("#field-help-status", Static).content)
        app.screen.query_one("#help-accept", Button).press()
        assert app.screen.query_one("#action", Input).value == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", ["matrix", "premortem"])
async def test_stop_with_focused_editor_never_accepts_partial(tmp_path, monkeypatch, method_id):
    import asyncio

    store = Store(tmp_path / f"stop-{method_id}.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Plan"), method_id, "Draft")
    store.save(session)
    waiting = asyncio.Event()

    class SlowProvider:
        async def stream(self, _request):
            yield "Partial draft"
            await waiting.wait()

    async def connect(_):
        return SlowProvider(), ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(field_ai, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=method_id == "matrix")
        await pilot.pause()
        if method_id == "matrix":
            app.screen.query_one("#field-alternatives", TextArea).focus()
            app.screen.query_one("#help-suggest-alternatives", Button).press()
        else:
            app.screen.query_one("#entry", Input).focus()
            app.screen.query_one("#help-entry", Button).press()
        await pilot.pause()
        await pilot.press("ctrl+g")
        assert app.screen.query_one("#field-help-preview", TextArea).text == "Partial draft"
        app.screen.query_one("#help-accept", Button).press()
        await pilot.pause()
        assert store.load(session.id).method_state == {}
        waiting.set()


@pytest.mark.asyncio
async def test_ai_error_does_not_expose_credentials(tmp_path, monkeypatch):
    store = Store(tmp_path / "error.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Plan"), "matrix", "Draft")
    store.save(session)

    async def connect(_):
        raise RuntimeError("secret-token-123")

    monkeypatch.setattr(field_ai, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#help-suggest-alternatives", Button).press()
        await pilot.pause()
        message = str(app.screen.query_one("#field-help-status", Static).content)
        assert "unavailable" in message and "secret-token" not in message
        assert store.load(session.id).method_state == {}


@pytest.mark.asyncio
async def test_remote_consent_and_off_mode_do_not_send_field_help(tmp_path, monkeypatch):
    store = Store(tmp_path / "consent.db")
    session = Session(store.new_project("Plan"), "premortem", "Plan")
    store.save(session)
    fake = FakeAIProvider("Check the plan")

    async def connect(_):
        return fake, ProviderConfig("openai", "https://example.org/v1", "fake")

    monkeypatch.setattr(field_ai, "connect", connect)
    store.set_setting("ai_provider", "openai")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        app.screen.query_one("#help-entry", Button).press()
        await pilot.pause()
        assert not fake.requests
        assert "consent" in str(app.screen.query_one("#field-help-status", Static).content)
        store.set_setting("ai_provider", "off")
        app.screen.query_one("#help-entry", Button).press()
        await pilot.pause()
        assert not fake.requests
        assert "off" in str(app.screen.query_one("#field-help-status", Static).content)
