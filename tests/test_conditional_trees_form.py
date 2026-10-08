"""Every accepted node-type enum has its required editable fields, at every depth."""

import pytest
from textual.widgets import Button, Input, Select

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.storage import Store


def control(screen, path):
    ident = next(i for i, (p, _) in screen.fields.items() if p == path)
    return screen.query_one(f"#{ident}")


async def append(screen, pilot, path):
    group = next(i for i, p in screen.groups.items() if p == path)
    screen.query_one(f"#{group}-add", Button).press()
    await pilot.pause()


@pytest.mark.asyncio
async def test_decision_tree_outcome_and_chance_fields_without_json(tmp_path):
    store = Store(tmp_path / "decision.db")
    session = Session(store.new_project("Plan"), "decision_tree", "Alternatives")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        node = control(app.screen, ("tree", "type"))
        assert isinstance(node, Select)
        node.value = "outcome"
        await pilot.pause()
        assert isinstance(control(app.screen, ("tree", "value")), Input)
        control(app.screen, ("tree", "value")).value = "-3.5"
        await pilot.pause()
        app.screen.action_save()
        assert (
            METHODS["decision_tree"].calculate(store.load(session.id).method_state)["analysis"]["expected_value"]
            == -3.5
        )
        control(app.screen, ("tree", "type")).value = "chance"
        await pilot.pause()
        assert ("tree", "branches") in app.screen.groups.values()
        for i, (label, probability, value) in enumerate((("Success", "0.25", "8"), ("Failure", "0.75", "-2"))):
            await append(app.screen, pilot, ("tree", "branches"))
            control(app.screen, ("tree", "branches", i, "name")).value = label
            control(app.screen, ("tree", "branches", i, "probability")).value = probability
            control(app.screen, ("tree", "branches", i, "node", "type")).value = "outcome"
            await pilot.pause()
            control(app.screen, ("tree", "branches", i, "node", "value")).value = value
        await pilot.pause()
        app.screen.action_save()
        result = METHODS["decision_tree"].calculate(store.load(session.id).method_state)
        assert result["analysis"]["expected_value"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_fault_tree_event_and_nested_gate_without_json(tmp_path):
    store = Store(tmp_path / "fault.db")
    session = Session(store.new_project("Plan"), "fault_tree", "Outage")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        control(app.screen, ("top_event",)).value = "Network outage"
        control(app.screen, ("tree", "type")).value = "event"
        await pilot.pause()
        control(app.screen, ("tree", "name")).value = "Router fails"
        control(app.screen, ("tree", "probability")).value = "0.2"
        await pilot.pause()
        app.screen.action_save()
        assert METHODS["fault_tree"].calculate(store.load(session.id).method_state)["result"]["probability"] == 0.2
        control(app.screen, ("tree", "type")).value = "AND"
        await pilot.pause()
        assert ("tree", "children") in app.screen.groups.values()
        control(app.screen, ("tree", "independent")).value = "Yes"
        for i in range(2):
            await append(app.screen, pilot, ("tree", "children"))
            control(app.screen, ("tree", "children", i, "type")).value = "event"
            await pilot.pause()
            control(app.screen, ("tree", "children", i, "name")).value = f"Device {i}"
            control(app.screen, ("tree", "children", i, "probability")).value = "0.1" if i == 0 else "0.2"
        await pilot.pause()
        app.screen.action_save()
        assert METHODS["fault_tree"].calculate(store.load(session.id).method_state)["result"][
            "probability"
        ] == pytest.approx(0.02)
