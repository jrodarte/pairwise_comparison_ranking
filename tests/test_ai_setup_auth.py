"""A rejected API credential opens the same safe setup path from every AI surface."""

import pytest
from textual.widgets import Button, Input

from thinktui import explain, field_ai, form_screen, screens
from thinktui.ai import ProviderConfig
from thinktui.ai_setup import AISetupDialog
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.explain import ExplainDialog
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.screens import Workspace
from thinktui.storage import Store


@pytest.mark.asyncio
@pytest.mark.parametrize("preset_id", ["openai", "custom"])
@pytest.mark.parametrize("entry", ["explain", "workspace", "field", "guided", "form"])
async def test_http_401_opens_api_key_settings_without_accepting_ai_text(tmp_path, monkeypatch, preset_id, entry):
    class Rejected:
        async def preparing_note(self):
            return ""

        async def stream(self, request):
            raise RuntimeError("AI request failed (HTTP 401: authentication failed; check the API key)")
            yield ""

    async def connect(_store):
        return Rejected(), ProviderConfig(preset_id, "https://example.org/v1", "model")

    module = {"explain": explain, "workspace": screens, "field": field_ai, "guided": field_ai, "form": form_screen}[
        entry
    ]
    monkeypatch.setattr(module, "connect", connect)
    store = Store(tmp_path / "ai.db")
    store.set_settings(
        {
            "ai_provider": preset_id,
            f"ai.{preset_id}.consent": "yes",
            f"ai.{preset_id}.consent_url": "https://example.org/v1",
        }
    )
    method_id = "matrix" if entry == "guided" else "backcasting" if entry == "form" else "premortem"
    session = Session(store.new_project("Plan"), method_id, "Work")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 45)) as pilot:
        if entry == "explain":
            app.push_screen(ExplainDialog(session))
            await pilot.pause()
            await pilot.press("enter")
        else:
            app.open_session(session, guided=entry in {"guided", "form"})
            await pilot.pause()
            if entry == "workspace":
                assert isinstance(app.screen, Workspace)
                app.screen.query_one("#challenge", Button).press()
            elif entry == "field":
                app.screen.query_one("#help-entry", Button).press()
            elif entry == "guided":
                assert isinstance(app.screen, GuidedScreen)
                app.screen.query_one("#help-suggest-alternatives", Button).press()
            else:
                assert isinstance(app.screen, FormScreen)
                field = next(k for k, (path, _) in app.screen.fields.items() if path == ("future_state",))
                app.screen.query_one(f"#suggest-{field}", Button).press()
        for _ in range(5):
            await pilot.pause()
        assert isinstance(app.screen, AISetupDialog)
        assert app.screen.issue.kind == "api_key"
        app.screen.query_one("#setup-settings", Button).press()
        for _ in range(4):
            await pilot.pause()
        assert app.screen.query_one("#api-key", Input).has_focus
    assert store.load(session.id).method_state == {}


def test_http_403_and_non_api_providers_do_not_claim_a_bad_key(tmp_path):
    from thinktui.ai_setup import prompt_missing_key

    store = Store(tmp_path / "ai.db")

    class App:
        def __init__(self):
            self.store = store
            self.prompted = False

        def push_screen(self, _screen):
            self.prompted = True

    app = App()
    for choice, failure in (
        ("openai", "AI request failed (HTTP 403: access denied; check the API key and account permissions)"),
        ("custom", "AI request failed (HTTP 403: access denied; check the API key and account permissions)"),
        ("openai", "HTTP 401 secret provider response"),
        ("ollama", "AI request failed (HTTP 401: authentication failed; check the API key)"),
        ("chatgpt", "AI request failed (HTTP 401: authentication failed; check the API key)"),
    ):
        store.set_setting("ai_provider", choice)
        assert not prompt_missing_key(app, RuntimeError(failure))
        assert not app.prompted
