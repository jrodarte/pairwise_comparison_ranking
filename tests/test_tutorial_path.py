"""End-to-end, local-only tutorial walkthrough using user-entered (not example) judgments."""

from __future__ import annotations

from copy import deepcopy

import pytest
from textual.widgets import Button, Static

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session
from thinktui.form_screen import FormScreen
from thinktui.guided_screen import GuidedScreen
from thinktui.planning import sensitivity_from_matrix, transfer
from thinktui.screens import Workspace
from thinktui.storage import Store


@pytest.mark.asyncio
async def test_tutorial_walkthrough_finished_and_no_raw_json(tmp_path):
    store = Store(tmp_path / "tutorial.db")
    project = store.new_project("Release decision")
    sessions = []

    def create(method: str, state: dict, title: str) -> Session:
        session = Session(project, method, title, method_state=deepcopy(state))
        assert not METHODS[method].validate(session.method_state), method
        store.save(session)
        sessions.append(session)
        return session

    create(
        "objectives",
        {
            "nodes": [
                {
                    "id": "quality",
                    "parent_id": None,
                    "label": "Reduce avoidable support incidents",
                    "kind": "fundamental",
                }
            ]
        },
        "Objectives",
    )
    create(
        "value_focused",
        {
            "objectives": [
                {
                    "name": "Reduce incidents",
                    "kind": "fundamental",
                    "measure": "Incidents per week",
                    "why": "Users need a stable service",
                }
            ],
            "alternatives": ["Stage", "Launch"],
        },
        "Value",
    )
    create(
        "issue_tree",
        {"nodes": [{"id": "root", "parent_id": None, "label": "What blocks a stable release?", "collapsed": False}]},
        "Questions",
    )
    create(
        "assumptions",
        {
            "entries": [
                {
                    "statement": "Failover works under load?",
                    "action": "Run a load test",
                    "confidence": 30,
                    "likelihood": 30,
                    "impact": 8,
                    "source": "USER",
                }
            ]
        },
        "Assumptions",
    )
    matrix = create(
        "matrix",
        {
            "criteria": [
                {"name": "Stability", "weight": 2, "direction": "benefit"},
                {"name": "Operating cost", "weight": 1, "direction": "cost"},
            ],
            "alternatives": [
                {"name": "Stage", "scores": [9, 3]},
                {"name": "Launch", "scores": [6, 8]},
                {"name": "Delay", "scores": [4, 0]},
            ],
        },
        "Ranking",
    )
    sensitivity = sensitivity_from_matrix(matrix)
    sensitivity.title = "Sensitivity"
    store.save(sensitivity)
    sessions.append(sensitivity)
    create(
        "reversibility",
        {
            "alternatives": [
                {
                    "name": "Stage",
                    "rollback_cost": 12.5,
                    "rollback_days": 2.5,
                    "trigger": "More outages",
                    "exit_plan": "Switch traffic back",
                },
                {
                    "name": "Launch",
                    "rollback_cost": 30.5,
                    "rollback_days": 5.5,
                    "trigger": "SLA breach",
                    "exit_plan": "Restore service",
                },
            ]
        },
        "Reversibility",
    )
    premortem = create(
        "premortem",
        {
            "entries": [
                {
                    "statement": "Release causes an outage",
                    "action": "Test failover",
                    "likelihood": 65,
                    "confidence": 65,
                    "impact": 9,
                    "source": "USER",
                }
            ]
        },
        "Premortem",
    )
    fmea_state = transfer(premortem, "fmea")
    row = fmea_state["failure_modes"][0]
    row.update(
        {
            "effect": "Checkout unavailable",
            "cause": "Database overload",
            "controls": "Rate limit",
            "owner": "Service team",
            "severity": 9,
            "occurrence": 4,
            "detectability": 6,
        }
    )
    create("fmea", fmea_state, "Failure analysis")

    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        for session in sessions:
            app.open_session(session, guided=True)
            await pilot.pause()
            if isinstance(app.screen, FormScreen):
                assert not app.screen.query_one("#form-error", Static).content
                app.screen.query_one("#form-finish", Button).press()
                await pilot.pause()
                assert "{" not in str(app.screen.query_one("#form-results", Static).content)
            elif isinstance(app.screen, GuidedScreen):
                assert app.screen.session.method_id == "matrix"
                await app.screen.action_next()
                await pilot.pause()
                assert not app.screen.query("#structured-input")
            else:
                assert isinstance(app.screen, Workspace)
                app.screen.query_one("#finish-stage", Button).press()
                await pilot.pause()
                assert not app.screen.query("#structured-input")
            assert store.load(session.id).completed_at, session.method_id
        assert store.load(sensitivity.id).method_state["alternatives"] == sensitivity.method_state["alternatives"]
        assert len(store.sessions(project)) == 9
    store.close()
