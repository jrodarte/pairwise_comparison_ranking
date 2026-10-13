"""AI co-planner: opt-in, follows the user across screens, remembers only what the user approves."""

from copy import deepcopy

import pytest
from textual.containers import Horizontal
from textual.widgets import Button, Input, TextArea

from thinktui import coach
from thinktui.ai import CodexCLI, FakeAIProvider, ProviderConfig
from thinktui.ai_setup import AISetupDialog
from thinktui.app import ThinkApp
from thinktui.coach import START, CoachPanel, MemoryDialog, coach_context, split_proposals
from thinktui.core import Session
from thinktui.form_screen import FormScreen
from thinktui.safe_widgets import Static
from thinktui.screens import Home, ProjectView, Settings
from thinktui.storage import Store

STATE = {
    "criteria": [
        {"name": "Trust", "weight": 5.0, "direction": "benefit"},
        {"name": "Time to first demo", "weight": 2.0, "direction": "cost"},
    ],
    "alternatives": [{"name": "Scripted", "scores": [8.0, 7.0]}, {"name": "Bulk", "scores": [7.0, 3.0]}],
    "vary": "Time to first demo",
    "range": [0, 1],
}
ANSWER = (
    "Welcome! What are you planning, and what decision will it support?\n"
    "Then press M to add an Objectives Hierarchy.\n"
    "I suggest a weight of 4.5 for trust.\n"
    "REMEMBER: The user is a data governance lead learning structured planning."
)


def fake(monkeypatch, answer: str = ANSWER, url: str = "http://localhost:11434") -> FakeAIProvider:
    provider = FakeAIProvider(answer)

    async def connect(_store):
        return provider, ProviderConfig("ollama", url, "m")

    monkeypatch.setattr(coach, "connect", connect)
    return provider


def panel_text(app) -> str:
    panel = app.screen.query_one(CoachPanel)
    return "\n".join(str(w.render()) for w in panel.query("#coach-transcript Static").results(Static))


async def settle(pilot, times: int = 4) -> None:
    for _ in range(times):
        await pilot.pause()


def test_split_proposals_moves_remember_lines_out_of_the_reply():
    text, proposals = split_proposals("Do this next.\nremember:  Prefers checklists ")
    assert text == "Do this next." and proposals == ["Prefers checklists"]


def test_memory_and_messages_persist_and_project_delete_removes_its_messages(tmp_path):
    store = Store(tmp_path / "m.db")
    project = store.new_project("Pilot")
    store.add_coach_memory("  Prefers   short checklists ")
    store.add_coach_message("user", "hello", project)
    store.add_coach_message("coach", "global hi", None)
    with pytest.raises(ValueError):
        store.add_coach_memory("   ")
    reopened = Store(tmp_path / "m.db")
    assert [row["text"] for row in reopened.coach_memory()] == ["Prefers short checklists"]
    reopened.delete_project(project)
    assert [row["text"] for row in reopened.coach_messages()] == ["global hi"]
    assert "coach" not in str(reopened.snapshot(reopened.new_project("Other")))


@pytest.mark.asyncio
async def test_walkthrough_from_home_follows_user_across_screens(tmp_path, monkeypatch):
    provider = fake(monkeypatch)
    store = Store(tmp_path / "w.db")
    project = store.new_project("Forsyth lineage pilot")
    session = Session(project, "sensitivity", "4 Where · Sensitivity", method_state=deepcopy(STATE), notes="secret")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, Home) and not app.screen.query(CoachPanel)
        await pilot.press("p")
        await settle(pilot)
        assert app.screen.query_one(CoachPanel)
        request = provider.requests[0]
        assert START in request.question and request.context["screen"] == "Home"
        shown = panel_text(app)
        assert "What are you planning" in shown and "4.5" not in shown and "1 line(s) withheld" in shown
        assert "REMEMBER" not in shown
        # The proposal waits for the user's decision; nothing is remembered yet.
        assert store.coach_memory() == []
        assert app.coach.proposals == ["The user is a data governance lead learning structured planning."]
        app.screen.query_one("#coach-accept", Button).press()
        await settle(pilot)
        assert [row["text"] for row in store.coach_memory()] == [
            "The user is a data governance lead learning structured planning."
        ]
        # Moving to a project and an analysis keeps the panel and the conversation.
        app.project_id = project
        app.show_project()
        await settle(pilot)
        assert isinstance(app.screen, ProjectView) and app.screen.query_one(CoachPanel)
        assert "What are you planning" in panel_text(app)
        app.open_session(session, guided=True)
        await settle(pilot)
        assert isinstance(app.screen, FormScreen)
        app.screen.query_one("#coach-q", TextArea).load_text("What does the switch weight mean?")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        context = provider.requests[1].context
        assert context["screen"] == "Analysis form"
        assert context["project"]["name"] == "Forsyth lineage pilot"
        assert context["current_analysis"]["results"]["switch_weight"] is not None
        assert context["memory"] == ["The user is a data governance lead learning structured planning."]
        assert context["recent_conversation"][0]["text"] == START
        assert "secret" not in str(context)
        assert store.load(session.id).method_state == STATE  # advice never edits analyses


@pytest.mark.asyncio
async def test_coach_accepts_multiline_pasted_specification(tmp_path, monkeypatch):
    provider = fake(monkeypatch, "Let's break this down.")
    store = Store(tmp_path / "paste.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        assert box.has_focus
        await pilot.press("enter")
        assert box.text == "\n"  # Enter edits the draft; it does not send it.
        assert not provider.requests
        specification = "User story: plan an import\nAcceptance criteria:\n" + "- preserve pasted details\n" * 150
        box.load_text(specification)
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert box.text == ""
        assert len(provider.requests) == 1
        assert provider.requests[0].question.endswith("My message: " + specification.strip())
        assert store.coach_messages()[0]["text"] == specification.strip()
        assert specification.strip() in panel_text(app)


@pytest.mark.asyncio
async def test_chat_bubbles_align_wrap_and_keep_streaming_reply_in_place(tmp_path):
    store = Store(tmp_path / "bubbles.db")
    user_text = "[red]A question[/red]\n" + "a long wrapped line " * 12
    store.add_coach_message("user", user_text)
    store.add_coach_message("coach", "Here is a reply.")
    app = ThinkApp(store=store)
    async with app.run_test(size=(90, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        panel = app.screen.query_one(CoachPanel)
        transcript = panel.query_one("#coach-transcript")
        rows = list(transcript.query(".coach-message-row").results(Horizontal))
        assert len(rows) == 2
        user, reply = (row.query_one(".coach-bubble") for row in rows)
        assert user.region.x > reply.region.x  # sent right, received left
        assert user.region.right <= rows[0].region.right
        assert user.region.width < rows[0].region.width
        assert user.query_one(".coach-message", Static).region.height > 1
        assert str(user.query_one(".coach-message", Static).render()) == user_text
        assert str(user.query_one(".coach-sender", Static).render()) == "You"
        assert str(reply.query_one(".coach-sender", Static).render()) == "Co-planner"
        await pilot.resize_terminal(60, 40)
        await settle(pilot, 2)
        rows = list(transcript.query(".coach-message-row").results(Horizontal))
        assert rows[0].query_one(".coach-bubble").region.right <= transcript.region.right
        assert rows[1].query_one(".coach-bubble").region.x >= transcript.region.x

        app.coach.busy = True
        app.coach.partial = "Working"
        panel.refresh_view()
        await settle(pilot, 2)
        live = panel.query_one(".coach-live", Static)
        assert live.parent.has_class("coach-coach-bubble")
        app.coach.partial = "Working on it"
        panel.show_partial()
        assert panel.query_one(".coach-live", Static) is live
        assert str(live.render()) == "Working on it"
        app.coach.busy = False
        app.coach.partial = ""
        panel.refresh_view()
        await settle(pilot, 2)
        assert not panel.query(".coach-live")


@pytest.mark.asyncio
async def test_f10_toggles_and_open_state_survives_restart(tmp_path, monkeypatch):
    fake(monkeypatch)
    store = Store(tmp_path / "t.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await pilot.press("f10")
        await settle(pilot, 2)
        assert app.screen.query_one(CoachPanel)
        assert app.screen.query_one("#coach-q", TextArea).has_focus
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, 2)
        assert app.screen.query_one(CoachPanel)
        await pilot.press("f10")
        await settle(pilot, 2)
        assert not app.screen.query(CoachPanel)


@pytest.mark.asyncio
async def test_coach_respects_ai_off_consent_and_remember_command(tmp_path, monkeypatch):
    provider = fake(monkeypatch, url="https://api.example.com/v1")
    store = Store(tmp_path / "c.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.coach.ask("Help me plan")
        await settle(pilot)
        assert not provider.requests and "consent" in app.coach.status
        assert isinstance(app.screen, AISetupDialog)
        await pilot.press("escape")
        assert store.coach_messages() == []  # A rejected request is not a conversation turn.
        app.action_coach()
        await settle(pilot, 2)
        draft = app.screen.query_one("#coach-q", TextArea)
        draft.load_text("Help me plan")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert draft.text == "Help me plan" and store.coach_messages() == []
        assert isinstance(app.screen, AISetupDialog)
        await pilot.press("escape")
        await settle(pilot, 2)
        store.set_settings({"ai.ollama.consent": "yes", "ai.ollama.consent_url": "https://api.example.com/v1"})
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert draft.text == "" and len(provider.requests) == 1
        assert [row["role"] for row in store.coach_messages()] == ["user", "coach"]
        store.set_setting("ai_provider", "off")
        draft.load_text("A long draft\nwith another line")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot, 2)
        assert draft.text == "A long draft\nwith another line"
        assert "AI is off" in app.coach.status and len(provider.requests) == 1
        app.coach.ask("/remember I prefer short checklists")
        assert [row["text"] for row in store.coach_memory()] == ["I prefer short checklists"]


@pytest.mark.asyncio
async def test_memory_dialog_adds_deletes_and_clears(tmp_path):
    store = Store(tmp_path / "d.db")
    store.add_coach_memory("Old fact")
    store.add_coach_message("user", "hi")
    app = ThinkApp(store=store)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.push_screen(MemoryDialog())
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#memory-new", Input).value = "New fact"
        await pilot.press("enter")
        await pilot.pause()
        assert [row["text"] for row in store.coach_memory()] == ["Old fact", "New fact"]
        dialog.query_one("#memory-list").value = store.coach_memory()[0]["id"]
        dialog.query_one("#memory-delete", Button).press()
        await pilot.pause()
        assert [row["text"] for row in store.coach_memory()] == ["New fact"]
        dialog.query_one("#memory-clear-chat", Button).press()
        dialog.query_one("#memory-clear", Button).press()
        await pilot.pause()
        assert store.coach_memory() == [] and store.coach_messages() == []


@pytest.mark.asyncio
async def test_chatgpt_prompts_for_login_before_sending_and_opens_settings(tmp_path, monkeypatch):
    class SignedOut(CodexCLI):
        def __init__(self):
            super().__init__(binary="codex")
            self.sent = False

        async def health_check(self):
            raise RuntimeError("Not signed in to ChatGPT")

        async def stream(self, request):
            self.sent = True
            yield "should never send"

    provider = SignedOut()

    async def connect(_store):
        return provider, ProviderConfig("chatgpt", "", "")

    monkeypatch.setattr(coach, "connect", connect)
    store = Store(tmp_path / "login.db")
    store.set_settings({"ai_provider": "chatgpt", "ai.chatgpt.consent": "yes"})
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        box.load_text("Plan this")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        dialog = app.screen
        assert isinstance(dialog, AISetupDialog)
        assert "Sign in required" in str(dialog.query_one(".hero").render())
        assert not provider.sent and store.coach_messages() == []
        assert box.text == "Plan this"
        dialog.query_one("#setup-settings", Button).press()
        await settle(pilot)
        assert isinstance(app.screen, Settings)
        assert app.screen.query_one("#signin", Button).has_focus


@pytest.mark.asyncio
async def test_signed_in_subscription_sends_after_consent(tmp_path, monkeypatch):
    class SignedIn(CodexCLI):
        def __init__(self):
            super().__init__(binary="codex")
            self.requests = []

        async def health_check(self):
            return "Signed in"

        async def stream(self, request):
            self.requests.append(request)
            yield "Check your assumptions."

    provider = SignedIn()

    async def connect(_store):
        return provider, ProviderConfig("chatgpt", "", "")

    monkeypatch.setattr(coach, "connect", connect)
    store = Store(tmp_path / "signed-in.db")
    store.set_settings({"ai_provider": "chatgpt", "ai.chatgpt.consent": "yes"})
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        box.load_text("What next?")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert len(provider.requests) == 1
        assert store.coach_messages()[-1]["text"] == "Check your assumptions."
        assert box.text == "" and not isinstance(app.screen, AISetupDialog)


@pytest.mark.asyncio
async def test_missing_api_key_prompts_for_settings_without_sending(tmp_path, monkeypatch):
    async def connect(_store):
        raise RuntimeError("No API key for OpenAI API. Add one in Settings")

    monkeypatch.setattr(coach, "connect", connect)
    store = Store(tmp_path / "key.db")
    store.set_setting("ai_provider", "openai")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        box.load_text("Plan this")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert isinstance(app.screen, AISetupDialog)
        assert box.text == "Plan this" and store.coach_messages() == []
        app.screen.query_one("#setup-settings", Button).press()
        await settle(pilot)
        assert isinstance(app.screen, Settings)
        assert app.screen.query_one("#api-key", Input).has_focus


@pytest.mark.asyncio
@pytest.mark.parametrize("preset_id", ["openai", "custom"])
async def test_rejected_api_key_prompts_without_losing_coach_draft(tmp_path, monkeypatch, preset_id):
    class Rejected:
        async def stream(self, request):
            raise RuntimeError("AI request failed (HTTP 401: authentication failed; check the API key)")
            yield ""

    async def connect(_store):
        return Rejected(), ProviderConfig(preset_id, "https://example.org/v1", "model")

    monkeypatch.setattr(coach, "connect", connect)
    store = Store(tmp_path / "rejected.db")
    store.set_settings(
        {
            "ai_provider": preset_id,
            f"ai.{preset_id}.consent": "yes",
            f"ai.{preset_id}.consent_url": "https://example.org/v1",
        }
    )
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        box.load_text("Keep this draft")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert isinstance(app.screen, AISetupDialog)
        assert app.screen.issue.kind == "api_key"
        assert box.text == "Keep this draft"
        assert store.coach_messages() == []
        app.screen.query_one("#setup-settings", Button).press()
        await settle(pilot)
        assert isinstance(app.screen, Settings)
        assert app.screen.query_one("#api-key", Input).has_focus


@pytest.mark.asyncio
async def test_subscription_failure_gives_actionable_status_without_exposing_provider_output(tmp_path, monkeypatch):
    class FailingProvider:
        async def stream(self, request):
            raise RuntimeError("Codex CLI failed: secret in vendor output. Use Sign in under Settings")
            yield ""

    async def connect(_store):
        return FailingProvider(), ProviderConfig("chatgpt", "", "")

    monkeypatch.setattr(coach, "connect", connect)
    store = Store(tmp_path / "subscription.db")
    store.set_settings({"ai_provider": "chatgpt", "ai.chatgpt.consent": "yes"})
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f10")
        await settle(pilot, 2)
        box = app.screen.query_one("#coach-q", TextArea)
        box.load_text("Help me plan")
        app.screen.query_one("#coach-ask", Button).press()
        await settle(pilot)
        assert "Sign in and Test connection in Settings" in app.coach.status
        assert "secret" not in app.coach.status
        assert not app.coach.busy


def test_doctor_accepts_current_schema(tmp_path, monkeypatch, capsys):
    import sys

    from thinktui import __main__

    Store(tmp_path / "thinktui.db").close()
    monkeypatch.setattr(__main__, "user_data_path", lambda _name: tmp_path)
    monkeypatch.setattr(sys, "argv", ["thinktui", "doctor"])
    __main__.main()
    output = capsys.readouterr().out
    assert "Schema version: 7" in output
    assert "requires a newer ThinkTUI" not in output


def test_context_outside_projects_omits_project(tmp_path):
    store = Store(tmp_path / "x.db")

    class FakeApp:
        def __init__(self):
            self.store = store
            self.project_id = None
            self.screen_stack = [Home()]
            self.screen = self.screen_stack[0]
            self.session = None

    context = coach_context(FakeApp())
    assert context["screen"] == "Home" and "project" not in context and "current_analysis" not in context
    assert "Weighted Decision Matrix" in context["app_guide"]
