"""Smoke-test navigation and repeated keypress workflow without a real terminal."""

import pytest
from textual.widgets import Input, TextArea

from pairwise_prioritizer.app import PairRankApp
from pairwise_prioritizer.comparison_engine import create_project, decide, next_pair
from pairwise_prioritizer.models import Item, Outcome
from pairwise_prioritizer.persistence import ProjectStore
from pairwise_prioritizer.screens.common import HelpDialog
from pairwise_prioritizer.screens.comparison import ComparisonScreen
from pairwise_prioritizer.screens.history import HistoryScreen
from pairwise_prioritizer.screens.home import HomeScreen
from pairwise_prioritizer.screens.project_setup import SetupScreen
from pairwise_prioritizer.screens.results import (
    DetailDialog,
    MatrixScreen,
    ResultsScreen,
    RevisitScreen,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("home", HomeScreen),
        ("new", SetupScreen),
        ("demo", SetupScreen),
        ("history", HistoryScreen),
        ("resume", HomeScreen),  # No saved incomplete project.
    ],
)
async def test_startup_modes(tmp_path, initial, expected):
    app = PairRankApp(ProjectStore(tmp_path), initial=initial)
    async with app.run_test(size=(100, 32)) as pilot:
        assert isinstance(app.screen, expected)
        if initial == "demo":
            assert "Automated Data Lineage" in app.screen.query_one(TextArea).text
            assert app.store.list_projects() == []
        if initial == "home":
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpDialog)
            await pilot.press("escape")
            assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_resume_startup_preserves_pair_and_progress(tmp_path):
    store = ProjectStore(tmp_path)
    project = create_project("Interrupted", [Item(name=name) for name in "ABC"], seed=14)
    decide(project, next_pair(project), Outcome.A_WINS)
    expected_pair = next_pair(project)
    store.save(project)

    app = PairRankApp(store, initial="resume")
    async with app.run_test(size=(100, 32)) as pilot:
        assert isinstance(app.screen, ComparisonScreen)
        assert app.project.id == project.id
        assert next_pair(app.project) == expected_pair
        await pilot.press("d")
        assert len(store.load(project.id).comparisons) == 2
        assert isinstance(app.screen, ComparisonScreen)


@pytest.mark.asyncio
async def test_keyboard_workflow(tmp_path):
    app = PairRankApp(ProjectStore(tmp_path))
    async with app.run_test(size=(105, 34)) as pilot:
        await pilot.press("n")
        app.screen.query_one("#name", Input).value = "Q4 Features"
        app.screen.query_one(TextArea).load_text("Alpha\nBravo\nCharlie")
        app.screen.start()
        await pilot.pause()
        assert isinstance(app.screen, ComparisonScreen)
        await pilot.press("s")
        assert len(app.project.skipped) == 1
        await pilot.press("a", "t")
        await pilot.press("u")
        assert len(app.project.comparisons) == 1
        await pilot.press("d", "a")
        await pilot.pause()
        assert isinstance(app.screen, ResultsScreen)
        assert len(app.store.load(app.project.id).comparisons) == 3
        await pilot.press("enter")
        assert isinstance(app.screen, DetailDialog)
        await pilot.press("escape")
        assert isinstance(app.screen, ResultsScreen)
        await pilot.press("m")
        assert isinstance(app.screen, MatrixScreen)
        await pilot.press("escape")
        await pilot.press("r")
        assert isinstance(app.screen, RevisitScreen)
        await pilot.press("enter", "t")
        assert isinstance(app.screen, ResultsScreen)
        assert sum(c.outcome == Outcome.TIE for c in app.project.comparisons.values()) >= 1
        assert len(app.store.load(app.project.id).comparisons) == 3
        await pilot.press("escape", "h")
        assert isinstance(app.screen, HistoryScreen)
