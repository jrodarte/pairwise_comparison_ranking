"""Fast, keyboard-first pair decisions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Label, ProgressBar, Static

from ..comparison_engine import decide, next_pair, skip, undo
from ..models import Outcome
from .common import BaseScreen


class ComparisonScreen(BaseScreen):
    """Fixed-position comparison cards and live autosaved progress."""

    BINDINGS = [
        ("a", "left", "Choose A"),
        ("left", "left", "Choose A"),
        ("d", "right", "Choose D"),
        ("right", "right", "Choose D"),
        ("t", "tie", "Tie"),
        ("u", "undo", "Undo"),
        ("s", "skip", "Skip"),
        ("p", "info", "Project info"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page comparison-page"):
            yield Label("Which should have the higher priority?", classes="hero compare-heading")
            yield Static("", id="comparison-number", classes="muted")
            with Horizontal(id="cards"):
                with Vertical(classes="feature-card"):
                    yield Label("OPTION A", classes="field-label")
                    yield Static("", id="left-name", classes="item-name")
                    yield Static("", id="left-description", classes="item-description")
                    yield Button("A   Choose this", id="left-choice", variant="primary")
                with Vertical(classes="feature-card"):
                    yield Label("OPTION B", classes="field-label")
                    yield Static("", id="right-name", classes="item-name")
                    yield Static("", id="right-description", classes="item-description")
                    yield Button("D   Choose this", id="right-choice", variant="primary")
            with Horizontal(classes="center-actions"):
                yield Button("T   Equally important", id="tie")
                yield Button("S   Skip for now", id="skip")
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield Static("", id="progress-text", classes="muted")

    def on_mount(self) -> None:
        self.refresh_pair()

    def refresh_pair(self) -> None:
        project = self.pairrank.project
        if project is None:
            return
        pair = next_pair(project)
        if pair is None:
            self.pairrank.results()
            return
        names = {item.id: item for item in project.items}
        for position, item_id in zip(("left", "right"), pair, strict=True):
            item = names[item_id]
            self.query_one(f"#{position}-name", Static).update(item.name)
            self.query_one(f"#{position}-description", Static).update(item.description or "")
        completed = len(project.comparisons)
        total = project.total
        self.query_one("#comparison-number", Static).update(
            f"Comparison {completed + 1:,} of {total:,}   ·   {project.name}"
        )
        self.query_one("#progress", ProgressBar).update(progress=100 * completed / total)
        decisive = sum(c.outcome != Outcome.TIE for c in project.comparisons.values())
        ties = completed - decisive
        self.query_one("#progress-text", Static).update(
            f"{completed / total:.1%} complete    ·    {project.remaining:,} remaining    ·    "
            f"{decisive} decisive    ·    {ties} ties    ·    {len(project.skipped)} skipped"
        )

    def choose(self, outcome: Outcome) -> None:
        project = self.pairrank.project
        if project is None:
            return
        pair = next_pair(project)
        if pair is None:
            return
        try:
            decide(project, pair, outcome)
            self.pairrank.store.save(project)
        except OSError as error:
            self.notify(f"Could not save decision: {error}", severity="error")
            return
        self.refresh_pair()

    def action_left(self) -> None:
        self.choose(Outcome.A_WINS)

    def action_right(self) -> None:
        self.choose(Outcome.B_WINS)

    def action_tie(self) -> None:
        self.choose(Outcome.TIE)

    def action_skip(self) -> None:
        project = self.pairrank.project
        if project is not None and (pair := next_pair(project)) is not None:
            skip(project, pair)
            self.pairrank.store.save(project)
            self.refresh_pair()

    def action_undo(self) -> None:
        project = self.pairrank.project
        if project is None:
            return
        try:
            undo(project)
        except ValueError as error:
            self.notify(str(error))
            return
        self.pairrank.store.save(project)
        self.refresh_pair()

    def action_info(self) -> None:
        project = self.pairrank.project
        if project:
            self.notify(
                f"{project.name}  ·  {len(project.items)} items  ·  {project.total:,} pairs  ·  "
                f"{project.description or 'No description'}",
                timeout=8,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "left-choice": self.action_left,
            "right-choice": self.action_right,
            "tie": self.action_tie,
            "skip": self.action_skip,
        }
        if event.button.id in actions:
            actions[event.button.id]()
