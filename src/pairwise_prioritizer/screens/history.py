"""Saved rankings management."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, DataTable, Label, Static

from ..comparison_engine import duplicate
from ..import_export import export_project
from ..models import Project, now
from ..ranking import BradleyTerry
from .common import BaseScreen, ConfirmDialog, PromptDialog


class HistoryScreen(BaseScreen):
    """Browse, resume, rename, duplicate, export or delete saved work."""

    BINDINGS = [
        ("escape", "back", "Home"),
        ("r", "open_selected", "Open"),
        ("n", "rename", "Rename"),
        ("d", "duplicate", "Duplicate"),
        ("delete", "delete", "Delete"),
        ("e", "export", "Export"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page"):
            yield Label("Saved rankings", classes="hero")
            yield Static(
                "All decisions are autosaved. Select a ranking to continue or review.",
                classes="muted",
            )
            yield DataTable(id="projects", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="actions"):
                yield Button("Open  R", id="open", variant="primary")
                yield Button("Rename  N", id="rename")
                yield Button("Duplicate  D", id="duplicate")
                yield Button("Export  E", id="export")
                yield Button("Delete  Del", id="delete", variant="error")
                yield Button("Home  Esc", id="back")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Ranking", "Created", "Modified", "Items", "Decisions", "Status")
        self.refresh_projects()
        table.focus()

    def refresh_projects(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for project in self.pairrank.store.list_projects():
            table.add_row(
                project.name,
                project.created_at[:10],
                project.modified_at[:10],
                str(len(project.items)),
                f"{len(project.comparisons)} / {project.total}",
                project.status,
                key=project.id,
            )

    def selected(self) -> Project | None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < table.row_count:
            # Row keys preserve project UUIDs independent of visual sorting.
            key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
            return self.pairrank.store.load(str(key))
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.pairrank.open_project(self.pairrank.store.load(str(event.row_key.value)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "open": self.action_open_selected,
            "rename": self.action_rename,
            "duplicate": self.action_duplicate,
            "export": self.action_export,
            "delete": self.action_delete,
            "back": self.action_back,
        }
        if event.button.id in actions:
            actions[event.button.id]()

    def action_open_selected(self) -> None:
        if project := self.selected():
            self.pairrank.open_project(project)

    def action_rename(self) -> None:
        project = self.selected()
        if not project:
            return

        def rename(value: str | None) -> None:
            if value:
                project.name = value
                project.modified_at = now()
                self.pairrank.store.save(project)
                self.refresh_projects()

        self.app.push_screen(PromptDialog("Rename ranking", value=project.name), rename)

    def action_duplicate(self) -> None:
        project = self.selected()
        if not project:
            return

        def copy(value: str | None) -> None:
            if value:
                new_project = duplicate(project, value)
                self.pairrank.store.save(new_project)
                self.refresh_projects()
                self.notify("Created a fresh ranking; previous decisions were not copied.")

        self.app.push_screen(
            PromptDialog("Name the new ranking", value=f"{project.name} (copy)"), copy
        )

    def action_export(self) -> None:
        project = self.selected()
        if not project:
            return

        def export(path: str | None) -> None:
            if not path:
                return
            from pathlib import Path

            try:
                results = BradleyTerry().calculate(
                    project.items, list(project.comparisons.values())
                )
                export_project(project, results, Path(path))
                self.notify(f"Exported to {path}")
            except (OSError, ValueError) as error:
                self.notify(str(error), severity="error")

        self.app.push_screen(
            PromptDialog("Export to a file", "~/ranking.csv / .json / .md"), export
        )

    def action_delete(self) -> None:
        project = self.selected()
        if not project:
            return

        def remove(confirmed: bool) -> None:
            if confirmed:
                self.pairrank.store.delete(project.id)
                self.refresh_projects()
                self.notify("Ranking deleted")

        self.app.push_screen(
            ConfirmDialog(f"Permanently delete ‘{project.name}’ and all of its decisions?"), remove
        )

    def action_back(self) -> None:
        self.pairrank.home()
