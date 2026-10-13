"""Safety regressions: hostile snapshot contents, literal UI text, atomic upgrades."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from textual.widgets import Button, Checkbox, Collapsible, DataTable, Input, TextArea
from textual.widgets import Select as TextualSelect
from textual.widgets import Static as TextualStatic

from pairwise_prioritizer.comparison_engine import create_project
from pairwise_prioritizer.models import Item
from thinktui import ai, screens
from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.field_ai import text_only
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.guided_workflow import LabelMappingRequired, MatrixMappingRequired, advance, reachable_index
from thinktui.label_mapping_screen import LabelMappingDialog
from thinktui.matrix_mapping_screen import MatrixMappingDialog
from thinktui.planning import planned_next, recommend
from thinktui.reports import decision_brief
from thinktui.safe_widgets import DataTable as SafeTable
from thinktui.safe_widgets import Label as SafeLabel
from thinktui.safe_widgets import Static as SafeStatic
from thinktui.screens import (
    AnalysisDialog,
    DeleteBranchDialog,
    DeleteProjectDialog,
    History,
    Home,
    JournalList,
    MoveAnalysisDialog,
    NewAnalysis,
    NewProject,
    Settings,
    Workspace,
)
from thinktui.storage import Store
from thinktui.text_field import TextField


def test_migrations_racing_on_a_fresh_database(tmp_path):
    path = tmp_path / "fresh.db"

    def open_store(_):
        store = Store(path)
        try:
            return store.db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(open_store, range(16))) == [7] * 16


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["attempt to write a readonly database", "database is locked"])
async def test_create_project_db_errors_keep_user_input(tmp_path, monkeypatch, error):
    store = Store(tmp_path / "blocked.db")

    def fail(name):
        raise sqlite3.OperationalError(error)

    monkeypatch.setattr(store, "new_project", fail)
    app = ThinkApp(store, initial="new")
    async with app.run_test() as pilot:
        editor = app.screen.query_one("#name", Input)
        editor.value = "Draft project"
        app.screen.create()
        await pilot.pause()
        assert isinstance(app.screen, NewProject)
        assert editor.value == "Draft project"
        assert store.projects() == []
    store.close()


@pytest.mark.asyncio
async def test_create_analysis_locked_db_keeps_draft(tmp_path, monkeypatch):
    store = Store(tmp_path / "blocked-analysis.db")
    project = store.new_project("Work")
    app = ThinkApp(store)
    app.project_id = project
    app.method_id = "premortem"
    async with app.run_test() as pilot:
        app.switch_screen(NewAnalysis())
        await pilot.pause()
        editor = app.screen.query_one("#title", Input)
        editor.value = "Do not lose this title"
        original_save = store.save

        def fail(session, description=""):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(store, "save", fail)
        app.screen.start()
        await pilot.pause()
        assert isinstance(app.screen, NewAnalysis)
        assert editor.value == "Do not lose this title"
        assert not store.sessions(project)
        monkeypatch.setattr(store, "save", original_save)
    store.close()


@pytest.mark.asyncio
async def test_malformed_ai_stream_notifies_without_mutating_analysis(tmp_path, monkeypatch):
    store = Store(tmp_path / "ai.db")
    store.set_setting("ai_provider", "ollama")
    project = store.new_project("Work")
    session = Session(project, "premortem", "Risk")
    store.save(session)

    class Malformed:
        async def preparing_note(self):
            return "ready"

        async def stream(self, prompt):
            yield 5  # not a text chunk: previously raised an unhandled TypeError

    async def connect(_):
        return Malformed(), ai.ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(screens, "connect", connect)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        app.screen.action_challenge()
        await app.screen.workers.wait_for_complete()
        assert "AI unavailable" in str(app.screen.query_one("#ai-response").content)
        assert store.load(session.id).method_state == {}
    store.close()


def test_v5_upgrade_creates_triggers_without_touching_prior_history(tmp_path):
    path = tmp_path / "v5.db"
    store = Store(path)
    project = store.new_project("Old project")
    session = Session(project, "issue_tree", "History")
    store.save(session)
    original = store.events(session.id)[0]["description"]
    with store.db:
        store.db.execute("DROP TRIGGER events_no_update")
        store.db.execute("DROP TRIGGER events_no_delete")
        store.db.execute("DROP TABLE event_delete_permissions")
        store.db.execute("PRAGMA user_version=5")
    store.close()
    store = Store(path)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 7
    assert store.events(session.id)[0]["description"] == original
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE events SET description='changed' WHERE session_id=?", (session.id,))
    store.close()


def test_event_triggers_block_updates_and_unapproved_deletes(tmp_path):
    store = Store(tmp_path / "audit.db")
    project = store.new_project("Work")
    session = Session(project, "issue_tree", "Tree")
    store.save(session)
    event = store.events(session.id)[0]
    with pytest.raises(sqlite3.IntegrityError, match="cannot be updated"):
        with store.db:
            store.db.execute("UPDATE events SET description=? WHERE session_id=?", ("Changed", session.id))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        with store.db:
            store.db.execute("DELETE FROM events WHERE session_id=?", (session.id,))
    assert store.events(session.id)[0]["description"] == event["description"]
    store.delete_session(session.id)  # confirmed destructive operations remain atomic
    assert store.events(session.id) == []
    assert store.db.execute("SELECT count(*) FROM event_delete_permissions").fetchone()[0] == 0
    store.close()


def test_stale_window_cannot_overwrite_another_windows_edit(tmp_path):
    store = Store(tmp_path / "stale.db")
    project = store.new_project("Work")
    session = Session(project, "issue_tree", "Tree")
    store.save(session)
    first, stale = store.load(session.id), store.load(session.id)
    first.problem_statement = "First editor"
    store.save(first)
    stale.problem_statement = "Second editor"
    with pytest.raises(ValueError, match="another window"):
        store.save(stale)
    assert store.load(session.id).problem_statement == "First editor"
    store.close()


def test_settings_batch_is_validated_and_committed_atomically(tmp_path):
    store = Store(tmp_path / "settings.db")
    store.set_setting("ollama_host", "http://localhost:11434")
    with pytest.raises(ValueError):
        store.set_settings({"ollama_host": "", "ai.custom.base_url": "http://user:password@example.test/v1"})
    assert store.setting("ollama_host") == "http://localhost:11434"
    with store.db:
        store.db.execute("""CREATE TRIGGER fail_provider BEFORE INSERT ON settings
            WHEN NEW.key='ai_provider' BEGIN SELECT RAISE(ABORT, 'database is locked'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.set_settings({"ollama_host": "", "ai_provider": "openai"})
    assert store.setting("ollama_host") == "http://localhost:11434"
    store.close()


@pytest.mark.asyncio
async def test_malformed_settings_provider_responses_keep_ui_alive(tmp_path, monkeypatch):
    store = Store(tmp_path / "settings-provider.db")
    app = ThinkApp(store, initial="settings")

    class BrokenProvider:
        async def models(self):
            return [None, 5]

        async def health_check(self):
            raise TypeError("invalid provider schema")

    monkeypatch.setattr(screens, "create", lambda *args, **kwargs: BrokenProvider())
    async with app.run_test():
        screen = app.screen
        screen.action_refresh_models()
        await screen.workers.wait_for_complete()
        assert "unreadable response" in str(screen.query_one("#models-status").content)
        screen.action_test()
        await screen.workers.wait_for_complete()
        assert "✗" in str(screen.query_one("#test-result").content)
        assert isinstance(app.screen, Settings)
    store.close()


@pytest.mark.asyncio
async def test_settings_invalid_url_does_not_clear_legacy_host(tmp_path):
    store = Store(tmp_path / "settings-ui.db")
    store.set_setting("ollama_host", "http://localhost:11434")
    app = ThinkApp(store, initial="settings")
    async with app.run_test() as pilot:
        screen = app.screen
        assert isinstance(screen, Settings)
        screen.drafts["custom"] = ("http://name:password@example.test/v1", "model", "")
        screen.action_save()
        await pilot.pause()
        assert isinstance(app.screen, Settings)
        assert store.setting("ollama_host") == "http://localhost:11434"
        assert store.setting("ai.custom.base_url") == ""
    store.close()


def test_newer_database_is_not_modified(tmp_path):
    path = tmp_path / "newer.db"
    import sqlite3

    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="newer"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


@pytest.mark.parametrize(
    ("steps", "index"),
    [
        (["issue_tree", "bogus"], 0),
        (["issue_tree", "premortem"], 2),
        (["premortem", "issue_tree"], 0),
        (["issue_tree", "premortem"], True),
        ([], 0),
    ],
)
def test_import_rejects_invalid_workflow_references_before_recommend(tmp_path, steps, index):
    store = Store(tmp_path / "bad-workflow.db")
    project = store.new_project("Study")
    state = {
        "nodes": [{"id": "node", "parent_id": None, "label": "Root", "collapsed": False}],
        "workflow_id": "plan",
        "workflow_goal": "Understand a problem",
        "workflow_steps": steps,
        "workflow_index": index,
    }
    session = Session(project, "issue_tree", "Tree", method_state=state, completed_at="2026-10-09T00:00:00+00:00")
    store.save(session)
    snapshot = store.snapshot(project)
    with pytest.raises(ValueError, match="workflow"):
        store.import_snapshot(snapshot)
    assert len(store.projects()) == 1
    # A pre-existing corrupt local record must not crash method recommendations either.
    assert planned_next(store.load(session.id)) is None
    assert all(method in METHODS for method, _ in recommend(source=store.load(session.id)))
    store.close()


def test_duplicate_event_links_remap_on_import(tmp_path):
    store = Store(tmp_path / "links.db")
    project = store.new_project("Work")
    original = Session(project, "issue_tree", "Outline")
    store.save(original)
    copied = store.duplicate_session(original.id)
    target = store.import_snapshot(store.snapshot(project))
    imported = {row.title: row for row in store.sessions(target)}
    assert store.events(imported[copied.title].id)[0]["description"] == (
        "Duplicated from analysis " + imported[original.title].id
    )
    store.close()


@pytest.mark.parametrize(
    ("method_id", "state"),
    [
        ("monte_carlo", {"variables": [{"name": "X", "distribution": "lognormal", "mean": 1000}]}),
        ("monte_carlo", {"variables": [{"name": "X", "distribution": "samples", "values": [1, {}]}]}),
        ("monte_carlo", {"variables": [{"name": "X", "distribution": "discrete", "weights": "bad"}]}),
        ("causal_loop", {"variables": [1]}),
        ("forecasting", {"forecasts": [{"question": "Q", "probability": []}]}),
        ("value_of_information", {"actions": [{"name": "A", "payoffs": []}]}),
        ("strategy_stress", {"strategies": [{"name": "A", "scores": None}]}),
        ("decision_tree", {"tree": {"type": "decision", "branches": [{"name": "A", "node": [1]}]}}),
        ("ach", {"evidence": [{"title": "Claim", "ratings": ["+"]}]}),
        ("scenarios", {"strategies": [{"name": "A", "actions": ["bad"]}]}),
        ("scenarios", {"strategies": [{"name": "A", "actions": {"low_low": [], "unknown": "x"}}]}),
        ("monte_carlo", {"variables": [{"name": "X", "distribution": "uniform", "unexpected": {"values": [1]}}]}),
    ],
)
def test_import_rejects_malformed_unfinished_method_states(tmp_path, method_id, state):
    store = Store(tmp_path / "invalid-draft.db")
    project = store.new_project("Backup")
    session = Session(project, method_id, "Unfinished", method_state=state)
    store.save(session)
    with pytest.raises(ValueError, match="Snapshot"):
        store.import_snapshot(store.snapshot(project))
    assert len(store.projects()) == 1
    store.close()


def test_all_40_methods_can_roundtrip_legitimate_unfinished_shapes(tmp_path):
    store = Store(tmp_path / "catalog-drafts.db")
    project = store.new_project("All methods")
    for method in METHODS.values():
        store.save(Session(project, method.id, method.id, method_state=deepcopy(getattr(method, "example", {}))))
    imported = store.import_snapshot(store.snapshot(project))
    assert len(store.sessions(imported)) == len(METHODS) == 40
    store.close()


def test_import_accepts_legitimate_incomplete_monte_carlo(tmp_path):
    store = Store(tmp_path / "draft.db")
    project = store.new_project("Backup")
    state = {"variables": [{"name": "X", "distribution": "lognormal", "mean": 1}]}
    store.save(Session(project, "monte_carlo", "Draft", method_state=state))
    restored = store.import_snapshot(store.snapshot(project))
    assert store.sessions(restored)[0].method_state == state
    store.close()


def test_bad_snapshots_are_atomic(tmp_path):
    store = Store(tmp_path / "backup.db")
    project = store.new_project("Work")
    session = Session(project, "issue_tree", "Outline")
    store.save(session)
    snapshot = store.snapshot(project)
    invalid = [
        ("updated_at", 123),
        ("problem_statement", ["x"]),
        ("method_state", {"nodes": [{"id": "x", "parent_id": "x", "label": "cycle"}]}),
        ("method_state", {"entries": "zzz"}),
        ("method_state", {"nodes": [1]}),
    ]
    for key, value in invalid:
        bad = deepcopy(snapshot)
        bad["sessions"][0][key] = value
        with pytest.raises(ValueError):
            store.import_snapshot(bad)
    bad = deepcopy(snapshot)
    bad["sessions"][0]["notes"] = float("nan")
    with pytest.raises(ValueError):
        store.import_snapshot(bad)
    assert len(store.projects()) == 1
    store.close()


def test_local_requests_disable_proxies_and_all_requests_block_redirects(monkeypatch):
    handlers = []

    class FakeOpener:
        def open(self, req, timeout):
            return req

    def build(*args):
        handlers.append(args)
        return FakeOpener()

    monkeypatch.setattr(ai.request, "build_opener", build)
    ai._open("http://localhost:11434/api/chat", {}, None, 1)
    assert any(isinstance(h, ai.request.ProxyHandler) and h.proxies == {} for h in handlers[-1])
    ai._open("https://example.com/chat", {}, {"Authorization": "Bearer secret"}, 1)
    assert any(isinstance(h, ai._NoRedirect) for h in handlers[-1])
    assert handlers[-1][0].redirect_request(None, None, 302, "Redirect", {}, "https://evil.test") is None


def test_report_escapes_table_cells_and_journal_headings():
    matrix = Session(
        "project",
        "matrix",
        "Options",
        method_state={
            "criteria": [{"name": "Price | total", "weight": 1, "direction": "cost"}],
            "alternatives": [{"name": "A | B", "scores": [2]}, {"name": "C", "scores": [3]}],
        },
    )
    report = decision_brief(matrix)
    assert "Price \\| total" in report and "A \\| B" in report
    journal = Session(
        "project",
        "journal",
        "Decision",
        method_state={"decision": "Decision", "chosen": "A", "rationale": "## Fake heading"},
    )
    assert "\\## Fake heading" in decision_brief(journal)


def test_missing_risk_ratings_are_not_invented():
    for method in ("assumptions", "premortem"):
        missing = {"entries": [{"statement": "User observation"}]}
        assert METHODS[method].validate(missing)
        with pytest.raises(ValueError):
            METHODS[method].calculate(missing)


def test_validation_accepts_arbitrary_json_shapes_without_crashing():
    shapes = [
        {},
        {"entries": "not a list"},
        {"criteria": ["bad"], "alternatives": [1]},
        {"ranking": None},
        {"variables": ["bad"]},
        {"decision": None},
        {"nodes": [None]},
    ]
    for method in METHODS.values():
        for shape in shapes:
            result = method.validate(shape)
            assert isinstance(result, list), (method.id, shape)


def test_dense_causal_graph_truncates_without_hanging():
    variables = [f"V{i:02}" for i in range(50)]
    links = [
        {"from": variables[i], "to": variables[(i + step) % 50], "polarity": 1}
        for i in range(50)
        for step in range(1, 7)
    ]
    result = METHODS["causal_loop"].calculate({"variables": variables, "links": links})
    assert result["truncated"] is True
    assert len(result["loops"]) <= 100


def test_ach_and_ahp_removal_requires_explicit_discard_and_preserves_remaining_judgments():
    ach = {
        "hypotheses": ["Fault", "Normal", "Unknown"],
        "evidence": [
            {
                "title": "Logs",
                "source": "Ops",
                "reliability": 0.8,
                "ratings": {"Fault": "+", "Normal": "-", "Unknown": "?"},
            }
        ],
    }
    with pytest.raises(ValueError, match="Unknown"):
        advance("ach", ach, 0, {"hypotheses": "Fault\nNormal"}, mapping=[0, 1])
    kept = advance("ach", ach, 0, {"hypotheses": "Fault\nNormal"}, mapping=[0, 1], discard_judgments=True)
    assert kept["evidence"][0]["ratings"] == {"Fault": "+", "Normal": "-"}
    assert "Unknown" in ach["evidence"][0]["ratings"]
    added = advance("ach", ach, 0, {"hypotheses": "Fault\nNormal\nUnknown\nNew"}, mapping=[0, 1, 2, None])
    assert added["evidence"][0]["ratings"]["New"] == ""  # AI must not invent a rating
    assert reachable_index("ach", added) == 1
    ratio = [[1, 3, 2], [1 / 3, 1, 0.5], [0.5, 2, 1]]
    ahp = {
        "criteria": ["Value", "Cost", "Speed"],
        "alternatives": ["A", "B", "C"],
        "criteria_matrix": ratio,
        "alternative_matrices": {key: deepcopy(ratio) for key in ("Value", "Cost", "Speed")},
    }
    with pytest.raises(ValueError, match="Speed"):
        advance("ahp", ahp, 0, {"criteria": "Value\nCost"}, mapping=[0, 1])
    reduced = advance("ahp", ahp, 0, {"criteria": "Value\nCost"}, mapping=[0, 1], discard_judgments=True)
    assert reduced["criteria_matrix"] == [[1, 3], [1 / 3, 1]]
    assert set(reduced["alternative_matrices"]) == {"Value", "Cost"}
    assert "Speed" in ahp["alternative_matrices"]
    with pytest.raises(ValueError, match="B"):
        advance("ahp", ahp, 1, {"alternatives": "A\nC"}, mapping=[0, 2])
    alt_reduced = advance("ahp", ahp, 1, {"alternatives": "A\nC"}, mapping=[0, 2], discard_judgments=True)
    assert alt_reduced["alternative_matrices"]["Value"] == [[1, 2], [0.5, 1]]
    expanded = advance("ahp", ahp, 0, {"criteria": "Value\nCost\nSpeed\nQuality"}, mapping=[0, 1, 2, None])
    assert expanded["criteria_matrix"][0][:3] == ratio[0]
    assert expanded["criteria_matrix"][0][3] == ""
    assert reachable_index("ahp", expanded) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", ["ach", "ahp"])
async def test_guided_removal_requires_named_checkbox_and_audits_saved_judgments(tmp_path, method_id):
    store = Store(tmp_path / "guided-removal.db")
    project = store.new_project("Work")
    if method_id == "ach":
        state = {
            "hypotheses": ["Fault", "Normal", "Unknown"],
            "evidence": [
                {
                    "title": "Logs",
                    "source": "Ops",
                    "reliability": 0.8,
                    "ratings": {"Fault": "+", "Normal": "-", "Unknown": "?"},
                }
            ],
        }
        field, text, lost = "hypotheses", "Fault\nNormal", "Unknown"
    else:
        matrix = [[1, 3, 2], [1 / 3, 1, 0.5], [0.5, 2, 1]]
        state = {
            "criteria": ["Value", "Cost", "Speed"],
            "alternatives": ["A", "B", "C"],
            "criteria_matrix": matrix,
            "alternative_matrices": {key: deepcopy(matrix) for key in ("Value", "Cost", "Speed")},
        }
        field, text, lost = "criteria", "Value\nCost", "Speed"
    state["_guided_step"] = 0
    session = Session(project, method_id, "Case", method_state=deepcopy(state))
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        screen.query_one(f"#field-{field}", TextArea).load_text(text)
        await screen.action_next()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, LabelMappingDialog)
        assert lost in str(dialog.query_one("#discard-label").content)
        assert not dialog.query_one("#discard-judgments", Checkbox).value
        dialog.query_one("#confirm", Button).press()
        await pilot.pause()
        assert lost in str(dialog.query_one("#mapping-error").content)
        assert store.load(session.id).method_state == state  # no silent changes before opt-in
        dialog.query_one("#discard-judgments", Checkbox).value = True
        dialog.query_one("#label-source-0", TextualSelect).value = 2
        await pilot.pause()
        assert not dialog.query_one("#discard-judgments", Checkbox).value  # any remapping requires new consent
        assert ("Fault" if method_id == "ach" else "Value") in str(dialog.query_one("#discard-label").content)
        dialog.query_one("#label-source-0", TextualSelect).value = 0
        await pilot.pause()
        assert lost in str(dialog.query_one("#discard-label").content)
        dialog.query_one("#discard-judgments", Checkbox).value = True
        dialog.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        saved = store.load(session.id).method_state
        assert lost not in saved[field]
        if method_id == "ach":
            assert saved["evidence"][0]["ratings"] == {"Fault": "+", "Normal": "-"}
            assert app.screen.query_one("#review-saved", Button)
            app.screen.query_one("#review-saved", Button).press()
            await pilot.pause()
            assert app.screen.index == 2
        else:
            assert saved["criteria_matrix"] == [[1, 3], [1 / 3, 1]]
            assert set(saved["alternative_matrices"]) == {"Value", "Cost"}
        changes = [entry["field"] for event in store.events(session.id) for entry in json.loads(event["changes"])]
        assert "method_state." + field in changes
    store.close()


@pytest.mark.asyncio
async def test_guided_ahp_addition_keeps_old_pairs_and_prompts_for_new_pairs(tmp_path):
    store = Store(tmp_path / "guided-ahp-addition.db")
    project = store.new_project("Work")
    state = {
        "criteria": ["Value", "Cost"],
        "alternatives": ["A", "B"],
        "criteria_matrix": [[1, 3], [1 / 3, 1]],
        "alternative_matrices": {"Value": [[1, 2], [0.5, 1]], "Cost": [[1, 0.5], [2, 1]]},
        "_guided_step": 0,
    }
    session = Session(project, "ahp", "Priorities", method_state=state)
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#field-criteria", TextArea).load_text("Value\nCost\nSpeed")
        await app.screen.action_next()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, LabelMappingDialog)
        assert dialog.query_one("#label-source-2", TextualSelect).value == -1
        dialog.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        saved = store.load(session.id).method_state
        assert saved["criteria_matrix"][0][1] == 3
        assert saved["criteria_matrix"][0][2] == ""
        await app.screen.action_next()  # unchanged alternatives
        assert app.screen.index == 2
        assert app.screen.query_one("#field-pair_0_2", TextField).value == ""
        app.screen.query_one("#field-pair_0_2", TextField).value = "2"
        app.screen.query_one("#field-pair_1_2", TextField).value = "1/2"
        await app.screen.action_next()
        assert store.load(session.id).method_state["criteria_matrix"][0][1] == 3
        assert store.load(session.id).method_state["criteria_matrix"][0][2] == 2
        assert app.screen.index == 3
    store.close()


@pytest.mark.asyncio
async def test_guided_ach_addition_keeps_old_evidence_and_requires_new_user_rating(tmp_path):
    store = Store(tmp_path / "guided-addition.db")
    project = store.new_project("Work")
    state = {
        "hypotheses": ["Fault", "Normal"],
        "evidence": [{"title": "Logs", "source": "Ops", "reliability": 0.8, "ratings": {"Fault": "+", "Normal": "-"}}],
        "_guided_step": 0,
    }
    session = Session(project, "ach", "Diagnosis", method_state=state)
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        app.screen.query_one("#field-hypotheses", TextArea).load_text("Fault\nNormal\nTraffic")
        await app.screen.action_next()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, LabelMappingDialog)
        assert dialog.query_one("#label-source-2", TextualSelect).value == -1
        dialog.query_one("#confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert app.screen.index == 1
        assert store.load(session.id).method_state["evidence"][0]["ratings"] == {
            "Fault": "+",
            "Normal": "-",
            "Traffic": "",
        }
        assert app.screen.query_one("#edit-saved", Button)
        app.screen.query_one("#edit-saved", Button).press()
        await pilot.pause()
        app.screen.query_one("#field-rating_2", TextField).value = "+"
        await app.screen.action_next()
        await pilot.pause()
        saved = store.load(session.id).method_state
        assert len(saved["evidence"]) == 1
        assert saved["evidence"][0]["ratings"]["Traffic"] == "+"
        assert METHODS["ach"].validate(saved) == []
    store.close()


def test_forecast_back_navigation_revises_instead_of_duplicating():
    state = advance("forecasting", {}, 0, {"question": "Will it ship?", "resolution_date": "", "rationale": ""})
    state = advance("forecasting", state, 1, {"probability": "60"})
    assert len(state["forecasts"]) == 1
    state = advance("forecasting", state, 1, {"probability": "70"})
    assert len(state["forecasts"]) == 1
    assert state["forecasts"][0]["probability"] == 0.7
    state = advance("forecasting", state, 0, {"question": "Will it launch?", "resolution_date": "", "rationale": ""})
    state = advance("forecasting", state, 1, {"probability": "70"})
    assert len(state["forecasts"]) == 1
    assert state["forecasts"][0]["question"] == "Will it launch?"


def test_numeric_drafts_cannot_supply_judgments():
    for sample in (
        "Quality | 9 | benefit",
        "**Probability:** 0.7",
        "Weight = .4",
        "Cost: $5000",
        "Severity: 9",
        "seventy percent",
        "eight out of ten",
        "½",
        "Source reliability: 0.8",
    ):
        assert text_only(sample) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("method_id", ["evidence_matrix", "ach", "bayesian_update"])
async def test_ai_cannot_draft_or_accept_evidence_and_source_fields(tmp_path, method_id):
    from thinktui.core import METHODS

    store = Store(tmp_path / "evidence.db")
    project = store.new_project("Work")
    session = Session(project, method_id, "Evidence", method_state=deepcopy(METHODS[method_id].example))
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.session = session
        app.project_id = project
        app.switch_screen(FormScreen(session))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        for ident, (path, field) in screen.fields.items():
            if path[0] == "evidence" and field.kind in {"text", "long_text"}:
                assert not screen.query(f"#suggest-{ident}"), path
                screen.ai_target = None
                screen.suggest(ident)  # stale/programmatic clicks must be refused too
                assert screen.ai_target is None, path
                screen.ai_ready = True
                screen.ai_target = ident
                screen.query_one("#form-preview", TextArea).load_text("Invented observation")
                screen.accept()
                assert screen.value_at(path) != "Invented observation"
        assert store.load(session.id).method_state == METHODS[method_id].example
    store.close()


@pytest.mark.asyncio
async def test_example_does_not_complete_a_form_or_seed_blank_json(tmp_path):
    store = Store(tmp_path / "examples.db")
    project = store.new_project("Work")
    session = Session(project, "backcasting", "Future")
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        screen.query_one("#load-example").press()
        await pilot.pause()
        screen.action_save()
        assert store.load(session.id).completed_at is None
        assert "illustrative" in str(screen.query_one("#form-error").content)
        app.open_session(Session(project, "backcasting", "Blank"), advanced=True)
        await pilot.pause()
        from textual.widgets import TextArea

        assert '"future_state"' not in app.screen.query_one("#structured-input", TextArea).text
    store.close()


@pytest.mark.asyncio
async def test_pending_editor_changes_flush_on_navigation_and_quit(tmp_path):
    store = Store(tmp_path / "autosave.db")
    project = store.new_project("Work")
    session = Session(project, "journal", "Decision")
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        app.screen.query_one("#change-mind", TextField).value = "Evidence contradicts the plan"
        await pilot.pause()
        app.home()
        await pilot.pause()
        assert store.load(session.id).method_state["change_mind"] == "Evidence contradicts the plan"
        app.open_session(store.load(session.id))
        await pilot.pause()
        app.screen.query_one("#change-mind", TextField).value = "A better alternative appears"
        await pilot.pause()
        app.action_quit()
        await pilot.pause()
        assert store.load(session.id).method_state["change_mind"] == "A better alternative appears"
    store.close()


@pytest.mark.asyncio
async def test_advanced_json_returns_to_form_with_f6(tmp_path):
    store = Store(tmp_path / "form-return.db")
    project = store.new_project("Work")
    session = Session(project, "backcasting", "Future")
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, advanced=True)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        await pilot.press("f6")
        assert isinstance(app.screen, FormScreen)
        app.screen.action_advanced()
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        assert app.screen.query_one("#guided")
    store.close()


@pytest.mark.asyncio
async def test_guided_export_key_and_enter_work_from_focused_path(tmp_path):
    store = Store(tmp_path / "guided-export.db")
    project = store.new_project("Work")
    session = Session(
        project,
        "matrix",
        "Options",
        method_state={
            "criteria": [{"name": "Value", "weight": 1, "direction": "benefit"}],
            "alternatives": [{"name": "A", "scores": [5]}, {"name": "B", "scores": [6]}],
        },
    )
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        assert app.screen.query_one("#guided-export-path", Input)
        first = tmp_path / "report.md"
        path = app.screen.query_one("#guided-export-path", Input)
        path.value = str(first)
        path.focus()
        await pilot.press("ctrl+e")
        assert first.exists()
        second = tmp_path / "analysis.json"
        path.value = str(second)
        path.focus()
        await pilot.press("enter")
        assert second.exists()
    store.close()


@pytest.mark.asyncio
async def test_markup_literal_on_history_journal_workspace_and_form_rows(tmp_path):
    store = Store(tmp_path / "markup-screens.db")
    project = store.new_project("Project [/]")
    issue = Session(project, "issue_tree", "Issue [/]")
    issue.method_state = {
        "nodes": [{"id": "root", "parent_id": None, "label": "Branch [/]\nTODO [x]", "collapsed": False}]
    }
    store.save(issue, "Created [/]")
    journal = Session(project, "journal", "Journal [/]")
    journal.method_state = {"decision": "Decision [/]\nTODO [x]", "chosen": "Chosen [x]"}
    store.save(journal, "Updated [/]")
    worksheet = Session(project, "evidence_matrix", "Method [/]")
    worksheet.method_state = deepcopy(METHODS["evidence_matrix"].example)
    worksheet.method_state["evidence"][0]["title"] = "Evidence [x] [/]"
    worksheet.method_state["evidence"][0]["source"] = "Source [/]"
    store.save(worksheet)
    cases = Session(project, "reference_class", "Reference [/]")
    cases.method_state = deepcopy(METHODS["reference_class"].example)
    cases.method_state["cases"][0]["name"] = "Case [/]"
    store.save(cases)
    ranked = create_project("Rank [/]\nTODO [x]", [Item(name="First [/]"), Item(name="Other [x]")])
    pairwise = Session(project, "pairwise", "Rank [/]\nTODO [x]", method_state={"ranking": ranked.to_dict()})
    store.save(pairwise)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        app.project_id = project
        app.switch_screen(History())
        await pilot.pause()
        assert any(
            "[/]" in row[1].plain or "[/]" in row[2].plain
            for row in (
                app.screen.query_one(DataTable).get_row_at(i) for i in range(app.screen.query_one(DataTable).row_count)
            )
        )
        app.switch_screen(JournalList())
        await pilot.pause()
        assert "[/]" in app.screen.query_one(DataTable).get_cell_at((0, 0)).plain
        app.open_session(issue)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        assert "[/]" in app.screen.query_one("#tree", DataTable).get_cell_at((0, 0)).plain
        app.open_session(pairwise)
        await pilot.pause()
        assert "[/]" in str(app.screen.query_one("#results").content)
        app.open_session(worksheet, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert any("Method [/]" in str(label.content) for label in app.screen.query(SafeLabel))
        # Row headings are collapsible titles; user text in them stays literal.
        assert any("Evidence [x] [/]" in str(row.title) for row in app.screen.query(Collapsible))
        assert any(editor.value == "Evidence [x] [/]" for editor in app.screen.query(TextField))
        assert any(editor.value == "Source [/]" for editor in app.screen.query(TextField))
        app.open_session(cases, guided=True)
        await pilot.pause()
        assert any("Case [/]" in str(row.title) for row in app.screen.query(Collapsible))
    store.close()


@pytest.mark.asyncio
async def test_markup_literal_in_delete_and_mapping_dialog_rows(tmp_path):
    store = Store(tmp_path / "markup-dialogs.db")
    store.new_project("Project [/]")
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        dialogs = [
            DeleteProjectDialog("Project [/]", 1),
            AnalysisDialog("Analysis [/]\nTODO [x]", delete=True),
            DeleteBranchDialog("Branch [/]"),
            MoveAnalysisDialog([("other", "Destination [/]")]),
            LabelMappingDialog({}, LabelMappingRequired("ach", 0, ["Old [/]"], ["New [x] [/] "]), {}),
            MatrixMappingDialog({}, MatrixMappingRequired(0, ["Old [/]"], ["New [x] [/] "]), {}),
        ]
        for dialog in dialogs:
            app.push_screen(dialog)
            await pilot.pause()
            if isinstance(dialog, (MoveAnalysisDialog, LabelMappingDialog)):
                selected = dialog.query_one(TextualSelect).query_one("#label", TextualStatic).content
                assert "[/]" in getattr(selected, "plain", str(selected))
            elif isinstance(dialog, MatrixMappingDialog):
                assert any("New [x] [/]" in str(label.content) for label in dialog.query(SafeLabel))
                assert any("Old [/]" in str(label) for label, _ in dialog.query_one(TextualSelect)._options)
            else:
                assert any(
                    "[/]" in str(label.content) for label in [*dialog.query(SafeLabel), *dialog.query(SafeStatic)]
                )
            app.pop_screen()
            await pilot.pause()
    store.close()


@pytest.mark.asyncio
async def test_untrusted_home_and_project_names_render_literally(tmp_path):
    store = Store(tmp_path / "names.db")
    project = store.new_project("[/] Phase [draft]")
    session = Session(project, "issue_tree", "[/] Task [x]")
    store.save(session)
    app = ThinkApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert isinstance(table, SafeTable)
        assert "[/] Phase [draft]" in table.get_cell_at((0, 0)).plain
        assert isinstance(app.screen, Home)
        app.project_id = project
        app.show_project()
        await pilot.pause()
        assert "[/] Task [x]" in app.screen.query_one(DataTable).get_cell_at((0, 0)).plain
        app.open_session(session, guided=True)
        await pilot.pause()
        assert "[/]" in app.screen.query_one(".hero").render().plain
    store.close()
