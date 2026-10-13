"""No-JSON discrete/empirical Monte Carlo editing, including old saved sessions."""

from copy import deepcopy

import pytest
from textual.widgets import Button, Select, Static

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.form_model import MONTE_FIELDS, parse, schema_for
from thinktui.form_screen import FormScreen
from thinktui.storage import Store


def field(screen, path):
    ident = next(ident for ident, (item, _) in screen.fields.items() if item == path)
    return screen.query_one(f"#{ident}")


def group(screen, path):
    return next(ident for ident, item in screen.groups.items() if item == path)


async def add_number(screen, pilot, path, raw):
    assert not screen.query(f"#suggest-rows-{group(screen, path)}")
    screen.query_one(f"#{group(screen, path)}-add", Button).press()
    await pilot.pause()
    index = len(screen.value_at(path)) - 1
    control = field(screen, (*path, index))
    control.value = raw
    await pilot.pause()
    assert not screen.query(f"#suggest-{control.id}")  # AI cannot suggest a numeric judgment


def test_distribution_choices_and_other_validator_enums_are_complete():
    variables = schema_for("monte_carlo")[0]
    children = {child.key: child for child in variables.children}
    assert children["distribution"].kind == "choice"
    assert (
        set(children["distribution"].choices)
        == set(MONTE_FIELDS)
        == {"normal", "lognormal", "uniform", "triangular", "discrete", "samples"}
    )
    assert children["values"].kind == children["weights"].kind == "rows"
    assert children["values"].children[0].kind == children["weights"].children[0].kind == "float"
    assert children["weights"].children[0].minimum == 0
    assert children["values"].show_for == ("discrete", "samples")
    assert children["weights"].show_for == ("discrete",)
    for method_id, accepted in (
        ("decision_tree", {"outcome", "chance", "decision"}),
        ("fault_tree", {"event", "AND", "OR"}),
    ):
        tree = next(item for item in schema_for(method_id) if item.key == "tree")
        kind = next(item for item in tree.children if item.key == "type")
        assert kind.kind == "choice" and set(kind.choices) == accepted
    assert set(next(c for c in schema_for("hypothesis_tree")[1].children if c.key == "kind").choices) == {
        "hypothesis",
        "test",
    }
    assert set(schema_for("bradley_terry")[1].children[-1].choices) == {"a_wins", "b_wins", "tie"}
    assert set(schema_for("signposts")[0].children[3].choices) == {"above", "below"}
    outcomes = schema_for("forecasting")[0].children
    outcome = next(child for child in outcomes if child.key == "outcome")
    assert outcome.kind == "choice" and outcome.choices == ("Unresolved", "No", "Yes")
    assert [parse(outcome, label) for label in outcome.choices] == [None, 0, 1]
    polarity = next(child for child in schema_for("causal_loop")[1].children if child.key == "polarity")
    assert polarity.kind == "choice"
    assert [parse(polarity, label) for label in polarity.choices] == [1, -1]
    for method_id, ratings in (("evidence_matrix", {"+", "-", "0", "?"}), ("ach", {"++", "+", "0", "-", "--", "?"})):
        evidence = next(field for field in schema_for(method_id) if field.key == "evidence")
        consistency = next(child for child in evidence.children if child.key == "ratings")
        assert consistency.kind == "keyed_grid"
        assert set(consistency.children[0].choices) == ratings


@pytest.mark.asyncio
async def test_evidence_rating_choices_follow_user_hypothesis_labels(tmp_path):
    store = Store(tmp_path / "evidence.db")
    session = Session(store.new_project("Plan"), "evidence_matrix", "Hypotheses")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        for label in ("Cache", "Network"):
            app.screen.query_one(f"#{group(app.screen, ('hypotheses',))}-add", Button).press()
            await pilot.pause()
            index = len(session.method_state["hypotheses"]) - 1
            field(app.screen, ("hypotheses", index)).value = label
            await pilot.pause()
        app.screen.query_one(f"#{group(app.screen, ('evidence',))}-add", Button).press()
        await pilot.pause()
        field(app.screen, ("evidence", 0, "title")).value = "Latency rose"
        field(app.screen, ("evidence", 0, "source")).value = "Telemetry"
        field(app.screen, ("evidence", 0, "reliability")).value = "0.8"
        for key, rating in (("Cache", "-"), ("Network", "+")):
            selector = field(app.screen, ("evidence", 0, "ratings", key))
            assert isinstance(selector, Select)
            selector.value = rating
        await pilot.pause()
        app.screen.action_save()
        assert store.load(session.id).completed_at
        assert store.load(session.id).method_state["evidence"][0]["ratings"] == {"Cache": "-", "Network": "+"}
        field(app.screen, ("hypotheses", 0)).value = "Storage"
        await pilot.pause()
        await app.screen.recompose_fields()
        assert store.load(session.id).method_state["evidence"][0]["ratings"] == {"Storage": "-", "Network": "+"}
        assert isinstance(field(app.screen, ("evidence", 0, "ratings", "Storage")), Select)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "distribution,parameters,visible",
    [
        ("uniform", {"min": 1, "max": 3}, {"min", "max"}),
        ("triangular", {"min": 1, "mode": 2, "max": 3}, {"min", "mode", "max"}),
        ("normal", {"mean": -1.5, "sd": 0.5}, {"mean", "sd"}),
        ("lognormal", {"mean": 1, "sd": 0.5}, {"mean", "sd"}),
        ("discrete", {"values": [1, 2], "weights": [2, 1]}, {"values", "weights"}),
        ("samples", {"values": [-1, 4]}, {"values"}),
    ],
)
async def test_each_supported_distribution_is_editable_in_saved_form(tmp_path, distribution, parameters, visible):
    store = Store(tmp_path / f"{distribution}.db")
    state = {
        "variables": [{"name": "Forecast", "distribution": distribution, "coefficient": 1, **parameters}],
        "iterations": 100,
        "seed": 11,
    }
    assert not METHODS["monte_carlo"].validate(state)
    session = Session(store.new_project("Forecast"), "monte_carlo", distribution, method_state=state)
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        paths = {path for path, _ in app.screen.fields.values()} | set(app.screen.groups.values())
        for key in ("min", "mode", "max", "mean", "sd", "values", "weights"):
            assert (("variables", 0, key) in paths) == (key in visible)
        assert field(app.screen, ("variables", 0, "distribution")).value == distribution
        assert store.load(session.id).method_state == state


@pytest.mark.asyncio
async def test_create_discrete_and_samples_without_json(tmp_path):
    store = Store(tmp_path / "create.db")
    session = Session(store.new_project("Plan"), "monte_carlo", "Forecast")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        screen = app.screen
        screen.query_one(f"#{group(screen, ('variables',))}-add", Button).press()
        await pilot.pause()
        field(screen, ("variables", 0, "name")).value = "Demand"
        field(screen, ("variables", 0, "coefficient")).value = "1.5"
        distribution = field(screen, ("variables", 0, "distribution"))
        assert isinstance(distribution, Select)
        distribution.value = "discrete"
        await pilot.pause()
        assert ("variables", 0, "values") in screen.groups.values()
        assert ("variables", 0, "weights") in screen.groups.values()
        assert ("variables", 0, "min") not in (path for path, _ in screen.fields.values())
        await add_number(screen, pilot, ("variables", 0, "values"), "-2.5")
        await add_number(screen, pilot, ("variables", 0, "values"), "5")
        assert "one weight for each value" in str(screen.query_one("#monte-error-0", Static).content)
        screen.action_save()
        assert store.load(session.id).completed_at is None
        await add_number(screen, pilot, ("variables", 0, "weights"), "0")
        await add_number(screen, pilot, ("variables", 0, "weights"), "0")
        assert "greater than zero" in str(screen.query_one("#monte-error-0", Static).content)
        field(screen, ("variables", 0, "weights", 1)).value = "2.5"
        await pilot.pause()
        assert not str(screen.query_one("#monte-error-0", Static).content)
        screen.query_one(f"#{group(screen, ('variables',))}-add", Button).press()
        await pilot.pause()
        field(screen, ("variables", 1, "name")).value = "Cost"
        field(screen, ("variables", 1, "coefficient")).value = "-1"
        field(screen, ("variables", 1, "distribution")).value = "samples"
        await pilot.pause()
        assert ("variables", 1, "values") in screen.groups.values()
        assert ("variables", 1, "weights") not in screen.groups.values()
        await add_number(screen, pilot, ("variables", 1, "values"), "2")
        await add_number(screen, pilot, ("variables", 1, "values"), "7.5")
        for key, raw in (("constant", "0"), ("threshold", "1"), ("iterations", "100"), ("seed", "7")):
            field(screen, (key,)).value = raw
        await pilot.pause()
        screen.action_save()
        state = store.load(session.id).method_state
        assert store.load(session.id).completed_at
        assert state["variables"] == [
            {
                "name": "Demand",
                "distribution": "discrete",
                "coefficient": 1.5,
                "values": [-2.5, 5.0],
                "weights": [0.0, 2.5],
            },
            {"name": "Cost", "distribution": "samples", "coefficient": -1.0, "values": [2.0, 7.5]},
        ]
        assert not METHODS["monte_carlo"].validate(state)


@pytest.mark.asyncio
async def test_resume_legacy_discrete_and_edit_values_weights_without_f6(tmp_path):
    store = Store(tmp_path / "legacy.db")
    state = {
        "variables": [
            {"name": "Yield", "distribution": "discrete", "values": [1, 3], "weights": [1, 2], "coefficient": -0.5}
        ],
        "constant": 0,
        "threshold": 0,
        "iterations": 100,
        "seed": 17,
    }
    session = Session(store.new_project("Old"), "monte_carlo", "Yield", method_state=deepcopy(state))
    store.save(session)
    event_count = len(store.events(session.id))
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FormScreen)
        assert len(store.events(session.id)) == event_count
        assert store.load(session.id).method_state == state
        assert field(screen, ("variables", 0, "values", 1)).value == "3"
        assert field(screen, ("variables", 0, "weights", 0)).value == "1"
        assert ("variables", 0, "min") not in (path for path, _ in screen.fields.values())
        weight_input = field(screen, ("variables", 0, "weights", 0))
        weight_input.value = "-1"
        await pilot.pause()
        assert screen.invalid_fields  # rejected text is not persisted
        assert store.load(session.id).method_state["variables"][0]["weights"] == [1, 2]
        field(screen, ("variables", 0, "distribution")).value = "samples"
        await pilot.pause()
        assert ("variables", 0, "weights") not in screen.groups.values()
        assert not screen.invalid_fields  # hidden rejected input cannot block this valid distribution
        assert store.load(session.id).method_state["variables"][0]["weights"] == [1, 2]
        field(screen, ("variables", 0, "distribution")).value = "discrete"
        await pilot.pause()
        assert ("variables", 0, "weights") in screen.groups.values()
        field(screen, ("variables", 0, "values", 1)).value = "4.5"
        field(screen, ("variables", 0, "weights", 0)).value = "3"
        await pilot.pause()
        screen.action_save()
        assert store.load(session.id).method_state["variables"][0] == {
            "name": "Yield",
            "distribution": "discrete",
            "values": [1, 4.5],
            "weights": [3, 2],
            "coefficient": -0.5,
        }
        assert store.load(session.id).completed_at
