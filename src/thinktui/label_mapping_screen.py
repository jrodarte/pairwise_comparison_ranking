"""Explicit, lossless mapping of saved ACH/AHP judgments when labels change."""

from __future__ import annotations

from copy import deepcopy

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static

from .guided_workflow import LabelMappingRequired, ScenarioMappingRequired, advance, matrix_mapping


class LabelMappingDialog(ModalScreen[dict | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self, state: dict, request: LabelMappingRequired | ScenarioMappingRequired, values: dict[str, str]
    ) -> None:
        super().__init__()
        self.original = deepcopy(state)
        self.request = request
        self.values = values.copy()

    def compose(self) -> ComposeResult:
        request = self.request
        exact = matrix_mapping(request.previous, request.proposed)
        remaining = [i for i in range(len(request.previous)) if i not in exact]
        proposed = [value if value is not None else remaining.pop(0) if remaining else -1 for value in exact]
        with Vertical(classes="matrix-dialog"):
            yield Label("Map saved judgments to edited labels", classes="hero")
            yield Static(
                "For each new label, select the old label whose judgments it retains. "
                "Every previous label must be mapped exactly once; Cancel leaves everything unchanged.",
                classes="muted",
            )
            with VerticalScroll(classes="matrix-dialog-rows"):
                for i, label in enumerate(request.proposed):
                    yield Label(f"New label: {label}", classes="heading")
                    yield Select(
                        [(old, j) for j, old in enumerate(request.previous)],
                        value=proposed[i],
                        allow_blank=False,
                        id=f"label-source-{i}",
                    )
            yield Static("", id="mapping-error", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("Confirm mapping", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "confirm":
            self.dismiss(None)
            return
        mapping = [self.query_one(f"#label-source-{i}", Select).value for i in range(len(self.request.proposed))]
        try:
            state = advance(self.request.method, self.original, self.request.index, self.values, mapping=mapping)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.query_one("#mapping-error", Static).update(str(exc))
            return
        self.dismiss(state)

    def action_cancel(self) -> None:
        self.dismiss(None)
