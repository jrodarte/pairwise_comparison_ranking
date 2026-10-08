"""AI drafts remain beside the editor; small terminals keep both panes reachable."""

import pytest
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, TextArea

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.storage import Store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_id", "guided", "trigger", "field", "preview"),
    [
        ("backcasting", True, "suggest-form-field-0", "form-field-0", "form-preview"),
        ("matrix", True, "help-suggest-alternatives", "field-alternatives", "field-help-preview"),
        ("assumptions", False, "help-entry", "entry", "field-help-preview"),
    ],
)
async def test_editor_and_ai_pane_responsive(tmp_path, method_id, guided, trigger, field, preview):
    store = Store(tmp_path / "layout.db")
    session = Session(store.new_project("Plan"), method_id, "Decision")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, guided=guided)
        await pilot.pause()
        screen = app.screen
        editor = screen.query_one(".editor-pane")
        ai = screen.query_one(".ai-pane")
        assert editor.region.right == ai.region.x
        assert ai.region.y == editor.region.y
        assert screen.query_one(f"#{preview}", TextArea).parent is ai
        button = screen.query_one(f"#{trigger}", Button)
        widget = screen.query_one(f"#{field}")
        assert isinstance(button.parent, Horizontal)
        assert button.parent is widget.parent
        assert button.region.x >= widget.region.right
        assert button.region.width <= 16
        if isinstance(widget, Input):
            assert widget.region.height == 2
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert screen.query_one(".workspace-layout").has_class("narrow")
        assert ai.region.y >= editor.region.bottom
        assert ai.region.width == editor.region.width == 80
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert not screen.query_one(".workspace-layout").has_class("narrow")
        assert ai.region.x == editor.region.right


@pytest.mark.asyncio
async def test_form_recompose_keeps_ai_draft_in_sidebar(tmp_path):
    store = Store(tmp_path / "layout.db")
    session = Session(store.new_project("Plan"), "backcasting", "Decision")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        preview = app.screen.query_one("#form-preview", TextArea)
        preview.load_text("Draft awaiting review")
        await app.screen.recompose_fields()
        assert preview is app.screen.query_one("#form-preview", TextArea)
        assert preview.text == "Draft awaiting review"


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", ["assumptions", "premortem"])
async def test_workspace_assumption_and_row_triggers_end_of_entry(tmp_path, method_id):
    store = Store(tmp_path / "layout.db")
    session = Session(store.new_project("Plan"), method_id, "Decision")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session)
        await pilot.pause()
        entry = app.screen.query_one("#entry", Input)
        ids = ["help-entry", "help-rows"] + (["suggest"] if method_id == "assumptions" else [])
        previous_right = entry.region.right
        for ident in ids:
            button = app.screen.query_one(f"#{ident}", Button)
            assert button.parent is entry.parent
            assert button.region.x >= previous_right
            assert button.region.width <= 16
            assert str(button.label)  # descriptive action
            assert button.tooltip
            previous_right = button.region.right
        if method_id == "premortem":
            assert not app.screen.query("#suggest")


@pytest.mark.asyncio
async def test_form_rows_trigger_beside_add_row_and_sidebar_scrolls_on_narrow_terminals(tmp_path):
    store = Store(tmp_path / "layout.db")
    session = Session(store.new_project("Plan"), "backcasting", "Decision")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        add = screen.query_one("#group-0-add", Button)
        suggest = screen.query_one("#suggest-rows-group-0", Button)
        assert suggest.parent is add.parent
        assert isinstance(add.parent, Horizontal)
        assert suggest.region.x >= add.region.right
        assert suggest.region.width <= 16
        assert str(suggest.label) == "Suggest rows"
        assert suggest.tooltip
        pane = screen.query_one(".ai-pane", VerticalScroll)
        preview = screen.query_one("#form-preview", TextArea)
        assert pane.region.height == 9
        assert pane.max_scroll_y > 0
        preview.focus()
        await pilot.pause()
        assert pane.region.y <= preview.region.y < pane.region.bottom
        for ident in ("form-accept", "form-dismiss", "form-stop"):
            button = screen.query_one(f"#{ident}", Button)
            button.focus()
            await pilot.pause()
            assert pane.region.y <= button.region.y < button.region.bottom
            assert button.region.bottom <= pane.region.bottom
