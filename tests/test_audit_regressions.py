"""Regression coverage for the full-app audit (no live network or real DB writes)."""

from __future__ import annotations

from copy import deepcopy

import pytest
from textual.widgets import Button, DataTable, Input

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.field_ai import text_only
from thinktui.form_model import parse, schema_for
from thinktui.form_screen import FormScreen
from thinktui.planning import continue_workflow, sensitivity_from_matrix
from thinktui.screens import ProjectView, Workspace
from thinktui.storage import Store


def field(method: str, *keys: str):
    result = schema_for(method)
    for key in keys:
        item = next(item for item in result if item.key == key)
        result = item.children
    return item


def test_optional_sensitivity_direction_and_fmea_scale_and_decimal_fields():
    assert field("sensitivity", "criteria", "direction").choices == ("benefit", "cost")
    assert field("fmea", "scale_max").kind == "int"
    assert parse(field("fmea", "scale_max"), "20") == 20
    for method, path in (
        ("expected_value", ("alternatives", "outcomes", "value")),
        ("value_of_information", ("research_cost",)),
        ("reversibility", ("alternatives", "rollback_cost")),
        ("assumption_mapping", ("assumptions", "impact")),
        ("bottleneck", ("stages", "capacity")),
        ("stock_flow", ("dt",)),
    ):
        assert parse(field(method, *path), "1.5") == 1.5
    assert parse(field("stock_flow", "flows", "from"), "") is None
    assert parse(field("signposts", "indicators", "current"), "") is None


def test_reference_choices_and_numeric_bounds():
    for method, path in (
        ("sensitivity", ("vary",)),
        ("opportunity_cost", ("chosen",)),
        ("bradley_terry", ("comparisons", "a")),
        ("causal_loop", ("links", "to")),
        ("stock_flow", ("flows", "from")),
        ("bottleneck", ("proposal", "stage")),
    ):
        assert field(method, *path).kind == "reference"
    for method, path, raw in (
        ("bayesian_update", ("prior",), "1.1"),
        ("monte_carlo", ("iterations",), "99"),
        ("fmea", ("scale_max",), "21"),
    ):
        with pytest.raises(ValueError):
            parse(field(method, *path), raw)


def test_noop_saves_and_finish_reset_only_on_real_edit(tmp_path):
    store = Store(tmp_path / "data.db")
    session = Session(store.new_project("Work"), "issue_tree", "Problem")
    store.save(session)
    original = store.load(session.id).updated_at
    store.save(session, "Opened")
    assert store.load(session.id).updated_at == original
    assert len(store.events(session.id)) == 1
    session.completed_at = "2025-01-01T00:00:00+00:00"
    store.save(session, "Finished")
    store.save(session, "Opened")
    assert store.load(session.id).completed_at
    session.method_state["change_mind"] = "Observed new evidence"
    store.save(session, "Edited")
    assert store.load(session.id).completed_at is None
    store.close()


def test_snapshot_invalid_types_are_atomic_and_legacy_completion_migrates(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    project = store.new_project("Legacy")
    session = Session(project, "issue_tree", "Tree")
    store.save(session)
    event_at = "2025-05-01T12:00:00+00:00"
    with store.db:
        store.db.execute(
            "INSERT INTO events(session_id,timestamp,description,changes) VALUES (?,?,?,?)",
            (session.id, event_at, "Completed Issue Tree", "[]"),
        )
        store.db.execute("DROP TABLE project_events")
        store.db.execute("PRAGMA user_version=3")
    store.close()
    store = Store(path)
    assert store.load(session.id).completed_at == event_at
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 5
    snapshot = store.snapshot(project)
    before = [
        store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("projects", "sessions", "events")
    ]
    for value in (None, [], "invalid"):
        bad = deepcopy(snapshot)
        bad["sessions"][0]["method_state"] = value
        with pytest.raises(ValueError):
            store.import_snapshot(bad)
    bad = deepcopy(snapshot)
    bad["project_events"] = [{"timestamp": None, "before": "", "after": "changed"}]
    with pytest.raises(ValueError):
        store.import_snapshot(bad)
    for name, value in (("title", 2), ("completed_at", [])):
        bad = deepcopy(snapshot)
        bad["sessions"][0][name] = value
        with pytest.raises(ValueError):
            store.import_snapshot(bad)
    assert before == [
        store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("projects", "sessions", "events")
    ]
    uppercase = deepcopy(snapshot)
    uppercase["project"]["id"] = uppercase["project"]["id"].upper()
    uppercase["sessions"][0]["id"] = uppercase["sessions"][0]["id"].upper()
    uppercase["sessions"][0]["project_id"] = uppercase["project"]["id"]
    for event in uppercase["events"]:
        event["session_id"] = event["session_id"].upper()
    imported = store.import_snapshot(uppercase)
    assert len(store.sessions(imported)) == 1
    store.close()


def test_planning_question_history_and_snapshot_migration(tmp_path):
    store = Store(tmp_path / "history.db")
    project = store.new_project("Study")
    store.set_planning_question(project, "Which release plan is safest?")
    store.set_planning_question(project, "Which release plan is safest?")
    assert len(store.project_events(project)) == 1
    snapshot = store.snapshot(project)
    restored = store.import_snapshot(snapshot)
    assert store.project_events(restored)[0]["after"] == "Which release plan is safest?"
    store.delete_project(project)
    assert not store.project_events(project)
    assert store.project_events(restored)
    store.close()


def test_duplicate_and_move_preserve_other_projects(tmp_path):
    store = Store(tmp_path / "move.db")
    a, b = store.new_project("One"), store.new_project("Two")
    session = Session(
        a,
        "matrix",
        "Analysis",
        method_state={"criteria": [{"name": "Time", "weight": 1}], "workflow_id": "original", "workflow_index": 0},
    )
    store.save(session)
    copy = store.duplicate_session(session.id)
    assert copy.title == "Analysis · copy"
    assert copy.completed_at is None and copy.id != session.id
    assert "workflow_id" not in copy.method_state
    assert session.id in [s.id for s in store.sessions(a)]
    store.move_session(copy.id, b)
    assert copy.id in [s.id for s in store.sessions(b)]
    assert copy.id not in [s.id for s in store.sessions(a)]
    assert store.load(session.id).project_id == a
    with pytest.raises(KeyError):
        store.move_session(session.id, "not-a-project")
    store.close()


def test_planned_rank_workflow_copies_two_only():
    state = {
        "criteria": [{"name": "Cost", "weight": 1, "direction": "cost"}, {"name": "Value", "weight": 2}],
        "alternatives": [
            {"name": name, "scores": scores} for name, scores in (("A", [2, 9]), ("B", [8, 5]), ("C", [4, 4]))
        ],
        "workflow_id": "wf",
        "workflow_goal": "Rank alternatives",
        "workflow_steps": ["matrix", "sensitivity", "premortem"],
        "workflow_index": 0,
    }
    matrix = Session("p", "matrix", "Ranking", method_state=state, completed_at="2025-01-01")
    draft = continue_workflow(matrix)
    assert len(draft.method_state["alternatives"]) == 2
    assert draft.method_state["source_session_id"] == matrix.id
    assert draft.method_state["workflow_index"] == 1
    assert not METHODS["sensitivity"].validate(draft.method_state)
    assert len(sensitivity_from_matrix(matrix).method_state["alternatives"]) == 2


def test_text_only_drops_judgments_not_phase_names():
    assert text_only("Phase 2 is urgent\nScore: 8\nReview in Q3\n2027-01-01\n80%") == "Phase 2 is urgent\nReview in Q3"


@pytest.mark.asyncio
async def test_sensitivity_reorder_keeps_scores_aligned_and_example_cannot_replace(tmp_path):
    store = Store(tmp_path / "app.db")
    state = {
        "criteria": [{"name": "Quality", "weight": 0.6}, {"name": "Cost", "weight": 0.4, "direction": "cost"}],
        "alternatives": [{"name": "A", "scores": [9, 2]}, {"name": "B", "scores": [5, 8]}],
        "vary": "Quality",
        "range": [0, 1],
    }
    session = Session(store.new_project("Work"), "sensitivity", "Ranking", method_state=deepcopy(state))
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        assert "Cost" in screen.grid_heading(("alternatives", 0, "scores"), 0, 1)
        group = next(g for g, path in screen.groups.items() if path == ("criteria",))
        screen.query_one(f"#{group}-up-1", Button).press()
        await pilot.pause()
        assert session.method_state["alternatives"] == [
            {"name": "A", "scores": [2, 9]},
            {"name": "B", "scores": [8, 5]},
        ]
        assert not METHODS["sensitivity"].validate(session.method_state)
        saved = deepcopy(session.method_state)
        screen.query_one("#load-example", Button).press()
        await pilot.pause()
        assert session.method_state == saved
        group = next(g for g, path in screen.groups.items() if path == ("alternatives",))
        screen.query_one(f"#{group}-add", Button).press()
        await pilot.pause()
        assert session.method_state["alternatives"][-1] == {"name": "", "scores": []}  # no nested score row
    store.close()


@pytest.mark.asyncio
async def test_project_rename_delete_single_analysis_and_finish(tmp_path):
    store = Store(tmp_path / "app.db")
    project = store.new_project("Work")
    session = Session(
        project,
        "issue_tree",
        "One",
        method_state={"nodes": [{"id": "root", "parent_id": None, "label": "Question?", "collapsed": False}]},
    )
    store.save(session)
    other = Session(project, "issue_tree", "Two")
    store.save(other)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        app.screen.query_one("#finish-stage", Button).press()
        await pilot.pause()
        assert store.load(session.id).completed_at
        app.show_project()
        await pilot.pause()
        assert isinstance(app.screen, ProjectView)
        table = app.screen.query_one("#analyses", DataTable)
        assert "Finished" in str(
            table.get_row_at(next(i for i, s in enumerate(store.sessions(project)) if s.id == session.id))
        )
        table.move_cursor(row=next(i for i, sid in enumerate(app.screen.analysis_rows) if sid == session.id))
        table.focus()
        await pilot.press("f2")
        await pilot.pause()
        app.screen.query_one("#new-name", Input).value = "Renamed"
        await pilot.click("#confirm")
        await pilot.pause()
        assert store.load(session.id).title == "Renamed"
        table = app.screen.query_one("#analyses", DataTable)
        table.move_cursor(row=next(i for i, sid in enumerate(app.screen.analysis_rows) if sid == session.id))
        table.focus()
        await pilot.press("delete")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        with pytest.raises(KeyError):
            store.load(session.id)
        assert store.load(other.id).title == "Two"
    store.close()
