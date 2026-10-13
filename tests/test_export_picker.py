"""Export paths: typos never crash the app, and the picker writes where the user chose."""

from pathlib import Path

import pytest
from textual.widgets import Button, Input

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.path_picker import ExportPicker, FolderTree, suggested_filename, user_path
from thinktui.storage import Store

SENSITIVITY = {
    "criteria": [
        {"name": "Value", "weight": 1, "direction": "benefit"},
        {"name": "Cost", "weight": 1, "direction": "cost"},
    ],
    "alternatives": [{"name": "A", "scores": [9, 8]}, {"name": "B", "scores": [6, 2]}],
    "vary": "Value",
    "range": [0, 1],
}


def sensitivity_session(store: Store) -> Session:
    session = Session(store.new_project("Export"), "sensitivity", "4 Where · Approach", method_state=dict(SENSITIVITY))
    store.save(session)
    return session


def test_user_path_turns_unknown_home_into_a_message():
    with pytest.raises(ValueError, match="use ~/"):
        user_path("~nosuchuser-thinktui/downloads/decisions.md")
    assert user_path("  ~/brief.md ") == Path.home() / "brief.md"


def test_suggested_filename_is_a_plain_slug():
    assert suggested_filename("4 Where · Approach · Sensitivity") == "4-where-approach-sensitivity.md"
    assert suggested_filename("···", ".json") == "analysis.json"


@pytest.mark.asyncio
async def test_form_export_with_tilde_typo_notifies_instead_of_crashing(tmp_path):
    store = Store(tmp_path / "typo.db")
    session = sensitivity_session(store)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        screen.query_one("#form-export-path", Input).value = "~nosuchuser-thinktui/downloads/decisions.md"
        screen.action_export()
        await pilot.pause()
        assert app.screen is screen
        assert any("use ~/" in str(n.message) for n in app._notifications)


@pytest.mark.asyncio
async def test_form_picker_exports_to_chosen_folder_and_remembers_it(tmp_path):
    store = Store(tmp_path / "pick.db")
    session = sensitivity_session(store)
    target = tmp_path / "plans"
    target.mkdir()
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.last_export_dir = target
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#form-export-browse", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ExportPicker)
        assert picker.folder == target
        filename = picker.query_one("#picker-filename", Input)
        assert filename.value == "4-where-approach.md"
        filename.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert (target / "4-where-approach.md").read_text().strip()
        assert app.last_export_dir == target


@pytest.mark.asyncio
async def test_picker_refuses_existing_file_wrong_suffix_and_cancels_cleanly(tmp_path):
    store = Store(tmp_path / "refuse.db")
    session = sensitivity_session(store)
    (tmp_path / "taken.md").write_text("keep me")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.last_export_dir = tmp_path
        app.open_session(session, guided=True)
        await pilot.pause()
        form = app.screen
        form.query_one("#form-export-browse", Button).press()
        await pilot.pause()
        picker = app.screen
        filename = picker.query_one("#picker-filename", Input)
        for bad in ("taken.md", "brief.txt", "sub/brief.md"):
            filename.value = bad
            picker.confirm()
            await pilot.pause()
            assert app.screen is picker
        assert (tmp_path / "taken.md").read_text() == "keep me"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is form
        assert form.query_one("#form-export-path", Input).value == ""


@pytest.mark.asyncio
async def test_picker_parent_folder_moves_up(tmp_path):
    store = Store(tmp_path / "up.db")
    session = sensitivity_session(store)
    child = tmp_path / "child"
    child.mkdir()
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.last_export_dir = child
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#form-export-browse", Button).press()
        await pilot.pause()
        picker = app.screen
        assert picker.query_one(FolderTree).has_focus
        await pilot.press("backspace")
        await pilot.pause()
        assert picker.folder == tmp_path
        assert Path(picker.query_one(FolderTree).path) == tmp_path


@pytest.mark.asyncio
async def test_guided_review_offers_picker(tmp_path):
    store = Store(tmp_path / "guided.db")
    state = {
        "criteria": [
            {"name": "Benefit", "weight": 3, "direction": "benefit"},
            {"name": "Effort", "weight": 1, "direction": "cost"},
        ],
        "alternatives": [{"name": "Build", "scores": [9, 8]}, {"name": "Buy", "scores": [6, 2]}],
        "_guided_step": 3,
    }
    matrix = Session(store.new_project("Choice"), "matrix", "Build or buy", method_state=state)
    store.save(matrix)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.last_export_dir = tmp_path
        app.open_session(matrix, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        app.screen.query_one("#export-browse", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ExportPicker)
        picker.query_one("#picker-filename", Input).value = "build-or-buy.json"
        picker.confirm()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert '"method_id": "matrix"' in (tmp_path / "build-or-buy.json").read_text()


@pytest.mark.asyncio
async def test_workspace_offers_picker(tmp_path):
    from thinktui.screens import Workspace

    store = Store(tmp_path / "workspace.db")
    session = sensitivity_session(store)
    app = ThinkApp(store=store)
    async with app.run_test(size=(140, 50)) as pilot:
        app.last_export_dir = tmp_path
        app.open_session(session, advanced=True)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        app.screen.query_one("#export-browse", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ExportPicker)
        picker.confirm()
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        assert (tmp_path / "4-where-approach.md").exists()
        assert app.screen.query_one("#export-path", Input).value == str(tmp_path / "4-where-approach.md")
