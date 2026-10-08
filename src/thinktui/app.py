"""ThinkTUI shell; screens own presentation, services own domain state."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.theme import Theme

from . import methods as _methods  # noqa: F401 - register method plugins
from .core import METHODS, Session
from .form_screen import FormScreen
from .guided_screen import GuidedScreen
from .guided_workflow import GUIDED
from .screens import HelpDialog, Home, JournalList, Library, NewProject, ProjectView, Settings, Workspace
from .storage import Store


class ThinkApp(App[None]):
    COMMAND_PALETTE_BINDING = "ctrl+shift+p"
    TITLE = "ThinkTUI"
    SUB_TITLE = "Structured Thinking & Decision Toolkit"
    BINDINGS = [
        Binding("ctrl+n", "new", "New"),
        Binding("ctrl+o", "home", "Home"),
        Binding("ctrl+p", "methods", "Methods"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]
    CSS = """
    Screen { background: #10151e; color: #e4e9ef; }
    Header, Footer { background: #1d2734; color: #e4e9ef; }
    .page { width: 100%; max-width: 110; height: 1fr; margin: 1 2; padding: 1 2; }
    .hero { color: #b4dcd5; text-style: bold; height: auto; margin-bottom: 1; }
    .heading { color: #83c6ba; text-style: bold; height: auto; margin-top: 1; }
    .muted { color: #aab9c6; height: auto; margin-bottom: 1; }
    .actions, .ai-actions { height: auto; margin: 1 0; }
    .actions Button, .ai-actions Button { margin-right: 1; }
    .matrix-score-scroll { width: 100%; height: auto; max-height: 18; overflow-y: auto; }
    .matrix-score-table { height: auto; }
    .matrix-grid-row { width: 100%; height: auto; min-height: 3; }
    .matrix-grid-name { width: 22; height: auto; }
    .matrix-grid-cell { width: 18; height: auto; }
    .matrix-grid-cell Input { width: 100%; }
    .matrix-entry-row, .matrix-entry-header { width: 100%; height: auto; align: left top; }
    .matrix-entry-header .matrix-col-name { width: 1fr; }
    .matrix-entry-header .matrix-col-weight { width: 12; }
    .matrix-entry-header .matrix-col-direction { width: 22; }
    .matrix-entry-header .matrix-col-remove { width: 17; }
    .matrix-entry-row Input { width: 1fr; }
    .matrix-entry-row Input.matrix-weight { width: 12; }
    .matrix-entry-row Select { width: 22; }
    .matrix-entry-row Button { margin: 0 0 1 1; }
    Input, TextArea { background: #202c39; color: #e4e9ef; margin: 0 0 1 0; }
    Input { height: 2; border: none; border-bottom: solid #344b57; padding: 0 1; }
    Input:focus { border-bottom: solid #83c6ba; background: #273844; }
    TextArea { height: 6; border: solid #344b57; }
    TextArea:focus { border: solid #83c6ba; background: #273844; }
    Select { margin-bottom: 1; }
    Button { background: #304653; color: #e4e9ef; }
    Button:hover, Button:focus { background: #406575; color: #ffffff; }
    Button.-primary { background: #397e76; color: #ffffff; }
    Button.-primary:hover, Button.-primary:focus { background: #4a9d91; }
    .workspace-layout { width: 100%; height: 1fr; }
    .editor-pane { width: 2fr; height: 1fr; padding: 1 2; background: #151e29; }
    .ai-pane { width: 1fr; min-width: 28; height: 1fr; padding: 1 2;
        background: #1b2932; border-left: solid #397e76; }
    .ai-pane TextArea { height: 1fr; min-height: 6; }
    .ai-pane .ai-actions { height: auto; }
    .ai-pane .ai-actions Button { min-width: 6; }
    .workspace-layout.narrow { layout: vertical; }
    .workspace-layout.very-narrow .matrix-entry-row { layout: vertical; }
    .very-narrow .matrix-entry-header { display: none; }
    .very-narrow .matrix-entry-row Input, .very-narrow .matrix-entry-row Select { width: 100%; }
    .very-narrow .matrix-entry-row Button { margin-left: 0; }
    .narrow .editor-pane { width: 100%; height: 2fr; }
    .narrow .ai-pane { width: 100%; min-width: 0; height: 1fr; min-height: 12;
        border-left: none; border-top: solid #397e76; }
    .field-editor { height: auto; width: 100%; align: left top; }
    .field-editor Input, .field-editor TextArea { width: 1fr; }
    Button.ai-trigger { width: auto; min-width: 10; height: 2; min-height: 2;
        margin: 0 0 1 1; padding: 0; background: #294b4e; color: #b4e3d6;
        border: none; }
    Button.ai-trigger:hover, Button.ai-trigger:focus { background: #397e76; color: #ffffff; }
    DataTable { height: 1fr; min-height: 9; border: round #344b57; }
    #entry-list { height: auto; max-height: 12; min-height: 3; }
    #results, #ai-response, #pair { height: auto; min-height: 2; margin: 1 0; }
    #ai-response { color: #b4dcd5; }
    #ai-status { height: auto; color: #e4bd83; text-style: bold; }
    DeleteProjectDialog, DeleteBranchDialog, AnalysisDialog, MoveAnalysisDialog, HelpDialog, MatrixMappingDialog, LabelMappingDialog { align: center middle; background: #080e16 80%; }
    DeleteProjectDialog .dialog, DeleteBranchDialog .dialog, AnalysisDialog .dialog, MoveAnalysisDialog .dialog, HelpDialog .dialog { width: 70%; max-width: 72; height: auto;
        border: round #ca837f; background: #202c39; padding: 2 3; }
    MatrixMappingDialog .matrix-dialog, LabelMappingDialog .matrix-dialog { width: 85%; max-width: 85; height: auto; max-height: 90%;
        border: round #83c6ba; background: #202c39; padding: 1 2; }
    MatrixMappingDialog .matrix-dialog-rows, LabelMappingDialog .matrix-dialog-rows { height: auto; max-height: 18; }
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
        self.register_theme(
            Theme(
                name="thinktui",
                primary="#83c6ba",
                secondary="#577d90",
                accent="#e4bd83",
                warning="#e4bd83",
                error="#ca837f",
                success="#83c6ba",
                foreground="#e4e9ef",
                background="#10151e",
                surface="#151e29",
                panel="#202c39",
            )
        )
        self.theme = "thinktui"
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

    def action_help(self) -> None:
        self.push_screen(HelpDialog())

    def action_quit(self) -> None:
        if isinstance(self.screen, Workspace) and self.session and self.session.method_id == "journal":
            self.screen.flush_journal()
        self.store.close()
        self.exit()
