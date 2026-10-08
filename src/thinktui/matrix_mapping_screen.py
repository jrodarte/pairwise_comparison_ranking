"""Explicit score mapping when labels change in a scored decision matrix."""

from __future__ import annotations

from copy import deepcopy

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Select, Static

from .guided_workflow import MatrixMappingRequired, advance, matrix_mapping


class MatrixMappingDialog(ModalScreen[dict | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, state: dict, request: MatrixMappingRequired, values: dict[str, str]) -> None:
        super().__init__()
        self.original = deepcopy(state)
        self.request = request
        self.values = values.copy()

    def compose(self) -> ComposeResult:
        request = self.request
        proposals = matrix_mapping(request.previous, request.proposed)
        with Vertical(classes="matrix-dialog"):
            yield Label("Confirm the score mapping", classes="hero")
            yield Static(
                "Select which old row each edited label represents. An unassigned label starts with blank scores. "
                "No scores change until you confirm this mapping.",
                classes="muted",
            )
            with VerticalScroll(classes="matrix-dialog-rows"):
                for i, label in enumerate(request.proposed):
                    yield Label(f"New {('option' if request.index == 0 else 'criterion')}: {label}", classes="heading")
                    options = [("New · leave judgments blank", -1)] + [
                        (f"Existing · {old}", j) for j, old in enumerate(request.previous)
                    ]
                    yield Select(
                        options,
                        value=proposals[i] if proposals[i] is not None else -1,
                        allow_blank=False,
                        id=f"matrix-source-{i}",
                    )
                if request.index == 0:
                    for row in self.original.get("alternatives", []):
                        yield Static(
                            f"Existing {row['name']}: scores {', '.join(str(v) for v in row.get('scores', []))}",
                            markup=False,
                        )
                else:
                    for j, criterion in enumerate(self.original.get("criteria", [])):
                        scored = [
                            f"{alt['name']}: {alt['scores'][j]}"
                            for alt in self.original.get("alternatives", [])
                            if j < len(alt.get("scores", []))
                        ]
                        yield Static(f"Existing {criterion['name']}: {', '.join(scored)}", markup=False)
            yield Checkbox("If any scored row is unmapped, I confirm discarding its scores", id="matrix-discard")
            yield Static("", id="matrix-mapping-error", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("Cancel · keep existing scores", id="cancel", variant="primary")
                yield Button("Confirm mapping", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "confirm":
            mapping = [
                None if (value := self.query_one(f"#matrix-source-{i}", Select).value) == -1 else value
                for i in range(len(self.request.proposed))
            ]
            try:
                candidate = advance(
                    "matrix",
                    self.original,
                    self.request.index,
                    self.values,
                    mapping=mapping,
                    discard_scores=self.query_one("#matrix-discard", Checkbox).value,
                )
            except (ValueError, KeyError, TypeError) as exc:
                self.query_one("#matrix-mapping-error", Static).update(str(exc))
                return
            self.dismiss(candidate)

    def action_cancel(self) -> None:
        self.dismiss(None)
