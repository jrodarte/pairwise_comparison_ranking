"""ThinkTUI shell; screens own presentation, services own domain state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from textual import events
from textual.app import App
from textual.binding import Binding
from textual.widgets import DataTable, Input, ListView, OptionList, Select, TextArea

from . import methods as _methods  # noqa: F401 - register method plugins
from .clipboard import read_clipboard, write_clipboard
from .coach import START, Coach, CoachHost, CoachPanel
from .core import METHODS, Session
from .form_screen import FormScreen
from .guided_screen import GuidedScreen
from .guided_workflow import GUIDED
from .screens import HelpDialog, Home, JournalList, Library, NewProject, ProjectView, Settings, Workspace
from .storage import Store
from .themes import THEMES
from .workspace_layout import WorkspaceLayout


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
        Binding("f10", "coach", "Co-planner", priority=True),
        Binding("f3", "shrink_editor", "Narrower form"),
        Binding("f4", "grow_editor", "Wider form"),
        Binding("ctrl+1", "toggle_editor", "Editor pane", show=False),
        Binding("ctrl+2", "toggle_ai", "AI pane", show=False),
        Binding("ctrl+0", "show_panes", "Both panes", show=False),
        Binding("j", "vim_down", "Down", show=False),
        Binding("k", "vim_up", "Up", show=False),
        Binding("h", "vim_left", "Left pane", show=False),
        Binding("l", "vim_right", "Right pane", show=False),
    ]
    CSS = """
    Screen { background: $background; color: $foreground; }
    Header, Footer { background: $surface; color: $foreground; }
    .page { width: 100%; max-width: 110; height: 1fr; margin: 1 2; padding: 1 2; }
    .hero { color: $primary; text-style: bold; height: auto; margin-bottom: 1; }
    .heading { color: $primary; text-style: bold; height: auto; margin-top: 1; }
    .muted { color: $text-muted; height: auto; margin-bottom: 1; }
    .actions, .ai-actions { height: auto; margin: 1 0; }
    .actions Button, .ai-actions Button { margin-right: 1; }
    .group-actions { height: auto; }
    .group-actions Button { margin-right: 1; }
    Collapsible.form-row { padding: 0 0 0 1; margin: 0 0 1 0; }
    Collapsible.form-row > Contents { padding: 0 0 0 2; }
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
    Input, TextArea { background: $panel; color: $foreground; margin: 0 0 1 0; }
    Input { height: 2; border: none; border-bottom: solid $secondary; padding: 0 1; }
    Input:focus { border-bottom: solid $primary; background: $surface; }
    TextArea { height: 6; border: solid $secondary; }
    TextArea:focus { border: solid $primary; background: $surface; }
    Select { margin-bottom: 1; }
    Button { background: $panel; color: $foreground; }
    Button:hover, Button:focus { background: $secondary; color: $foreground; }
    Button.-primary { background: $primary; color: $background; }
    Button.-primary:hover, Button.-primary:focus { background: $secondary; color: $background; }
    .workspace-layout { width: 100%; height: 1fr; }
    .editor-pane { width: 2fr; min-width: 20; height: 1fr; padding: 1 2; background: $surface; }
    .pane-handle { width: 2; height: 100%; background: $primary; color: $background;
        content-align: center middle; }
    .pane-handle:hover { background: $secondary; }
    .ai-pane { width: 1fr; min-width: 18; height: 1fr; padding: 1 1;
        background: $panel; }
    .ai-pane TextArea { height: 1fr; min-height: 6; }
    TextField { height: auto; min-height: 2; max-height: 12; border: none;
        border-bottom: solid $secondary; padding: 0 1; }
    TextField.-multiline { min-height: 4; }
    TextField:focus { border: none; border-bottom: solid $primary; }
    TextField:hover { border-bottom: heavy $secondary; }
    TextField.-resizing { border-bottom: heavy $primary; }
    .ai-pane TextField { height: auto; min-height: 2; }
    .ai-pane .ai-actions { height: auto; }
    .ai-pane .ai-actions Button { min-width: 6; }
    .workspace-layout.narrow { layout: vertical; }
    .workspace-layout.very-narrow .matrix-entry-row { layout: vertical; }
    .very-narrow .matrix-entry-header { display: none; }
    .very-narrow .matrix-entry-row Input, .very-narrow .matrix-entry-row Select { width: 100%; }
    .very-narrow .matrix-entry-row Button { margin-left: 0; }
    .narrow .pane-handle { width: 100%; height: 2; }
    .narrow .editor-pane { width: 100%; height: 2fr; min-height: 8; }
    .narrow .ai-pane { width: 100%; min-width: 0; height: 1fr; min-height: 12;
        border-left: none; border-top: none; }
    .field-editor { height: auto; width: 100%; align: left top; }
    .keyed-grid-row { layout: vertical; width: 100%; height: auto; }
    .keyed-grid-row Input { width: 100%; }
    .field-editor Input, .field-editor TextArea { width: 1fr; }
    Button.ai-trigger { width: auto; min-width: 10; height: 2; min-height: 2;
        margin: 0 0 1 1; padding: 0; background: $panel; color: $primary;
        border: none; }
    Button.ai-trigger:hover, Button.ai-trigger:focus { background: $primary; color: $background; }
    DataTable { height: 1fr; min-height: 9; border: round $secondary; }
    #entry-list { height: auto; max-height: 12; min-height: 3; }
    #results, #ai-response, #pair { height: auto; min-height: 2; margin: 1 0; }
    #ai-response { color: $primary; }
    #ai-status { height: auto; color: $warning; text-style: bold; }
    DeleteProjectDialog, DeleteBranchDialog, AnalysisDialog, MoveAnalysisDialog, HelpDialog, MatrixMappingDialog, LabelMappingDialog { align: center middle; background: $background 80%; }
    DeleteProjectDialog .dialog, DeleteBranchDialog .dialog, AnalysisDialog .dialog, MoveAnalysisDialog .dialog, HelpDialog .dialog { width: 70%; max-width: 72; height: auto;
        border: round $error; background: $panel; padding: 2 3; }
    MatrixMappingDialog .matrix-dialog, LabelMappingDialog .matrix-dialog { width: 85%; max-width: 85; height: auto; max-height: 90%;
        border: round $primary; background: $panel; padding: 1 2; }
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
        self.coach = Coach(self)
        # Chosen when the dock mounts, after the actual terminal width is known.
        self.coach_width: int | None = None

    @property
    def clipboard(self) -> str:
        # Ctrl+V reads the OS clipboard when available; Textual's internal copy
        # remains a fallback for headless terminals and test pilots.
        desktop = read_clipboard()
        return desktop if desktop is not None else super().clipboard

    def copy_to_clipboard(self, text: str) -> None:
        super().copy_to_clipboard(text)  # OSC 52 for terminal clipboard support
        if text:
            write_clipboard(text)

    @property
    def last_export_dir(self) -> Path | None:
        """The folder of the most recent picker export, kept between sessions."""
        value = self.store.setting("export_dir")
        return Path(value) if value else None

    @last_export_dir.setter
    def last_export_dir(self, folder: Path) -> None:
        try:
            self.store.set_setting("export_dir", str(folder))
        except (ValueError, sqlite3.Error):
            pass  # Remembering the folder is a convenience; the export itself already succeeded.

    async def _on_resize(self, event: events.Resize) -> None:
        await super()._on_resize(event)
        if self.screen_stack and self.coach_width is not None:
            # The dock's own fixed width does not change when the terminal does.
            self.call_after_refresh(self._clamp_coach_width)

    def _clamp_coach_width(self) -> None:
        if self.coach_width is not None:
            for panel in self.screen.query(CoachPanel).results(CoachPanel):
                panel._set_width(self.coach_width)

    def on_mount(self) -> None:
        for theme in THEMES.values():
            self.register_theme(theme)
        saved_theme = self.store.setting("theme", "thinktui")
        self.theme = saved_theme if saved_theme in THEMES else "thinktui"
        self.push_screen(
            {"new": NewProject, "methods": Library, "settings": Settings, "journal": JournalList}.get(
                self.initial, Home
            )()
        )

    def _flush_pending(self) -> None:
        if not self.screen_stack:
            return
        screen = self.screen
        if isinstance(screen, Workspace):
            screen.flush_journal()
        elif isinstance(screen, FormScreen) and screen.save_timer is not None:
            screen.flush_save()
        elif isinstance(screen, ProjectView) and screen.question_timer is not None:
            screen.save_question()

    def switch_screen(self, screen):
        self._flush_pending()
        return super().switch_screen(screen)

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

    def attach_coach(self, screen) -> None:
        """Show or hide the co-planner on a screen as it becomes active."""
        panels = list(screen.query(CoachPanel).results(CoachPanel))
        if self.coach.open and not panels:
            screen.mount(CoachPanel())
        elif self.coach.open:
            for panel in panels:
                panel.refresh_view()  # A setup modal may have hidden the panel when its worker finished.
        else:
            for panel in panels:
                panel.remove()

    def _layout(self) -> WorkspaceLayout | None:
        return next(self.screen.query(WorkspaceLayout).results(WorkspaceLayout), None)

    def _toggle_pane(self, pane: str) -> None:
        layout = self._layout()
        if layout is None:
            return
        focused = self.focused
        layout.toggle_pane(pane)
        if focused is not None and focused.ancestors and layout.hidden_pane == pane:
            hidden = layout.query_one(f".{pane}-pane")
            if focused is hidden or hidden in focused.ancestors:
                self._focus_pane("ai" if pane == "editor" else "editor")

    def _focus_pane(self, pane: str) -> None:
        layout = self._layout()
        if layout is None or layout.hidden_pane == pane:
            return
        container = layout.query_one(f".{pane}-pane")
        target = next((widget for widget in container.query("*") if widget.can_focus and not widget.disabled), None)
        if target is not None:
            target.focus()
        else:
            container.focus()

    def action_toggle_editor(self) -> None:
        self._toggle_pane("editor")

    def action_toggle_ai(self) -> None:
        self._toggle_pane("ai")

    def action_show_panes(self) -> None:
        layout = self._layout()
        if layout is not None:
            layout.show_both()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action.startswith("vim_") and isinstance(self.focused, (Input, TextArea, Select)):
            return False  # Never steal typing or selection from editors.
        return True

    def _vim_vertical(self, down: bool) -> None:
        focused = self.focused
        if isinstance(focused, (DataTable, ListView, OptionList)):
            (focused.action_cursor_down if down else focused.action_cursor_up)()
        elif down:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def action_vim_down(self) -> None:
        self._vim_vertical(True)

    def action_vim_up(self) -> None:
        self._vim_vertical(False)

    def _vim_horizontal(self, right: bool) -> None:
        focused = self.focused
        if isinstance(focused, DataTable):
            (focused.action_cursor_right if right else focused.action_cursor_left)()
        elif self._layout() is not None:
            self._focus_pane("ai" if right else "editor")
        elif right:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def action_vim_left(self) -> None:
        self._vim_horizontal(False)

    def action_vim_right(self) -> None:
        self._vim_horizontal(True)

    def _resize_editor(self, delta: int) -> None:
        layout = self._layout()
        if layout is not None and layout.hidden_pane is None:
            layout.set_split(layout.editor_share + delta)
            if layout.has_class("narrow"):
                layout.query_one(".ai-pane").styles.min_height = 6

    def action_shrink_editor(self) -> None:
        self._resize_editor(-8)

    def action_grow_editor(self) -> None:
        self._resize_editor(8)

    def action_coach(self) -> None:
        self.coach.open = not self.coach.open
        screen = next((s for s in reversed(self.screen_stack) if isinstance(s, CoachHost)), None)
        if screen is None:
            return
        self.attach_coach(screen)
        if self.coach.open and screen is self.screen:
            self.call_after_refresh(lambda: screen.query_one("#coach-q").focus())

    def start_coach(self) -> None:
        """Open the co-planner and begin the guided walkthrough at the user's request."""
        if not self.coach.open:
            self.action_coach()
        self.call_after_refresh(lambda: self.coach.ask(START))

    def action_help(self) -> None:
        self.push_screen(HelpDialog())

    def action_quit(self) -> None:
        self._flush_pending()
        self.exit()
