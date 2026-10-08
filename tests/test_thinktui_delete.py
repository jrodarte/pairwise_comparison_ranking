"""Project deletion requires confirmation and removes only the selected project's data."""

import sqlite3

import pytest
from textual.widgets import DataTable

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.screens import DeleteProjectDialog, Home, ProjectView
from thinktui.storage import Store


def seed(store: Store, name: str) -> tuple[str, str]:
    project_id = store.new_project(name)
    session = Session(project_id, "assumptions", "Check")
    store.save(session, "Created")
    store.save(session, "Updated")
    return project_id, session.id


def test_repository_delete_cascades_and_is_atomic(tmp_path):
    store = Store(tmp_path / "records.db")
    victim, analysis = seed(store, "Delete me")
    survivor, other = seed(store, "Keep me")
    store.set_setting("ai_provider", "off")
    with pytest.raises(KeyError):
        store.delete_project("nonexistent")
    store.db.execute(
        f"""CREATE TRIGGER block_delete BEFORE DELETE ON projects
                       WHEN old.id = '{victim}' BEGIN SELECT RAISE(ABORT, 'blocked'); END"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.delete_project(victim)
    assert store.load(analysis).id == analysis
    assert len(store.events(analysis)) == 2
    store.db.execute("DROP TRIGGER block_delete")
    store.delete_project(victim)
    assert [r["id"] for r in store.projects()] == [survivor]
    with pytest.raises(KeyError):
        store.load(analysis)
    assert store.events(analysis) == []
    assert store.load(other).id == other
    assert len(store.events(other)) == 2
    assert store.setting("ai_provider") == "off"
    store.close()
    reopened = Store(tmp_path / "records.db")
    assert [r["id"] for r in reopened.projects()] == [survivor]
    reopened.close()


@pytest.mark.asyncio
async def test_home_delete_cancel_then_confirm_selected_project(tmp_path):
    store = Store(tmp_path / "app.db")
    victim, analysis = seed(store, "Victim")
    survivor, _ = seed(store, "Survivor")  # newest is first, so move cursor to Victim
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, Home)
        app.screen.query_one("#projects", DataTable).move_cursor(row=1)
        await pilot.press("d")
        assert isinstance(app.screen, DeleteProjectDialog)
        assert app.screen.project_name == "Victim"
        assert app.screen.analysis_count == 1
        assert app.screen.query_one("#cancel").has_focus
        await pilot.press("enter")  # safe default
        assert isinstance(app.screen, Home)
        assert store.load(analysis).id == analysis
        app.screen.query_one("#projects", DataTable).move_cursor(row=1)
        await pilot.press("d")
        assert isinstance(app.screen, DeleteProjectDialog)
        await pilot.press("escape")
        assert store.load(analysis).id == analysis
        app.screen.query_one("#projects", DataTable).move_cursor(row=1)
        await pilot.press("d")
        await pilot.click("#confirm-delete")
        assert isinstance(app.screen, Home)
        assert app.project_id is None
        assert app.screen.query_one("#projects", DataTable).row_count == 1
        assert store.events(analysis) == []
        assert [r["id"] for r in store.projects()] == [survivor]
        assert victim != survivor
    store.close()


@pytest.mark.asyncio
async def test_open_project_delete_and_empty_home(tmp_path):
    store = Store(tmp_path / "open.db")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.screen.action_delete()  # empty list is safe
        project, _ = seed(store, "Active")
        app.project_id = project
        app.show_project()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        await pilot.press("d")
        assert isinstance(app.screen, DeleteProjectDialog)
        await pilot.click("#confirm-delete")
        assert isinstance(app.screen, Home)
        assert store.projects() == []
        assert app.project_id is None
        empty = store.new_project("Empty")
        app.home()
        await pilot.pause()
        await pilot.press("d")
        assert isinstance(app.screen, DeleteProjectDialog)
        assert app.screen.analysis_count == 0
        await pilot.click("#confirm-delete")
        assert store.projects() == []
        assert empty not in [row["id"] for row in store.projects()]
    store.close()
