"""Landing screen with recent work and navigation."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, DataTable, Label, Static

from .common import BaseScreen


class HomeScreen(BaseScreen):
    """Workspace entry point."""

    BINDINGS = [
        ("n", "new", "New"),
        ("r", "resume", "Resume"),
        ("h", "history", "History"),
        ("i", "import_items", "Import"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page"):
            yield Label("Make priorities clearer.", classes="hero")
            yield Static("Compare two at a time. Find an evidence-based ordering.", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("New ranking   N", id="new", variant="primary")
                yield Button("Resume   R", id="resume")
                yield Button("Previous results   H", id="history")
                yield Button("Import items   I", id="import")
            yield Label("RECENT RANKINGS", classes="section-title")
            yield DataTable(id="recent", cursor_type="row")
            yield Static(
                "No saved rankings yet. Start a new ranking or import a list.",
                id="empty",
                classes="muted",
            )

    def on_mount(self) -> None:
        table = self.query_one("#recent", DataTable)
        table.add_columns("Ranking", "Items", "Decisions", "Status")
        projects = self.pairrank.store.list_projects()[:8]
        for project in projects:
            table.add_row(
                project.name,
                str(len(project.items)),
                f"{len(project.comparisons)} / {project.total}",
                project.status,
                key=project.id,
            )
        self.query_one("#empty").display = not projects

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.pairrank.open_project(self.pairrank.store.load(str(event.row_key.value)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "new": self.action_new,
            "resume": self.action_resume,
            "history": self.action_history,
            "import": self.action_import_items,
        }
        if event.button.id in actions:
            actions[event.button.id]()

    def action_new(self) -> None:
        self.pairrank.setup()

    def action_import_items(self) -> None:
        self.pairrank.setup(import_focus=True)

    def action_resume(self) -> None:
        projects = self.pairrank.store.list_projects()
        incomplete = next((p for p in projects if p.remaining), None)
        if incomplete:
            self.pairrank.open_project(incomplete)
        else:
            self.notify("No unfinished ranking. Create a new one.")

    def action_history(self) -> None:
        self.pairrank.history()
