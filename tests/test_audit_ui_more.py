"""Pilot regressions for deliberate editing, providers and non-destructive exports."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from textual.widgets import Button, DataTable, Input, Select, TextArea

from thinktui.ai import ProviderConfig, remote_consent
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.guided_screen import GuidedScreen
from thinktui.guided_workflow import LabelMappingRequired, ScenarioMappingRequired, advance, final_index
from thinktui.reports import export
from thinktui.screens import HelpDialog, Settings, Workspace
from thinktui.storage import Store


@pytest.mark.parametrize("method", ["assumptions", "premortem"])
@pytest.mark.asyncio
async def test_dedicated_entry_edit_and_confirmed_delete(tmp_path, method):
    store = Store(tmp_path / "entries.db")
    session = Session(
        store.new_project("Work"),
        method,
        "Review",
        method_state={
            "entries": [
                {
                    "statement": "Original",
                    "action": "Check",
                    "confidence": 20,
                    "likelihood": 20,
                    "impact": 9,
                    "source": "USER",
                }
            ]
        },
        completed_at="2025-01-01T00:00:00+00:00",
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Workspace)
        table = screen.query_one("#entry-list", DataTable)
        assert ("7.2" if method == "assumptions" else "180") in str(table.get_row_at(0))
        screen.query_one("#edit-entry", Button).press()
        await pilot.pause()
        assert screen.query_one("#entry", Input).value == "Original"
        screen.query_one("#entry", Input).value = "Revised"
        screen.query_one("#add", Button).press()
        await pilot.pause()
        assert len(store.load(session.id).method_state["entries"]) == 1
        assert store.load(session.id).method_state["entries"][0]["statement"] == "Revised"
        assert store.load(session.id).completed_at is None
        screen.query_one("#delete-entry", Button).press()
        await pilot.pause()
        await pilot.click("#cancel")
        assert len(store.load(session.id).method_state["entries"]) == 1
        screen.query_one("#delete-entry", Button).press()
        await pilot.pause()
        await pilot.click("#confirm")
        assert store.load(session.id).method_state["entries"] == []
    store.close()


@pytest.mark.asyncio
async def test_settings_no_key_sign_in_no_crash_and_no_auto_refresh(tmp_path, monkeypatch):
    store = Store(tmp_path / "settings.db")
    store.set_setting("ai_provider", "openai")
    app = ThinkApp(store=store, initial="settings")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, Settings)
        await pilot.press("ctrl+l")
        assert isinstance(app.screen, Settings)
        app.screen.query_one("#provider", Select).value = "off"
        await pilot.pause()
        await pilot.press("ctrl+l")
        assert isinstance(app.screen, Settings)
    store.close()


def test_guided_judgment_label_mapping_is_explicit_and_lossless():
    state = {
        "hypotheses": ["Fault", "Normal"],
        "evidence": [{"title": "Logs", "source": "Ops", "reliability": 0.7, "ratings": {"Fault": "+", "Normal": "-"}}],
    }
    values = {"hypotheses": "Healthy\nBroken"}
    with pytest.raises(LabelMappingRequired):
        advance("ach", state, 0, values)
    with pytest.raises(ValueError):
        advance("ach", state, 0, values, mapping=[0, 0])
    renamed = advance("ach", state, 0, values, mapping=[1, 0])
    assert renamed["evidence"][0]["ratings"] == {"Healthy": "-", "Broken": "+"}
    assert state["hypotheses"] == ["Fault", "Normal"]

    ahp = {
        "criteria": ["Value", "Cost"],
        "alternatives": ["A", "B"],
        "criteria_matrix": [[1, 3], [1 / 3, 1]],
        "alternative_matrices": {"Value": [[1, 5], [0.2, 1]], "Cost": [[1, 2], [0.5, 1]]},
    }
    with pytest.raises(LabelMappingRequired):
        advance("ahp", ahp, 0, {"criteria": "Expense\nBenefit"})
    updated = advance("ahp", ahp, 0, {"criteria": "Expense\nBenefit"}, mapping=[1, 0])
    assert updated["criteria_matrix"][0][1] == 1 / 3
    assert updated["alternative_matrices"]["Expense"] == ahp["alternative_matrices"]["Cost"]
    updated = advance("ahp", updated, 1, {"alternatives": "B copy\nA copy"}, mapping=[1, 0])
    assert updated["alternative_matrices"]["Benefit"][0][1] == 0.2

    from thinktui.guided_workflow import QUADRANTS

    scenarios = {
        "question": "Which growth path?",
        "drivers": ["Demand", "Regulation"],
        "axes": [
            {"name": "Demand", "low": "Low", "high": "High"},
            {"name": "Regulation", "low": "Loose", "high": "Strict"},
        ],
        "scenarios": {q: {"name": q, "narrative": "Reviewed", "implications": [], "indicators": []} for q in QUADRANTS},
        "strategies": [{"name": "Hedge", "actions": {q: f"Action {q}" for q in QUADRANTS}}],
    }
    reversed_demand = {
        "axis_0_name": "Demand",
        "axis_0_low": "High",
        "axis_0_high": "Low",
        "axis_1_name": "Regulation",
        "axis_1_low": "Loose",
        "axis_1_high": "Strict",
    }
    with pytest.raises(ScenarioMappingRequired):
        advance("scenarios", scenarios, 1, reversed_demand)
    remapped = advance("scenarios", scenarios, 1, reversed_demand, mapping=[2, 3, 0, 1])
    assert remapped["scenarios"]["low_low"]["name"] == "high_low"
    assert remapped["strategies"][0]["actions"]["low_low"] == "Action high_low"
    assert scenarios["scenarios"]["low_low"]["name"] == "low_low"


@pytest.mark.asyncio
async def test_guided_label_mapping_dialog_preserves_evidence(tmp_path):
    store = Store(tmp_path / "labels.db")
    session = Session(
        store.new_project("Study"),
        "ach",
        "Diagnosis",
        method_state={
            "hypotheses": ["Fault", "Normal"],
            "evidence": [
                {"title": "Log", "source": "Ops", "reliability": 0.7, "ratings": {"Fault": "+", "Normal": "-"}}
            ],
            "_guided_step": 0,
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#field-hypotheses", TextArea).load_text("Healthy\nBroken")
        await screen.action_next()
        await pilot.pause()
        assert app.screen.query_one("#label-source-0", Select)
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert store.load(session.id).method_state["hypotheses"] == ["Fault", "Normal"]
        await screen.action_next()
        await pilot.pause()
        app.screen.query_one("#label-source-0", Select).value = 1
        app.screen.query_one("#label-source-1", Select).value = 0
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert store.load(session.id).method_state["evidence"][0]["ratings"] == {"Healthy": "-", "Broken": "+"}
    store.close()


@pytest.mark.parametrize("method", ["ach", "scenarios"])
@pytest.mark.asyncio
async def test_guided_saved_row_edit_and_delete(tmp_path, method):
    store = Store(tmp_path / "guided.db")
    if method == "ach":
        state = {
            "hypotheses": ["Failure", "Normal"],
            "evidence": [
                {
                    "title": "Observed logs",
                    "source": "Operator",
                    "reliability": 0.7,
                    "ratings": {"Failure": "+", "Normal": "-"},
                }
            ],
        }
        name_key, rows_key = "title", "evidence"
    else:
        from thinktui.guided_workflow import QUADRANTS

        state = {
            "question": "Will demand change?",
            "drivers": ["Policy", "Revenue"],
            "axes": [
                {"name": "Policy", "low": "Slow", "high": "Fast"},
                {"name": "Revenue", "low": "Low", "high": "High"},
            ],
            "scenarios": {
                q: {"name": q, "narrative": "Observed trajectory", "implications": ["Plan"], "indicators": ["Orders"]}
                for q in QUADRANTS
            },
            "strategies": [{"name": "Pilot", "actions": {q: "Prepare" for q in QUADRANTS}}],
        }
        name_key, rows_key = "name", "strategies"
    state["_guided_step"] = final_index(method, state)
    session = Session(
        store.new_project("Study"),
        method,
        "Scenario or evidence",
        method_state=state,
        completed_at="2025-01-01T00:00:00+00:00",
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GuidedScreen)
        await screen.action_edit_saved()
        assert screen.query_one(f"#field-{name_key}", Input).value == state[rows_key][0][name_key]
        screen.query_one(f"#field-{name_key}", Input).value = "Updated user entry"
        await screen.action_next()
        await pilot.pause()
        assert len(store.load(session.id).method_state[rows_key]) == 1
        assert store.load(session.id).method_state[rows_key][0][name_key] == "Updated user entry"
        assert store.load(session.id).completed_at is None
        await screen.action_review()
        screen.action_delete_saved()
        await pilot.pause()
        await pilot.click("#cancel")
        assert len(store.load(session.id).method_state[rows_key]) == 1
        screen.action_delete_saved()
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert store.load(session.id).method_state[rows_key] == []
    store.close()


@pytest.mark.asyncio
async def test_guided_forecast_picker_resolves_older_forecast(tmp_path):
    store = Store(tmp_path / "forecasts.db")
    state = {
        "forecasts": [
            {"question": "Will a pilot pass?", "probability": 0.6, "outcome": None},
            {"question": "Will rollout finish?", "probability": 0.7, "outcome": None},
        ],
        "_guided_step": 2,
    }
    session = Session(store.new_project("Work"), "forecasting", "Forecasts", method_state=state)
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        picker = app.screen.query_one("#forecast-picker", Select)
        assert len(picker._options) == 2
        picker.value = 0
        await pilot.pause()
        app.screen.query_one("#field-outcome", Input).value = "yes"
        await app.screen.action_next()
        assert store.load(session.id).method_state["forecasts"][0]["outcome"] == 1
        assert store.load(session.id).method_state["forecasts"][1]["outcome"] is None
    store.close()


@pytest.mark.asyncio
async def test_help_key_does_not_interrupt_typing(tmp_path):
    store = Store(tmp_path / "help.db")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpDialog)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpDialog)
        app.project_id = store.new_project("Work")
        app.show_project()
        await pilot.pause()
        editor = app.screen.query_one("#project-question", Input)
        editor.focus()
        await pilot.press("question_mark")
        assert not isinstance(app.screen, HelpDialog)
        assert editor.value == "?"
    store.close()


def test_doctor_is_read_only_without_probes(tmp_path):
    import sqlite3

    root = tmp_path / "data"
    database = root / "thinktui" / "thinktui.db"
    database.parent.mkdir(parents=True)
    db = sqlite3.connect(database)
    db.execute("PRAGMA user_version=3")
    db.close()
    before = database.read_bytes()
    run = subprocess.run(
        [sys.executable, "-m", "thinktui", "doctor"],
        env={**os.environ, "XDG_DATA_HOME": str(root)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Schema version: 3" in run.stdout
    assert database.read_bytes() == before
    assert sorted(p.name for p in database.parent.iterdir()) == ["thinktui.db"]


def test_consent_specific_destination_and_export_exclusive(tmp_path):
    store = Store(tmp_path / "app.db")
    store.set_setting("ai_consent", "yes")  # historical global consent cannot authorize a new provider
    openai = ProviderConfig("openai", "https://api.openai.com/v1", "model")
    anthropic = ProviderConfig("anthropic", "https://api.anthropic.com", "model")
    assert not remote_consent(store, openai)
    store.set_setting("ai.openai.consent", "yes")
    assert remote_consent(store, openai)
    assert not remote_consent(store, anthropic)
    report = tmp_path / "brief.md"
    session = Session(store.new_project("Work"), "issue_tree", "Tree")
    export(session, report)
    first = report.read_bytes()
    with pytest.raises(FileExistsError):
        export(session, report)
    assert report.read_bytes() == first
    store.close()
