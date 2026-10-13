"""Clipboard and resizable workspace regressions (no desktop clipboard required)."""

import pytest
from textual import events
from textual.widgets import Input, Static

from thinktui import clipboard
from thinktui.app import ThinkApp
from thinktui.coach import CoachPanel
from thinktui.core import Session
from thinktui.storage import Store
from thinktui.workspace_layout import WorkspaceLayout


async def drag_from_terminal(app, pilot, handle, x, y):
    """Exercise the real driver path: terminal mouse events have widget=None."""
    start_x, start_y = handle.region.x, handle.region.y
    for cls, px, py in (
        (events.MouseDown, start_x, start_y),
        (events.MouseMove, x, y),
        (events.MouseUp, x, y),
    ):
        await app.on_event(cls(None, px, py, 0, 0, 1, False, False, False))
        await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["advanced", "guided", "form"])
async def test_panes_drag_and_stack(tmp_path, mode):
    store = Store(tmp_path / "work.db")
    project = store.new_project("Example")
    session = Session(project, "assumptions" if mode == "form" else "pairwise", "Test")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, guided=mode != "advanced", advanced=mode == "advanced")
        await pilot.pause()
        layout = app.screen.query_one(WorkspaceLayout)
        handle = layout.query_one(".pane-handle", Static)
        assert layout.query_one(".editor-pane")
        assert layout.query_one(".ai-pane")
        original_width = layout.query_one(".editor-pane").region.width
        await pilot.press("f4")
        assert layout.query_one(".editor-pane").region.width > original_width
        await pilot.press("f3")
        await drag_from_terminal(app, pilot, handle, 95, 10)
        assert layout.query_one(".editor-pane").region.width > original_width
        await pilot.resize_terminal(80, 40)
        await pilot.pause()
        assert layout.has_class("narrow")
        original_height = layout.query_one(".editor-pane").region.height
        await pilot.press("f4")
        assert layout.query_one(".editor-pane").region.height > original_height
        await pilot.press("f3")
        await drag_from_terminal(app, pilot, handle, 10, 30)
        assert layout.query_one(".editor-pane").region.height > original_height
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("columns", "initial"), [(80, 46), (60, 34)])
async def test_small_terminal_coach_resize_bounds_and_real_mouse(tmp_path, columns, initial):
    from textual.widgets import Button

    store = Store(tmp_path / f"coach-{columns}.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(columns, 40)) as pilot:
        app.action_coach()
        await pilot.pause()
        panel = app.screen.query_one(CoachPanel)
        minimum, maximum = panel._width_bounds()
        assert panel.region.width == app.coach_width == initial
        assert minimum < initial < maximum
        await pilot.click(panel.query_one("#coach-wider", Button))
        assert panel.region.width > initial  # + must never shrink
        wider = panel.region.width
        await pilot.click(panel.query_one("#coach-narrower", Button))
        assert panel.region.width < wider  # - must never grow
        handle = panel.query_one(".coach-resize-handle", Static)
        start = panel.region.width
        await drag_from_terminal(app, pilot, handle, panel.region.x - 5, 5)
        assert start < panel.region.width <= maximum
        start = panel.region.width
        await drag_from_terminal(app, pilot, handle, panel.region.x + 5, 5)
        assert minimum <= panel.region.width < start
        await drag_from_terminal(app, pilot, handle, 0, 5)
        assert panel.region.width == maximum
        await drag_from_terminal(app, pilot, handle, columns - 1, 5)
        assert panel.region.width == minimum
    store.close()


@pytest.mark.asyncio
async def test_coplanner_has_visible_no_resize_state_when_too_narrow(tmp_path):
    from textual.widgets import Button

    store = Store(tmp_path / "tiny.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(24, 40)) as pilot:
        app.action_coach()
        await pilot.pause()
        panel = app.screen.query_one(CoachPanel)
        minimum, maximum = panel._width_bounds()
        assert minimum == maximum == panel.region.width
        assert panel.query_one("#coach-resize-notice", Static).display
        assert panel.query_one("#coach-narrower", Button).disabled
        assert panel.query_one("#coach-wider", Button).disabled
    store.close()


@pytest.mark.asyncio
async def test_coplanner_clamps_when_terminal_shrinks(tmp_path):
    from textual.widgets import Button

    store = Store(tmp_path / "resize.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(80, 40)) as pilot:
        app.action_coach()
        await pilot.pause()
        panel = app.screen.query_one(CoachPanel)
        assert panel.region.width == 46
        await pilot.resize_terminal(60, 40)
        await pilot.pause()
        minimum, maximum = panel._width_bounds()
        assert minimum <= panel.region.width <= maximum
        before = panel.region.width
        await pilot.click(panel.query_one("#coach-narrower", Button))
        assert panel.region.width < before
        await pilot.click(panel.query_one("#coach-wider", Button))
        assert panel.region.width == before
    store.close()


@pytest.mark.asyncio
async def test_form_drag_while_coplanner_open(tmp_path):
    store = Store(tmp_path / "together.db")
    session = Session(store.new_project("Project"), "backcasting", "Plan")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, guided=True)
        app.action_coach()
        await pilot.pause()
        editor = app.screen.query_one(".editor-pane")
        handle = app.screen.query_one(".pane-handle")
        panel = app.screen.query_one(CoachPanel)
        assert handle.region.right < panel.region.x
        original_width = editor.region.width
        await drag_from_terminal(app, pilot, handle, panel.region.x - 20, 10)
        assert editor.region.width > original_width
    store.close()


@pytest.mark.asyncio
async def test_coplanner_dock_resizes_by_drag(tmp_path):
    store = Store(tmp_path / "coach.db")
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_coach()
        await pilot.pause()
        panel = app.screen.query_one(CoachPanel)
        handle = panel.query_one(".coach-resize-handle", Static)
        assert handle.region.x == panel.region.x  # visible border must be the draggable target
        from textual.widgets import Button

        wider = panel.query_one("#coach-wider", Button)
        narrower = panel.query_one("#coach-narrower", Button)
        await pilot.click(wider)
        assert panel.region.width == 52
        await pilot.click(narrower)
        assert panel.region.width == 46
        await drag_from_terminal(app, pilot, handle, 55, 5)
        assert panel.region.width == 65
        app.action_coach()
        await pilot.pause()
        app.action_coach()
        await pilot.pause()
        assert app.screen.query_one(CoachPanel).region.width == 65
    store.close()


def test_desktop_clipboard_failure_is_private_and_falls_back(monkeypatch):
    import subprocess

    monkeypatch.setattr(clipboard, "_command", lambda read: ["missing-clipboard"])

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, stderr=b"secret")

    monkeypatch.setattr(clipboard.subprocess, "run", fail)
    assert clipboard.read_clipboard() is None
    assert clipboard.write_clipboard("text") is None


@pytest.mark.asyncio
async def test_copy_paste_between_inputs_and_desktop(monkeypatch, tmp_path):
    store = Store(tmp_path / "clipboard.db")
    app = ThinkApp(store=store)
    external = [None]
    copied = []
    monkeypatch.setattr("thinktui.app.read_clipboard", lambda: external[0])
    monkeypatch.setattr("thinktui.app.write_clipboard", copied.append)
    async with app.run_test() as pilot:
        from thinktui.screens import NewProject

        app.push_screen(NewProject(app))
        await pilot.pause()
        field = app.screen.query_one("#name", Input)
        field.value = "Copy this"
        field.focus()
        await pilot.press("ctrl+shift+a", "ctrl+c")
        assert copied[-1] == "Copy this"
        external[0] = "From desktop"
        await pilot.press("ctrl+v")
        assert field.value == "From desktop"
        external[0] = None
        await pilot.press("ctrl+v")
        assert field.value.endswith("Copy this")
    store.close()
