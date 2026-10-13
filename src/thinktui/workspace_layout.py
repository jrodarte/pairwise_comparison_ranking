"""Mouse-resizable editor / co-planner split shared by analysis screens."""

from textual import events
from textual.containers import Horizontal
from textual.widgets import Button

from .safe_widgets import Static

HIDE_AI_ID = "hide-ai-pane"
AI_SMALLER_ID = "ai-pane-smaller"
AI_LARGER_ID = "ai-pane-larger"


def ai_pane_header(title: str) -> Horizontal:
    """Heading row for an analysis AI pane: size and Hide buttons for terminals without mouse drag."""
    row = Horizontal(classes="ai-pane-header")
    row.compose_add_child(Static(title, classes="heading"))
    for label, ident, tip in (
        ("−", AI_SMALLER_ID, "Shrink the AI pane (F4)"),
        ("+", AI_LARGER_ID, "Enlarge the AI pane (F3)"),
    ):
        button = Button(label, id=ident, classes="pane-close", tooltip=tip)
        button.active_effect_duration = 0  # Every rapid click resizes; the press animation would swallow repeats.
        row.compose_add_child(button)
    row.compose_add_child(Button("✕ Hide", id=HIDE_AI_ID, classes="pane-close", tooltip="Hide the AI pane (F5)"))
    return row


class WorkspaceLayout(Horizontal):
    def __init__(self) -> None:
        super().__init__(classes="workspace-layout")
        self.editor_share = 67
        self.dragging = False
        self.hidden_pane: str | None = None

    def toggle_pane(self, pane: str) -> None:
        """Hide one pane at a time; toggling it again restores the split."""
        if pane not in {"editor", "ai"}:
            raise ValueError(pane)
        self.hidden_pane = None if self.hidden_pane == pane else pane
        self.set_split(self.editor_share)

    def show_both(self) -> None:
        self.hidden_pane = None
        self.set_split(self.editor_share)

    def set_split(self, share: int) -> None:
        self.editor_share = max(15, min(85, share))
        editor = self.query_one(".editor-pane")
        ai = self.query_one(".ai-pane")
        handle = self.query_one(".pane-handle")
        narrow = self.has_class("narrow")
        editor.display = self.hidden_pane != "editor"
        ai.display = self.hidden_pane != "ai"
        # A collapsed pane leaves its handle behind as a strip that restores it on click.
        handle.set_class(self.hidden_pane is not None, "collapsed")
        handle.update(self.handle_label(narrow))
        if self.hidden_pane is not None:
            visible = ai if self.hidden_pane == "editor" else editor
            visible.styles.width = "100%" if narrow else "1fr"
            visible.styles.height = "1fr"
            return
        if narrow:
            editor.styles.width = "100%"
            ai.styles.width = "100%"
            editor.styles.height = f"{self.editor_share}fr"
            ai.styles.height = f"{100 - self.editor_share}fr"
        else:
            editor.styles.height = "1fr"
            ai.styles.height = "1fr"
            editor.styles.width = f"{self.editor_share}fr"
            ai.styles.width = f"{100 - self.editor_share}fr"

    def handle_label(self, narrow: bool) -> str:
        if self.hidden_pane == "ai":
            return "▴ Show AI pane · click or F5" if narrow else "◂\nA\nI"
        if self.hidden_pane == "editor":
            return "▾ Show editor · click or Shift+F5" if narrow else "▸"
        return "⋮"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            HIDE_AI_ID: self.app.action_toggle_ai,
            AI_SMALLER_ID: self.app.action_grow_editor,
            AI_LARGER_ID: self.app.action_shrink_editor,
        }
        if event.button.id in actions:
            event.stop()
            actions[event.button.id]()

    def update_split(self, narrow: bool) -> None:
        self.set_class(narrow, "narrow")
        if not narrow:
            self.query_one(".ai-pane").styles.min_height = None
        self.set_split(self.editor_share)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # Terminal drivers leave event.widget unset (unlike Textual's pilot).
        # Hit-test screen coordinates instead of relying on event.widget.
        on_handle = event.button == 1 and self.screen.get_widget_at(event.screen_x, event.screen_y)[
            0
        ] is self.query_one(".pane-handle")
        if on_handle and self.hidden_pane is not None:
            self.show_both()
            event.stop()
        elif on_handle:
            if self.has_class("narrow"):
                # Preserve the comfortable default sidebar, but let the user shrink it.
                self.query_one(".ai-pane").styles.min_height = 6
            self.dragging = True
            self.capture_mouse()
            event.stop()

    def _drag_to(self, x: float, y: float) -> None:
        axis = (y - self.region.y) if self.has_class("narrow") else (x - self.region.x)
        length = self.size.height if self.has_class("narrow") else self.size.width
        if length > 0:
            self.set_split(round(100 * axis / length))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.dragging:
            self._drag_to(event.screen_x, event.screen_y)
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.dragging:
            self._drag_to(event.screen_x, event.screen_y)
            self.dragging = False
            self.release_mouse()
            event.stop()
