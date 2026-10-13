"""Decision records and persisted before/after event history."""

import json
import sqlite3

import pytest
from textual.widgets import DataTable, Input, Static, TextArea

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.methods import DecisionJournal
from thinktui.screens import History, JournalList, NewAnalysis, ProjectView, Workspace
from thinktui.storage import Store, field_changes
from thinktui.text_field import TextField


def test_journal_validation_and_non_numeric_result():
    method = DecisionJournal()
    assert method.calculate({"decision": "Migrate"})["status"] == "Draft"
    assert "Confidence" in method.validate({"decision": "Migrate", "chosen": "A", "confidence": "120"})[0]
    state = {"decision": "Migrate", "chosen": "A", "confidence": "72", "actual_outcome": "Delayed"}
    assert method.calculate(state)["status"] == "Recorded"
    assert "score" not in method.calculate(state)
    assert "Review date" in method.validate({"decision": "Migrate", "chosen": "A", "review_date": "20270101"})[0]
    due = {"decision": "Migrate", "chosen": "A", "review_date": "2020-01-01"}
    assert method.calculate(due)["review_due"] is True
    due["actual_outcome"] = "Done"
    assert method.calculate(due)["review_due"] is False


def test_field_changes_and_migration_from_v1(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            method_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE events (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            timestamp TEXT NOT NULL, description TEXT NOT NULL);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO projects VALUES ('p', 'Legacy', 'yesterday');
        INSERT INTO sessions VALUES ('s','p','journal','{}','yesterday');
        INSERT INTO events (session_id,timestamp,description) VALUES ('s','yesterday','Legacy event');
        PRAGMA user_version=1;
    """)
    db.close()
    store = Store(path)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 7
    assert json.loads(store.events("s")[0]["changes"]) == []
    changes = field_changes({"method_state": {"chosen": "A"}}, {"method_state": {"chosen": "B"}})
    assert changes == [
        {"field": "method_state.chosen", "before": "A", "after": "B", "before_exists": True, "after_exists": True}
    ]
    store.close()


@pytest.mark.asyncio
async def test_journal_create_autosave_review_export_and_history(tmp_path):
    store = Store(tmp_path / "journal.db")
    project = store.new_project("FY27")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.project_id = project
        app.show_project()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        await pilot.click("#journal")
        assert isinstance(app.screen, NewAnalysis)
        app.screen.query_one("#title", Input).value = "Vendor choice"
        app.screen.start()
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        session_id = app.session.id
        for key, value in {
            "decision": "Build or buy?",
            "alternatives": "Build, Buy, Delay",
            "chosen": "Buy",
            "confidence": "70",
            "review_date": "2027-01-01",
            "expected_outcome": "Lower time to market",
            "risks": "Vendor lock-in",
        }.items():
            app.screen.query_one(f"#journal-{key}").value = value
        app.screen.query_one("#journal-rationale", TextArea).load_text("Buy is reversible.")
        await pilot.pause(1.2)
        saved = store.load(session_id)
        assert saved.method_state["chosen"] == "Buy"
        assert "Buy is reversible." in saved.method_state["rationale"]
        assert json.loads(store.events(session_id)[0]["changes"])
        app.screen.query_one("#journal-actual_outcome", TextField).value = "Vendor failed"
        app.screen.query_one("#journal-lessons", TextField).value = "Pilot earlier"
        destination = tmp_path / "journal.md"
        app.screen.query_one("#export-path", Input).value = str(destination)
        await pilot.press("ctrl+e")  # export also flushes pending edits
        assert "Vendor failed" in destination.read_text()
        assert "Pilot earlier" in destination.read_text()
        app.show_project()
        await pilot.pause()
        await pilot.press("h")
        assert isinstance(app.screen, History)
        table = app.screen.query_one("#events", DataTable)
        assert table.row_count >= 2
        await pilot.press("enter")
        details = str(app.screen.query_one("#event-details", Static).render())
        assert "method state" in details
        await pilot.press("escape")
        app.home()
        await pilot.pause()
        await pilot.press("j")
        assert isinstance(app.screen, JournalList)
        assert app.screen.query_one("#decisions", DataTable).row_count == 1
        await pilot.press("enter")
        assert isinstance(app.screen, Workspace)
        assert app.screen.query_one("#journal-chosen", TextField).value == "Buy"
    store.close()
    reopened = Store(tmp_path / "journal.db")
    assert reopened.load(session_id).method_state["actual_outcome"] == "Vendor failed"
    reopened.close()


@pytest.mark.asyncio
async def test_due_decision_surfaces_on_home_and_journal(tmp_path):
    store = Store(tmp_path / "due.db")
    project = store.new_project("Decision")
    record = Session(project, "journal", "Review")
    record.method_state = {"decision": "Vendor?", "chosen": "Buy", "review_date": "2020-01-01"}
    store.save(record)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        assert "1 decision review(s) due" in str(app.screen.query_one("#review-due", Static).render())
        await pilot.press("j")
        rows = app.screen.query_one("#decisions", DataTable)
        assert "DUE" in str(rows.get_row_at(0))
        await pilot.press("enter")
        assert "REVIEW DUE" in str(app.screen.query_one("#results", Static).render())
    store.close()
