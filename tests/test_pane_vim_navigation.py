"""Pane visibility and non-destructive keyboard navigation."""

import pytest
from textual.widgets import Button, DataTable, Input, TextArea

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.screens import JournalList, PlanningScreen
from thinktui.storage import Store
from thinktui.text_field import TextField
from thinktui.workspace_layout import WorkspaceLayout


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["advanced", "form", "guided"])
async def test_pane_toggle_and_focus_at_both_widths(tmp_path, mode):
    store = Store(tmp_path / "panes.db")
    method = "pairwise" if mode == "advanced" else "matrix"
    session = Session(store.new_project("Example"), method, "Test")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, advanced=mode == "advanced", guided=mode != "advanced")
        await pilot.pause()
        layout = app.screen.query_one(WorkspaceLayout)
        editor = layout.query_one(".editor-pane")
        ai = layout.query_one(".ai-pane")
        handle = layout.query_one(".pane-handle")
        field = editor.query_one(Input) if editor.query(Input) else editor.query_one(TextArea)
        field.focus()
        await pilot.press("shift+f5")
        await pilot.pause()
        assert not editor.display and ai.display and handle.has_class("collapsed")
        assert app.focused not in editor.query("*")
        assert ai.region.width == layout.region.width - handle.region.width
        await pilot.press("f5")  # switch which pane is hidden
        await pilot.pause()
        assert editor.display and not ai.display
        assert editor.region.width == layout.region.width - handle.region.width
        await pilot.press("ctrl+0")
        await pilot.pause()
        assert editor.display and ai.display and not handle.has_class("collapsed")
        await pilot.resize_terminal(80, 40)
        await pilot.pause()
        await pilot.press("f5")
        await pilot.pause()
        assert not ai.display and editor.region.height == layout.region.height - handle.region.height
        await pilot.press("ctrl+@")  # how Ctrl+2 arrives from tmux and legacy terminals
        await pilot.pause()
        assert ai.display and not handle.has_class("collapsed")
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["advanced", "form", "guided"])
@pytest.mark.parametrize("size", [(120, 40), (80, 40)])
async def test_ai_pane_hide_button_and_restore_strip(tmp_path, mode, size):
    store = Store(tmp_path / "hide.db")
    method = "pairwise" if mode == "advanced" else "matrix"
    session = Session(store.new_project("Example"), method, "Test")
    app = ThinkApp(store=store)
    async with app.run_test(size=size) as pilot:
        app.open_session(session, advanced=mode == "advanced", guided=mode != "advanced")
        await pilot.pause()
        layout = app.screen.query_one(WorkspaceLayout)
        ai = layout.query_one(".ai-pane")
        handle = layout.query_one(".pane-handle")
        hide = ai.query_one("#hide-ai-pane", Button)
        hide.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert not ai.display and handle.has_class("collapsed")
        assert app.focused is not None and app.focused not in ai.query("*")
        await pilot.click(handle)
        await pilot.pause()
        assert ai.display and not handle.has_class("collapsed")
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["advanced", "form", "guided"])
async def test_ai_pane_hide_button_stays_visible_when_scrolled(tmp_path, mode):
    store = Store(tmp_path / "scroll.db")
    method = "assumptions" if mode == "form" else "pairwise" if mode == "advanced" else "matrix"
    session = Session(store.new_project("Example"), method, "Test")
    app = ThinkApp(store=store)
    async with app.run_test(size=(110, 16)) as pilot:
        app.open_session(session, advanced=mode == "advanced", guided=mode != "advanced")
        await pilot.pause()
        ai = app.screen.query_one(".ai-pane")
        ai.scroll_end(animate=False)
        await pilot.pause()
        hide = ai.query_one("#hide-ai-pane", Button)
        assert ai.region.contains_region(hide.region)
        await pilot.click(hide)
        await pilot.pause()
        assert not ai.display
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 40), (80, 40)])
async def test_ai_pane_size_buttons_resize_without_dragging(tmp_path, size):
    store = Store(tmp_path / "size.db")
    session = Session(store.new_project("Example"), "matrix", "Test")
    app = ThinkApp(store=store)
    async with app.run_test(size=size) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        ai = app.screen.query_one(".ai-pane")
        extent = (lambda: ai.region.height) if size[0] < 100 else (lambda: ai.region.width)
        original = extent()
        await pilot.click(ai.query_one("#ai-pane-larger", Button))
        await pilot.pause()
        assert extent() > original
        for _ in range(2):
            await pilot.click(ai.query_one("#ai-pane-smaller", Button))
            await pilot.pause()
        assert extent() < original
    store.close()


@pytest.mark.asyncio
async def test_vim_focus_panes_and_text_entry(tmp_path):
    store = Store(tmp_path / "navigation.db")
    session = Session(store.new_project("Example"), "pairwise", "Test")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, advanced=True)
        await pilot.pause()
        editor = app.screen.query_one(".editor-pane")
        ai = app.screen.query_one(".ai-pane")
        field = editor.query_one("#change-mind", TextField)
        field.focus()
        await pilot.press("j", "k", "h", "l")
        assert field.value == "jkhl"
        assert app.focused is field
        await pilot.press("tab")
        await pilot.press("l")
        assert app.focused is ai or app.focused in ai.query("*")
        await pilot.press("h")
        assert app.focused is editor or app.focused in editor.query("*")
        editor.query_one("#initialize", Button).focus()
        await pilot.pause()
        first = app.focused
        await pilot.press("j")
        assert app.focused is field
        await pilot.press("k")
        assert field.value.endswith("k")
        first.focus()
        await pilot.pause()
        await pilot.press("k")
        assert app.focused is editor.query_one("#items", TextArea)
        await pilot.press("f5", "l")
        assert app.focused is editor or app.focused in editor.query("*")
    store.close()


@pytest.mark.asyncio
async def test_vim_table_rows_and_existing_home_shortcuts(tmp_path):
    store = Store(tmp_path / "lists.db")
    project = store.new_project("Example")
    for title in ("First", "Second"):
        store.save(Session(project, "pairwise", title), "Create")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        await pilot.press("j")
        assert isinstance(app.screen, JournalList)
        app.home()
        await pilot.pause()
        await pilot.press("h")
        assert isinstance(app.screen, PlanningScreen)
        app.project_id = project
        app.show_project()
        await pilot.pause()
        table = app.screen.query_one("#analyses", DataTable)
        table.focus()
        await pilot.press("j")
        assert table.cursor_coordinate.row == 1
        await pilot.press("k")
        assert table.cursor_coordinate.row == 0
    store.close()
