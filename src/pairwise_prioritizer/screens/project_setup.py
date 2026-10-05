"""New ranking form, bulk paste and file import."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from ..comparison_engine import create_project, validate_names
from ..import_export import import_items
from ..models import Item
from .common import BaseScreen


class ColumnDialog(ModalScreen[str | None]):
    """Select the CSV item-name field when several are available."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, columns: list[str]) -> None:
        super().__init__()
        self.columns = columns

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label("Which CSV column contains the item names?", classes="section-title")
            yield Select(
                [(column, column) for column in self.columns], id="column", allow_blank=False
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Import", id="confirm", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(str(self.query_one(Select).value))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SetupScreen(BaseScreen):
    """Create a validated ranking from typed, pasted or imported items."""

    BINDINGS = [("escape", "back", "Home")]

    def __init__(self, import_focus: bool = False, demo: bool = False) -> None:
        super().__init__()
        self.import_focus = import_focus
        self.demo = demo
        self.imported: dict[str, Item] = {}

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page setup-page"):
            yield Label("New ranking", classes="hero")
            yield Static(
                "Give your decision set a name and add one item per line. "
                "Paste a whole list at once.",
                classes="muted",
            )
            yield Label("PROJECT NAME", classes="field-label")
            yield Input(placeholder="e.g. Q4 Feature Priorities", id="name")
            yield Label("DESCRIPTION  ·  OPTIONAL", classes="field-label")
            yield Input(placeholder="Context for this decision set", id="description")
            yield Label("ITEMS  ·  ONE PER LINE", classes="field-label")
            yield TextArea(id="items", soft_wrap=True)
            yield Static(
                "Items: 0   •   Comparisons required: 0   •   Estimated workload: 0 decisions",
                id="workload",
                classes="muted",
            )
            yield Label("IMPORT FROM FILE  ·  .TXT / .CSV / .JSON", classes="field-label")
            with Horizontal(classes="import-row"):
                yield Input(placeholder="/path/to/items.csv", id="path")
                yield Button("Import", id="import")
            with Horizontal(classes="actions"):
                yield Button("Start comparisons", id="start", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self.demo:
            self.query_one("#name", Input).value = "Demo · Feature Priorities"
            self.query_one(TextArea).load_text(
                "\n".join(
                    [
                        "Automated Data Lineage",
                        "Data Quality Dashboard",
                        "Business Metadata Search",
                        "Role Management Improvements",
                        "Data Product Marketplace",
                        "Enterprise Metric Store",
                        "Observability Improvements",
                        "Developer Self-Service Portal",
                    ]
                )
            )
        (
            self.query_one("#path", Input) if self.import_focus else self.query_one("#name", Input)
        ).focus()
        self.refresh_workload()

    def on_text_area_changed(self, _: TextArea.Changed) -> None:
        self.refresh_workload()

    def refresh_workload(self) -> None:
        lines = [
            line.strip() for line in self.query_one(TextArea).text.splitlines() if line.strip()
        ]
        count = len(lines)
        total = count * (count - 1) // 2
        warning = "  ⚠ Large set: consider the workload before starting." if count > 30 else ""
        duplicates = (
            "  ⚠ Duplicate names: remove them before starting."
            if len({line.casefold() for line in lines}) != count
            else ""
        )
        self.query_one("#workload", Static).update(
            f"Items: {count}   •   Comparisons required: {total:,}   •   "
            f"Estimated workload: {total:,} decisions{warning}{duplicates}"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path":
            self.import_file()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import":
            self.import_file()
        elif event.button.id == "start":
            self.start()
        elif event.button.id == "cancel":
            self.action_back()

    def import_file(self, column: str | None = None) -> None:
        path = Path(self.query_one("#path", Input).value).expanduser()
        try:
            items = import_items(path, column)
        except (OSError, ValueError) as error:
            message = str(error)
            if message.startswith("Choose a CSV column: "):
                columns = message.removeprefix("Choose a CSV column: ").split(", ")
                self.app.push_screen(
                    ColumnDialog(columns),
                    lambda selected: self.import_file(selected) if selected else None,
                )
                return
            self.notify(message, severity="error")
            return
        area = self.query_one(TextArea)
        lines = [line.strip() for line in area.text.splitlines() if line.strip()]
        lines.extend(item.name for item in items)
        area.load_text("\n".join(lines))
        self.imported.update({item.name: item for item in items})
        self.notify(f"Imported {len(items)} items. Review the list before starting.")

    def start(self) -> None:
        try:
            names = validate_names(self.query_one(TextArea).text.splitlines())
            items = [self.imported.get(name, Item(name=name)) for name in names]
            project = create_project(
                self.query_one("#name", Input).value,
                items,
                self.query_one("#description", Input).value,
            )
            self.pairrank.store.save(project)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity="error")
            return
        self.pairrank.open_project(project)

    def action_back(self) -> None:
        self.pairrank.home()
