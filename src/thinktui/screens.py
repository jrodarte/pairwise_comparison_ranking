"""Keyboard-first workspace screens. Every change is persisted immediately."""

from __future__ import annotations

import asyncio
import json
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path

from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

from pairwise_prioritizer.comparison_engine import create_project, decide, next_pair, skip, undo
from pairwise_prioritizer.models import Item, Outcome, Project

from . import credentials
from .ai import (
    AUTO_NOTE,
    PRESETS,
    AIRequest,
    ProviderConfig,
    SubscriptionCLI,
    config_for,
    connect,
    context_for,
    create,
    describe,
    key_status,
    parse_json_object,
    pick_ollama_model,
    remote_consent,
    selected_provider,
    sharing_destination,
    status_label,
    visible_text,
)
from .context_offers import offers
from .core import METHODS, Session, timestamp
from .field_ai import FieldHelpMixin, text_only
from .guided_workflow import GUIDED
from .issue_tree import add as tree_add
from .issue_tree import delete as tree_delete
from .issue_tree import edit as tree_edit
from .issue_tree import toggle as tree_toggle
from .issue_tree import visible as tree_visible
from .planning import planned_next, sensitivity_from_matrix, sensitivity_pair
from .planning_screen import PlanningScreen
from .project_progress import checklist
from .reports import export


class AIStatus(Static):
    """Animated progress line so a slow AI request (e.g. a cold local model) visibly keeps working."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    SLOW_AFTER = 15

    def on_mount(self) -> None:
        self.started = 0.0
        self.label = ""
        self.phase = ""
        self.frame = 0
        self.timer = None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def running(self) -> bool:
        return self.timer is not None

    def start(self, label: str, phase: str) -> None:
        self.started, self.label, self.phase, self.frame = time.monotonic(), label, phase, 0
        if self.timer is None:
            self.timer = self.set_interval(0.25, self.tick)
        self.tick()

    def set_phase(self, phase: str, label: str | None = None) -> None:
        self.phase = phase
        self.label = label or self.label
        self.tick()

    def tick(self) -> None:
        self.frame = (self.frame + 1) % len(self.FRAMES)
        waiting = self.phase.startswith(("waiting", "loading", "connecting", "sending"))
        hint = (
            " · still working; local models can be slow on first use"
            if waiting and self.elapsed >= self.SLOW_AFTER
            else ""
        )
        self.update(
            f"{self.FRAMES[self.frame]} {self.label} · {self.phase} · {self.elapsed:.0f}s{hint}  (Ctrl+G stops)"
        )

    def finish(self, message: str) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.update(f"{message} · {self.elapsed:.0f}s" if self.started else message)


class Base(Screen):
    def chrome(self) -> ComposeResult:
        yield Header()
        yield Footer()

    @property
    def workbench(self):
        return self.app


class DeleteProjectDialog(ModalScreen[bool]):
    """Deliberate confirmation; Return starts on Cancel, not the destructive button."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str, analysis_count: int) -> None:
        super().__init__()
        self.project_name = name
        self.analysis_count = analysis_count

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Delete project permanently?", classes="hero")
            yield Static(
                f"{self.project_name}\n\nThis will permanently delete {self.analysis_count} "
                f"{'analysis' if self.analysis_count == 1 else 'analyses'} and their event history. This cannot be undone.",
                markup=False,
            )
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("Delete project permanently", id="confirm-delete", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-delete")

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpDialog(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_help", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("ThinkTUI keyboard help", classes="hero")
            yield Static(
                "Tab / Shift+Tab: move focus. Enter: activate selected button or row.\n"
                "Ctrl+O: Home · Ctrl+P: Methods · Ctrl+N: New project · Esc: go back.\n"
                "Project: F2 rename analysis · Del delete analysis · Ctrl+D duplicate · Ctrl+M move.\n"
                "Forms: Ctrl+S calculate / finish · F6 Advanced JSON · Ctrl+E export.\n"
                "Guided: F7 previous · F8 or Ctrl+S validate/next · F6 Advanced JSON.\n"
                "Pairwise only: A/D choose, T tie, S skip, U undo.\n"
                "Issue tree: A child · S sibling · F fold focused branch · D asks before subtree deletion.\n"
                "Question-mark leaf labels on a Finished Issue Tree can feed Key Assumptions.\n"
                "AI: request explicitly; review text then Accept. Ctrl+G stops; numeric judgments are yours.",
                markup=False,
            )
            yield Button("Close  Esc", id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


class AnalysisDialog(ModalScreen[str | None]):
    """Rename or confirm deletion without relying on a mouse."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, label: str, *, delete: bool = False) -> None:
        super().__init__()
        self.label = label
        self.delete = delete

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Delete analysis permanently?" if self.delete else "Rename", classes="hero")
            yield Static(
                self.label + ("\nThis deletes its history too. This cannot be undone." if self.delete else ""),
                markup=False,
            )
            if not self.delete:
                yield Input(value=self.label, id="new-name")
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button(
                    "Delete analysis" if self.delete else "Save name",
                    id="confirm",
                    variant="error" if self.delete else "success",
                )

    def on_mount(self) -> None:
        self.query_one("#cancel" if self.delete else "#new-name").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.delete:
            self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(
            ("DELETE" if self.delete else self.query_one("#new-name", Input).value.strip())
            if event.button.id == "confirm"
            else None
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class DeleteBranchDialog(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Delete this branch and all descendants?", classes="hero")
            yield Static(self.label + "\nThis cannot be undone.", markup=False)
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("Delete subtree", id="confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MoveAnalysisDialog(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list[tuple[str, str]]) -> None:
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Move analysis and its history to another project?", classes="hero")
            yield Select(
                [(name, project_id) for project_id, name in self.projects], id="destination", allow_blank=False
            )
            with Horizontal(classes="actions"):
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("Move analysis", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#destination", Select).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(str(self.query_one("#destination", Select).value) if event.button.id == "confirm" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def confirm_project_deletion(screen: Base, project_id: str) -> None:
    app = screen.workbench
    try:
        project = app.store.project(project_id)
        count = len(app.store.sessions(project_id))
    except KeyError:
        app.notify("Project no longer exists", severity="error")
        app.home()
        return

    def finish(confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            app.store.delete_project(project_id)
        except (KeyError, sqlite3.Error):
            app.notify("Could not delete project; database changes were rolled back.", severity="error")
            return
        if app.session and app.session.project_id == project_id:
            app.session = None
        app.home()
        app.notify("Project deleted")

    app.push_screen(DeleteProjectDialog(project["name"], count), finish)


class Home(Base):
    BINDINGS = [
        ("n", "new", "New project"),
        ("m", "methods", "Methods"),
        ("s", "settings", "Settings"),
        ("j", "journal", "Journal"),
        ("h", "choose", "Help me choose"),
        ("d", "delete", "Delete selected"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("ThinkTUI", classes="hero")
            yield Static("Structured Thinking & Decision Toolkit\nLocal-first · AI optional", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("New project  N", id="new", variant="primary")
                yield Button("Method library  M", id="methods")
                yield Button("Settings  S", id="settings")
                yield Button("Decision journal  J", id="journal")
                yield Button("Help me choose  H", id="choose")
            yield Static("", id="review-due", classes="muted")
            yield Label("Recent work", classes="heading")
            yield Static(
                "Select a project to open · D deletes the highlighted project (with confirmation).", classes="muted"
            )
            yield Button("Delete highlighted project  D", id="delete")
            with Horizontal(classes="actions"):
                yield Input(placeholder="Import project snapshot: /path/to/backup.json", id="import-path")
                yield Button("Import snapshot", id="import_snapshot")
            yield DataTable(id="projects", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Project", "Analyses", "Updated")
        self.project_rows = []
        for row in self.workbench.store.projects():
            self.project_rows.append(row["id"])
            sessions = self.workbench.store.sessions(row["id"])
            table.add_row(
                row["name"],
                str(len(sessions)),
                max((s.updated_at[:16] for s in sessions), default=row["created_at"][:16]),
                key=row["id"],
            )
        if self.project_rows:
            table.focus()
        due = sum(
            METHODS["journal"].calculate(session.method_state)["review_due"]
            for session in self.workbench.store.sessions()
            if session.method_id == "journal"
        )
        self.query_one("#review-due", Static).update(
            f"{due} decision review(s) due · press J to open the journal" if due else "Decision reviews: none due"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.workbench.project_id = str(event.row_key.value)
        self.workbench.show_project()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        getattr(self, f"action_{event.button.id}")()

    def action_new(self) -> None:
        self.workbench.switch_screen(NewProject())

    def action_methods(self) -> None:
        self.workbench.switch_screen(Library())

    def action_settings(self) -> None:
        self.workbench.switch_screen(Settings())

    def action_journal(self) -> None:
        self.workbench.switch_screen(JournalList())

    def action_choose(self) -> None:
        self.workbench.switch_screen(PlanningScreen())

    def action_import_snapshot(self) -> None:
        path = Path(self.query_one("#import-path", Input).value).expanduser()
        if path.suffix.lower() != ".json":
            self.notify("Choose a .json snapshot file", severity="warning")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.workbench.project_id = self.workbench.store.import_snapshot(data)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            self.notify(f"Could not import snapshot: {exc}", severity="error")
            return
        self.workbench.show_project()
        self.notify("Project snapshot imported as a new project")

    def action_delete(self) -> None:
        cursor = self.query_one("#projects", DataTable).cursor_row
        if not 0 <= cursor < len(self.project_rows):
            self.notify("No project selected", severity="warning")
            return
        confirm_project_deletion(self, self.project_rows[cursor])


class NewProject(Base):
    BINDINGS = [("escape", "back", "Home")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("New project", classes="hero")
            yield Input(placeholder="Project name", id="name")
            yield Button("Create", id="create", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.create()

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.create()

    def create(self) -> None:
        try:
            self.workbench.project_id = self.workbench.store.new_project(self.query_one(Input).value)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        if self.workbench.pending_method_id:
            self.workbench.method_id = self.workbench.pending_method_id
            self.workbench.pending_method_id = None
            self.workbench.switch_screen(NewAnalysis())
        else:
            self.workbench.show_project()

    def action_back(self) -> None:
        self.workbench.home()


class ProjectView(Base):
    BINDINGS = [
        ("escape", "back", "Home"),
        ("m", "methods", "Methods"),
        ("h", "history", "History"),
        ("d", "delete", "Delete project"),
        ("delete", "delete_analysis", "Delete analysis"),
        ("f2", "rename_analysis", "Rename analysis"),
        ("ctrl+d", "duplicate_analysis", "Duplicate analysis"),
        ("ctrl+m", "move_analysis", "Move analysis"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("Project analyses", classes="hero")
            yield Label("Shared planning question", classes="heading")
            yield Input(
                value=self.workbench.store.project(self.workbench.project_id)["planning_question"],
                placeholder="What are we trying to understand or decide?",
                id="project-question",
            )
            yield Button("Save planning question", id="save-question")
            yield Static(
                "Select an analysis to resume; create another from the method library.",
                classes="muted",
            )
            with Horizontal(classes="actions"):
                yield Button("Add analysis  M", id="methods", variant="primary")
                yield Button("History  H", id="history")
                yield Button("Delete project  D", id="delete")
                yield Button("New journal entry", id="journal")
                yield Button("Plan workflow", id="plan")
            with Horizontal(classes="actions"):
                yield Input(placeholder="Export snapshot to /path/to/backup.json", id="snapshot-path")
                yield Button("Export project snapshot", id="export_snapshot")
            progress, suggested = checklist(self.workbench.store.sessions(self.workbench.project_id))
            yield Label("Planning progress · Why / Who / What / Where / When / How", classes="heading")
            yield Static("\n".join(progress), classes="muted")
            if suggested:
                yield Button("Suggested next: " + METHODS[suggested].name, id="next-step")
            yield DataTable(id="analyses", cursor_type="row")
            with Horizontal(classes="actions"):
                yield Button("Rename project", id="rename-project")
                yield Button("Rename analysis  F2", id="rename-analysis")
                yield Button("Delete analysis  Del", id="delete-analysis")
                yield Button("Duplicate analysis  Ctrl+D", id="duplicate-analysis")
                yield Button("Move analysis  Ctrl+M", id="move-analysis")

    def on_mount(self) -> None:
        self.question_timer = None
        self.question_value = self.workbench.store.project(self.workbench.project_id)["planning_question"]
        table = self.query_one(DataTable)
        table.add_columns("Analysis", "Method", "Status", "Updated")
        self.analysis_rows = []
        for session in self.workbench.store.sessions(self.workbench.project_id):
            state = session.method_state
            progress = (
                f"{state['workflow_index'] + 1}/{len(state['workflow_steps'])} · "
                + ("Finished" if session.completed_at else "Draft")
                if "workflow_steps" in state
                else "Finished"
                if session.completed_at
                else "Draft"
            )
            self.analysis_rows.append(session.id)
            table.add_row(
                session.title,
                METHODS[session.method_id].name,
                progress,
                session.updated_at[:16],
                key=session.id,
            )
        if self.analysis_rows:
            table.focus()

    def save_question(self) -> None:
        if self.question_timer is not None:
            self.question_timer.stop()
            self.question_timer = None
        editor = self.query("#project-question")
        value = editor.first().value if editor else self.question_value
        project_id = self.workbench.project_id
        if value.strip() != self.workbench.store.project(project_id)["planning_question"]:
            self.workbench.store.set_planning_question(project_id, value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "project-question":
            self.question_value = event.value
            if self.question_timer is None:
                self.question_timer = self.set_timer(0.6, self.save_question)
            else:
                self.question_timer.reset()

    def on_unmount(self) -> None:
        if self.question_timer is not None:
            self.save_question()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.save_question()
        self.workbench.open_session(self.workbench.store.load(str(event.row_key.value)), guided=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-step":
            _, suggested = checklist(self.workbench.store.sessions(self.workbench.project_id))
            if suggested:
                self.workbench.method_id = suggested
                self.workbench.switch_screen(NewAnalysis())
        elif event.button.id == "save-question":
            self.save_question()
            self.notify("Planning question saved for future analyses")
        elif event.button.id == "history":
            self.action_history()
        elif event.button.id == "rename-analysis":
            self.action_rename_analysis()
        elif event.button.id == "delete-analysis":
            self.action_delete_analysis()
        elif event.button.id == "rename-project":
            self.action_rename_project()
        elif event.button.id == "duplicate-analysis":
            self.action_duplicate_analysis()
        elif event.button.id == "move-analysis":
            self.action_move_analysis()
        elif event.button.id == "delete":
            self.action_delete()
        elif event.button.id == "journal":
            self.workbench.method_id = "journal"
            self.workbench.switch_screen(NewAnalysis())
        elif event.button.id == "plan":
            self.workbench.switch_screen(PlanningScreen())
        elif event.button.id == "export_snapshot":
            self.action_export_snapshot()
        else:
            self.action_methods()

    def selected_analysis(self) -> Session | None:
        table = self.query_one("#analyses", DataTable)
        if not 0 <= table.cursor_row < len(self.analysis_rows):
            self.notify("Select an analysis first", severity="warning")
            return None
        return self.workbench.store.load(self.analysis_rows[table.cursor_row])

    def action_rename_analysis(self) -> None:
        session = self.selected_analysis()
        if session:

            def finish(value: str | None) -> None:
                if value:
                    self.workbench.store.rename_session(session.id, value)
                    self.workbench.show_project()

            self.workbench.push_screen(AnalysisDialog(session.title), finish)

    def action_delete_analysis(self) -> None:
        session = self.selected_analysis()
        if session:

            def finish(value: str | None) -> None:
                if value == "DELETE":
                    self.workbench.store.delete_session(session.id)
                    if self.workbench.session and self.workbench.session.id == session.id:
                        self.workbench.session = None
                    self.workbench.show_project()

            self.workbench.push_screen(AnalysisDialog(session.title, delete=True), finish)

    def action_duplicate_analysis(self) -> None:
        session = self.selected_analysis()
        if session:
            self.workbench.store.duplicate_session(session.id)
            self.workbench.show_project()

    def action_move_analysis(self) -> None:
        session = self.selected_analysis()
        if not session:
            return
        targets = [
            (row["id"], row["name"]) for row in self.workbench.store.projects() if row["id"] != session.project_id
        ]
        if not targets:
            self.notify("Create another project before moving an analysis", severity="warning")
            return

        def finish(project_id: str | None) -> None:
            if project_id:
                self.workbench.store.move_session(session.id, project_id)
                self.workbench.show_project()

        self.workbench.push_screen(MoveAnalysisDialog(targets), finish)

    def action_rename_project(self) -> None:
        project_id = self.workbench.project_id

        def finish(value: str | None) -> None:
            if value:
                self.workbench.store.rename_project(project_id, value)
                self.workbench.show_project()

        self.workbench.push_screen(AnalysisDialog(self.workbench.store.project(project_id)["name"]), finish)

    def action_delete(self) -> None:
        if self.workbench.project_id:
            confirm_project_deletion(self, self.workbench.project_id)

    def action_export_snapshot(self) -> None:
        path = Path(self.query_one("#snapshot-path", Input).value).expanduser()
        if path.suffix.lower() != ".json":
            self.notify("Choose a .json filename", severity="warning")
            return
        try:
            data = self.workbench.store.snapshot(self.workbench.project_id)
            content = json.dumps(data, indent=2, ensure_ascii=False)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except (OSError, ValueError, KeyError) as exc:
            self.notify(f"Could not export snapshot: {exc}", severity="error")
            return
        self.notify(f"Project snapshot exported to {path}")

    def action_history(self) -> None:
        self.workbench.switch_screen(History())

    def action_methods(self) -> None:
        self.workbench.switch_screen(Library())

    def action_back(self) -> None:
        self.save_question()
        self.workbench.home()


class History(Base):
    """Read-only, project-scoped append-only event history."""

    BINDINGS = [("escape", "back", "Project")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("Project analysis history", classes="hero")
            yield Static(
                "Select an event to inspect saved field changes. Events before database v2 have descriptions only.",
                classes="muted",
            )
            yield DataTable(id="events", cursor_type="row")
            yield Static("Select an event for before/after details", id="event-details", markup=False)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("When (UTC)", "Analysis", "Event")
        events = [
            (event["timestamp"], session.title, event["description"], event["changes"])
            for session in self.workbench.store.sessions(self.workbench.project_id)
            for event in self.workbench.store.events(session.id)
        ]
        events.extend(
            (
                row["timestamp"],
                self.workbench.store.project(self.workbench.project_id)["name"],
                "Updated shared planning question",
                json.dumps([{"field": "planning question", "before": row["before"], "after": row["after"]}]),
            )
            for row in self.workbench.store.project_events(self.workbench.project_id)
        )
        self.displayed_events = sorted(events, reverse=True)
        for when, title, description, _ in self.displayed_events:
            table.add_row(when[:19], title, description)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.cursor_row
        if not 0 <= row < len(self.displayed_events):
            return
        changes = json.loads(self.displayed_events[row][3])

        def display(value: object) -> str:
            if isinstance(value, (dict, list)):
                return (
                    f"{len(value)} {'fields' if isinstance(value, dict) else 'entries'} (open the analysis for details)"
                )
            if isinstance(value, str):
                try:
                    return self.workbench.store.load(value).title
                except KeyError:
                    return value[:80] + ("…" if len(value) > 80 else "")
            return str(value)

        self.query_one("#event-details", Static).update(
            "\n".join(
                f"{entry['field'].replace('_', ' ')}: {display(entry.get('before'))} → {display(entry.get('after'))}"
                for entry in changes
            )
            if changes
            else "No field differences recorded."
        )

    def action_back(self) -> None:
        self.workbench.show_project()


class JournalList(Base):
    """Decision records across projects; select one to resume or review."""

    BINDINGS = [("escape", "back", "Home")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("Decision journal", classes="hero")
            yield Static("Select a decision to review. Create new entries inside a project.", classes="muted")
            yield DataTable(id="decisions", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Decision", "Chosen", "Review", "Updated")
        for session in self.workbench.store.sessions():
            if session.method_id == "journal":
                state = session.method_state
                result = METHODS["journal"].calculate(state)
                review = ("DUE · " if result["review_due"] else "") + (state.get("review_date") or "—")
                table.add_row(
                    state.get("decision") or session.title,
                    state.get("chosen", "—"),
                    review,
                    session.updated_at[:16],
                    key=session.id,
                )
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.workbench.open_session(self.workbench.store.load(str(event.row_key.value)))

    def action_back(self) -> None:
        self.workbench.home()


class Library(Base):
    BINDINGS = [("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("Method library", classes="hero")
            yield Static(
                "Search by problem, category or method. Select a method to begin; calculations stay local.",
                classes="muted",
            )
            yield Input(placeholder="Search methods (e.g. risks, forecast, rank)", id="method-search")
            yield DataTable(id="methods", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Category", "Method", "Description")
        self.refresh_methods("")
        self.query_one("#method-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "method-search":
            self.refresh_methods(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "method-search":
            self.query_one("#methods", DataTable).focus()

    def refresh_methods(self, query: str) -> None:
        table = self.query_one("#methods", DataTable)
        table.clear()
        term = query.casefold().strip()

        def order(method: object) -> tuple:
            label = method.name.casefold()
            relevance = 0 if label == term else 1 if label.startswith(term) else 2 if term in label else 3
            return (relevance if term else 0, method.category, label)

        for method in sorted(METHODS.values(), key=order):
            if term in f"{method.name} {method.category} {method.description}".casefold():
                table.add_row(method.category, method.name, method.description, key=method.id)
        if table.row_count:
            table.move_cursor(row=0)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.workbench.method_id = str(event.row_key.value)
        if self.workbench.project_id is None:
            self.workbench.pending_method_id = self.workbench.method_id
            self.notify("Create or open a project first", severity="warning")
            self.workbench.switch_screen(NewProject())
        else:
            self.workbench.switch_screen(NewAnalysis())

    def action_back(self) -> None:
        self.workbench.show_project() if self.workbench.project_id else self.workbench.home()


class NewAnalysis(Base):
    BINDINGS = [("escape", "back", "Library")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("Start " + METHODS[self.workbench.method_id].name, classes="hero")
            yield Input(placeholder="Analysis title", id="title")
            yield Input(placeholder="What are you trying to understand or decide?", id="problem")
            yield Input(placeholder="Objective (optional)", id="objective")
            yield Button("Start", id="start", variant="primary")

    def on_mount(self) -> None:
        if self.workbench.project_id:
            self.query_one("#problem", Input).value = self.workbench.store.project(self.workbench.project_id)[
                "planning_question"
            ]
        self.query_one("#title", Input).focus()

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.start()

    def start(self) -> None:
        title = self.query_one("#title", Input).value.strip()
        if not title:
            self.notify("Enter a title", severity="error")
            return
        session = Session(
            project_id=self.workbench.project_id,
            method_id=self.workbench.method_id,
            title=title,
            problem_statement=self.query_one("#problem", Input).value,
            objective=self.query_one("#objective", Input).value,
        )
        existing = {s.title.casefold() for s in self.workbench.store.sessions(self.workbench.project_id)}
        if title.casefold() in existing:
            self.notify("An analysis already has this title; choose a distinct title", severity="warning")
            return
        self.workbench.store.save(session, "Created analysis")
        self.workbench.open_session(session, guided=True)

    def action_back(self) -> None:
        self.workbench.switch_screen(Library())


class Workspace(FieldHelpMixin, Base):
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        method = self.workbench.session.method_id
        if action in {"left", "right", "skip"}:
            return method in {"pairwise", "issue_tree"}
        if action in {"tie", "undo"}:
            return method == "pairwise"
        if action in {"tree_toggle", "tree_sibling"}:
            return method == "issue_tree"
        return True

    BINDINGS = [
        ("a", "left", "Left"),
        ("d", "right", "Right"),
        ("t", "tie", "Tie"),
        ("s", "skip", "Skip"),
        ("u", "undo", "Undo"),
        ("escape", "back", "Project"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+k", "challenge", "Challenge"),
        Binding("ctrl+g", "stop_ai", "Stop AI", priority=True),
        ("ctrl+e", "export", "Export"),
        Binding("f", "tree_toggle", "Fold tree", priority=False),
        Binding("shift+enter", "tree_sibling", "Add sibling", priority=True),
    ]

    def compose(self) -> ComposeResult:
        session = self.workbench.session
        yield from self.chrome()
        with Horizontal(classes="workspace-layout"):
            with VerticalScroll(classes="editor-pane"):
                yield Label(f"{session.title}  ·  {METHODS[session.method_id].name}", classes="hero")
                yield Static(
                    session.problem_statement or "Define the question as clearly as you can.",
                    classes="muted",
                )
                if session.method_id == "pairwise":
                    yield Static(
                        "Enter one alternative per line, then compare all pairs. A/D choose, T tie, S skip, U undo.",
                        classes="muted",
                    )
                    if "ranking" not in session.method_state:
                        yield TextArea(id="items")
                        yield Button("Start comparisons", id="initialize", variant="primary")
                        yield Static("", id="results")
                    else:
                        yield Static("", id="pair")
                        with Horizontal(classes="actions"):
                            yield Button("A · Left", id="left")
                            yield Button("D · Right", id="right")
                            yield Button("T · Tie", id="tie")
                            yield Button("S · Skip", id="skip")
                            yield Button("U · Undo", id="undo")
                        yield Static("", id="results")
                else:
                    instructions = {
                        "matrix": 'Enter JSON: {"criteria":[{"name":"Value","weight":3,"direction":"benefit"}],"alternatives":[{"name":"A","scores":[8]},{"name":"B","scores":[6]}]}',
                        "assumptions": "Add one assumption at a time. Rate confidence 0–100 and impact 1–10. What would falsify it?",
                        "premortem": "Imagine it failed in 12 months. What went wrong? Add a cause and preventive action.",
                        "issue_tree": "Select a branch, type a label, Enter adds its child; Shift+Enter adds a sibling. A/S/D work on the tree; Edit changes a label; Tab folds.",
                        "journal": "Record your reasoning now; later compare the actual outcome without conflating decision quality and luck.",
                    }
                    if hasattr(METHODS[session.method_id], "example"):
                        yield Static(
                            "Structured JSON worksheet: edit the example below with your own judgments/data; "
                            "validate and save to calculate. Examples are NOT evidence and cannot be saved unchanged. "
                            + METHODS[session.method_id].description,
                            classes="muted",
                        )
                        yield TextArea(id="structured-input")
                        yield Button("Validate · Calculate · Save", id="structured-calculate", variant="primary")
                        if session.method_id in GUIDED:
                            yield Button("Guided steps", id="guided")
                    else:
                        yield Static(instructions[session.method_id], classes="muted")
                    if hasattr(METHODS[session.method_id], "example"):
                        pass  # generic workflow above replaces the method-specific editor
                    elif session.method_id == "matrix":
                        yield TextArea(id="matrix-input")
                        with Horizontal(classes="actions"):
                            yield Button("Calculate & save", id="calculate", variant="primary")
                            if (
                                not METHODS["matrix"].validate(session.method_state)
                                and len(session.method_state.get("criteria", [])) >= 2
                            ):
                                first, second = sensitivity_pair(session)
                                options = [
                                    (f"{i + 1}. {row['name']}", i)
                                    for i, row in enumerate(session.method_state["alternatives"])
                                ]
                                yield Static("Choose two options (top two ranked by default) for sensitivity.")
                                yield Select(options, value=first, allow_blank=False, id="sensitivity-first")
                                yield Select(options, value=second, allow_blank=False, id="sensitivity-second")
                            yield Button("Test sensitivity of two options", id="sensitivity")
                            yield Button("Guided steps", id="guided")
                    elif session.method_id == "journal":
                        fields = (
                            ("decision", "Decision to make"),
                            ("alternatives", "Alternatives considered"),
                            ("chosen", "Chosen option"),
                            ("expected_outcome", "Expected outcome"),
                            ("confidence", "Confidence 0–100 (optional)"),
                            ("risks", "Risks and important assumptions"),
                            ("review_date", "Review date YYYY-MM-DD"),
                            ("actual_outcome", "Actual outcome (at review)"),
                            ("lessons", "Lessons learned (at review)"),
                        )
                        for field, hint in fields:
                            yield Label(hint, classes="heading")
                            yield Input(
                                value=str(session.method_state.get(field, "")), placeholder=hint, id=f"journal-{field}"
                            )
                        yield Label("Rationale · Why this choice?", classes="heading")
                        yield TextArea(str(session.method_state.get("rationale", "")), id="journal-rationale")
                        yield Button("Save decision record", id="journal-save", variant="primary")
                    elif session.method_id == "issue_tree":
                        yield Static(
                            "Add a '?' at the end of a leaf question to offer it to Key Assumptions. Enter adds a child; S adds a sibling (Shift+Enter may not work in every terminal). F folds when the tree is focused; Tab moves focus.",
                            classes="muted",
                        )
                        yield Input(placeholder="Branch label (select a row for child/sibling/edit)", id="entry")
                        with Horizontal(classes="actions"):
                            yield Button("Add root", id="tree-root")
                            yield Button("A · Add child", id="tree-child")
                            yield Button("S · Add sibling", id="tree-sibling")
                            yield Button("Edit label", id="tree-edit")
                            yield Button("D · Delete subtree (confirm)", id="tree-delete")
                            yield Button("F · Fold / unfold", id="tree-toggle")
                        yield DataTable(id="tree", cursor_type="row")
                    else:
                        yield Label("Ranked entries · local risk priority", classes="heading")
                        yield DataTable(id="entry-list", cursor_type="row")
                        with Horizontal(classes="actions"):
                            yield Button("Calculate · refresh ranking", id="calculate-entries")
                            yield Button("Edit selected entry", id="edit-entry")
                            yield Button("Delete selected entry", id="delete-entry")
                        if session.method_id == "assumptions":
                            suggestions = offers(
                                "assumptions", self.workbench.store.sessions(session.project_id), session.id
                            )
                            if suggestions:
                                yield Static(
                                    "Earlier issue-tree questions (labels only): "
                                    + "; ".join(suggestions["statements"]),
                                    classes="muted",
                                )
                                yield Button("Use next issue-tree question", id="use-issue-offer")
                        yield Label(
                            "Assumption" if session.method_id == "assumptions" else "Possible failure",
                            classes="heading",
                        )
                        yield Static(
                            "Describe one testable claim or failure. Why: this is what you will review or prevent.",
                            classes="muted",
                        )
                        with Horizontal(classes="field-editor"):
                            yield Input(placeholder="Assumption / failure mode", id="entry")
                            yield Button(
                                "Draft text",
                                id="help-entry",
                                classes="ai-trigger",
                                tooltip="Draft text for this statement",
                            )
                            yield Button(
                                "Suggest rows",
                                id="help-rows",
                                classes="ai-trigger",
                                tooltip="Suggest several statement rows for review",
                            )
                            if session.method_id == "assumptions":
                                yield Button(
                                    "Suggest one",
                                    id="suggest",
                                    classes="ai-trigger",
                                    tooltip="Suggest one assumption for review in the AI panel",
                                )
                        yield Label("Test or prevention", classes="heading")
                        yield Static(
                            "Describe what to test or prevent. Why: a useful risk needs a response.", classes="muted"
                        )
                        with Horizontal(classes="field-editor"):
                            yield Input(placeholder="Validation test / preventive action (optional)", id="action")
                            yield Button(
                                "Draft text", id="help-action", classes="ai-trigger", tooltip="Draft action text"
                            )
                        yield Label(
                            "Confidence (0–100)" if session.method_id == "assumptions" else "Likelihood (0–100)",
                            classes="heading",
                        )
                        yield Static(
                            "Your rating, 0–100. Why: likelihood or confidence changes which risks to test first.",
                            classes="muted",
                        )
                        yield Input(id="confidence", type="integer", placeholder="Your rating, 0–100")
                        yield Label("Impact (1–10)", classes="heading")
                        yield Static(
                            "Your rating, 1–10. Why: larger consequences need closer attention.", classes="muted"
                        )
                        yield Input(id="impact", type="integer", placeholder="Your rating, 1–10")
                        yield Static("", id="dedicated-feedback", classes="muted")
                        yield Button("Add / save entry", id="add", variant="primary")
                        yield Button("Use next accepted row", id="next-draft-row")
                    yield Static("", id="results")
                yield Label("What would change your mind?", classes="heading")
                with Horizontal(classes="field-editor"):
                    yield Input(value=session.method_state.get("change_mind", ""), id="change-mind")
                    if session.method_id in {"assumptions", "premortem"}:
                        yield Button(
                            "Draft text",
                            id="help-change-mind",
                            classes="ai-trigger",
                            tooltip="Draft a change-of-mind observation",
                        )
                if session.method_id in {"assumptions", "premortem"}:
                    yield Static(
                        "What new observation would change this assessment? Why: it makes review actionable.",
                        classes="muted",
                    )
                with Horizontal(classes="actions"):
                    yield Button("Export  Ctrl+E", id="export")
                    yield Button("Challenge  Ctrl+K", id="challenge")
                    yield Button("Stop AI  Ctrl+G", id="stop-ai", disabled=True)
                    yield Button("Mark finished", id="finish-stage")
                    yield Button(
                        "Continue planned workflow" if planned_next(session) else "Recommended next method", id="plan"
                    )
                yield Input(placeholder="Export path: ~/decision.md or ~/decision.json", id="export-path")
            with VerticalScroll(classes="ai-pane"):
                yield Label("AI workspace", classes="heading")
                yield Static(
                    "REMOTE → selected provider unless local. Sharing on request: method, problem, objective, assumptions and full method state; not notes/history.",
                    classes="muted",
                )
                yield Static(
                    "AI: " + status_label(self.workbench.store) + " · context shared only on request", classes="muted"
                )
                yield AIStatus("", id="ai-status")
                yield Static("", id="ai-response")
                if session.method_id == "assumptions":
                    yield Input(placeholder="Edit proposed assumption before accepting", id="suggestion")
                    with Horizontal(classes="ai-actions"):
                        yield Button("Accept", id="accept")
                        yield Button("Dismiss", id="dismiss")
                if session.method_id in {"assumptions", "premortem"}:
                    yield Static(
                        "Text-only draft · edit before Accept; you supply every numeric rating.", classes="muted"
                    )
                    yield Static("", id="field-help-status", classes="muted")
                    yield TextArea(id="field-help-preview")
                    with Horizontal(classes="ai-actions"):
                        yield Button("Accept", id="help-accept")
                        yield Button("Dismiss", id="help-dismiss")
                        yield Button("Stop  Ctrl+G", id="help-stop")

    def on_resize(self) -> None:
        self.query_one(".workspace-layout").set_class(self.size.width < 100, "narrow")

    def on_mount(self) -> None:
        self.on_resize()
        self.refresh_bindings()
        session = self.workbench.session
        self.journal_timer = None
        self.tree_editing: str | None = None
        self.tree_rows: list[str] = []
        self.pending_ai_rows: list[str] = list(session.method_state.get("_text_row_drafts", []))
        self.accepted_draft = False
        self.editing_entry_index: int | None = None
        if self.pending_ai_rows and session.method_id in {"assumptions", "premortem"}:
            self.query_one("#entry", Input).value = self.pending_ai_rows[0]
            self.accepted_draft = True
        if session.method_id == "issue_tree":
            self.query_one("#tree", DataTable).add_column("Issue branches")
        if session.method_id in {"assumptions", "premortem"}:
            self.query_one("#entry-list", DataTable).add_columns("Statement", "Risk priority", "Action")
        if session.method_id == "matrix":
            self.query_one("#matrix-input", TextArea).load_text(
                json.dumps(session.method_state, indent=2) if session.method_state else ""
            )
        elif hasattr(METHODS[session.method_id], "example"):
            method = METHODS[session.method_id]
            state = session.method_state
            metadata = {key: value for key, value in state.items() if key.startswith("workflow_")}
            worksheet = {**method.example, **metadata} if not state or len(state) == len(metadata) else state
            self.query_one("#structured-input", TextArea).load_text(json.dumps(worksheet, indent=2, ensure_ascii=False))
        self.refresh_results()

    def persist(self, description: str) -> None:
        self.workbench.store.save(self.workbench.session, description)

    def field_help_session(self) -> Session:
        return self.workbench.session

    def apply_field_help(self, target: str, text: str, rows: bool) -> None:
        if self.workbench.session.method_id not in {"assumptions", "premortem"}:
            return
        if rows and target == "entries":
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                return
            self.pending_ai_rows.extend(lines)
            self.workbench.session.method_state["_text_row_drafts"] = list(self.pending_ai_rows)
            self.persist("Accepted text-only row drafts")
            if not self.query_one("#entry", Input).value.strip():
                self.query_one("#entry", Input).value = self.pending_ai_rows[0]
                self.accepted_draft = True
            self.query_one("#confidence", Input).value = ""
            self.query_one("#impact", Input).value = ""
            return
        if target in {"entry", "action", "change-mind"}:
            self.query_one(f"#{target}", Input).value = text
            if target == "entry":
                self.accepted_draft = True

    def dedicated_feedback(self) -> None:
        if self.workbench.session.method_id not in {"assumptions", "premortem"}:
            return
        targets = self.query("#dedicated-feedback")
        if not targets or len(self.query("#entry, #confidence, #impact")) != 3:
            return
        statement = self.query_one("#entry", Input).value.strip()
        confidence = self.query_one("#confidence", Input).value.strip()
        impact = self.query_one("#impact", Input).value.strip()
        message = "Describe the assumption or failure mode." if not statement else ""
        for raw, label, minimum, maximum in (
            (confidence, "Confidence / likelihood", 0, 100),
            (impact, "Impact", 1, 10),
        ):
            if raw:
                try:
                    value = int(raw)
                    if not minimum <= value <= maximum:
                        raise ValueError
                except ValueError:
                    message = f"{label}: enter your own whole number from {minimum} to {maximum}."
                    break
        if not message and confidence and impact:
            score = (
                (1 - int(confidence) / 100) * int(impact)
                if self.workbench.session.method_id == "assumptions"
                else int(confidence) * int(impact)
            )
            message = f"Local risk priority preview: {score:g}. Your ratings are not set by AI."
        targets.first().update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("journal-"):
            self.workbench.session.method_state[event.input.id.removeprefix("journal-")] = event.value
            self.schedule_journal_save()
        elif event.input.id == "change-mind":
            state = self.workbench.session.method_state
            if state.get("change_mind", "") != event.value:
                state["change_mind"] = event.value
                self.schedule_journal_save()
        elif event.input.id in {"entry", "action", "confidence", "impact"}:
            self.dedicated_feedback()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "journal-rationale":
            self.workbench.session.method_state["rationale"] = event.text_area.text
            self.schedule_journal_save()

    def schedule_journal_save(self) -> None:
        if self.journal_timer is None:
            self.journal_timer = self.set_timer(0.5, self.flush_journal)
        else:
            self.journal_timer.reset()

    def flush_journal(self) -> None:
        if self.journal_timer is not None:
            self.journal_timer.stop()
            self.journal_timer = None
            self.persist("Updated editor fields")
            self.refresh_results()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "entry" and self.workbench.session.method_id == "issue_tree":
            self.tree_action("child" if self.selected_tree_node() else "root")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "tree":
            # Selection changes the target, never replaces a drafted label.
            self.tree_editing = None

    def selected_tree_node(self) -> dict | None:
        table = self.query_one("#tree", DataTable)
        index = table.cursor_row
        if not 0 <= index < len(self.tree_rows):
            return None
        return next(
            (
                node
                for node, _ in tree_visible(self.workbench.session.method_state)
                if node["id"] == self.tree_rows[index]
            ),
            None,
        )

    def refresh_tree(self, selected_id: str | None = None) -> None:
        table = self.query_one("#tree", DataTable)
        rows = tree_visible(self.workbench.session.method_state)
        if selected_id is None and 0 <= table.cursor_row < len(self.tree_rows):
            selected_id = self.tree_rows[table.cursor_row]
        table.clear()
        self.tree_rows = [node["id"] for node, _ in rows]
        for node, depth in rows:
            has_children = any(child["parent_id"] == node["id"] for child, _ in rows)
            marker = "▸" if node.get("collapsed") else "▾" if has_children else "·"
            table.add_row(f"{'  ' * depth}{marker} {node['label']}", key=node["id"])
        if self.tree_rows:
            table.move_cursor(row=self.tree_rows.index(selected_id) if selected_id in self.tree_rows else 0)

    def tree_action(self, operation: str) -> None:
        if self.workbench.session.method_id != "issue_tree":
            return
        state = self.workbench.session.method_state
        node = self.selected_tree_node()
        label_input = self.query_one("#entry", Input)
        label = label_input.value
        try:
            if operation == "root":
                selected = tree_add(state, label)
            elif operation in {"child", "sibling"}:
                if node is None:
                    raise ValueError("Select a branch first (or add a root)")
                selected = tree_add(
                    state,
                    label,
                    parent_id=node["id"] if operation == "child" else node["parent_id"],
                    after_id=None if operation == "child" else node["id"],
                )
                if operation == "child" and node.get("collapsed"):
                    tree_toggle(state, node["id"])
            elif operation == "edit":
                if node is None:
                    raise ValueError("Select a branch first")
                tree_edit(state, node["id"], label)
                selected = node["id"]
            elif operation == "toggle":
                if node is None:
                    return
                tree_toggle(state, node["id"])
                selected = node["id"]
            elif operation == "delete":
                if node is None:
                    return
                selected_id = node["id"]

                def finish(confirmed: bool) -> None:
                    if confirmed:
                        tree_delete(state, selected_id)
                        self.persist("Issue tree: deleted subtree")
                        self.refresh_tree()

                self.workbench.push_screen(DeleteBranchDialog(node["label"]), finish)
                return
            else:
                return
        except (ValueError, KeyError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.tree_editing = None
        label_input.value = ""
        self.persist(f"Issue tree: {operation}")
        self.refresh_tree(selected)
        if operation in {"root", "child", "sibling"}:
            label_input.focus()
        else:
            self.query_one("#tree", DataTable).focus()

    def action_tree_sibling(self) -> None:
        if self.workbench.session.method_id == "issue_tree" and self.query_one("#entry", Input).has_focus:
            self.tree_action("sibling")

    def refresh_entry_list(self, ranked: list[dict]) -> None:
        table = self.query_one("#entry-list", DataTable)
        table.clear()
        entries = self.workbench.session.method_state.get("entries", [])
        for row in ranked:
            index = next(i for i, entry in enumerate(entries) if entry is row)
            risk = (
                (1 - row.get("confidence", 50) / 100) * row.get("impact", 5)
                if self.workbench.session.method_id == "assumptions"
                else row.get("likelihood", 0) * row.get("impact", 0)
            )
            table.add_row(row["statement"], f"{risk:g}", row.get("action") or "—", key=str(index))

    def selected_entry_index(self) -> int | None:
        table = self.query_one("#entry-list", DataTable)
        if not 0 <= table.cursor_row < table.row_count:
            return None
        index = int(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return index if index < len(self.workbench.session.method_state.get("entries", [])) else None

    def refresh_results(self) -> None:
        session = self.workbench.session
        state = session.method_state
        output = self.query_one("#results", Static)
        if session.method_id == "pairwise" and "ranking" in state:
            project = Project.from_dict(state["ranking"])
            pair = next_pair(project)
            names = {item.id: item.name for item in project.items}
            self.query_one("#pair", Static).update(
                f"{names[pair[0]]}   vs   {names[pair[1]]}  ·  {project.total - project.remaining}/{project.total}"
                if pair
                else "All comparisons complete. Reopen to review results."
            )
            rows = METHODS["pairwise"].calculate(state)["ranking"]
            output.update(
                "\n".join(
                    f"{r['rank']}. {r['name']}  {r['score']:.1f}  W{r['wins']} L{r['losses']} T{r['ties']}"
                    for r in rows
                )
            )
        elif session.method_id == "issue_tree":
            self.refresh_tree()
        elif session.method_id == "assumptions":
            rows = METHODS["assumptions"].calculate(state)["priorities"]
            self.refresh_entry_list(rows)
            output.update(
                "\n".join(
                    f"{i}. {r['statement']} · risk {(1 - r.get('confidence', 50) / 100) * r.get('impact', 5):g} · {r.get('confidence', 50)}% confidence · "
                    f"impact {r.get('impact', 5)}/10 · "
                    f"{'TEST FIRST' if r.get('confidence', 50) < 50 and r.get('impact', 5) >= 6 else 'Review'}"
                    f" · Test: {r.get('action') or 'not defined'}"
                    for i, r in enumerate(rows, 1)
                )
            )
        elif session.method_id == "premortem":
            rows = METHODS["premortem"].calculate(state)["risks"]
            self.refresh_entry_list(rows)
            output.update(
                "\n".join(
                    f"{i}. {r['statement']} · likelihood {r.get('likelihood', 1)}% · "
                    f"impact {r.get('impact', 1)}/10 · priority {r.get('likelihood', 1) * r.get('impact', 1)}"
                    f" · Prevent: {r.get('action') or 'not defined'}"
                    for i, r in enumerate(rows, 1)
                )
            )
        elif session.method_id == "journal":
            result = METHODS["journal"].calculate(state)
            status = "REVIEW DUE" if result["review_due"] else result["status"]
            output.update(
                f"{status} · Chosen: {state.get('chosen') or 'not set'} · "
                f"Review: {state.get('review_date') or 'not set'}\n"
                "Decision quality and outcome quality are different; review the rationale after resolution."
            )
        elif session.method_id == "matrix" and state.get("criteria"):
            try:
                output.update(json.dumps(METHODS["matrix"].calculate(state), indent=2))
            except ValueError as exc:
                output.update(str(exc))
        elif hasattr(METHODS[session.method_id], "example"):
            if state and any(key != "change_mind" for key in state):
                if session.method_id == "monte_carlo":
                    output.update("Running deterministic simulation…")
                    self.run_worker(self.compute_simulation(state, save=False), group="simulation", exclusive=True)
                    return
                try:
                    result = METHODS[session.method_id].calculate(state)
                    output.update(
                        "Calculated locally · user-supplied inputs\n" + json.dumps(result, ensure_ascii=False, indent=2)
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    output.update("Saved input needs review: " + str(exc))
            else:
                output.update("Draft · replace the example and calculate to save.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        if action in {"left", "right", "tie", "skip", "undo"}:
            self.compare(action)
        elif action == "initialize":
            names = [s.strip() for s in self.query_one("#items", TextArea).text.splitlines() if s.strip()]
            try:
                project = create_project(self.workbench.session.title, [Item(name=n) for n in names])
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            self.workbench.session.method_state["ranking"] = project.to_dict()
            self.persist("Created pairwise comparison set")
            self.workbench.open_session(self.workbench.session)
        elif action in {"calculate", "structured-calculate"}:
            try:
                method = METHODS[self.workbench.session.method_id]
                field = "#matrix-input" if action == "calculate" else "#structured-input"
                state = json.loads(self.query_one(field, TextArea).text)
                if not isinstance(state, dict):
                    raise ValueError("Input must be a JSON object")
                saved = self.workbench.session.method_state
                prior_matrix = (saved.get("criteria"), saved.get("alternatives")) if method.id == "matrix" else None
                links = ("source_session_id", "workflow_id", "workflow_goal", "workflow_steps", "workflow_index")
                if any(key in saved and state.get(key) != saved[key] for key in links):
                    raise ValueError(
                        "Preserve source/workflow links in advanced JSON; create an independent analysis to detach"
                    )
                if (
                    action == "structured-calculate"
                    and {
                        key: value
                        for key, value in state.items()
                        if key != "change_mind" and not key.startswith("workflow_")
                    }
                    == method.example
                ):
                    raise ValueError("Replace the illustrative example with your own input before saving")
                if method.id == "monte_carlo":
                    self.query_one("#results", Static).update("Running deterministic simulation…")
                    self.run_worker(self.compute_simulation(state, save=True), group="simulation", exclusive=True)
                    return
                issues = method.validate(state)
                if issues:
                    raise ValueError(" ".join(issues))
                state["change_mind"] = self.workbench.session.method_state.get("change_mind", "")
                self.workbench.session.method_state = state
                if planned_next(self.workbench.session) or "workflow_id" in state:
                    self.workbench.session.completed_at = timestamp()
                self.persist("Calculated " + method.name)
                if method.id == "matrix" and prior_matrix != (state.get("criteria"), state.get("alternatives")):
                    self.workbench.open_session(self.workbench.session)
                else:
                    self.refresh_results()
            except (ValueError, TypeError) as exc:
                self.notify(str(exc), severity="error")
        elif action.startswith("tree-"):
            self.tree_action(action.removeprefix("tree-"))
        elif action == "sensitivity":
            self.start_sensitivity()
        elif action == "guided":
            self.workbench.open_session(self.workbench.session, guided=True)
        elif action == "finish-stage":
            issues = METHODS[self.workbench.session.method_id].validate(self.workbench.session.method_state)
            if issues:
                self.notify(" ".join(issues), severity="error")
                return
            self.flush_journal()
            self.workbench.session.completed_at = timestamp()
            self.persist("Finished workflow step")
            self.notify("Analysis marked Finished")
        elif action == "plan":
            self.flush_journal()
            self.workbench.switch_screen(PlanningScreen(self.workbench.session))
        elif action == "journal-save":
            self.flush_journal()
            issues = METHODS["journal"].validate(self.workbench.session.method_state)
            if issues:
                self.notify(" ".join(issues), severity="warning")
            else:
                self.workbench.session.completed_at = timestamp()
                self.persist("Saved decision record")
                self.notify("Decision journal saved")
        elif action == "use-issue-offer":
            suggestions = offers(
                "assumptions",
                self.workbench.store.sessions(self.workbench.session.project_id),
                self.workbench.session.id,
            )
            existing = {row.get("statement") for row in self.workbench.session.method_state.get("entries", [])}
            candidate = next((label for label in suggestions.get("statements", []) if label not in existing), None)
            if candidate:
                self.query_one("#entry", Input).value = candidate
                self.query_one("#confidence", Input).focus()
                self.notify("Enter your own confidence and impact before adding")
        elif action == "add":
            self.add_entry()
        elif action == "calculate-entries":
            self.refresh_results()
            self.notify("Risk priorities calculated locally")
        elif action == "edit-entry":
            index = self.selected_entry_index()
            if index is not None:
                row = self.workbench.session.method_state["entries"][index]
                self.editing_entry_index = index
                self.query_one("#entry", Input).value = row["statement"]
                self.query_one("#action", Input).value = row.get("action", "")
                self.query_one("#confidence", Input).value = str(
                    row.get("confidence" if self.workbench.session.method_id == "assumptions" else "likelihood", "")
                )
                self.query_one("#impact", Input).value = str(row.get("impact", ""))
                self.query_one("#entry", Input).focus()
        elif action == "delete-entry":
            index = self.selected_entry_index()
            if index is not None:
                row = self.workbench.session.method_state["entries"][index]

                def finish(value: str | None) -> None:
                    if value == "DELETE":
                        self.workbench.session.method_state["entries"].pop(index)
                        self.editing_entry_index = None
                        self.persist("Deleted entry")
                        self.refresh_results()

                self.workbench.push_screen(AnalysisDialog(row["statement"], delete=True), finish)
        elif action == "export":
            self.action_export()
        elif action == "challenge":
            self.action_challenge()
        elif action == "stop-ai":
            self.action_stop_ai()
        elif action == "next-draft-row":
            if self.pending_ai_rows:
                self.query_one("#entry", Input).value = self.pending_ai_rows[0]
                self.query_one("#confidence", Input).value = ""
                self.query_one("#impact", Input).value = ""
                self.accepted_draft = True
            else:
                self.notify("No accepted row drafts waiting")
        elif action in {"help-entry", "help-action", "help-change-mind", "help-rows"}:
            target = action.removeprefix("help-")
            if target == "rows":
                self.field_help_request(
                    "assumptions" if self.workbench.session.method_id == "assumptions" else "failure modes",
                    "entries",
                    rows=True,
                )
            else:
                self.field_help_request(
                    {
                        "entry": "a testable assumption or possible failure",
                        "action": "a validation test or preventive action",
                        "change-mind": "what would change your mind",
                    }[target],
                    target,
                )
        elif action == "help-accept":
            self.field_help_accept()
        elif action == "help-dismiss":
            self.field_help_dismiss()
        elif action == "help-stop":
            self.field_help_stop()
        elif action == "suggest":
            self.request_ai("suggest")
        elif action == "accept":
            suggestion = self.query_one("#suggestion", Input)
            if suggestion.value.strip():
                self.query_one("#entry", Input).value = suggestion.value.strip()
                if self.add_entry(source="AI_ACCEPTED"):
                    suggestion.value = ""
                    self.query_one("#ai-response", Static).update("Accepted as user-approved assumption.")
        elif action == "dismiss":
            self.query_one("#suggestion", Input).value = ""
            self.query_one("#ai-response", Static).update("Suggestion dismissed; no data changed.")

    def start_sensitivity(self) -> None:
        try:
            selectors = self.query("#sensitivity-first")
            pair = (
                (
                    self.query_one("#sensitivity-first", Select).value,
                    self.query_one("#sensitivity-second", Select).value,
                )
                if selectors
                else None
            )
            analysis = sensitivity_from_matrix(self.workbench.session, pair)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.workbench.store.save(analysis, "Created sensitivity analysis from " + self.workbench.session.id)
        self.workbench.open_session(analysis, guided=True)
        self.notify("Copied matrix judgments; change the varied criterion and range to explore tradeoffs")

    async def compute_simulation(self, state: dict, *, save: bool) -> None:
        session = self.workbench.session
        try:
            result = await asyncio.to_thread(METHODS["monte_carlo"].calculate, state)
        except (ValueError, KeyError, TypeError) as exc:
            if self.is_mounted:
                self.query_one("#results", Static).update("Simulation needs review: " + str(exc))
            return
        if not self.is_mounted or self.workbench.session is not session:
            return
        if save:
            state["change_mind"] = session.method_state.get("change_mind", "")
            session.method_state = state
            self.persist("Calculated Monte Carlo Simulation")
        self.query_one("#results", Static).update(
            "Calculated locally · user-supplied inputs\n" + json.dumps(result, indent=2, ensure_ascii=False)
        )

    def add_entry(self, source: str = "USER") -> bool:
        statement = self.query_one("#entry", Input).value.strip()
        if not statement:
            self.notify("Enter a statement", severity="error")
            return False
        try:
            raw_confidence = self.query_one("#confidence", Input).value.strip()
            raw_impact = self.query_one("#impact", Input).value.strip()
            if not raw_confidence or not raw_impact:
                raise ValueError("Enter your own likelihood/confidence and impact; no defaults are assumed")
            confidence = int(raw_confidence)
            impact = int(raw_impact)
            if not 0 <= confidence <= 100 or not 1 <= impact <= 10:
                raise ValueError("Confidence must be 0–100; impact 1–10")
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return False
        if self.accepted_draft and source == "USER":
            source = "AI_ACCEPTED"
        entries = self.workbench.session.method_state.setdefault("entries", [])
        row = {
            "statement": statement,
            "action": self.query_one("#action", Input).value,
            "confidence": confidence,
            "likelihood": confidence,
            "impact": impact,
            "source": source
            if self.editing_entry_index is None
            else entries[self.editing_entry_index].get("source", "USER"),
        }
        if self.editing_entry_index is None:
            entries.append(row)
        else:
            entries[self.editing_entry_index] = row
            self.editing_entry_index = None
        if self.accepted_draft and self.pending_ai_rows:
            self.pending_ai_rows.pop(0)
            if self.pending_ai_rows:
                self.workbench.session.method_state["_text_row_drafts"] = list(self.pending_ai_rows)
            else:
                self.workbench.session.method_state.pop("_text_row_drafts", None)
        self.persist("Saved " + source + " entry")
        self.query_one("#entry", Input).value = ""
        self.query_one("#action", Input).value = ""
        self.query_one("#confidence", Input).value = ""
        self.query_one("#impact", Input).value = ""
        self.accepted_draft = False
        if self.pending_ai_rows:
            self.query_one("#entry", Input).value = self.pending_ai_rows[0]
            self.accepted_draft = True
        self.refresh_results()
        return True

    def compare(self, action: str) -> None:
        session = self.workbench.session
        project = Project.from_dict(session.method_state["ranking"])
        pair = next_pair(project)
        if action == "undo":
            try:
                undo(project)
            except ValueError as exc:
                self.notify(str(exc))
                return
        elif pair is None:
            return
        elif action == "skip":
            skip(project, pair)
        else:
            decide(
                project,
                pair,
                {"left": Outcome.A_WINS, "right": Outcome.B_WINS, "tie": Outcome.TIE}[action],
            )
        session.method_state["ranking"] = project.to_dict()
        if not project.remaining:
            session.completed_at = timestamp()
        else:
            session.completed_at = None
        self.persist("Pairwise: " + action)
        self.refresh_results()

    def action_save(self) -> None:
        self.flush_journal()
        self.persist("Manual save")
        self.notify("Saved")

    def action_export(self) -> None:
        self.flush_journal()
        path = self.query_one("#export-path", Input).value.strip()
        if not path:
            self.notify("Enter an export path (.md or .json)", severity="warning")
            self.query_one("#export-path", Input).focus()
            return
        try:
            export(self.workbench.session, Path(path).expanduser(), store=self.workbench.store)
            self.notify(f"Exported {path}")
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error")

    def action_left(self) -> None:
        if self.workbench.session.method_id == "issue_tree":
            self.tree_action("child")
        elif self.workbench.session.method_id == "pairwise" and "ranking" in self.workbench.session.method_state:
            self.compare("left")

    def action_right(self) -> None:
        if self.workbench.session.method_id == "issue_tree":
            self.tree_action("delete")
        elif self.workbench.session.method_id == "pairwise" and "ranking" in self.workbench.session.method_state:
            self.compare("right")

    def action_tie(self) -> None:
        if self.workbench.session.method_id == "pairwise" and "ranking" in self.workbench.session.method_state:
            self.compare("tie")

    def action_skip(self) -> None:
        if self.workbench.session.method_id == "issue_tree":
            self.tree_action("sibling")
        elif self.workbench.session.method_id == "pairwise" and "ranking" in self.workbench.session.method_state:
            self.compare("skip")

    def action_tree_toggle(self) -> None:
        if (
            self.workbench.session.method_id == "issue_tree"
            and self.query_one("#tree", DataTable).has_focus
            and self.selected_tree_node()
        ):
            self.tree_action("toggle")
        else:
            self.focus_next()

    def action_undo(self) -> None:
        if self.workbench.session.method_id == "pairwise" and "ranking" in self.workbench.session.method_state:
            self.compare("undo")

    def action_challenge(self) -> None:
        self.request_ai("challenge")

    def request_ai(self, mode: str) -> None:
        if selected_provider(self.workbench.store) == "off":
            self.notify("AI is off; choose a provider in Settings", severity="warning")
            return
        if self.query_one(AIStatus).running:
            self.notify("AI is still working on the last request (Ctrl+G stops it)", severity="warning")
            return
        self.ai_partial = ""
        self.query_one("#ai-response", Static).update("")
        self.ai_busy(True)
        self.query_one(AIStatus).start("AI", "connecting to provider")
        self.run_worker(self.ask_ai(mode), exclusive=True, group="ai")

    def ai_busy(self, busy: bool) -> None:
        """Disable request buttons while a request runs; Stop is only useful then."""
        for button in self.query("#challenge, #suggest").results(Button):
            button.disabled = busy
        self.query_one("#stop-ai", Button).disabled = not busy

    def action_stop_ai(self) -> None:
        if self.workbench.session.method_id in {"assumptions", "premortem"}:
            self.field_help_stop()
        if not any(w.group == "ai" and w.is_running for w in self.workers):
            return
        self.workers.cancel_group(self, "ai")
        self.ai_busy(False)
        self.query_one(AIStatus).finish("■ AI request stopped")
        partial = visible_text(getattr(self, "ai_partial", "")).strip()
        self.query_one("#ai-response", Static).update(
            "Your analysis is preserved."
            + (f"\nPartial answer (not saved or accepted):\n{text_only(partial)}" if partial else "")
        )

    async def ask_ai(self, mode: str) -> None:
        try:
            await self._ask_ai(mode)
        finally:
            self.ai_busy(False)

    async def _ask_ai(self, mode: str) -> None:
        store = self.workbench.store
        response = self.query_one("#ai-response", Static)
        status = self.query_one(AIStatus)
        question = (
            "Suggest ONE testable missing assumption. Return ONLY a JSON object "
            'with a string field named "statement". No invented evidence.'
            if mode == "suggest"
            else "Challenge this analysis: identify weak assumptions, missing alternatives "
            "and disconfirming tests. Do not choose for me."
        )
        try:
            provider, config = await connect(store)
            # Local endpoints keep data on this machine; anything else needs explicit consent.
            if not remote_consent(store, config):
                status.finish("AI request not sent")
                self.notify(
                    f"Review AI privacy and consent in Settings before sending data to {config.preset.label}",
                    severity="warning",
                )
                return
            label = describe(config)
            self.notify(f"Asking {label}…", timeout=3)
            status.set_phase("checking model", label)
            status.set_phase(await provider.preparing_note() or "waiting for first response")
            response.update(
                f"{sharing_destination(config)} · Sharing: method, problem, objective, assumptions, method state (not notes or history)."
            )
            async for chunk in provider.stream(AIRequest(question, context_for(self.workbench.session))):
                self.ai_partial += chunk
                words = len(visible_text(self.ai_partial).split())
                status.set_phase(f"receiving answer · {words} words")
                if mode != "suggest":
                    response.update(
                        "AI suggestion (streaming · not saved):\n" + text_only(visible_text(self.ai_partial))
                    )
        except (RuntimeError, KeyError) as exc:
            status.finish("✗ AI request failed")
            response.update(f"AI unavailable: {exc}. Your analysis is preserved.")
            return
        answer = visible_text(self.ai_partial).strip()
        if mode == "suggest":
            try:
                statement = parse_json_object(answer)["statement"]
                if not isinstance(statement, str):
                    raise ValueError("Empty suggestion")
                statement = text_only(statement)
                if not statement:
                    raise ValueError("Empty suggestion")
            except (ValueError, KeyError, TypeError):
                status.finish("✗ AI reply was not usable")
                response.update("AI returned an invalid suggestion. No data changed.")
                return
            self.query_one("#suggestion", Input).value = statement
            status.finish(f"✓ Suggestion received from {label}")
            response.update("AI-suggested only · edit, accept or dismiss below. Not yet part of analysis.")
        elif not answer:
            status.finish(f"✗ {label} returned an empty answer")
            response.update("Your analysis is preserved.")
        else:
            status.finish(f"✓ Answer received from {label}")
            response.update("AI suggestion (not saved or accepted):\n" + text_only(answer))

    def action_back(self) -> None:
        self.flush_journal()
        self.workbench.show_project()


class Settings(Base):
    BINDINGS = [
        ("escape", "back", "Home"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+r", "refresh_models", "Refresh models"),
        ("ctrl+t", "test", "Test connection"),
        ("ctrl+l", "sign_in", "Sign in"),
    ]

    def compose(self) -> ComposeResult:
        store = self.workbench.store
        yield from self.chrome()
        with VerticalScroll(classes="page"):
            yield Label("AI settings", classes="hero")
            yield Static(
                "AI is optional. Local calculations stay local. AI receives only selected analysis context, and only when you ask. "
                "API keys are kept in your OS keyring (or for this session only), never in the database or exports. "
                "Never put secrets in analysis fields.",
                classes="muted",
            )
            yield Label("Provider", classes="heading")
            yield Select(
                [("Auto — local Ollama when running", "auto")] + [(p.label, p.id) for p in PRESETS.values()],
                value=selected_provider(store),
                id="provider",
                allow_blank=False,
            )
            yield Static("", id="provider-note", classes="muted")
            with Vertical(id="connection"):
                with Vertical(id="url-box"):
                    yield Label("Base URL", classes="heading")
                    yield Input(placeholder="https://…/v1", id="base-url")
                yield Label("Model", classes="heading")
                yield Input(placeholder="Model id (blank = provider default / first installed)", id="model")
                yield Select([], prompt="Available models (Ctrl+R to refresh)", id="models")
                yield Static("", id="models-status", classes="muted")
                with Vertical(id="key-box"):
                    yield Label("API key", classes="heading")
                    yield Static("", id="key-status", classes="muted")
                    yield Input(password=True, placeholder="Paste a new API key, then Save", id="api-key")
                    yield Checkbox(
                        "Remember key in OS keyring (otherwise this session only)", value=True, id="remember"
                    )
                    yield Button("Forget saved key", id="forget")
                with Horizontal(classes="actions"):
                    yield Button("Sign in  Ctrl+L", id="signin", variant="success")
                    yield Button("Refresh models  Ctrl+R", id="refresh")
                    yield Button("Test connection  Ctrl+T", id="test")
                yield Static("", id="test-result")
            yield Label(
                "Allow sending selected analysis content to this provider? (resets when provider changes)",
                classes="heading",
            )
            yield Static("Local providers (Ollama or LM Studio on this computer) never need consent.", classes="muted")
            yield Select(
                [("No", "no"), ("Yes", "yes")],
                value=store.setting(f"ai.{self.fields_for(selected_provider(store))}.consent", "no"),
                id="consent",
                allow_blank=False,
            )
            yield Button("Save settings  Ctrl+S", id="save", variant="primary")

    def on_mount(self) -> None:
        self.drafts: dict[str, tuple[str, str]] = {}
        self.shown: str | None = None
        self.show_provider(selected_provider(self.workbench.store))

    @property
    def choice(self) -> str:
        return str(self.query_one("#provider", Select).value)

    def fields_for(self, choice: str) -> str:
        return "ollama" if choice == "auto" else choice

    def stash(self) -> None:
        if self.shown and self.shown != "off":
            self.drafts[self.shown] = (
                self.query_one("#base-url", Input).value.strip(),
                self.query_one("#model", Input).value.strip(),
            )

    def current_config(self) -> ProviderConfig:
        preset_id = self.fields_for(self.choice)
        base = self.query_one("#base-url", Input).value.strip() or PRESETS[preset_id].base_url
        return ProviderConfig(preset_id, base.rstrip("/"), self.query_one("#model", Input).value.strip())

    def show_provider(self, choice: str) -> None:
        self.stash()
        preset_id = self.fields_for(choice)
        preset = PRESETS[preset_id]
        self.shown = preset_id
        self.query_one("#consent", Select).value = self.workbench.store.setting(f"ai.{preset_id}.consent", "no")
        note = AUTO_NOTE if choice == "auto" else preset.note
        self.query_one("#provider-note", Static).update(note)
        self.query_one("#connection").display = preset.kind != "off"
        subscription = preset.kind in {"claude_cli", "codex_cli"}
        self.query_one("#url-box").display = not subscription
        signin = self.query_one("#signin", Button)
        signin.display = subscription
        signin.label = "Sign in with ChatGPT  Ctrl+L" if preset.kind == "codex_cli" else "Sign in to Claude  Ctrl+L"
        self.query_one("#key-box").display = preset.kind in {"openai", "anthropic"}
        if preset.kind == "off":
            return
        config = config_for(self.workbench.store, preset_id)
        base, model = self.drafts.get(preset_id, (config.base_url, config.model))
        self.query_one("#base-url", Input).value = base
        self.query_one("#model", Input).value = model
        self.query_one("#api-key", Input).value = ""
        self.query_one("#key-status", Static).update(key_status(preset_id))
        self.query_one("#test-result", Static).update("")
        self.query_one("#models", Select).set_options([])
        self.query_one("#models-status", Static).update("Ctrl+R to refresh available models")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "base-url" and self.shown and self.query("#consent"):
            consented_url = self.workbench.store.setting(f"ai.{self.shown}.consent_url", PRESETS[self.shown].base_url)
            if event.value.strip().rstrip("/") != consented_url.rstrip("/"):
                self.query_one("#consent", Select).value = "no"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider" and self.shown is not None and self.fields_for(self.choice) != self.shown:
            self.show_provider(self.choice)
        elif event.select.id == "provider" and self.shown is not None:
            self.query_one("#provider-note", Static).update(
                AUTO_NOTE if self.choice == "auto" else PRESETS[self.shown].note
            )
        elif event.select.id == "models" and event.value != Select.BLANK:
            self.query_one("#model", Input).value = str(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "forget":
            credentials.forget_key(self.fields_for(self.choice))
            self.query_one("#key-status", Static).update(key_status(self.fields_for(self.choice)))
            self.notify("Saved key removed (environment variables are unaffected)")
        else:
            {
                "save": self.action_save,
                "refresh": self.action_refresh_models,
                "test": self.action_test,
                "signin": self.action_sign_in,
            }[str(event.button.id)]()

    def action_sign_in(self) -> None:
        """Hand the terminal to the vendor's own login command (browser OAuth), then re-check status."""
        if self.choice == "off":
            return
        try:
            provider = create(self.current_config())
        except RuntimeError as exc:
            self.query_one("#test-result", Static).update(f"✗ {exc}")
            return
        if not isinstance(provider, SubscriptionCLI):
            return
        try:
            command = provider.login_command()
        except RuntimeError as exc:
            self.query_one("#test-result", Static).update(f"✗ {exc}")
            return
        try:
            with self.app.suspend():
                try:
                    subprocess.run(command, env=provider.environment(), check=False)
                except KeyboardInterrupt:
                    pass
        except SuspendNotSupported:
            self.notify(f"Run `{shlex.join(command)}` in a terminal to sign in", severity="warning")
            return
        self.action_test()

    def typed_key(self) -> str | None:
        return self.query_one("#api-key", Input).value.strip() or None

    def action_refresh_models(self) -> None:
        if self.choice == "off":
            return
        self.query_one("#models-status", Static).update("Looking for models…")
        self.run_worker(self.refresh_models(), exclusive=True, group="models")

    async def refresh_models(self) -> None:
        status = self.query_one("#models-status", Static)
        try:
            models = await create(self.current_config(), self.typed_key()).models()
        except RuntimeError as exc:
            status.update(f"Could not list models: {exc}")
            return
        self.query_one("#models", Select).set_options([(m, m) for m in models])
        if self.choice == "auto" and models:
            chosen = self.query_one("#model", Input).value.strip()
            using = chosen if chosen in models else pick_ollama_model(models)
            status.update(f"Ollama detected with {len(models)} model(s). Auto will use {using}.")
        else:
            status.update(f"{len(models)} model(s) available" if models else "No models reported; type a model id")

    def action_test(self) -> None:
        if self.choice == "off":
            return
        self.query_one("#test-result", Static).update("Testing…")
        self.run_worker(self.test_connection(), exclusive=True, group="test")

    async def test_connection(self) -> None:
        result = self.query_one("#test-result", Static)
        config = self.current_config()
        try:
            message = await create(config, self.typed_key()).health_check()
        except RuntimeError as exc:
            result.update(f"✗ {exc}")
        else:
            result.update(f"✓ {describe(config)} · {message}")

    def action_save(self) -> None:
        self.stash()
        store = self.workbench.store
        try:
            for preset_id, (base, model) in self.drafts.items():
                preset = PRESETS[preset_id]
                store.set_setting(f"ai.{preset_id}.base_url", "" if base == preset.base_url else base)
                store.set_setting(f"ai.{preset_id}.model", "" if model == preset.default_model else model)
                if preset_id == "ollama":  # explicit values replace pre-1.1 settings
                    store.set_setting("ollama_host", "")
                    store.set_setting("ollama_model", "")
                elif preset_id == "openai":
                    store.set_setting("openai_model", "")
            store.set_setting("ai_provider", self.choice)
            store.set_setting(
                f"ai.{self.fields_for(self.choice)}.consent", str(self.query_one("#consent", Select).value)
            )
            store.set_setting(f"ai.{self.fields_for(self.choice)}.consent_url", self.current_config().base_url)
            key = self.typed_key()
            where = ""
            if key and self.query_one("#key-box").display:
                stored = credentials.set_key(
                    self.fields_for(self.choice), key, self.query_one("#remember", Checkbox).value
                )
                where = (
                    " API key saved to OS keyring." if stored == "keyring" else " API key kept for this session only."
                )
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.query_one("#api-key", Input).value = ""
        self.notify("Settings saved." + where)
        self.workbench.home()

    def action_back(self) -> None:
        self.workbench.home()
