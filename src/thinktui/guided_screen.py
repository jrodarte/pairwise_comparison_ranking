"""Keyboard-first, autosaved steps for the five flagship analytical workflows."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from .core import METHODS, Session, timestamp
from .guided_workflow import GUIDED, advance, definition, final_index, next_index, reachable_index
from .planning import planned_next
from .reports import export


class GuidedScreen(Screen):
    BINDINGS = [
        ("f8", "next", "Validate & next"),
        ("f7", "previous", "Previous"),
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "next", "Save step"),
        ("ctrl+e", "export", "Export"),
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
            for field in step.fields:
                yield Label(field.label, classes="heading")
                if field.multiline:
                    yield TextArea(field.value, id=f"field-{field.key}")
                else:
                    yield Input(value=field.value, placeholder=field.label, id=f"field-{field.key}")
            if step.review:
                try:
                    issues = method.validate(self.session.method_state)
                    result = (
                        "Complete the missing judgments:\n" + "\n".join(issues)
                        if issues
                        else json.dumps(method.calculate(self.session.method_state), indent=2, ensure_ascii=False)
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
        yield Footer()

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
        try:
            state = advance(method, self.session.method_state, self.index, self.current_values())
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.notify(str(exc), severity="error")
            return
        is_review = self.index == final_index(method, state)
        self.index = next_index(method, state, self.index)
        state["_guided_step"] = self.index
        self.session.method_state = state
        self.session.completed_at = timestamp() if is_review else None
        self.app.store.save(
            self.session, f"Guided {method}: {self.index + 1} · " + ("Reviewed" if is_review else "Saved step")
        )
        await self.recompose()
        self.focus_first()
        if is_review:
            self.notify("Analysis saved; results are calculated locally")

    async def action_previous(self) -> None:
        if self.index:
            self.index -= 1
            self.session.method_state["_guided_step"] = self.index
            self.app.store.save(self.session, "Revisited guided step")
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
        else:
            self.action_project()
