"""Keyboard-first file picker for exports, and safe parsing of typed paths."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input

from .safe_widgets import Label, Static


def user_path(value: str) -> Path:
    """Expand ~ without letting a typo such as ``~home/x`` crash the app."""
    try:
        return Path(value.strip()).expanduser()
    except RuntimeError:
        raise ValueError(f"Unknown home folder in {value.strip()!r}; use ~/ for your own home folder") from None


def suggested_filename(title: str, suffix: str = ".md") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug or "analysis") + suffix


class FolderTree(DirectoryTree):
    """Folders only, hidden ones left out, so the tree stays short enough to navigate by keyboard."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [path for path in paths if not path.name.startswith(".") and path.is_dir()]


class ExportPicker(ModalScreen[Path | None]):
    """Choose a folder and a .md or .json filename; returns the full path, or None when cancelled."""

    DEFAULT_CSS = """
    ExportPicker { align: center middle; background: $background 80%; }
    ExportPicker .picker-dialog { width: 85%; max-width: 90; height: 90%; border: round $primary;
        background: $panel; padding: 1 2; }
    ExportPicker FolderTree { height: 1fr; min-height: 6; border: solid $secondary; }
    ExportPicker .actions { height: auto; }
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("backspace", "parent", "Parent folder", show=False),
    ]

    def __init__(self, filename: str, start: Path | None = None) -> None:
        super().__init__()
        self.filename = filename
        start = start if start is not None and start.is_dir() else Path.home()
        self.folder = start

    def compose(self) -> ComposeResult:
        with Vertical(classes="picker-dialog"):
            yield Label("Export to…", classes="hero")
            yield Static(
                "Arrows move, Enter opens a folder, Backspace goes up. Tab to the filename, then Enter to export.",
                classes="muted",
            )
            yield Static(str(self.folder), id="picker-folder", classes="muted")
            yield FolderTree(self.folder, id="picker-tree")
            yield Input(value=self.filename, placeholder="name.md or name.json", id="picker-filename")
            with Horizontal(classes="actions"):
                yield Button("Export here", id="picker-ok", variant="primary")
                yield Button("Parent folder", id="picker-parent")
                yield Button("Cancel", id="picker-cancel")

    def on_mount(self) -> None:
        self.query_one(FolderTree).focus()

    def set_folder(self, folder: Path) -> None:
        self.folder = folder
        self.query_one("#picker-folder", Static).update(str(folder))

    def on_tree_node_highlighted(self, event: FolderTree.NodeHighlighted) -> None:
        if event.node.data is not None:
            self.set_folder(event.node.data.path)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.set_folder(event.path)

    def action_parent(self) -> None:
        tree = self.query_one(FolderTree)
        if not tree.has_focus:
            return
        parent = Path(tree.path).parent
        if parent != Path(tree.path):
            tree.path = parent
            self.set_folder(parent)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def confirm(self) -> None:
        name = self.query_one("#picker-filename", Input).value.strip()
        if not name or "/" in name or name in {".", ".."}:
            self.notify("Enter a filename without folders, such as brief.md", severity="warning")
            return
        if Path(name).suffix.lower() not in {".md", ".json"}:
            self.notify("Use a .md or .json filename", severity="warning")
            return
        destination = self.folder / name
        if destination.exists():
            self.notify(f"{name} already exists here; choose another name", severity="warning")
            return
        self.dismiss(destination)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "picker-filename":
            self.confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "picker-ok":
            self.confirm()
        elif event.button.id == "picker-parent":
            tree = self.query_one(FolderTree)
            tree.focus()
            self.action_parent()
        elif event.button.id == "picker-cancel":
            self.dismiss(None)
