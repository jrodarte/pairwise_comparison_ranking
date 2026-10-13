"""AI co-planner: a persistent, opt-in teaching companion docked beside every screen.

The co-planner advises, instructs and explains; it never edits analyses. It sees only
whitelisted context when the user presses Ask: the current screen, the open project's
name, planning question and analysis titles, the current analysis (inputs and local
results, never notes or history), the user-approved memory and the recent conversation.
Memory persists across projects, but only text the user typed or explicitly accepted.
Lines containing numbers the AI did not take from that context are withheld.
"""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, TextArea

from .ai import (
    AIRequest,
    connect,
    describe,
    public_error,
    selected_provider,
    sharing_destination,
    visible_text,
)
from .ai_setup import AISetupRequired, prompt_ai_setup, prompt_missing_key, require_ai_setup
from .core import METHODS, Session
from .explain import explain_context, grounded
from .safe_widgets import Label, Select, Static

SHARING = (
    "screen, project name, planning question and analysis titles, the open analysis's inputs and results, "
    "approved memory and recent chat (never notes or history)"
)
START = (
    "Walk me through planning step by step, like a patient teacher. Start by asking what I am planning "
    "and what decision it supports, then guide me one step at a time through ThinkTUI: tell me which "
    "screen, key and method to use and why, and wait for me before moving on."
)
HISTORY_TURNS = 8

FLOW = """Six-question planning flow (each step names ThinkTUI methods):
1 Why: what outcome matters? Objectives Hierarchy, Value-Focused Thinking (measures).
2 Who: stakeholders and what each needs; record them in the analysis Objective field.
3 What: scope and unknowns. Issue Tree, Key Assumptions Check (confidence and impact per assumption).
4 Where: choose the approach. Weighted Decision Matrix, then Sensitivity Analysis from its review step,
  Reversibility Analysis, Premortem, FMEA, Bow-Tie.
5 When: order and timing. Pairwise Ranking, Reference-Class Forecasting, Backcasting, Probability Forecast Journal.
6 How: hold the plan accountable. Scenario Planning, Indicators & Signposts, Strategy Stress Test, Decision Journal.
Export each analysis as a .md brief and assemble them into the plan."""

KEYS = """ThinkTUI navigation:
Home: N new project, M method library, S settings, J decision journal, H help me choose (rule-based), P co-planner.
Project: M add analysis; select an analysis to resume; Export project snapshot backs up.
Method library: type to filter, pick a method, give it a title and press Start.
Guided screens (Decision Matrix, AHP, ACH, Forecast Journal, Scenario Planning): F8 validates and saves a step,
F7 goes back, F6 opens raw JSON; the review step offers Export and, for a matrix, Test sensitivity of two options.
Forms and JSON worksheets: fill fields, Ctrl+S saves and calculates, Mark finished, Choose location exports.
Everywhere: Ctrl+E export, F9 explain results, F10 shows or hides this co-planner, Ctrl+O home, Ctrl+P methods,
Esc goes back. Every analysis has a 'What would change your mind?' field worth filling in."""


def app_guide() -> str:
    catalog = "\n".join(f"- {m.name} ({m.id}): {m.description}" for m in METHODS.values())
    return f"{FLOW}\n\n{KEYS}\n\nMethod catalog:\n{catalog}"


def tutor_prompt(question: str) -> str:
    return (
        "You are the ThinkTUI co-planner, a patient teacher and planning coach working beside me inside the "
        "ThinkTUI app. Use the app guide, my current screen, project and analysis, my approved memory and our "
        "recent conversation from the context.\n"
        "- Guide one step at a time: say exactly what to do next in ThinkTUI (screen, key, button, method) "
        "and why, then stop and wait for me.\n"
        "- Teach as you go: the purpose of each method, how to read its results, common mistakes.\n"
        "- Never calculate, estimate or invent numbers, and never propose weights, scores, probabilities, "
        "ratings or dates; I supply every judgment. You may quote numbers that already appear in the context.\n"
        "- You cannot change my data; never claim you did. Do not decide for me.\n"
        "- Be concise: short paragraphs or a short numbered list. Plain text, no tables.\n"
        "- If I share a durable fact about myself that would help in future projects (role, goals, "
        "preferences, experience, lessons learned), you may end with ONE line starting 'REMEMBER:' and a "
        "single sentence without numbers or confidential details. I decide whether to keep it.\n"
        f"My message: {question}"
    )


def split_proposals(text: str) -> tuple[str, list[str]]:
    kept, proposals = [], []
    for line in text.splitlines():
        if line.strip().upper().startswith("REMEMBER:"):
            fact = " ".join(line.strip()[len("REMEMBER:") :].split())
            if fact:
                proposals.append(fact)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), proposals


def screen_label(screen) -> str:
    names = {
        "Home": "Home",
        "NewProject": "New project",
        "ProjectView": "Project",
        "History": "Event history",
        "JournalList": "Decision journal",
        "Library": "Method library",
        "NewAnalysis": "New analysis",
        "Settings": "Settings",
        "PlanningScreen": "Help me choose (method recommendations)",
        "FormScreen": "Analysis form",
        "GuidedScreen": "Guided analysis steps",
        "Workspace": "Analysis workspace",
    }
    return names.get(type(screen).__name__, type(screen).__name__)


def current_session(app) -> Session | None:
    for screen in reversed(app.screen_stack):
        if isinstance(screen, ModalScreen):
            continue
        name = type(screen).__name__
        if name in {"FormScreen", "GuidedScreen"}:
            return screen.session
        if name == "Workspace":
            return app.session
        return None
    return None


def coach_context(app) -> dict:
    """Whitelisted context for one request; built fresh each time the user presses Ask."""
    store = app.store
    base = next((s for s in reversed(app.screen_stack) if not isinstance(s, ModalScreen)), app.screen)
    context: dict = {"screen": screen_label(base), "app_guide": app_guide()}
    if app.project_id and type(base).__name__ not in {"Home", "NewProject", "Settings", "JournalList"}:
        try:
            project = store.project(app.project_id)
        except KeyError:
            project = None
        if project is not None:
            context["project"] = {
                "name": project["name"],
                "planning_question": project["planning_question"],
                "analyses": [
                    {
                        "title": s.title,
                        "method": METHODS[s.method_id].name,
                        "finished": bool(s.completed_at),
                    }
                    for s in store.sessions(app.project_id)
                ],
            }
    session = current_session(app)
    if session is not None:
        context["current_analysis"] = explain_context(session)
    context["memory"] = [row["text"] for row in store.coach_memory()]
    context["recent_conversation"] = [
        {"role": row["role"], "text": row["text"]} for row in store.coach_messages(HISTORY_TURNS * 2)
    ]
    return context


class Coach:
    """Conversation state owned by the app, so streaming survives screen changes."""

    def __init__(self, app) -> None:
        self.app = app
        self.partial = ""
        self.status = "Ask anything about planning or the screen you are on. Nothing is sent until you press Ask."
        self.proposals: list[str] = []
        self.busy = False

    @property
    def open(self) -> bool:
        return self.app.store.setting("coach_open", "no") == "yes"

    @open.setter
    def open(self, value: bool) -> None:
        try:
            self.app.store.set_setting("coach_open", "yes" if value else "no")
        except (ValueError, sqlite3.Error):
            pass  # Staying open is a convenience; a read-only database must not break the panel.

    @property
    def running(self) -> bool:
        return self.busy

    def refresh(self) -> None:
        for panel in self.app.screen.query(CoachPanel).results(CoachPanel):
            panel.refresh_view()

    def ask(self, question: str) -> bool:
        question = question.strip()
        if not question or self.running:
            return False
        if question.lower().startswith("/remember "):
            try:
                self.app.store.add_coach_memory(question[len("/remember ") :])
                self.status = "Saved to memory. Manage it with Memory."
            except ValueError as exc:
                self.status = str(exc)
                self.refresh()
                return False
            self.refresh()
            return True
        if selected_provider(self.app.store) == "off":
            self.status = "AI is off. Choose a provider in Settings (S on Home) to use the co-planner."
            self.refresh()
            return False
        context = coach_context(self.app)  # built before the question joins the history
        self.partial = ""
        self.status = "Connecting…"
        self.busy = True
        self.refresh()
        self.app.run_worker(self._stream(question, context), group="coach", exclusive=True)
        return True

    async def _stream(self, question: str, context: dict) -> None:
        try:
            provider, config = await connect(self.app.store)
            await require_ai_setup(self.app.store, provider, config)
            label = describe(config)
            self.status = f"{sharing_destination(config)} · {label} is answering… Stop ends it."
            self.refresh()
            async for chunk in provider.stream(AIRequest(tutor_prompt(question), context)):
                self.partial += chunk
                for panel in self.app.screen.query(CoachPanel).results(CoachPanel):
                    panel.show_partial()
            text, withheld = grounded(visible_text(self.partial).strip(), context)
            text, proposals = split_proposals(text)
            if not text:
                self.status = f"{label} returned no usable answer. Nothing changed."
                return
            if withheld:
                text += f"\n[{withheld} line(s) withheld: numbers not found in your work]"
            self.app.store.add_coach_message("user", question, self.app.project_id)
            self.app.store.add_coach_message("coach", text, self.app.project_id)
            for panel in self.app.screen.query(CoachPanel).results(CoachPanel):
                draft = panel.query_one("#coach-q", TextArea)
                if draft.text.strip() == question:
                    draft.load_text("")
            self.proposals.extend(p for p in proposals if p not in self.proposals)
            self.status = f"✓ {label} · advice only; your analyses are unchanged."
        except AISetupRequired as exc:
            self.status = f"{exc.provider}: {exc.kind.replace('_', ' ')} required. Nothing sent; your draft is intact."
            prompt_ai_setup(self.app, exc)
        except Exception as exc:
            if prompt_missing_key(self.app, exc):
                self.status = "API key needed or rejected. No answer saved; your draft is intact."
            else:
                self.status = f"AI unavailable: {public_error(exc)}. Your work is unchanged."
        finally:
            self.partial = ""
            self.busy = False
            self.refresh()

    def stop(self) -> None:
        if self.running:
            self.app.workers.cancel_group(self.app, "coach")
            self.busy = False
            self.partial = ""
            self.status = "Stopped. Nothing was saved from the partial answer."
            self.refresh()

    def accept(self, text: str) -> None:
        try:
            self.app.store.add_coach_memory(text)
        except ValueError as exc:
            self.status = str(exc)
        else:
            self.status = "Remembered across projects. Manage it with Memory."
        if self.proposals:
            self.proposals.pop(0)
        self.refresh()

    def dismiss(self) -> None:
        if self.proposals:
            self.proposals.pop(0)
        self.status = "Not remembered."
        self.refresh()


class CoachStrip(Static):
    """Collapsed co-planner: a thin edge strip on every full screen; click it (or press F10) to reopen."""

    DEFAULT_CSS = """
    CoachStrip { dock: right; width: 3; height: 1fr; background: $primary; color: $background;
        content-align: center middle; text-style: bold; }
    CoachStrip:hover { background: $secondary; }
    """

    def __init__(self) -> None:
        super().__init__("◂\n\nC\no\n-\np\nl\na\nn\n\nF\n1\n0", id="coach-strip")
        self.tooltip = "Show the AI co-planner (F10)"

    def on_click(self, event) -> None:
        event.stop()
        self.app.action_coach()


class CoachPanel(Vertical):
    """Docked beside every full screen while the co-planner is open (F10)."""

    DEFAULT_CSS = """
    CoachPanel { dock: right; width: 46; height: 1fr; background: $panel;
        padding: 0 1 0 0; }
    CoachPanel .coach-resize-handle { dock: left; width: 2; height: 100%;
        background: $primary; color: $background; content-align: center middle; }
    CoachPanel .coach-resize-handle:hover { background: $secondary; }
    CoachPanel #coach-transcript { height: 1fr; }
    CoachPanel #coach-q { height: 8; }
    CoachPanel .coach-message-row { width: 100%; height: auto; margin-bottom: 1; }
    CoachPanel .coach-user-row { align: right top; }
    CoachPanel .coach-coach-row { align: left top; }
    CoachPanel .coach-bubble { width: 85%; height: auto;
        padding: 0 1; border: round $secondary; background: $surface; }
    CoachPanel .coach-user-bubble { background: $primary; color: $background; border: round $primary; }
    CoachPanel .coach-coach-bubble { background: $surface; color: $foreground; }
    CoachPanel .coach-sender { text-style: bold; height: auto; }
    CoachPanel .coach-message { height: auto; }
    CoachPanel .coach-empty { height: auto; }
    CoachPanel Horizontal { height: auto; }
    CoachPanel Button { min-width: 6; margin-right: 1; }
    CoachPanel #coach-proposal-box { height: auto; }
    CoachPanel .coach-header { height: auto; margin-top: 1; }
    CoachPanel #coach-close { width: auto; min-width: 4; height: 1; min-height: 1; border: none;
        padding: 0 1; margin: 0; background: $panel; color: $text-muted; }
    CoachPanel #coach-close:hover, CoachPanel #coach-close:focus { background: $error; color: $background; }
    """

    def __init__(self) -> None:
        super().__init__(id="coach-panel")
        self.dragging = False

    @property
    def coach(self) -> Coach:
        return self.app.coach

    def compose(self) -> ComposeResult:
        yield Static("⋮", classes="coach-resize-handle")
        with Horizontal(classes="coach-header"):
            yield Label("AI co-planner", classes="heading")
            yield Button("✕ Close  F10", id="coach-close", tooltip="Close the co-planner; your conversation is kept")
        with Horizontal(classes="coach-size-controls"):
            yield Button("− Width", id="coach-narrower")
            yield Button("+ Width", id="coach-wider")
        yield Static("", id="coach-resize-notice", classes="muted")
        yield Static(f"Shared only when you press Ask: {SHARING}. Advice only.", classes="muted")
        yield Static("", id="coach-status", classes="muted")
        yield VerticalScroll(id="coach-transcript")
        with Vertical(id="coach-proposal-box"):
            yield Static("", id="coach-proposal-label", classes="muted")
            yield Input(id="coach-proposal")
            with Horizontal():
                yield Button("Remember", id="coach-accept")
                yield Button("Dismiss", id="coach-dismiss")
        yield Static(
            "Paste or type a question (Enter adds a line); press Ask to send. /remember adds a fact.", classes="muted"
        )
        yield TextArea(id="coach-q")
        with Horizontal():
            yield Button("Ask", id="coach-ask", variant="primary")
            yield Button("Stop", id="coach-stop")
            yield Button("Memory", id="coach-memory")
            yield Button("Walk me through", id="coach-start")

    def on_mouse_down(self, event) -> None:
        # Real terminal MouseDown events have widget=None; pilot events do not.
        if event.button == 1 and self.screen.get_widget_at(event.screen_x, event.screen_y)[0] is self.query_one(
            ".coach-resize-handle"
        ):
            self.dragging = True
            self.capture_mouse()
            event.stop()

    def _width_bounds(self) -> tuple[int, int]:
        columns = self.screen.size.width
        # Give both the dock and the rest of the screen space even at 60 columns.
        minimum = min(28, max(18, columns // 3))
        main_minimum = max(16, min(40, columns // 3))
        maximum = max(minimum, columns - main_minimum)
        return minimum, maximum

    def _set_width(self, width: float) -> None:
        minimum, maximum = self._width_bounds()
        chosen = max(minimum, min(maximum, round(width)))
        self.app.coach_width = chosen
        self.styles.width = chosen
        self.query_one("#coach-narrower", Button).disabled = chosen <= minimum
        self.query_one("#coach-wider", Button).disabled = chosen >= maximum
        notice = self.query_one("#coach-resize-notice", Static)
        notice.display = maximum == minimum
        if maximum == minimum:
            notice.update("Terminal too narrow to resize the co-planner.")

    def _drag_to(self, x: float) -> None:
        self._set_width(self.screen.size.width - x)

    def on_mouse_move(self, event) -> None:
        if self.dragging:
            self._drag_to(event.screen_x)
            event.stop()

    def on_mouse_up(self, event) -> None:
        if self.dragging:
            self._drag_to(event.screen_x)
            self.dragging = False
            self.release_mouse()
            event.stop()

    def on_mount(self) -> None:
        for ident in ("#coach-narrower", "#coach-wider"):
            self.query_one(ident, Button).active_effect_duration = 0  # Rapid clicks keep resizing.
        minimum, maximum = self._width_bounds()
        initial = self.app.coach_width
        # Leave room to grow as well as shrink when opening on a small screen.
        self._set_width(max(minimum, min(46, maximum - 6)) if initial is None else initial)
        self.refresh_view()

    def on_resize(self) -> None:
        if self.app.coach_width is not None:
            self._set_width(self.app.coach_width)

    @staticmethod
    def message_bubble(role: str, text: str, *, live: bool = False) -> Horizontal:
        """Keep sender and multiline text together in a terminal-sized chat bubble."""
        sender = "You" if role == "user" else "Co-planner"
        bubble = Vertical(classes=f"coach-bubble coach-{role}-bubble")
        bubble.compose_add_child(Static(sender, classes="coach-sender"))
        bubble.compose_add_child(Static(text, classes="coach-message coach-live" if live else "coach-message"))
        row = Horizontal(classes=f"coach-message-row coach-{role}-row")
        row.compose_add_child(bubble)
        return row

    def refresh_view(self) -> None:
        coach = self.coach
        self.query_one("#coach-status", Static).update(coach.status)
        transcript = self.query_one("#coach-transcript", VerticalScroll)
        transcript.remove_children()
        rows = self.app.store.coach_messages()
        widgets = [self.message_bubble(row["role"], row["text"]) for row in rows]
        if coach.running:
            widgets.append(self.message_bubble("coach", visible_text(coach.partial) or "…", live=True))
        if not widgets:
            widgets.append(
                Static(
                    "New here? Press 'Walk me through' and the co-planner will guide you step by step.",
                    classes="muted coach-empty",
                )
            )
        transcript.mount_all(widgets)
        transcript.call_after_refresh(transcript.scroll_end, animate=False)
        busy = coach.running
        self.query_one("#coach-ask", Button).disabled = busy
        self.query_one("#coach-start", Button).disabled = busy
        self.query_one("#coach-stop", Button).disabled = not busy
        box = self.query_one("#coach-proposal-box")
        box.display = bool(coach.proposals)
        if coach.proposals:
            self.query_one("#coach-proposal-label", Static).update(
                "Remember this across projects? Edit it first if you like."
            )
            proposal = self.query_one("#coach-proposal", Input)
            if proposal.value != coach.proposals[0] and not proposal.has_focus:
                proposal.value = coach.proposals[0]

    def show_partial(self) -> None:
        live = self.query(".coach-live").results(Static)
        for widget in live:
            widget.update(visible_text(self.coach.partial) or "…")
        transcript = self.query_one("#coach-transcript", VerticalScroll)
        transcript.scroll_end(animate=False)

    def ask(self) -> None:
        box = self.query_one("#coach-q", TextArea)
        question = box.text
        if not question.strip() or self.coach.running:
            return
        self.coach.ask(question)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.id == "coach-proposal":
            self.coach.accept(event.input.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        ident = event.button.id
        if ident == "coach-close":
            self.app.action_coach()
        elif ident == "coach-narrower":
            self._set_width(self.app.coach_width - 6)
        elif ident == "coach-wider":
            self._set_width(self.app.coach_width + 6)
        elif ident == "coach-ask":
            self.ask()
        elif ident == "coach-stop":
            self.coach.stop()
        elif ident == "coach-start":
            self.coach.ask(START)
        elif ident == "coach-memory":
            self.app.push_screen(MemoryDialog())
        elif ident == "coach-accept":
            self.coach.accept(self.query_one("#coach-proposal", Input).value)
        elif ident == "coach-dismiss":
            self.coach.dismiss()


class MemoryDialog(ModalScreen[None]):
    """Everything the co-planner remembers across projects; nothing else is remembered."""

    DEFAULT_CSS = """
    MemoryDialog { align: center middle; background: $background 80%; }
    MemoryDialog .memory-dialog { width: 85%; max-width: 90; height: auto; max-height: 90%;
        border: round $primary; background: $panel; padding: 1 2; }
    MemoryDialog .actions { height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="memory-dialog"):
            yield Label("Co-planner memory", classes="hero")
            yield Static(
                "Shared with the AI on every co-planner request, in every project. Only facts you typed or accepted. "
                "Never store secrets or confidential details here.",
                classes="muted",
            )
            yield Static("", id="memory-count", classes="muted")
            yield Select([], allow_blank=True, id="memory-list", prompt="No memory yet")
            with Horizontal(classes="actions"):
                yield Button("Delete selected", id="memory-delete")
                yield Button("Clear all memory", id="memory-clear")
                yield Button("Clear conversation", id="memory-clear-chat")
            yield Input(placeholder="Add a fact, e.g. I prefer short checklists", id="memory-new")
            with Horizontal(classes="actions"):
                yield Button("Add", id="memory-add", variant="primary")
                yield Button("Close  Esc", id="memory-close")

    def on_mount(self) -> None:
        self.reload()
        self.query_one("#memory-new", Input).focus()

    def reload(self) -> None:
        rows = self.app.store.coach_memory()
        picker = self.query_one("#memory-list", Select)
        picker.set_options([(row["text"], row["id"]) for row in rows])
        self.query_one("#memory-count", Static).update(f"{len(rows)} remembered fact(s)")

    def add(self) -> None:
        box = self.query_one("#memory-new", Input)
        try:
            self.app.store.add_coach_memory(box.value)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        box.value = ""
        self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memory-new":
            self.add()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        ident = event.button.id
        store = self.app.store
        if ident == "memory-add":
            self.add()
        elif ident == "memory-delete":
            value = self.query_one("#memory-list", Select).value
            if isinstance(value, int):
                store.delete_coach_memory(value)
                self.reload()
        elif ident == "memory-clear":
            store.clear_coach_memory()
            self.reload()
        elif ident == "memory-clear-chat":
            store.clear_coach_messages()
            self.notify("Co-planner conversation cleared")
        elif ident == "memory-close":
            self.action_close()

    def action_close(self) -> None:
        self.app.coach.refresh()
        self.dismiss(None)


class CoachHost:
    """Mixed into every full screen so the open co-planner follows the user everywhere."""

    def on_screen_resume(self) -> None:
        self.app.attach_coach(self)
