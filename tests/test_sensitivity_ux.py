"""A guided matrix can lead directly to an editable sensitivity form."""

from copy import deepcopy

import pytest
from textual.widgets import Button, Input, Select, Static

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.form_model import parse, schema_for
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.planning import sensitivity_from_matrix, sensitivity_pair
from thinktui.storage import Store


def field_at(screen, path):
    ident = next(ident for ident, (field_path, _) in screen.fields.items() if field_path == path)
    return screen.query_one(f"#{ident}", Input)


def range_fields(screen):
    return [
        screen.query_one(f"#{next(ident for ident, (path, _) in screen.fields.items() if path == ('range', i))}", Input)
        for i in range(2)
    ]


@pytest.mark.asyncio
async def test_guided_matrix_review_starts_sensitivity_form_and_saves_decimal_bounds(tmp_path):
    store = Store(tmp_path / "sensitivity.db")
    state = {
        "criteria": [
            {"name": "Benefit", "weight": 3, "direction": "benefit"},
            {"name": "Effort", "weight": 1, "direction": "cost"},
        ],
        "alternatives": [{"name": "Build", "scores": [9.5, 8]}, {"name": "Buy", "scores": [6, 2]}],
        "_guided_step": 3,
    }
    matrix = Session(store.new_project("Choice"), "matrix", "Build or buy", method_state=deepcopy(state))
    store.save(matrix)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(matrix, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, GuidedScreen) and app.screen.index == 3
        button = app.screen.query_one("#sensitivity", Button)
        assert not button.disabled
        button.press()
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        analysis = app.session
        assert analysis.method_id == "sensitivity"
        assert analysis.method_state["source_session_id"] == matrix.id
        assert analysis.method_state["alternatives"] == state["alternatives"]
        assert store.load(matrix.id).method_state == state
        low, high = range_fields(app.screen)
        assert (low.value, high.value) == ("0", "1")
        score = field_at(app.screen, ("alternatives", 0, "scores", 0))
        assert score.value == "9.5"
        assert (
            next(field.kind for path, field in app.screen.fields.values() if path == ("alternatives", 0, "scores", 0))
            == "float"
        )
        for invalid in ("-0.1", "10.1", "nan", "inf"):
            score.value = invalid
            await pilot.pause()
            assert ("alternatives", 0, "scores", 0) in app.screen.invalid_fields
            assert store.load(analysis.id).method_state["alternatives"][0]["scores"][0] == 9.5
            app.screen.action_save()
            assert not store.load(analysis.id).completed_at
        score.value = "8.75"
        low.value = "0.25"
        high.value = "0.75"
        await pilot.pause()
        assert app.session.method_state["range"] == [0.25, 0.75]
        assert app.session.method_state["alternatives"][0]["scores"][0] == 8.75
        app.screen.action_save()
        assert store.load(analysis.id).method_state["range"] == [0.25, 0.75]
        assert store.load(analysis.id).method_state["alternatives"][0]["scores"][0] == 8.75
        assert store.load(analysis.id).completed_at
        app.open_session(store.load(analysis.id), guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert [field.value for field in range_fields(app.screen)] == ["0.25", "0.75"]
        assert field_at(app.screen, ("alternatives", 0, "scores", 0)).value == "8.75"
        assert store.load(matrix.id).method_state == state


@pytest.mark.asyncio
async def test_copied_decimal_matrix_score_saves_without_editing_score_fields(tmp_path):
    store = Store(tmp_path / "copied.db")
    matrix = Session(
        store.new_project("Choice"),
        "matrix",
        "Source",
        method_state={
            "criteria": [{"name": "Quality", "weight": 3}, {"name": "Cost", "weight": 1, "direction": "cost"}],
            "alternatives": [
                {"name": "Build", "scores": [8.5, 6]},
                {"name": "Buy", "scores": [5, 3]},
            ],
        },
    )
    store.save(matrix)
    linked = sensitivity_from_matrix(matrix)
    assert linked.method_state["alternatives"][0]["scores"] == [8.5, 6]
    assert METHODS["sensitivity"].validate(linked.method_state) == []
    store.save(linked)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(store.load(linked.id), guided=True)
        await pilot.pause()  # includes Input.Changed events for mounted, copied values
        screen = app.screen
        assert isinstance(screen, FormScreen)
        copied = field_at(screen, ("alternatives", 0, "scores", 0))
        assert copied.value == "8.5"
        assert ("alternatives", 0, "scores", 0) not in screen.invalid_fields
        assert not screen.invalid_fields
        screen.action_save()  # no score field changed by the user
        assert "Saved" in str(screen.query_one("#form-error", Static).content)
        saved = store.load(linked.id)
        assert saved.completed_at
        assert saved.method_state["alternatives"][0]["scores"] == [8.5, 6]
        assert store.load(matrix.id).method_state["alternatives"][0]["scores"] == [8.5, 6]
        app.open_session(saved, guided=True)
        await pilot.pause()
        assert field_at(app.screen, ("alternatives", 0, "scores", 0)).value == "8.5"
        assert not app.screen.invalid_fields


@pytest.mark.asyncio
async def test_sensitivity_review_selects_two_of_four_options(tmp_path):
    store = Store(tmp_path / "matrix.db")
    session = Session(
        store.new_project("Choice"),
        "matrix",
        "Four choices",
        method_state={
            "criteria": [{"name": "Value", "weight": 2}, {"name": "Cost", "weight": 1}],
            "alternatives": [
                {"name": label, "scores": [i + 1, 2]} for i, label in enumerate(("Build", "Buy", "Wait", "Pause"))
            ],
            "_guided_step": 3,
        },
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert not app.screen.query_one("#sensitivity", Button).disabled
        first = app.screen.query_one("#sensitivity-first", Select)
        second = app.screen.query_one("#sensitivity-second", Select)
        assert (first.value, second.value) == (3, 2)  # top ranked, not first entered
        second.value = first.value
        await pilot.pause()
        app.screen.action_sensitivity()
        assert len(store.sessions(session.project_id)) == 1
        second.value = 0
        await pilot.pause()
        app.screen.query_one("#sensitivity", Button).press()
        await pilot.pause()
        assert app.session.method_state["alternatives"] == [
            session.method_state["alternatives"][3],
            session.method_state["alternatives"][0],
        ]
        assert store.load(session.id).method_state == session.method_state
        assert len(store.sessions(session.project_id)) == 2


def test_sensitivity_pair_rejects_invalid_selection_and_preserves_source():
    source = Session(
        "project",
        "matrix",
        "Four",
        method_state={
            "criteria": [{"name": "A", "weight": 1}, {"name": "B", "weight": 1}],
            "alternatives": [
                {"name": name, "scores": [score, 3]}
                for name, score in (("First", 1), ("Second", 2), ("Third", 3), ("Fourth", 4))
            ],
        },
    )
    original = deepcopy(source.method_state)
    assert sensitivity_pair(source) == (3, 2)
    assert [row["name"] for row in sensitivity_from_matrix(source).method_state["alternatives"]] == ["Fourth", "Third"]
    for pair in ((1, 1), (0, 4), (-1, 2), (True, 1)):
        with pytest.raises(ValueError, match="Choose two different"):
            sensitivity_from_matrix(source, pair)
    assert source.method_state == original


def test_sensitivity_range_and_score_schema_accept_finite_decimals_not_invalid_values():
    bound = next(field for field in schema_for("sensitivity") if field.key == "range").children[0]
    assert bound.kind == "float"
    assert parse(bound, "0.25") == 0.25
    assert parse(bound, "0") == 0
    for bad in ("-0.01", "1.01", "nan", "inf"):
        with pytest.raises(ValueError):
            parse(bound, bad)
    alternatives = next(field for field in schema_for("sensitivity") if field.key == "alternatives")
    scores = next(field for field in alternatives.children if field.key == "scores").children[0]
    assert scores.kind == "float"
    assert (scores.minimum, scores.maximum) == (0, 10)
    assert parse(scores, "8.5") == 8.5
    for bad in ("-0.1", "10.1", "nan", "inf", "-inf"):
        with pytest.raises(ValueError):
            parse(scores, bad)
    integer = next(field for field in schema_for("monte_carlo") if field.key == "iterations")
    assert integer.kind == "int"
    with pytest.raises(ValueError, match="whole number"):
        parse(integer, "8.5")


@pytest.mark.parametrize(
    ("method_id", "path"),
    [
        ("fermi", ("factors", 0, "low")),
        ("fermi", ("factors", 0, "estimate")),
        ("fermi", ("factors", 0, "high")),
        ("reference_class", ("cases", 0, "estimate")),
        ("reference_class", ("cases", 0, "actual")),
        ("reference_class", ("inside_estimate",)),
        ("signposts", ("indicators", 0, "threshold")),
        ("signposts", ("indicators", 0, "current")),
        ("monte_carlo", ("constant",)),
        ("monte_carlo", ("threshold",)),
        ("monte_carlo", ("variables", 0, "coefficient")),
        ("monte_carlo", ("variables", 0, "min")),
    ],
)
def test_measured_judgments_accept_finite_decimals(method_id, path):
    field = next(field for field in schema_for(method_id) if field.key == path[0])
    position = 1
    while position < len(path):
        if isinstance(path[position], int):
            position += 1
            if position == len(path):
                field = field.children[0]
        else:
            field = next(child for child in field.children if child.key == path[position])
            position += 1
    assert field.kind == "float"
    assert parse(field, "0.5") == 0.5
    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(ValueError):
            parse(field, bad)


@pytest.mark.parametrize(
    ("method_id", "path"),
    [
        ("fermi", ("factors", 0, "low")),
        ("reference_class", ("cases", 0, "actual")),
        ("signposts", ("indicators", 0, "threshold")),
        ("monte_carlo", ("constant",)),
    ],
)
@pytest.mark.asyncio
async def test_decimal_judgments_autosave_resume_and_calculate(tmp_path, method_id, path):
    store = Store(tmp_path / "decimals.db")
    session = Session(
        store.new_project("Decimals"), method_id, "User data", method_state=deepcopy(METHODS[method_id].example)
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        widget = field_at(screen, path)
        widget.value = "nan"
        await pilot.pause()
        assert path in screen.invalid_fields
        widget.value = "0.5"
        await pilot.pause()
        assert path not in screen.invalid_fields
        screen.action_save()
        saved = store.load(session.id)
        assert saved.completed_at
        assert METHODS[method_id].validate(saved.method_state) == []
        app.open_session(saved, guided=True)
        await pilot.pause()
        assert field_at(app.screen, path).value == "0.5"


@pytest.mark.asyncio
async def test_blank_sensitivity_form_does_not_invent_range_bounds(tmp_path):
    store = Store(tmp_path / "blank.db")
    session = Session(store.new_project("Choice"), "sensitivity", "New analysis")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        low, high = range_fields(screen)
        assert low.value == high.value == ""
        high.value = "0.8"  # second index before first must not raise or copy example bounds
        await pilot.pause()
        assert store.load(session.id).method_state["range"] == ["", 0.8]
        screen.action_save()
        assert not store.load(session.id).completed_at
        assert "Please review" in str(screen.query_one("#form-error", Static).content)


@pytest.mark.asyncio
async def test_long_sensitivity_form_scrolls_to_its_last_field(tmp_path):
    store = Store(tmp_path / "scroll.db")
    criteria = [{"name": f"C{i}", "weight": 1, "direction": "benefit"} for i in range(5)]
    state = {
        "criteria": criteria,
        "alternatives": [{"name": "A", "scores": [5] * 5}, {"name": "B", "scores": [4] * 5}],
        "vary": "C0",
        "range": [0, 1],
    }
    session = Session(store.new_project("Scroll"), "sensitivity", "Long form", method_state=state)
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(100, 30)) as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        pane = screen.query_one(".editor-pane")
        assert pane.max_scroll_y > 0
        export = screen.query_one("#form-export-path", Input)
        export.focus()
        await pilot.pause()
        assert pane.scroll_y > 0
        assert export.region.height > 0
