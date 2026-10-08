"""Form regressions: blank drafts, legacy state and explicit example loading."""

import pytest
from textual.widgets import Button, DataTable, Input, Select

from thinktui.ai import FakeAIProvider, ProviderConfig
from thinktui.app import ThinkApp
from thinktui.context_offers import offers
from thinktui.core import METHODS, Session
from thinktui.form_model import normalize_ids, parse, schema_for
from thinktui.form_screen import FormScreen
from thinktui.project_progress import checklist
from thinktui.reports import plain_result
from thinktui.screens import Workspace
from thinktui.storage import Store


def test_schemas_cover_structured_methods_and_preserve_generated_references():
    for method in METHODS.values():
        if hasattr(method, "example"):
            assert {field.key for field in schema_for(method.id)} == set(method.example)
    state = {"nodes": [{"label": "A choice?", "parent_id": None}, {"label": "A choice?", "parent_id": None}]}
    normalize_ids(state)
    assert [node["id"] for node in state["nodes"]] == ["a-choice", "a-choice-2"]
    assert schema_for("objectives")[0].children[1].kind == "reference"


def test_project_question_migration_and_text_only_offers(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE sessions(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, method_id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE events(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,timestamp TEXT NOT NULL,description TEXT NOT NULL,changes TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        PRAGMA user_version=2;
    """)
    legacy.commit()
    legacy.close()
    store = Store(path)
    project = store.new_project("Plan")
    store.set_planning_question(project, "What should we launch?")
    assert store.project(project)["planning_question"] == "What should we launch?"
    snapshot = store.snapshot(project)
    assert snapshot["project"]["planning_question"] == "What should we launch?"
    invalid = {**snapshot, "project": {**snapshot["project"], "planning_question": 42}}
    with pytest.raises(ValueError, match="planning question"):
        store.import_snapshot(invalid)
    source = Session(
        project,
        "value_focused",
        "Values",
        completed_at="yesterday",
        method_state={
            "alternatives": ["Pilot", "Wait"],
            "objectives": [{"kind": "fundamental", "measure": "Speed", "name": "Faster"}],
        },
    )
    tree = Session(
        project,
        "issue_tree",
        "Questions",
        completed_at="yesterday",
        method_state={
            "nodes": [
                {"id": "root", "parent_id": None, "label": "Why?"},
                {"id": "leaf", "parent_id": "root", "label": "Will customers care?"},
            ]
        },
    )
    assert offers("matrix", [source], "new") == {"alternatives": ["Pilot", "Wait"], "criteria": ["Speed"]}
    assert offers("assumptions", [tree], "new") == {"statements": ["Will customers care?"]}
    assert offers("matrix", [Session(project, "value_focused", "Draft", method_state=source.method_state)], "new") == {}


def test_guided_results_are_readable_not_raw_json():
    result = plain_result({"ranking": [{"name": "Pilot", "score": 7.5}], "normalized_weights": [1.0]})
    assert "Pilot" in result and "Normalized weights" in result
    assert "{" not in result and '"score"' not in result


def test_progress_only_counts_finished_analyses():
    draft = Session("p", "objectives", "Goals")
    rows, next_method = checklist([draft])
    assert "In progress" in rows[0]
    assert next_method == "objectives"
    draft.completed_at = "now"
    rows, next_method = checklist([draft])
    assert "Reviewed" in rows[0]
    assert next_method == "issue_tree"


def test_numeric_and_date_validation():
    field = schema_for("backcasting")[1]
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse(field, "tomorrow")
    assert parse(field, "2030-01-01") == "2030-01-01"
    assert parse(schema_for("objectives")[0].children[1], "") is None
    assert schema_for("hypothesis_tree")[1].children[-1].choices == ("hypothesis", "test")
    assert schema_for("bradley_terry")[1].children[-1].choices == ("a_wins", "b_wins", "tie")
    assert schema_for("bradley_terry")[1].children[-1].kind == "choice"
    assert parse(schema_for("assumption_mapping")[0].children[1], "0.3") == 0.3
    with pytest.raises(ValueError):
        parse(schema_for("assumption_mapping")[0].children[1], "30")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_id, rows, scalars",
    [
        (
            "value_of_information",
            {
                "states": [{"name": "Rain", "probability": "0.6"}, {"name": "Sun", "probability": "0.4"}],
                "actions": [
                    {"name": "Coat", "payoffs": {"Rain": "10", "Sun": "-2"}},
                    {"name": "Umbrella", "payoffs": {"Rain": "8", "Sun": "3"}},
                ],
                "signals": [
                    {"name": "Cloudy", "likelihoods": {"Rain": "0.8", "Sun": "0.3"}},
                    {"name": "Clear", "likelihoods": {"Rain": "0.2", "Sun": "0.7"}},
                ],
            },
            {"research_cost": "1"},
        ),
        (
            "strategy_stress",
            {
                "scenarios": ["Recession", "Growth"],
                "strategies": [
                    {"name": "Reserve", "scores": {"Recession": "8", "Growth": "5"}},
                    {"name": "Invest", "scores": {"Recession": "2", "Growth": "9"}},
                ],
            },
            {},
        ),
    ],
)
async def test_dynamic_keyed_grids_complete_without_json(tmp_path, method_id, rows, scalars):
    store = Store(tmp_path / f"{method_id}.db")
    session = Session(store.new_project("Grid"), method_id, "Own labels")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        for key, entries in rows.items():
            group = next(ident for ident, path in app.screen.groups.items() if path == (key,))
            for index, row in enumerate(entries):
                app.screen.query_one(f"#{group}-add", Button).press()
                await pilot.pause()
                for name, value in row.items() if isinstance(row, dict) else [("value", row)]:
                    if isinstance(value, dict):
                        for column, judgment in value.items():
                            path = (key, index, name, column)
                            ident = next(i for i, (p, _) in app.screen.fields.items() if p == path)
                            app.screen.change(ident, judgment)
                    else:
                        path = (key, index) if name == "value" else (key, index, name)
                        ident = next(i for i, (p, _) in app.screen.fields.items() if p == path)
                        app.screen.change(ident, value)
        for key, raw in scalars.items():
            ident = next(i for i, (p, _) in app.screen.fields.items() if p == (key,))
            app.screen.change(ident, raw)
        assert not METHODS[method_id].validate(session.method_state)
        app.screen.action_save()
        assert store.load(session.id).completed_at
        source = "states" if method_id == "value_of_information" else "scenarios"
        old, new = ("Rain", "Storm") if source == "states" else ("Recession", "Downturn")
        source_path = (source, 0, "name") if source == "states" else (source, 0)
        name_field = next(i for i, (p, _) in app.screen.fields.items() if p == source_path)
        app.screen.change(name_field, new)
        await app.screen.recompose()
        state = store.load(session.id).method_state
        dependent = ("actions", "payoffs") if source == "states" else ("strategies", "scores")
        for row in state[dependent[0]]:
            assert new in row[dependent[1]] and old not in row[dependent[1]]
        assert not METHODS[method_id].validate(state)


@pytest.mark.asyncio
async def test_bradley_terry_outcome_is_select_and_saves_enum(tmp_path):
    store = Store(tmp_path / "bradley.db")
    session = Session(store.new_project("Comparison"), "bradley_terry", "Choices")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        items = next(group for group, path in app.screen.groups.items() if path == ("items",))
        for label in ("North", "South"):
            app.screen.query_one(f"#{items}-add", Button).press()
            await pilot.pause()
            index = len(session.method_state["items"]) - 1
            ident = next(i for i, (path, _) in app.screen.fields.items() if path == ("items", index))
            app.screen.query_one(f"#{ident}", Input).value = label
        comparisons = next(group for group, path in app.screen.groups.items() if path == ("comparisons",))
        app.screen.query_one(f"#{comparisons}-add", Button).press()
        await pilot.pause()
        for key, label in (("a", "North"), ("b", "South")):
            ident = next(i for i, (path, _) in app.screen.fields.items() if path == ("comparisons", 0, key))
            app.screen.query_one(f"#{ident}", Input).value = label
        ident = next(i for i, (path, _) in app.screen.fields.items() if path == ("comparisons", 0, "outcome"))
        selector = app.screen.query_one(f"#{ident}", Select)
        assert {value for _, value in selector._options} >= {"a_wins", "b_wins", "tie"}
        selector.value = "tie"
        await pilot.pause()
        assert store.load(session.id).method_state["comparisons"][0]["outcome"] == "tie"


@pytest.mark.asyncio
async def test_legacy_grid_rename_preserves_judgments_and_collision(tmp_path):
    from copy import deepcopy

    store = Store(tmp_path / "legacy-grid.db")
    session = Session(
        store.new_project("Old"),
        "value_of_information",
        "Legacy",
        method_state=deepcopy(METHODS["value_of_information"].example),
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        ident = next(i for i, (p, _) in screen.fields.items() if p == ("states", 0, "name"))
        editor = screen.query_one(f"#{ident}", Input)
        editor.value = ""
        editor.value = "Storm"
        await pilot.pause()
        assert session.method_state["actions"][0]["payoffs"]["Storm"] == 100
        assert session.method_state["signals"][0]["likelihoods"]["Storm"] == 0.8
        assert "Demand" not in session.method_state["actions"][0]["payoffs"]
        await screen.recompose()
        ident = next(i for i, (p, _) in screen.fields.items() if p == ("states", 0, "name"))
        screen.query_one(f"#{ident}", Input).value = "No demand"  # never erase either judgment
        await pilot.pause()
        assert session.method_state["actions"][0]["payoffs"] == {"Storm": 100, "No demand": -50}
        await screen.recompose()
        assert any(path == ("actions", 0, "payoffs", "Storm") for path in screen.extra_keys.values())


@pytest.mark.asyncio
async def test_matrix_scores_render_as_rows_and_criteria_columns(tmp_path):
    from textual.widgets import TextArea

    from thinktui.guided_screen import GuidedScreen

    store = Store(tmp_path / "matrix.db")
    session = Session(store.new_project("Plan"), "matrix", "Options")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen)
        app.screen.query_one("#field-alternatives", TextArea).load_text("Pilot\nNo change")
        await app.screen.action_next()
        app.screen.query_one("#field-criteria", TextArea).load_text("Speed | 3 | benefit\nEffort | 2 | cost")
        await app.screen.action_next()
        assert len(app.screen.query(".matrix-grid-row Input")) == 4
        assert len(app.screen.query(".matrix-grid-row")) == 3  # heading and two alternatives


@pytest.mark.asyncio
async def test_issue_tree_enter_adds_child_and_shift_enter_sibling(tmp_path):
    store = Store(tmp_path / "tree.db")
    session = Session(store.new_project("Plan"), "issue_tree", "Questions")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        editor = app.screen.query_one("#entry", Input)
        editor.value = "Root"
        editor.focus()
        await pilot.press("enter")
        editor.value = "Child?"
        editor.focus()
        await pilot.press("enter")
        assert [node["label"] for node in session.method_state["nodes"]] == ["Root", "Child?"]
        assert session.method_state["nodes"][1]["parent_id"] == session.method_state["nodes"][0]["id"]
        editor.value = "Sibling?"
        app.screen.query_one("#tree", DataTable).move_cursor(row=1)
        assert editor.value == "Sibling?"
        editor.focus()
        await pilot.press("shift+enter")
        assert session.method_state["nodes"][2]["parent_id"] == session.method_state["nodes"][0]["id"]


@pytest.mark.asyncio
async def test_blank_form_example_opt_in_and_resume(tmp_path):
    store = Store(tmp_path / "form.db")
    session = Session(store.new_project("Work"), "objectives", "Goals")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert session.method_state == {}
        app.screen.query_one("#group-0-add", Button).press()
        await pilot.pause()
        label = next(ident for ident, (path, _) in app.screen.fields.items() if path == ("nodes", 0, "label"))
        app.screen.query_one(f"#{label}", Input).value = "Customer value"
        await pilot.pause()
        assert session.method_state["nodes"][0]["id"] == "customer-value"
        app.open_session(store.load(session.id), guided=True)
        await pilot.pause()
        assert next(ident for ident, (path, _) in app.screen.fields.items() if path == ("nodes", 0, "label"))
        assert app.screen.query_one(f"#{label}", Input).value == "Customer value"
        app.screen.query_one("#load-example", Button).press()
        await pilot.pause()
        assert (
            session.method_state == METHODS["objectives"].example
            or app.session.method_state == METHODS["objectives"].example
        )
        assert app.screen.query_one(Select)
        assert "{" not in str(app.screen.query_one("#form-results"))
        await pilot.press("f6")
        assert isinstance(app.screen, Workspace)
        assert app.screen.query_one("#structured-input")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_id, values, row_values",
    [
        ("objectives", {}, {"nodes": [{"label": "Reliable service", "kind": "fundamental", "parent_id": None}]}),
        (
            "value_focused",
            {},
            {
                "objectives": [
                    {"name": "Quick delivery", "kind": "fundamental", "measure": "Lead time", "why": "Less waiting"}
                ],
                "alternatives": ["Pilot", "No change"],
            },
        ),
        (
            "backcasting",
            {"future_state": "Self-service release", "target_date": "2030-01-01"},
            {"milestones": [{"date": "2029-01-01", "requirement": "Run pilot", "owner": "Team"}]},
        ),
    ],
)
async def test_complete_structured_form_without_json(tmp_path, method_id, values, row_values):
    store = Store(tmp_path / f"{method_id}.db")
    session = Session(store.new_project("Project"), method_id, "Draft")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        for key, value in values.items():
            ident = next(i for i, (path, _) in app.screen.fields.items() if path == (key,))
            app.screen.change(ident, value)
        for key, rows in row_values.items():
            group = next(i for i, path in app.screen.groups.items() if path == (key,))
            for index, row in enumerate(rows):
                app.screen.query_one(f"#{group}-add", Button).press()
                await pilot.pause()
                for field, value in row.items() if isinstance(row, dict) else [("value", row)]:
                    path = (key, index) if field == "value" else (key, index, field)
                    ident = next(i for i, (p, _) in app.screen.fields.items() if p == path)
                    app.screen.change(ident, "" if value is None else value)
        assert not METHODS[method_id].validate(session.method_state)
        app.screen.action_save()
        assert store.load(session.id).completed_at is not None
        destination = tmp_path / f"{method_id}.md"
        app.screen.query_one("#form-export-path", Input).value = str(destination)
        app.screen.action_export()
        assert destination.exists() and session.title in destination.read_text()


@pytest.mark.asyncio
async def test_stopped_ai_partial_is_never_accepted(tmp_path, monkeypatch):
    import asyncio

    from textual.widgets import TextArea

    from thinktui import form_screen

    store = Store(tmp_path / "stop.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Plan"), "backcasting", "Future")
    store.save(session)
    waiting = asyncio.Event()

    class SlowProvider:
        async def stream(self, _request):
            yield "Suggested future"
            await waiting.wait()

    async def connect(_):
        return SlowProvider(), ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(form_screen, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        ident = next(i for i, (path, _) in app.screen.fields.items() if path == ("future_state",))
        app.screen.suggest(ident)
        await pilot.pause()
        app.screen.accept()  # cannot accept streamed partial text
        assert session.method_state == {}
        await pilot.press("ctrl+g")
        assert app.screen.query_one("#form-preview", TextArea).text == "Suggested future"
        app.screen.accept()
        assert session.method_state == {}
        waiting.set()


@pytest.mark.asyncio
async def test_ai_text_requires_accept_and_cannot_add_numeric_judgments(tmp_path, monkeypatch):
    from textual.widgets import Static, TextArea

    from thinktui import form_screen

    store = Store(tmp_path / "ai.db")
    store.set_setting("ai_provider", "ollama")
    session = Session(store.new_project("Planning"), "backcasting", "Future")
    store.save(session)
    fake = FakeAIProvider("Build a small pilot")

    async def connect(_):
        return fake, ProviderConfig("ollama", "http://localhost:11434", "fake")

    monkeypatch.setattr(form_screen, "connect", connect)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        field = next(k for k, (path, _) in app.screen.fields.items() if path == ("future_state",))
        app.screen.suggest(field)
        await pilot.pause()
        assert session.method_state == {}
        assert app.screen.query_one("#form-preview", TextArea).text == "Build a small pilot"
        assert fake.requests[0].context["problem"] == ""
        assert "notes" not in fake.requests[0].context
        app.screen.accept()
        await pilot.pause()
        assert store.load(session.id).method_state["future_state"] == "Build a small pilot"
        fake.answer = "Deadline 2028-12-31"
        app.screen.suggest(field)
        await pilot.pause()
        assert "numeric" in str(app.screen.query_one("#form-ai-status", Static).render())
        assert store.load(session.id).method_state["future_state"] == "Build a small pilot"
