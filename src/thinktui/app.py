"""ThinkTUI shell; screens own presentation, services own domain state."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from . import methods as _methods  # noqa: F401 - register method plugins
from .core import METHODS, Session
from .form_screen import FormScreen
from .guided_screen import GuidedScreen
from .guided_workflow import GUIDED
from .screens import Home, JournalList, Library, NewProject, ProjectView, Settings, Workspace
from .storage import Store


class ThinkApp(App[None]):
    TITLE = "ThinkTUI"
    SUB_TITLE = "Structured Thinking & Decision Toolkit"
    BINDINGS = [
        Binding("ctrl+n", "new", "New"),
        Binding("ctrl+o", "home", "Open"),
        Binding("ctrl+p", "methods", "Methods"),
        Binding("q", "quit", "Quit"),
    ]
    CSS = """
    Screen { background: #111b27; color: #dfebf5; }
    Header, Footer { background: #1b3042; }
    .page { width: 100%; max-width: 110; height: 1fr; margin: 1 2; padding: 1 2; }
    .hero { color: #b8dfff; text-style: bold; height: auto; margin-bottom: 1; }
    .heading { color: #91c7d8; text-style: bold; height: auto; margin-top: 1; }
    .muted { color: #aabccc; height: auto; margin-bottom: 1; }
    .actions { height: auto; margin: 1 0; }
    .actions Button { margin-right: 1; }
    .matrix-grid-row { height: auto; min-height: 3; }
    .matrix-grid-name { width: 22; height: auto; }
    .matrix-grid-cell { width: 1fr; min-width: 12; height: auto; }
    Input, TextArea { background: #1b3042; border: tall #38576a; margin: 0 0 1 0; }
    Input:focus, TextArea:focus { border: tall #89bed7; }
    TextArea { height: 12; }
    DataTable { height: 1fr; min-height: 9; border: round #38576a; }
    #results, #ai-response, #pair { height: auto; min-height: 2; margin: 1 0; }
    #ai-response { color: #91c7d8; }
    #ai-status { height: auto; color: #f0c674; text-style: bold; }
    DeleteProjectDialog { align: center middle; background: #070d15 80%; }
    DeleteProjectDialog .dialog { width: 70%; max-width: 72; height: auto;
        border: round #b87c78; background: #1b3042; padding: 2 3; }
    """

    def __init__(self, store: Store | None = None, initial: str = "home") -> None:
        super().__init__()
        self.store = store or Store()
        self.initial = initial
        self.project_id: str | None = None
        self.method_id = "pairwise"
        self.pending_method_id: str | None = None
        self.session: Session | None = None

    def on_mount(self) -> None:
        self.push_screen(
            {"new": NewProject, "methods": Library, "settings": Settings, "journal": JournalList}.get(
                self.initial, Home
            )()
        )

    def home(self) -> None:
        self.project_id = None
        self.pending_method_id = None
        self.switch_screen(Home())

    def show_project(self) -> None:
        self.switch_screen(ProjectView())

    def open_session(self, session: Session, *, guided: bool = False, advanced: bool = False) -> None:
        self.session = session
        self.project_id = session.project_id
        if advanced:
            screen = Workspace()
        elif guided and session.method_id in GUIDED:
            screen = GuidedScreen(session)
        elif guided and hasattr(METHODS[session.method_id], "example"):
            screen = FormScreen(session)
        else:
            screen = Workspace()
        self.switch_screen(screen)

    def action_new(self) -> None:
        self.switch_screen(NewProject())

    def action_home(self) -> None:
        self.home()

    def action_methods(self) -> None:
        self.switch_screen(Library())

    def action_quit(self) -> None:
        if isinstance(self.screen, Workspace) and self.session and self.session.method_id == "journal":
            self.screen.flush_journal()
        self.store.close()
        self.exit()
