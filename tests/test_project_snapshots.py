"""Portable project backups preserve analysis links and history, not settings."""

import json

import pytest
from textual.widgets import Button, Input

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.screens import Home, ProjectView
from thinktui.storage import Store


def test_snapshot_roundtrip_links_events_and_no_settings(tmp_path):
    store = Store(tmp_path / "data.db")
    project = store.new_project("A")
    first = Session(project, "premortem", "Risks")
    first.method_state["entries"] = [{"statement": "Outage", "source": "USER"}]
    store.save(first, "Added risk")
    second = Session(project, "fmea", "FMEA")
    store.save(second, "Created FMEA")
    second.method_state["source_session_id"] = first.id
    store.save(second, "Linked from analysis " + first.id)
    store.set_setting("ai_provider", "off")
    snapshot = store.snapshot(project)
    assert "settings" not in snapshot and "ai_provider" not in json.dumps(snapshot)
    assert len(snapshot["events"]) == 3
    imported = store.import_snapshot(snapshot)
    assert imported != project
    sessions = {row.method_id: row for row in store.sessions(imported)}
    assert sessions["fmea"].method_state["source_session_id"] == sessions["premortem"].id
    assert store.events(sessions["premortem"].id)[0]["description"] == "Added risk"
    imported_audit = store.events(sessions["fmea"].id)
    changes = json.loads(imported_audit[0]["changes"])
    assert changes[0]["field"] == "method_state.source_session_id"
    assert changes[0]["after"] == sessions["premortem"].id
    assert imported_audit[0]["description"] == "Linked from analysis " + sessions["premortem"].id
    creation = json.dumps(json.loads(imported_audit[1]["changes"]))
    assert sessions["fmea"].id in creation and imported in creation
    assert second.id not in creation and project not in creation
    assert first.id not in json.dumps(changes)
    before = len(store.projects())
    invalid = json.loads(json.dumps(snapshot))
    invalid["events"][0]["session_id"] = "outside"
    with pytest.raises(ValueError):
        store.import_snapshot(invalid)
    assert len(store.projects()) == before
    store.delete_project(project)
    assert len(store.sessions(imported)) == 2
    assert store.setting("ai_provider") == "off"
    store.close()


@pytest.mark.asyncio
async def test_snapshot_export_import_from_tui(tmp_path):
    store = Store(tmp_path / "app.db")
    project = store.new_project("Back up")
    store.save(Session(project, "journal", "Decision"))
    app = ThinkApp(store=store)
    path = tmp_path / "backup.json"
    async with app.run_test() as pilot:
        app.project_id = project
        app.show_project()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        app.screen.query_one("#snapshot-path", Input).value = str(path)
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#export_snapshot", Button)))
        assert path.exists()
        app.home()
        await pilot.pause()
        assert isinstance(app.screen, Home)
        app.screen.query_one("#import-path", Input).value = str(path)
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#import_snapshot", Button)))
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        assert app.project_id != project
        assert len(store.sessions(app.project_id)) == 1
    store.close()
