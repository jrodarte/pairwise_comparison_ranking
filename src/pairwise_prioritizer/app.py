"""Textual application shell and navigation."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.worker import get_current_worker

from .models import Project
from .persistence import ProjectStore
from .screens.common import HelpDialog
from .screens.comparison import ComparisonScreen
from .screens.history import HistoryScreen
from .screens.home import HomeScreen
from .screens.project_setup import SetupScreen
from .screens.results import ResultsScreen
from .updater import CHECK_INTERVAL_SECONDS, check_and_pull


class PairRankApp(App[None]):
    """Keyboard-first project navigation; domain logic lives outside the UI."""

    TITLE = "PairRank"
    SUB_TITLE = "Pairwise Prioritization"
    BINDINGS = [
        ("question_mark", "help", "Help"),
        ("q", "quit", "Save & quit"),
        Binding("ctrl+c", "quit", "Save & quit", priority=True),
    ]
    CSS = """
    Screen { background: #101924; color: #e6edf5; }
    Header { background: #172637; color: #e6edf5; }
    Footer { background: #172637; color: #b7c8d8; }
    .page { width: 100%; max-width: 112; height: 1fr; margin: 1 2; padding: 1 2; }
    .hero { text-style: bold; color: #eaf3ff; text-align: left; height: auto; margin-bottom: 1; }
    .muted { color: #91a5ba; height: auto; margin-bottom: 1; }
    .section-title, .field-label { color: #82b7d9; text-style: bold; height: auto;
        margin-top: 1; margin-bottom: 1; }
    .actions { height: auto; margin: 1 0 2 0; }
    .actions Button { margin-right: 1; }
    Button { min-width: 12; }
    Button.-primary { background: #246889; }
    DataTable { height: 1fr; border: round #30465d; background: #152232; }
    DataTable > .datatable--cursor { background: #25526c; }
    Input, TextArea { background: #172637; border: tall #30465d; }
    Input:focus, TextArea:focus { border: tall #82b7d9; }
    .setup-page { overflow-y: auto; }
    .setup-page TextArea { height: 10; min-height: 5; }
    .import-row { height: auto; }
    .import-row Input { width: 1fr; }
    .import-row Button { margin-left: 1; }
    .comparison-page { align-horizontal: center; }
    .compare-heading { text-align: center; width: 100%; margin: 1 0 0 0; }
    #comparison-number { text-align: center; width: 100%; }
    #cards { height: 1fr; min-height: 13; max-height: 24; margin: 1 0; }
    .feature-card { width: 1fr; height: 100%; border: round #42627e;
        background: #172637; padding: 1 2; margin: 0 1; }
    .feature-card .field-label { margin: 0 0 1 0; }
    .item-name { color: #eaf3ff; text-style: bold; height: auto; min-height: 3; }
    .item-description { color: #a8bed0; height: 1fr; overflow-y: auto; }
    .feature-card Button { width: 100%; }
    .center-actions { height: auto; align-horizontal: center; }
    .center-actions Button { margin: 0 1; }
    #progress { margin-top: 2; }
    #progress-text { text-align: center; width: 100%; }
    #insight { margin: 1 0; }
    #items { height: 7; margin: 1 0; }
    #matchups { height: 1fr; }
    ModalScreen { align: center middle; background: #070d15 75%; }
    .dialog { width: 75%; max-width: 85; height: auto; max-height: 85%;
        background: #172637; border: round #6d9dbb; padding: 2 3; }
    .dialog-buttons { height: auto; margin: 1 0; }
    .dialog-buttons Button { margin-right: 1; }
    .help-dialog { max-width: 80; }
    .help-text { height: auto; margin: 1 0; }
    .detail-dialog { height: 80%; }
    .detail-scroll { height: 1fr; margin: 1 0; }
    .detail-list { height: auto; margin-bottom: 1; }
    """

    def __init__(
        self,
        store: ProjectStore | None = None,
        initial: str = "home",
        auto_update: bool = False,
    ) -> None:
        super().__init__()
        self.store = store or ProjectStore()
        self.project: Project | None = None
        self.initial = initial
        self.auto_update = auto_update
        self.update_pulled = False

    def on_mount(self) -> None:
        if self.auto_update:
            self.check_for_updates()
            self.set_interval(CHECK_INTERVAL_SECONDS, self.check_for_updates)
        if self.initial == "new":
            self.push_screen(SetupScreen())
        elif self.initial == "demo":
            self.push_screen(SetupScreen(demo=True))
        elif self.initial == "history":
            self.push_screen(HistoryScreen())
        elif self.initial == "resume":
            project = next((p for p in self.store.list_projects() if p.remaining), None)
            if project:
                self.project = project
                self.push_screen(ComparisonScreen())
            else:
                self.push_screen(HomeScreen())
                self.notify("No unfinished ranking; create a new one.")
        else:
            self.push_screen(HomeScreen())

    def home(self) -> None:
        """Return to the landing page."""
        self.switch_screen(HomeScreen())

    def history(self) -> None:
        """Open project management."""
        self.switch_screen(HistoryScreen())

    def setup(self, import_focus: bool = False) -> None:
        """Open project creation."""
        self.switch_screen(SetupScreen(import_focus=import_focus))

    def open_project(self, project: Project) -> None:
        """Resume incomplete work, or review finished results."""
        self.project = project
        if project.remaining:
            self.switch_screen(ComparisonScreen())
        else:
            self.results()

    def results(self) -> None:
        """Show the current recalculated leaderboard."""
        self.switch_screen(ResultsScreen())

    def check_for_updates(self) -> None:
        """Pull new commits from GitHub in the background."""
        if not self.update_pulled:
            self.run_worker(self._pull_updates, thread=True, exclusive=True, group="update")

    def _pull_updates(self) -> None:
        result = check_and_pull()
        if result.updated and not get_current_worker().is_cancelled:
            self.update_pulled = True
            self.call_from_thread(self.notify, result.message, title="Update", timeout=15)

    def action_help(self) -> None:
        self.push_screen(HelpDialog())

    def action_quit(self) -> None:
        # Every mutation is saved immediately, so quitting never discards a decision.
        self.exit()
