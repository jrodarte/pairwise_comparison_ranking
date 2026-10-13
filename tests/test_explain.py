"""Explain results: an opt-in, display-only AI tutor that may only quote numbers the user already has."""

from copy import deepcopy

import pytest
from textual.widgets import Button, Input

from thinktui import explain
from thinktui.ai import FakeAIProvider, ProviderConfig
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.explain import ExplainDialog, explain_context, grounded
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.reports import decision_brief, plain_result
from thinktui.safe_widgets import Static
from thinktui.screens import Workspace
from thinktui.storage import Store

STATE = {
    "criteria": [
        {"name": "Trust in lineage", "weight": 5.0, "direction": "benefit"},
        {"name": "Coverage", "weight": 5.0, "direction": "benefit"},
        {"name": "Upkeep", "weight": 1.0, "direction": "cost"},
        {"name": "Effort", "weight": 3.0, "direction": "cost"},
        {"name": "Time to first demo", "weight": 2.0, "direction": "cost"},
    ],
    "alternatives": [
        {"name": "Scripted (API-based) ingestion", "scores": [8.0, 8.0, 3.0, 2.0, 7.0]},
        {"name": "Bulk import", "scores": [7.0, 8.0, 4.0, 3.0, 3.0]},
    ],
    "vary": "Time to first demo",
    "range": [0, 1],
}

ANSWER = (
    "The switch weight is about 0.138, or 13.8% of the total weight.\n"
    "Today Time to first demo holds 0.125 of the weight.\n"
    "Raising the weight to 2.25 would flip the result.\n"
    "Scripted scores 9 on trust.\n"
    "So the two options are close."
)


def session_in(store: Store, notes: str = "") -> Session:
    session = Session(
        store.new_project("Explain"), "sensitivity", "4 Where · Sensitivity", method_state=deepcopy(STATE), notes=notes
    )
    store.save(session)
    return session


def fake(monkeypatch, answer: str = ANSWER, url: str = "http://localhost:11434") -> FakeAIProvider:
    provider = FakeAIProvider(answer)

    async def connect(_store):
        return provider, ProviderConfig("ollama", url, "m")

    monkeypatch.setattr(explain, "connect", connect)
    return provider


def transcript(screen) -> str:
    return "\n".join(str(widget.render()) for widget in screen.query("#explain-transcript Static").results(Static))


def test_grounded_keeps_quoted_and_rounded_numbers_and_withholds_new_ones(tmp_path):
    context = explain_context(session_in(Store(tmp_path / "g.db")))
    text, withheld = grounded(ANSWER, context)
    assert "0.138" in text and "13.8%" in text and "0.125" in text and "close" in text
    assert "2.25" not in text and "scores 9" not in text
    assert withheld == 2


def test_grounded_ignores_list_markers():
    text, withheld = grounded("1. First idea\n2) Second idea", {"results": {}})
    assert withheld == 0 and "Second idea" in text


def test_context_shares_results_and_local_share_but_not_notes(tmp_path):
    context = explain_context(session_in(Store(tmp_path / "c.db"), notes="private"))
    assert context["results"]["switch_weight"] == pytest.approx(0.13846, abs=1e-4)
    assert context["derived_locally"] == {"current_share_of_varied_criterion": 0.125}
    assert "private" not in str(context) and "notes" not in context


def test_context_for_incomplete_analysis_has_no_results(tmp_path):
    store = Store(tmp_path / "i.db")
    session = session_in(store)
    session.method_state["criteria"].append({"name": "", "weight": "", "direction": ""})
    assert explain_context(session)["results"] is None


@pytest.mark.asyncio
async def test_form_f9_explains_without_saving_and_follow_up_carries_history(tmp_path, monkeypatch):
    provider = fake(monkeypatch)
    store = Store(tmp_path / "f.db")
    session = session_in(store)
    before = store.load(session.id).method_state
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        await pilot.press("f9")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ExplainDialog)
        assert not provider.requests  # nothing is shared until the user asks
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert explain.DEFAULT_QUESTION in provider.requests[0].question
        assert provider.requests[0].context["results"]["switch_weight"] == pytest.approx(0.13846, abs=1e-4)
        shown = transcript(dialog)
        assert "0.138" in shown and "2.25" not in shown and "2 line(s) withheld" in shown
        dialog.query_one("#explain-q", Input).value = "Why does a cost criterion favour Bulk import?"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        follow_up = provider.requests[1].question
        assert "Why does a cost criterion" in follow_up and "Earlier question" in follow_up
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
    assert store.load(session.id).method_state == before


@pytest.mark.asyncio
async def test_explain_respects_ai_off_and_remote_consent(tmp_path, monkeypatch):
    provider = fake(monkeypatch, url="https://api.example.com/v1")
    store = Store(tmp_path / "o.db")
    session = session_in(store)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(ExplainDialog(session))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert not provider.requests
        assert app.screen.__class__.__name__ == "AISetupDialog"
        await pilot.press("escape")
        store.set_setting("ai_provider", "off")
        await pilot.press("enter")
        await pilot.pause()
        assert "AI is off" in str(app.screen.query_one("#explain-status", Static).render())
        assert not provider.requests


@pytest.mark.asyncio
async def test_guided_and_workspace_offer_explain(tmp_path, monkeypatch):
    fake(monkeypatch)
    store = Store(tmp_path / "w.db")
    matrix = Session(
        store.new_project("Choice"),
        "matrix",
        "Build or buy",
        method_state={
            "criteria": [{"name": "Benefit", "weight": 3, "direction": "benefit"}, {"name": "Effort", "weight": 1}],
            "alternatives": [{"name": "Build", "scores": [9, 8]}, {"name": "Buy", "scores": [6, 2]}],
            "_guided_step": 3,
        },
    )
    store.save(matrix)
    app = ThinkApp(store=store)
    async with app.run_test(size=(140, 50)) as pilot:
        app.open_session(matrix, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        app.screen.query_one("#explain", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ExplainDialog)
        await pilot.press("escape")
        await pilot.pause()
        app.open_session(matrix, advanced=True)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        app.screen.query_one("#explain", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ExplainDialog)


def test_results_keep_user_spelling_of_option_names():
    shown = plain_result({"switch_weight": 0.1, "endpoints": [{"scores": {"Scripted (API-based) ingestion": 3.0}}]})
    assert "Switch weight: 0.1" in shown and "Scripted (API-based) ingestion: 3.0" in shown


def test_brief_keeps_option_names(tmp_path):
    brief = decision_brief(session_in(Store(tmp_path / "b.db")))
    assert "(api-based)" not in brief and "Scripted (API-based) ingestion: 7.92" in brief


@pytest.mark.asyncio
async def test_export_folder_is_remembered_between_sessions(tmp_path):
    store = Store(tmp_path / "dir.db")
    app = ThinkApp(store=store)
    async with app.run_test():
        assert app.last_export_dir is None
        app.last_export_dir = tmp_path
    assert ThinkApp(store=store).last_export_dir == tmp_path
