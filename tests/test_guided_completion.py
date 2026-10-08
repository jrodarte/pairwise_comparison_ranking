"""Run complete guided analysis stages, including extra entries, with TUI keys."""

from __future__ import annotations

import pytest
from textual.widgets import Input, TextArea

from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.guided_screen import GuidedScreen
from thinktui.storage import Store


async def fill(screen, pilot, values):
    for key, value in values.items():
        widget = screen.query_one(f"#field-{key}")
        if isinstance(widget, TextArea):
            widget.load_text(value)
        else:
            widget.value = value
    await pilot.press("f8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_id,stages,more",
    [
        (
            "ach",
            [
                {"hypotheses": "Network\nServer"},
                {"title": "Server logs show no faults", "reliability": "0.8", "rating_0": "+", "rating_1": "--"},
            ],
            {"title": "Packet loss", "reliability": "0.6", "rating_0": "+", "rating_1": "-"},
        ),
        (
            "forecasting",
            [
                {"question": "Ship by year end?", "resolution_date": "", "rationale": "User estimate"},
                {"probability": "65"},
                {"outcome": "?"},
            ],
            {"question": "Launch approved?", "resolution_date": "2026-12-31", "rationale": "User estimate"},
        ),
        (
            "scenarios",
            [
                {"question": "How to expand?", "drivers": "Policy\nDemand"},
                {
                    "axis_0_name": "Policy",
                    "axis_0_low": "Loose",
                    "axis_0_high": "Strict",
                    "axis_1_name": "Demand",
                    "axis_1_low": "Slow",
                    "axis_1_high": "Fast",
                },
                *[
                    {
                        "name": f"Future {i}",
                        "narrative": "User-written plausible story",
                        "implications": "Staffing",
                        "indicators": "Sales trend",
                    }
                    for i in range(4)
                ],
                {
                    "name": "Pilot",
                    "action_low_low": "Explore",
                    "action_low_high": "Scale",
                    "action_high_low": "Wait",
                    "action_high_high": "Partner",
                },
            ],
            {
                "name": "Hedge",
                "action_low_low": "Partner",
                "action_low_high": "Reserve",
                "action_high_low": "Reduce",
                "action_high_high": "Expand",
            },
        ),
    ],
)
async def test_review_multiple_records_and_export(tmp_path, method_id, stages, more):
    store = Store(tmp_path / "analysis.db")
    session = Session(store.new_project("Study"), method_id, "Study")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session, guided=True)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GuidedScreen)
        for values in stages:
            await fill(screen, pilot, values)
        assert screen.query_one("#guided-results")
        await pilot.press("f8")
        assert store.load(session.id).completed_at
        screen.query_one("#more").press()
        await pilot.pause()
        assert store.load(session.id).completed_at  # navigating to Add does not invalidate review
        await fill(screen, pilot, more)
        if method_id == "forecasting":
            await fill(screen, pilot, {"probability": "80"})
            await fill(screen, pilot, {"outcome": "yes"})
        assert screen.query_one("#guided-results")
        await pilot.press("f8")
        state = store.load(session.id).method_state
        key = {"ach": "evidence", "forecasting": "forecasts", "scenarios": "strategies"}[method_id]
        assert len(state[key]) == 2
        destination = tmp_path / f"{method_id}.json"
        screen.query_one("#guided-export-path", Input).value = str(destination)
        screen.action_export()
        assert method_id in destination.read_text()
    store.close()
