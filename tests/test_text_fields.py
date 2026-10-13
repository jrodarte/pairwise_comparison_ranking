"""Long text stays readable: fields grow and resize, form rows collapse, ranked rows expand."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Collapsible, DataTable, Input

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.form_screen import FormScreen
from thinktui.screens import Workspace
from thinktui.storage import Store
from thinktui.text_field import TextField

LONG = "word " * 200


class FieldApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str | None, str]] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield TextField("short", id="short")
            yield TextField(LONG, id="long")
            yield TextField("note", multiline=True, id="note")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.events.append(("changed", event.input.id, event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.events.append(("submitted", event.input.id, event.value))


@pytest.fixture(autouse=True)
def forget_sizes():
    TextField.remembered.clear()
    yield
    TextField.remembered.clear()


@pytest.mark.asyncio
async def test_text_field_wraps_and_grows_with_its_text_up_to_a_limit():
    app = FieldApp()
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        short, long = app.query_one("#short", TextField), app.query_one("#long", TextField)
        assert short.outer_size.height == 2  # one line plus its bottom edge
        assert long.outer_size.height == 12  # grows, then scrolls inside past max-height
        short.value = "word " * 20
        await pilot.pause()
        assert short.outer_size.height > 2


@pytest.mark.asyncio
async def test_text_field_behaves_like_input_for_single_line_entry():
    app = FieldApp()
    async with app.run_test(size=(60, 40)) as pilot:
        field = app.query_one("#short", TextField)
        field.focus()
        await pilot.press("end", "!", "enter")
        await pilot.pause()
        assert field.value == "short!"  # Enter submits instead of adding a line
        field.value = ""
        field.value = "a\nb"  # each assignment reports its own value; line breaks become spaces
        await pilot.pause()
        assert app.events == [
            ("changed", "short", "short!"),
            ("submitted", "short", "short!"),
            ("changed", "short", ""),
            ("changed", "short", "a b"),
        ]
        note = app.query_one("#note", TextField)
        note.focus()
        await pilot.press("end", "enter", "x")
        assert note.value == "note\nx"  # multiline fields keep Enter for new lines


@pytest.mark.asyncio
async def test_text_field_resizes_by_keyboard_and_by_dragging_its_bottom_edge():
    app = FieldApp()
    async with app.run_test(size=(60, 40)) as pilot:
        field = app.query_one("#long", TextField)
        field.focus()
        await pilot.pause()
        await pilot.press("alt+down")
        await pilot.pause()
        assert field.outer_size.height == 14
        await pilot.press("alt+up", "alt+up", "alt+up")
        await pilot.pause()
        assert field.outer_size.height == 8
        bottom = field.outer_size.height - 1
        await pilot.mouse_down(field, offset=(3, bottom))
        await pilot.hover(field, offset=(3, bottom + 10))
        await pilot.mouse_up(field, offset=(3, bottom + 10))
        await pilot.pause()
        assert field.outer_size.height == 18
        assert field.value == LONG  # resizing never edits the text
        await pilot.click(field, offset=(3, field.outer_size.height - 1), times=2)
        await pilot.pause()
        assert field.outer_size.height == 12  # double-click the edge to fit the text again


@pytest.mark.asyncio
async def test_form_rows_collapse_expand_and_keep_state_when_rows_change(tmp_path):
    store = Store(tmp_path / "rows.db")
    session = Session(
        store.new_project("Plan"),
        "root_cause",
        "Outage",
        method_state={
            "problem": "Timeouts",
            "causes": [
                {"claim": "Pool exhausted " + LONG, "supporting": [], "contradicting": [], "test": "t"},
                {"claim": "Bad deploy", "supporting": [], "contradicting": [], "test": "t"},
            ],
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen(FormScreen(session))
        await pilot.pause()
        screen = app.screen
        group = next(group for group, path in screen.groups.items() if path == ("causes",))
        first, second = (screen.query_one(f"#{group}-row-{i}", Collapsible) for i in (0, 1))
        assert not first.collapsed and str(first.title).startswith("Cause 1 · Pool exhausted")
        assert str(first.title).endswith("…")  # a long label is shortened in the heading only
        claim = next(i for i, (p, _) in screen.fields.items() if p == ("causes", 0, "claim"))
        assert screen.query_one(f"#{claim}", TextField).outer_size.height > 2  # long text is readable

        first.collapsed = True
        await pilot.pause()
        assert screen.collapsed_rows == {(("causes",), 0)}
        screen.query_one(f"#{group}-down-0", Button).press()  # hidden while collapsed; still works by id
        await pilot.pause()
        group = next(group for group, path in screen.groups.items() if path == ("causes",))
        assert str(screen.query_one(f"#{group}-row-1", Collapsible).title).startswith("Cause 2 · Pool")
        assert screen.query_one(f"#{group}-row-1", Collapsible).collapsed  # state moved with the row
        assert not screen.query_one(f"#{group}-row-0", Collapsible).collapsed

        screen.query_one(f"#{group}-collapseall", Button).press()
        await pilot.pause()
        assert all(row.collapsed for row in screen.query(Collapsible))
        screen.query_one(f"#{group}-expandall", Button).press()
        await pilot.pause()
        assert not any(row.collapsed for row in screen.query(Collapsible))
        assert [c["claim"][:8] for c in store.load(session.id).method_state["causes"]] == ["Bad depl", "Pool exh"]
    store.close()


@pytest.mark.asyncio
async def test_resized_form_field_keeps_its_height_after_rows_change(tmp_path):
    store = Store(tmp_path / "size.db")
    session = Session(store.new_project("Plan"), "root_cause", "Outage", method_state={"problem": "Timeouts"})
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen(FormScreen(session))
        await pilot.pause()
        screen = app.screen
        problem = next(i for i, (p, _) in screen.fields.items() if p == ("problem",))
        screen.query_one(f"#{problem}", TextField).set_lines(7)
        group = next(group for group, path in screen.groups.items() if path == ("causes",))
        screen.query_one(f"#{group}-add", Button).press()
        await pilot.pause()
        problem = next(i for i, (p, _) in screen.fields.items() if p == ("problem",))
        assert screen.query_one(f"#{problem}", TextField).outer_size.height == 8
    store.close()


@pytest.mark.asyncio
async def test_ranked_rows_expand_to_full_text_one_at_a_time_or_all(tmp_path):
    store = Store(tmp_path / "kac.db")
    entries = [
        {"statement": "Vendor API holds load " + "under peak traffic " * 6, "confidence": 20, "impact": 9},
        {"statement": "Team has capacity", "confidence": 80, "impact": 4},
    ]
    session = Session(store.new_project("Plan"), "assumptions", "Check", method_state={"entries": entries})
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(140, 60)) as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Workspace)
        table = screen.query_one("#entry-list", DataTable)
        assert [row.height for row in table.ordered_rows] == [1, 1]
        table.focus()
        table.move_cursor(row=0)
        await pilot.press("space")
        await pilot.pause()
        assert table.ordered_rows[0].height > 1 and table.ordered_rows[1].height == 1
        assert table.cursor_row == 0
        await pilot.press("space")
        await pilot.pause()
        assert table.ordered_rows[0].height == 1
        screen.query_one("#expand-entries", Button).press()
        await pilot.pause()
        assert table.ordered_rows[0].height > 1
        assert str(screen.query_one("#expand-entries", Button).label) == "One line per row"
        screen.query_one("#expand-entries", Button).press()
        await pilot.pause()
        assert all(row.height == 1 for row in table.ordered_rows)
        screen.query_one("#entry", TextField).focus()
        await pilot.press("space")  # Space types into a field instead of toggling rows
        assert screen.query_one("#entry", TextField).value == " "
    store.close()
