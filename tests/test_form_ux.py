"""Form regressions: blank drafts, legacy state and explicit example loading."""

import pytest
from textual.widgets import Button, Input, Select

from thinktui.ai import FakeAIProvider, ProviderConfig
from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.form_model import normalize_ids, parse, schema_for
from thinktui.form_screen import FormScreen
from thinktui.storage import Store


def test_schemas_cover_structured_methods_and_preserve_generated_references():
    for method in METHODS.values():
        if hasattr(method, "example"):
            assert {field.key for field in schema_for(method.id)} == set(method.example)
    state = {"nodes": [{"label": "A choice?", "parent_id": None}, {"label": "A choice?", "parent_id": None}]}
    normalize_ids(state)
    assert [node["id"] for node in state["nodes"]] == ["a-choice", "a-choice-2"]
    assert schema_for("objectives")[0].children[1].kind == "reference"


def test_numeric_and_date_validation():
    field = schema_for("backcasting")[1]
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse(field, "tomorrow")
    assert parse(field, "2030-01-01") == "2030-01-01"
    assert parse(schema_for("objectives")[0].children[1], "") is None


@pytest.mark.asyncio
async def test_blank_form_example_opt_in_and_resume(tmp_path):
    store = Store(tmp_path / "form.db")
    session = Session(store.new_project("Work"), "objectives", "Goals")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert session.method_state == {}
        app.screen.query_one("#group-0-add", Button).press()
        await pilot.pause()
        label = next(ident for ident, (path, _) in app.screen.fields.items() if path == ("nodes", 0, "label"))
        app.screen.query_one(f"#{label}", Input).value = "Customer value"
        await pilot.pause()
        assert session.method_state["nodes"][0]["id"] == "customer-value"
        app.open_session(store.load(session.id), guided=True)
        await pilot.pause()
        assert next(ident for ident, (path, _) in app.screen.fields.items() if path == ("nodes", 0, "label"))
        assert app.screen.query_one(f"#{label}", Input).value == "Customer value"
        app.screen.query_one("#load-example", Button).press()
        await pilot.pause()
        assert (
            session.method_state == METHODS["objectives"].example
            or app.session.method_state == METHODS["objectives"].example
        )
        assert app.screen.query_one(Select)
        assert "{" not in str(app.screen.query_one("#form-results"))


@pytest.mark.asyncio
async def test_ai_text_requires_accept_and_cannot_add_numeric_judgments(tmp_path, monkeypatch):
    from textual.widgets import Static, TextArea

    from thinktui import form_screen

    store = Store(tmp_path / "ai.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Planning"), "backcasting", "Future")
    store.save(session)
    fake = FakeAIProvider("Build a small pilot")

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(form_screen, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        field = next(k for k, (path, _) in app.screen.fields.items() if path == ("future_state",))
        app.screen.suggest(field)
        await pilot.pause()
        assert session.method_state == {}
        assert app.screen.query_one("#form-preview", TextArea).text == "Build a small pilot"
        assert fake.requests[0].context["problem"] == ""
        assert "notes" not in fake.requests[0].context
        app.screen.accept()
        await pilot.pause()
        assert store.load(session.id).method_state["future_state"] == "Build a small pilot"
        fake.answer = "Deadline 2028-12-31"
        app.screen.suggest(field)
        await pilot.pause()
        assert "numeric" in str(app.screen.query_one("#form-ai-status", Static).render())
        assert store.load(session.id).method_state["future_state"] == "Build a small pilot"
