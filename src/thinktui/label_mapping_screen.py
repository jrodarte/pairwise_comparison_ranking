"""Explicit, lossless mapping of saved ACH/AHP judgments when labels change."""

from __future__ import annotations

from copy import deepcopy

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox

from .guided_workflow import LabelMappingRequired, ScenarioMappingRequired, advance, matrix_mapping
from .safe_widgets import Label, Select, Static


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
                "Map each retained label to its saved judgments. New labels start blank. "
                "Removing an old label discards its judgments only after explicit confirmation. Cancel changes nothing.",
                classes="muted",
            )
            with VerticalScroll(classes="matrix-dialog-rows"):
                for i, label in enumerate(request.proposed):
                    yield Label(f"New label: {label}", classes="heading")
                    yield Select(
                        [("New label · no saved judgments", -1)] + [(old, j) for j, old in enumerate(request.previous)],
                        value=proposed[i],
                        allow_blank=False,
                        id=f"label-source-{i}",
                    )
            if request.method in {"ach", "ahp"}:
                lost = [label for j, label in enumerate(request.previous) if j not in proposed]
                yield Static(self._discard_message(lost), id="discard-label", classes="muted")
                yield Checkbox(
                    "I confirm discarding the named labels and their saved judgments", id="discard-judgments"
                )
            yield Static("", id="mapping-error", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("Confirm mapping", id="confirm")

    @staticmethod
    def _discard_message(lost: list[str]) -> str:
        return "Judgments to discard: " + ", ".join(lost) if lost else "All existing labels keep their judgments."

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if (
            not event.select.id
            or not event.select.id.startswith("label-source-")
            or not self.query("#discard-judgments")
        ):
            return
        if any(not self.query(f"#label-source-{i}") for i in range(len(self.request.proposed))):
            return
        selected = [self.query_one(f"#label-source-{i}", Select).value for i in range(len(self.request.proposed))]
        lost = [label for i, label in enumerate(self.request.previous) if i not in selected]
        self.query_one("#discard-label", Static).update(self._discard_message(lost))
        self.query_one("#discard-judgments", Checkbox).value = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "confirm":
            self.dismiss(None)
            return
        mapping = [
            None if (value := self.query_one(f"#label-source-{i}", Select).value) == -1 else value
            for i in range(len(self.request.proposed))
        ]
        discard = (
            bool(self.query_one("#discard-judgments", Checkbox).value) if self.query("#discard-judgments") else False
        )
        try:
            state = advance(
                self.request.method,
                self.original,
                self.request.index,
                self.values,
                mapping=mapping,
                discard_judgments=discard,
            )
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.query_one("#mapping-error", Static).update(str(exc))
            return
        self.dismiss(state)

    def action_cancel(self) -> None:
        self.dismiss(None)
