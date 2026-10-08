"""Matrix options and criteria are editable as rows, with bulk paste as an opt-in alternative."""

import pytest
from textual.containers import HorizontalScroll
from textual.widgets import Button, Input, Select, Static, TextArea

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.guided_screen import GuidedScreen
from thinktui.guided_workflow import definition
from thinktui.matrix_mapping_screen import MatrixMappingDialog
from thinktui.storage import Store


@pytest.mark.asyncio
async def test_matrix_row_editor_validates_and_saves_user_judgments(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(store.new_project("Decision"), "matrix", "Approach")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GuidedScreen)
        assert screen.query_one("#matrix-row-0-name", Input).has_focus
        assert len(screen.query(".matrix-entry-row")) == 2
        screen.query_one("#matrix-row-0-name", Input).value = "Bulk import"
        await screen.action_next()  # incomplete second row must not silently disappear
        assert screen.index == 0
        assert "every row" in str(screen.query_one("#matrix-rows-error", Static).content)
        assert not store.load(session.id).method_state.get("alternatives")
        screen.query_one("#matrix-row-1-name", Input).value = "Manual stitching"
        screen.query_one("#matrix-add", Button).press()
        await pilot.pause()
        assert screen.query_one("#matrix-row-0-name", Input).value == "Bulk import"
        assert screen.query_one("#matrix-row-1-name", Input).value == "Manual stitching"
        screen.query_one("#matrix-row-2-name", Input).value = "Do nothing"
        await screen.action_next()
        assert screen.index == 1
        assert [r["name"] for r in store.load(session.id).method_state["alternatives"]] == [
            "Bulk import",
            "Manual stitching",
            "Do nothing",
        ]
        screen.query_one("#matrix-row-0-name", Input).value = "Trust in lineage"
        await screen.action_next()  # weight required; no invented defaults
        assert screen.index == 1
        assert "weight" in str(screen.query_one("#matrix-rows-error", Static).content).lower()
        screen.query_one("#matrix-row-0-weight", Input).value = "5"
        await screen.action_next()
        assert screen.index == 1
        assert "Benefit" in str(screen.query_one("#matrix-rows-error", Static).content)
        screen.query_one("#matrix-row-0-direction", Select).value = "benefit"
        screen.query_one("#matrix-add", Button).press()
        await pilot.pause()
        screen.query_one("#matrix-row-1-name", Input).value = "Effort per document"
        screen.query_one("#matrix-row-1-weight", Input).value = "3"
        screen.query_one("#matrix-row-1-direction", Select).value = "cost"
        await pilot.pause()
        assert store.load(session.id).method_state.get("criteria") is None
        await screen.action_next()
        saved = store.load(session.id).method_state
        assert saved["criteria"] == [
            {"name": "Trust in lineage", "weight": 5.0, "direction": "benefit"},
            {"name": "Effort per document", "weight": 3.0, "direction": "cost"},
        ]
        assert screen.index == 2
        assert screen.query_one("#field-score_0_0", Input)
        assert any("weight 3" in str(label.render()) for label in screen.query(".matrix-grid-cell"))
        for i in range(3):
            for j in range(2):
                screen.query_one(f"#field-score_{i}_{j}", Input).value = str(8 - i - j)
        await screen.action_next()
        assert screen.index == 3
        await screen.action_next()
        assert store.load(session.id).completed_at


@pytest.mark.asyncio
async def test_matrix_row_edits_keep_score_mapping_explicit(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(
        store.new_project("Decision"),
        "matrix",
        "Approach",
        completed_at="reviewed",
        method_state={
            "criteria": [{"name": "Value", "weight": 2, "direction": "benefit"}],
            "alternatives": [{"name": "Build", "scores": [8]}, {"name": "Buy", "scores": [3]}],
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        for _ in range(3):
            await screen.action_previous()
        screen.query_one("#matrix-row-0-name", Input).value = "Build ourselves"
        await screen.action_next()
        await pilot.pause()
        assert isinstance(app.screen, MatrixMappingDialog)
        assert [r["scores"] for r in store.load(session.id).method_state["alternatives"]] == [[8], [3]]
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert screen.index == 0
        assert screen.query_one("#matrix-row-0-name", Input).value == "Build ourselves"
        await screen.action_next()
        await pilot.pause()
        app.screen.query_one("#matrix-source-0", Select).value = 0
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert [r["scores"] for r in store.load(session.id).method_state["alternatives"]] == [[8], [3]]
        assert store.load(session.id).method_state["alternatives"][0]["name"] == "Build ourselves"


@pytest.mark.asyncio
async def test_matrix_bulk_paste_after_row_edits_remains_available(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(store.new_project("Decision"), "matrix", "Approach")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#matrix-row-0-name", Input).value = "Row draft"
        await pilot.pause()
        screen.query_one("#field-alternatives", TextArea).load_text("Pilot\nWait")
        await screen.action_next()  # no event loop pause required
        assert [r["name"] for r in store.load(session.id).method_state["alternatives"]] == ["Pilot", "Wait"]


@pytest.mark.asyncio
async def test_accepted_matrix_text_draft_keeps_existing_row_names(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(store.new_project("Decision"), "matrix", "Approach")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#matrix-row-0-name", Input).value = "Build"
        screen.query_one("#matrix-row-1-name", Input).value = "Buy"
        screen.apply_field_help("alternatives", "Wait", rows=True)
        assert screen.query_one("#field-alternatives", TextArea).text == "Build\nBuy\nWait"
        assert not store.load(session.id).method_state.get("alternatives")
        await screen.action_next()
        assert [r["name"] for r in store.load(session.id).method_state["alternatives"]] == ["Build", "Buy", "Wait"]


@pytest.mark.asyncio
async def test_zero_weight_survives_reopen_bulk_validation_and_save(tmp_path):
    state = {
        "criteria": [
            {"name": "Not important", "weight": 0, "direction": "benefit"},
            {"name": "Effort", "weight": 2, "direction": "cost"},
        ],
        "alternatives": [{"name": "Build", "scores": [8, 6]}, {"name": "Buy", "scores": [3, 2]}],
        "_guided_step": 1,
    }
    assert definition("matrix", state, 1).fields[0].value == ("Not important | 0 | benefit\nEffort | 2 | cost")
    # An unknown weight is still blank; zero is a deliberate, valid judgment.
    missing = {"criteria": [{"name": "Unknown", "weight": None, "direction": "benefit"}]}
    assert definition("matrix", missing, 1).fields[0].value == "Unknown |  | benefit"
    store = Store(tmp_path / "zero.db")
    session = Session(store.new_project("Decision"), "matrix", "Approach", method_state=state)
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(store.load(session.id), guided=True)
        await pilot.pause()
        screen = app.screen
        assert screen.index == 1
        assert screen.query_one("#matrix-row-0-weight", Input).value == "0"
        bulk = screen.query_one("#field-criteria", TextArea)
        assert bulk.text == "Not important | 0 | benefit\nEffort | 2 | cost"
        bulk.load_text("Not important |  | benefit\nEffort | 4 | cost")
        await screen.action_next()
        assert screen.index == 1
        assert "weight" in str(screen.query_one("#matrix-rows-error", Static).content).lower()
        assert store.load(session.id).method_state["criteria"] == state["criteria"]
        bulk.load_text("Not important | 0 | benefit\nEffort | 4 | cost")
        await screen.action_next()
        assert screen.index == 2
        saved = store.load(session.id).method_state
        assert [c["weight"] for c in saved["criteria"]] == [0, 4]
        assert [a["scores"] for a in saved["alternatives"]] == [[8, 6], [3, 2]]
        await screen.action_previous()
        assert screen.query_one("#field-criteria", TextArea).text == (
            "Not important | 0.0 | benefit\nEffort | 4.0 | cost"
        )
        await screen.action_next()
        app.open_session(store.load(session.id), guided=True)
        await pilot.pause()
        await app.screen.action_previous()
        assert app.screen.query_one("#matrix-row-0-weight", Input).value == "0.0"
        assert "Not important | 0.0 | benefit" in app.screen.query_one("#field-criteria", TextArea).text


@pytest.mark.asyncio
async def test_matrix_narrow_rows_and_many_score_columns_are_keyboard_reachable(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(
        store.new_project("Decision"),
        "matrix",
        "Approach",
        method_state={
            "criteria": [{"name": f"Criterion {i}", "weight": 2, "direction": "benefit"} for i in range(5)],
            "alternatives": [{"name": f"Option {i}", "scores": []} for i in range(12)],
            "_guided_step": 2,
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(55, 24)) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        scroller = screen.query_one(".matrix-score-scroll", HorizontalScroll)
        last = screen.query_one("#field-score_11_4", Input)
        assert scroller.max_scroll_x > 0 and scroller.max_scroll_y > 0
        last.focus()
        # Nested Textual scrollers animate independently; wait for both axes to settle.
        for _ in range(20):
            await pilot.pause(0.15)
            if (
                scroller.region.x <= last.region.x < last.region.right <= scroller.region.right
                and scroller.region.y <= last.region.y < last.region.bottom <= scroller.region.bottom
            ):
                break
        assert scroller.scroll_x > 0 and scroller.scroll_y > 0
        assert scroller.region.x <= last.region.x < last.region.right <= scroller.region.right
        assert scroller.region.y <= last.region.y < last.region.bottom <= scroller.region.bottom
        await screen.action_previous()
        await pilot.pause()
        assert screen.query_one(".workspace-layout").has_class("very-narrow")
        name = screen.query_one("#matrix-row-0-name", Input)
        assert name.region.width > 20
        for key in ("name", "weight", "direction"):
            widget = screen.query_one(f"#matrix-row-0-{key}")
            widget.focus()
            await pilot.pause()
            assert widget.region.width > 20
            assert screen.query_one(".editor-pane").region.y <= widget.region.y < 14
