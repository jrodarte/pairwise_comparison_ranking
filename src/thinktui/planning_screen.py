"""Keyboard-first rule-based method selection and explicit cross-method handoff."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header

from .coach import CoachHost
from .core import METHODS, Session
from .planning import GOALS, begin_workflow, continue_workflow, planned_next, recommend, transfer
from .safe_widgets import DataTable, Label, Select, Static
from .text_field import TextField


class PlanningScreen(CoachHost, Screen):
    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, source: Session | None = None) -> None:
        super().__init__()
        self.source = source
        self.options: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="page"):
            yield Label("Recommended thinking methods", classes="hero")
            if self.source:
                yield Static(f"From {self.source.title} · recommendations are rule-based, not AI.", classes="muted")
                if planned_next(self.source):
                    state = self.source.method_state
                    yield Static(
                        f"Workflow · {state['workflow_goal']} · step {state['workflow_index'] + 1} "
                        f"of {len(state['workflow_steps'])}. Finish this step before the planned handoff.",
                        classes="muted",
                    )
                yield Static(
                    "Explicit handoff: copy problem/objective and approved user input only. "
                    "No weights, ratings, probabilities or evidence are invented. Review the draft.",
                    classes="muted",
                )
            else:
                yield Static(
                    "What are you trying to do? Choose a goal, then a suggested method. "
                    "Recommendations explain their fit, not which decision to make.",
                    classes="muted",
                )
                yield Select([(goal, goal) for goal in GOALS], value=next(iter(GOALS)), id="goal", allow_blank=False)
                yield TextField(
                    placeholder="Problem statement for a linked workflow (no example data)", id="workflow-problem"
                )
                yield Button("Start linked, step-by-step workflow", id="workflow")
                yield Static(
                    "Creates only the first draft. You approve each next step; no judgments are filled in.",
                    classes="muted",
                )
            yield DataTable(id="recommendations", cursor_type="row")
            yield Button(
                "Continue planned workflow" if self.source and planned_next(self.source) else "Start selected method",
                id="start",
                variant="primary",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Method", "Why it fits")
        self.refresh_options()
        self.query_one(DataTable).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "goal":
            self.refresh_options()

    def refresh_options(self) -> None:
        goal = str(self.query_one("#goal", Select).value) if not self.source else None
        options = recommend(goal, self.source)
        table = self.query_one("#recommendations", DataTable)
        table.clear()
        self.options = [method_id for method_id, _ in options]
        for method_id, reason in options:
            table.add_row(METHODS[method_id].name, reason, key=method_id)
        if self.options:
            table.move_cursor(row=0)

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        self.start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workflow":
            self.start_workflow()
        else:
            self.start()

    def start_workflow(self) -> None:
        app = self.app
        if not app.project_id:
            self.notify("Open or create a project first", severity="warning")
            return
        try:
            session = begin_workflow(
                app.project_id,
                str(self.query_one("#goal", Select).value),
                self.query_one("#workflow-problem", TextField).value,
            )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        app.store.save(session, "Started linked workflow: " + session.objective)
        app.open_session(session, guided=True)

    def start(self) -> None:
        app = self.app
        row = self.query_one(DataTable).cursor_row
        if not 0 <= row < len(self.options):
            self.notify("Select a method first", severity="warning")
            return
        method_id = self.options[row]
        app.method_id = method_id
        if self.source:
            if method_id == planned_next(self.source):
                try:
                    session = continue_workflow(self.source)
                except ValueError as exc:
                    self.notify(str(exc), severity="warning")
                    return
                # Reopening a planned stage must not create parallel copies on repeated confirmation.
                existing = next(
                    (
                        saved
                        for saved in app.store.sessions(self.source.project_id)
                        if saved.method_state.get("workflow_id") == session.method_state["workflow_id"]
                        and saved.method_state.get("workflow_index") == session.method_state["workflow_index"]
                    ),
                    None,
                )
                if existing:
                    app.open_session(existing, guided=True)
                    self.notify("Resumed the existing planned step")
                    return
            else:
                if method_id == "sensitivity" and self.source.method_id == "matrix":
                    existing = next(
                        (
                            saved
                            for saved in app.store.sessions(self.source.project_id)
                            if saved.method_id == "sensitivity"
                            and saved.method_state.get("source_session_id") == self.source.id
                        ),
                        None,
                    )
                    if existing:
                        app.open_session(existing, guided=True)
                        self.notify("Resumed the linked sensitivity analysis")
                        return
                try:
                    state = transfer(self.source, method_id)
                except ValueError as exc:
                    self.notify(str(exc), severity="warning")
                    return
                session = Session(
                    project_id=self.source.project_id,
                    method_id=method_id,
                    title=self.source.title + " · " + METHODS[method_id].name,
                    problem_statement=self.source.problem_statement,
                    objective=self.source.objective,
                    method_state=state,
                )
            app.store.save(session, "Linked from analysis " + self.source.id)
            app.open_session(session, guided=True)
            self.notify("Review transferred data; missing judgments must be supplied by you.")
        elif app.project_id:
            from .screens import NewAnalysis

            app.switch_screen(NewAnalysis())
        else:
            from .screens import NewProject

            app.pending_method_id = method_id
            app.switch_screen(NewProject())

    def action_back(self) -> None:
        if self.source:
            self.app.open_session(self.source, guided=True)
        elif self.app.project_id:
            self.app.show_project()
        else:
            self.app.home()
