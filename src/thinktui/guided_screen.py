"""Keyboard-first, autosaved steps for the five flagship analytical workflows."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from .context_offers import offers
from .core import METHODS, Session, timestamp
from .field_ai import FieldHelpMixin
from .guided_workflow import (
    GUIDED,
    MatrixMappingRequired,
    advance,
    definition,
    final_index,
    next_index,
    reachable_index,
)
from .matrix_mapping_screen import MatrixMappingDialog
from .planning import planned_next
from .reports import export, plain_result


class GuidedScreen(FieldHelpMixin, Screen):
    BINDINGS = [
        ("f8", "next", "Validate & next"),
        ("f7", "previous", "Previous"),
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "next", "Save step"),
        ("ctrl+e", "export", "Export"),
        Binding("ctrl+g", "stop_ai", "Stop AI", priority=True),
        ("escape", "project", "Project"),
    ]

    def __init__(self, session: Session) -> None:
        if session.method_id not in GUIDED:
            raise ValueError("No guided screen for this method")
        super().__init__()
        self.session = session
        state = session.method_state
        stored_step = state.get("_guided_step")
        if not isinstance(stored_step, int) or isinstance(stored_step, bool):
            stored_step = final_index(session.method_id, state) if not METHODS[session.method_id].validate(state) else 0
        self.index = max(0, min(stored_step, reachable_index(session.method_id, state)))

    def compose(self) -> ComposeResult:
        method = METHODS[self.session.method_id]
        step = definition(self.session.method_id, self.session.method_state, self.index)
        yield Header()
        with VerticalScroll(classes="page"):
            yield Label(f"{self.session.title} · {method.name}", classes="hero")
            yield Static(
                f"Step {self.index + 1} of {final_index(method.id, self.session.method_state) + 1} · {step.title}",
                classes="heading",
                id="step-heading",
            )
            yield Static(step.help, classes="muted")
            if method.id == "matrix" and self.index == 0:
                available = offers("matrix", self.app.store.sessions(self.session.project_id), self.session.id)
                if available:
                    yield Static(
                        "Earlier value-focused analysis: "
                        + "; ".join(f"{key}: {', '.join(values)}" for key, values in available.items())
                        + ". Labels only; you supply weights and scores.",
                        classes="muted",
                    )
                    yield Button("Use these starting points", id="use-offer")
            if method.id == "matrix" and self.index == 2:
                criteria = self.session.method_state.get("criteria", [])
                alternatives = self.session.method_state.get("alternatives", [])
                yield Static(
                    "Scores grid · rows are options, columns are your criteria. Use Tab to move between cells.",
                    classes="muted",
                )
                with Horizontal(classes="matrix-grid-row"):
                    yield Label("Option", classes="matrix-grid-name")
                    for criterion in criteria:
                        yield Label(str(criterion["name"]), classes="matrix-grid-cell")
                for i, alternative in enumerate(alternatives):
                    with Horizontal(classes="matrix-grid-row"):
                        yield Label(str(alternative["name"]), classes="matrix-grid-name")
                        for j, criterion in enumerate(criteria):
                            field = next(field for field in step.fields if field.key == f"score_{i}_{j}")
                            with Vertical(classes="matrix-grid-cell"):
                                yield Input(
                                    value=field.value,
                                    placeholder="0–10",
                                    id=f"field-{field.key}",
                                    tooltip=f"{alternative['name']} · {criterion['name']}: your score matters to the ranking.",
                                )
                                yield Static(
                                    "Your score, 0–10. Why: this criterion contributes to the ranking.", classes="muted"
                                )
                                yield Static("", id=f"guided-error-{field.key}", classes="muted")
            else:
                for field in step.fields:
                    yield Label(field.label, classes="heading")
                    yield Static(
                        (field.help or f"Enter your own {field.label.lower()}.")
                        + " Why: "
                        + (field.why or "This input explains or changes the local calculation."),
                        classes="muted",
                    )
                    if field.multiline:
                        yield TextArea(field.value, id=f"field-{field.key}")
                    else:
                        yield Input(value=field.value, placeholder=field.label, id=f"field-{field.key}")
                    if self.can_suggest(field.key):
                        yield Button(
                            "Suggest rows"
                            if field.key in {"alternatives", "criteria", "hypotheses"}
                            else "Suggest text",
                            id=f"help-suggest-{field.key}",
                        )
                    yield Static("", id=f"guided-error-{field.key}", classes="muted")
            if step.review:
                try:
                    issues = method.validate(self.session.method_state)
                    result = (
                        "Complete the missing judgments:\n" + "\n".join(issues)
                        if issues
                        else plain_result(method.calculate(self.session.method_state))
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    result = "Review the analysis: " + str(exc)
                yield Static(result, id="guided-results", classes="muted", markup=False)
                yield Input(
                    placeholder="Export decision brief: /path/to/brief.md or analysis.json", id="guided-export-path"
                )
            with Horizontal(classes="actions"):
                yield Button("← Previous  F7", id="previous", disabled=self.index == 0)
                yield Button("Finish & save" if step.review else "Validate & next  F8", id="next", variant="primary")
                if step.review and self.session.method_id in {"ach", "forecasting", "scenarios"}:
                    yield Button(
                        "Add more evidence"
                        if method.id == "ach"
                        else "Add forecast"
                        if method.id == "forecasting"
                        else "Add strategy",
                        id="more",
                    )
                if (
                    not step.review
                    and self.session.method_id in {"ach", "forecasting", "scenarios"}
                    and not method.validate(self.session.method_state)
                ):
                    yield Button("Return to saved review (discard this step's edits)", id="review")
                if step.review:
                    yield Button("Export  Ctrl+E", id="export")
                    if planned_next(self.session):
                        yield Button("Continue planned workflow", id="plan")
                yield Button("Advanced JSON  F6", id="advanced")
                yield Button("Project  Esc", id="project")
            yield Static("AI text draft · edit, Accept or Dismiss. Numbers are always yours.", classes="muted")
            yield Static("", id="field-help-status", classes="muted")
            yield TextArea(id="field-help-preview")
            with Horizontal(classes="actions"):
                yield Button("Accept edited text", id="help-accept")
                yield Button("Dismiss", id="help-dismiss")
                yield Button("Stop AI  Ctrl+G", id="help-stop")
        yield Footer()

    def can_suggest(self, key: str) -> bool:
        return key in {
            "alternatives",
            "criteria",
            "hypotheses",
            "title",
            "source",
            "question",
            "rationale",
            "narrative",
            "implications",
            "indicators",
            "name",
            "drivers",
            "axes",
        } or key.startswith("action_")

    def field_help_session(self) -> Session:
        draft = deepcopy(self.session)
        if self.index != final_index(self.session.method_id, self.session.method_state):
            draft.method_state = {**draft.method_state, "_draft_fields": self.current_values()}
        return draft

    def apply_field_help(self, target: str, text: str, rows: bool) -> None:
        if target not in {
            field.key for field in definition(self.session.method_id, self.session.method_state, self.index).fields
        }:
            return
        widget = self.query_one(f"#field-{target}")
        if isinstance(widget, (Input, TextArea)):
            current = widget.value if isinstance(widget, Input) else widget.text
            value = (current.rstrip() + "\n" + text).strip() if rows and current.strip() else text
            if isinstance(widget, TextArea):
                widget.load_text(value)
            else:
                widget.value = value

    def guided_issue(self, key: str, text: str) -> str:
        if not text.strip():
            return "Enter your own input before continuing."
        if key.startswith("score_"):
            try:
                value = float(text)
                if not 0 <= value <= 10:
                    raise ValueError
            except ValueError:
                return "Enter your own score from 0 to 10."
        if self.session.method_id == "matrix" and (self.index, key) in {(0, "alternatives"), (1, "criteria")}:
            try:
                advance("matrix", self.session.method_state, self.index, {key: text})
            except (ValueError, KeyError) as exc:
                return str(exc)
        return ""

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("field-"):
            key = event.input.id.removeprefix("field-")
            targets = self.query(f"#guided-error-{key}")
            if targets:
                targets.first().update(self.guided_issue(key, event.value))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id and event.text_area.id.startswith("field-"):
            key = event.text_area.id.removeprefix("field-")
            targets = self.query(f"#guided-error-{key}")
            if targets:
                targets.first().update(self.guided_issue(key, event.text_area.text))

    def action_stop_ai(self) -> None:
        self.field_help_stop()

    def on_mount(self) -> None:
        self.focus_first()

    def focus_first(self) -> None:
        fields = definition(self.session.method_id, self.session.method_state, self.index).fields
        if fields:
            self.query_one(f"#field-{fields[0].key}").focus()
        else:
            self.query_one("#next", Button).focus()

    def current_values(self) -> dict[str, str]:
        step = definition(self.session.method_id, self.session.method_state, self.index)
        return {
            field.key: (
                self.query_one(f"#field-{field.key}", TextArea).text
                if field.multiline
                else self.query_one(f"#field-{field.key}", Input).value
            )
            for field in step.fields
        }

    async def action_next(self) -> None:
        method = self.session.method_id
        values = self.current_values()
        try:
            state = advance(method, self.session.method_state, self.index, values)
        except MatrixMappingRequired as request:
            self.app.push_screen(
                MatrixMappingDialog(self.session.method_state, request, values), self.mapping_confirmed
            )
            return
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.notify(str(exc), severity="error")
            return
        await self.commit_next(state)

    def mapping_confirmed(self, state: dict | None) -> None:
        if state is not None:
            self.run_worker(self.commit_next(state), group="matrix-edit", exclusive=True)

    async def commit_next(self, state: dict) -> None:
        method = self.session.method_id
        is_review = self.index == final_index(method, state)
        self.index = next_index(method, state, self.index)
        state["_guided_step"] = self.index
        self.session.method_state = state
        self.session.completed_at = timestamp() if is_review else None
        self.app.store.save(
            self.session, f"Guided {method}: {self.index + 1} · " + ("Reviewed" if is_review else "Saved step")
        )
        self.field_help_stop()
        self.field_help_dismiss()
        await self.recompose()
        self.focus_first()
        if is_review:
            self.notify("Analysis saved; results are calculated locally")

    async def action_previous(self) -> None:
        if self.index:
            self.index -= 1
            self.session.method_state["_guided_step"] = self.index
            self.app.store.save(self.session, "Revisited guided step")
            self.field_help_stop()
            self.field_help_dismiss()
            await self.recompose()
            self.focus_first()

    async def action_more(self) -> None:
        if self.index != final_index(self.session.method_id, self.session.method_state):
            return
        self.index = {"ach": 1, "forecasting": 0, "scenarios": 6}[self.session.method_id]
        self.session.method_state["_guided_step"] = self.index
        self.session.completed_at = None
        self.app.store.save(self.session, "Opened another guided entry")
        await self.recompose()
        self.focus_first()

    def action_plan(self) -> None:
        from .planning_screen import PlanningScreen

        self.app.switch_screen(PlanningScreen(self.session))

    async def action_review(self) -> None:
        self.index = final_index(self.session.method_id, self.session.method_state)
        self.session.method_state["_guided_step"] = self.index
        self.app.store.save(self.session, "Returned to guided review")
        await self.recompose()
        self.focus_first()

    def action_advanced(self) -> None:
        self.app.open_session(self.session)

    def action_export(self) -> None:
        if self.index != final_index(self.session.method_id, self.session.method_state):
            self.notify("Save this step and reach review before exporting", severity="warning")
            return
        value = self.query_one("#guided-export-path", Input).value.strip()
        if not value:
            self.query_one("#guided-export-path", Input).focus()
            self.notify("Enter an export path", severity="warning")
            return
        try:
            export(self.session, Path(value).expanduser())
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Exported {value}")

    def action_project(self) -> None:
        self.app.show_project()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            await self.action_next()
        elif event.button.id == "previous":
            await self.action_previous()
        elif event.button.id == "more":
            await self.action_more()
        elif event.button.id == "advanced":
            self.action_advanced()
        elif event.button.id == "export":
            self.action_export()
        elif event.button.id == "plan":
            self.action_plan()
        elif event.button.id == "review":
            await self.action_review()
        elif event.button.id and event.button.id.startswith("help-suggest-"):
            key = event.button.id.removeprefix("help-suggest-")
            if self.can_suggest(key):
                field = next(
                    field
                    for field in definition(self.session.method_id, self.session.method_state, self.index).fields
                    if field.key == key
                )
                self.field_help_request(field.label, key, rows=key in {"alternatives", "criteria", "hypotheses"})
        elif event.button.id == "help-accept":
            self.field_help_accept()
        elif event.button.id == "help-dismiss":
            self.field_help_dismiss()
        elif event.button.id == "help-stop":
            self.field_help_stop()
        elif event.button.id == "use-offer":
            available = offers("matrix", self.app.store.sessions(self.session.project_id), self.session.id)
            state = self.session.method_state
            if not state.get("alternatives"):
                state["alternatives"] = [{"name": label, "scores": []} for label in available.get("alternatives", [])]
            if not state.get("criteria"):
                state["criteria"] = [
                    {"name": label, "weight": None, "direction": "benefit"} for label in available.get("criteria", [])
                ]
            self.app.store.save(self.session, "Accepted text-only value-focused starting points")
            await self.recompose()
        else:
            self.action_project()
