"""Shared screen furniture and small modal dialogs."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

if TYPE_CHECKING:
    from ..app import PairRankApp


class BaseScreen(Screen[None]):
    """Standard chrome and typed access to application services."""

    @property
    def pairrank(self) -> PairRankApp:
        return cast("PairRankApp", self.app)

    def chrome(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Footer()


class HelpDialog(ModalScreen[None]):
    """Keyboard help and concise explanation of the method."""

    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(classes="dialog help-dialog"):
            yield Label("PAIRWISE PRIORITIZATION", classes="section-title")
            yield Static(
                "Choose which of two items deserves higher priority. Every unique pair is "
                "compared once; there are n × (n − 1) / 2 decisions. Ties split the point.\n\n"
                "Bradley–Terry estimates relative priority strength from all head-to-head "
                "results, including cycles. Scores are relative, not percentages.\n\n"
                "Compare: A / ← left  ·  D / → right  ·  T tie  ·  S skip  ·  U undo\n"
                "Results: ↑↓ select  ·  Enter details  ·  M matrix  ·  R revisit\n"
                "Global: ? help  ·  Q save & quit  ·  Ctrl+C safe exit",
                classes="help-text",
            )
            yield Button("Close  [Esc]", id="close", variant="primary")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()


class PromptDialog(ModalScreen[str | None]):
    """Ask for a short string, such as a path or new project name."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, placeholder: str = "", value: str = "") -> None:
        super().__init__()
        self.prompt_title = title
        self.placeholder = placeholder
        self.value = value

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label(self.prompt_title, classes="section-title")
            yield Input(value=self.value, placeholder=self.placeholder, id="response")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Continue", id="submit", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.action_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        self.dismiss(self.query_one(Input).value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDialog(ModalScreen[bool]):
    """Destructive-action confirmation."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Confirm deletion", classes="section-title")
            yield Static(self.message)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Keep project", id="cancel")
                yield Button("Delete", id="delete", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "delete")

    def action_cancel(self) -> None:
        self.dismiss(False)
