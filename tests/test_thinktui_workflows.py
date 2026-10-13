"""Focused tests for visible priorities, hierarchy, resume, export and history."""

import pytest
from textual.widgets import Button, DataTable, Input, Label, Static

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.issue_tree import add, delete, nested, toggle, visible
from thinktui.reports import decision_brief, export
from thinktui.screens import History, Workspace
from thinktui.storage import Store
from thinktui.text_field import TextField


def test_tree_hierarchy_validation_and_legacy():
    state = {}
    root = add(state, "Root")
    child = add(state, "Child", parent_id=root)
    add(state, "Grandchild", parent_id=child)
    add(state, "Sibling", parent_id=root, after_id=child)
    assert [node["label"] for node in nested(state)[0]["children"]] == ["Child", "Sibling"]
    toggle(state, child)
    assert [node["label"] for node, _ in visible(state)] == ["Root", "Child", "Sibling"]
    assert len(nested(state)[0]["children"][0]["children"]) == 1  # folding is only visual
    delete(state, child)
    assert [node["label"] for node, _ in visible(state)] == ["Root", "Sibling"]
    legacy = {"entries": [{"statement": "Old branch"}]}
    assert METHODS["issue_tree"].calculate(legacy)["branches"][0]["label"] == "Old branch"
    add(legacy, "New branch")
    assert "entries" not in legacy
    assert [row["label"] for row in nested(legacy)] == ["Old branch", "New branch"]
    state["nodes"][1]["parent_id"] = "missing"
    with pytest.raises(ValueError, match="missing parent"):
        METHODS["issue_tree"].calculate(state)
    state["nodes"][1]["parent_id"] = state["nodes"][1]["id"]
    with pytest.raises(ValueError, match="cycle"):
        METHODS["issue_tree"].calculate(state)


@pytest.mark.asyncio
async def test_tree_keyboard_resume_and_export(tmp_path):
    store = Store(tmp_path / "tree.db")
    project = store.new_project("Incident")
    session = Session(project, "issue_tree", "Low adoption")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Workspace)
        editor = screen.query_one("#entry", TextField)
        editor.value = "Awareness"
        screen.tree_action("root")
        editor.value = "Documentation"
        screen.query_one("#tree", DataTable).focus()
        await pilot.press("a")
        editor.value = "Communication"
        screen.query_one("#tree", DataTable).move_cursor(row=1)
        screen.query_one("#tree", DataTable).focus()
        await pilot.press("s")
        assert [node["label"] for node in nested(session.method_state)[0]["children"]] == [
            "Documentation",
            "Communication",
        ]
        screen.query_one("#tree", DataTable).move_cursor(row=0)
        screen.query_one("#tree", DataTable).focus()
        await pilot.press("f")
        assert len(screen.tree_rows) == 1
        assert len(nested(session.method_state)[0]["children"]) == 2
        await pilot.press("f")
        screen.query_one("#tree", DataTable).move_cursor(row=1)
        screen.query_one("#tree", DataTable).focus()
        editor.value = "API documentation"
        screen.query_one("#tree", DataTable).move_cursor(row=1)
        assert editor.value == "API documentation"  # selecting a row never overwrites a draft
        screen.tree_action("edit")
        assert nested(session.method_state)[0]["children"][0]["label"] == "API documentation"
        path = tmp_path / "tree.md"
        export(session, path)
        assert "Children:" in path.read_text()
        assert "API documentation" in path.read_text()
        screen.query_one("#tree", DataTable).focus()
        await pilot.press("d")
        assert len(nested(session.method_state)[0]["children"]) == 2  # confirmation required
        app.screen.query_one("#cancel", Button).press()
        await pilot.pause()
        assert len(nested(session.method_state)[0]["children"]) == 2
        await pilot.press("d")
        app.screen.query_one("#confirm", Button).press()
        await pilot.pause()
        assert len(nested(session.method_state)[0]["children"]) == 1
        app.open_session(store.load(session.id))
        await pilot.pause()
        assert [node["label"] for node, _ in visible(app.session.method_state)] == ["Awareness", "Communication"]
        assert len(app.screen.tree_rows) == 2
    store.close()
    reopened = Store(tmp_path / "tree.db")
    assert [node["label"] for node, _ in visible(reopened.load(session.id).method_state)] == [
        "Awareness",
        "Communication",
    ]
    reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,entries,first,second,detail",
    [
        (
            "assumptions",
            [
                {"statement": "Minor", "confidence": 90, "impact": 2, "action": "Monitor"},
                {"statement": "Critical", "confidence": 20, "impact": 9, "action": "Run capacity test"},
            ],
            "Critical",
            "Minor",
            "TEST FIRST",
        ),
        (
            "premortem",
            [
                {"statement": "Minor", "likelihood": 10, "impact": 2, "action": "Log"},
                {"statement": "Critical", "likelihood": 80, "impact": 9, "action": "Add redundancy"},
            ],
            "Critical",
            "Minor",
            "Prevent: Add redundancy",
        ),
    ],
)
async def test_priority_visible_and_resumed(tmp_path, method, entries, first, second, detail):
    store = Store(tmp_path / "risk.db")
    project = store.new_project("Decision")
    session = Session(project, method, "Review")
    session.method_state["entries"] = entries
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(store.load(session.id))
        await pilot.pause()
        text = str(app.screen.query_one("#results", Static).render())
        assert text.index(first) < text.index(second)
        assert detail in text
        assert "impact 9/10" in text
        app.open_session(store.load(session.id))
        await pilot.pause()
        assert detail in str(app.screen.query_one("#results", Static).render())
    assert first in decision_brief(session)
    store.close()


@pytest.mark.asyncio
async def test_assumptions_impact_visible_and_saved_in_narrow_terminal(tmp_path):
    store = Store(tmp_path / "assumptions.db")
    project = store.new_project("Decision")
    session = Session(project, "assumptions", "Check")
    app = ThinkApp(store=store)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        impact = screen.query_one("#impact", Input)
        confidence = screen.query_one("#confidence", Input)
        assert impact.region.y > confidence.region.y
        assert impact.region.x + impact.region.width <= app.size.width
        assert any("Impact if wrong (1–10)" in str(label.render()) for label in screen.query(Label))
        screen.query_one("#entry", TextField).value = "Capacity holds"
        confidence.value = "25"
        impact.value = "9"
        assert screen.add_entry()
        assert store.load(session.id).method_state["entries"][0]["impact"] == 9
        app.open_session(store.load(session.id))
        await pilot.pause()
        assert "impact 9/10" in str(app.screen.query_one("#results", Static).render())
        path = tmp_path / "assumptions.md"
        export(app.session, path)
        assert "Impact: 9" in path.read_text()
    store.close()


@pytest.mark.asyncio
async def test_history_accessible_from_project(tmp_path):
    store = Store(tmp_path / "history.db")
    project = store.new_project("Decision")
    session = Session(project, "assumptions", "Check")
    store.save(session, "Created analysis")
    store.save(session, "Added assumption")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.project_id = project
        app.show_project()
        await pilot.pause()
        await pilot.press("h")
        assert isinstance(app.screen, History)
        assert app.screen.query_one("#events", DataTable).row_count == 1  # no event for an unchanged save
        rows = app.screen.query_one("#events", DataTable)
        assert "Created analysis" in str(rows.get_row_at(0))
        await pilot.press("escape")
        assert app.project_id == project
    store.close()
