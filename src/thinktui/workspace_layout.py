"""Mouse-resizable editor / co-planner split shared by analysis screens."""

from textual import events
from textual.containers import Horizontal


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
        editor.display = self.hidden_pane != "editor"
        ai.display = self.hidden_pane != "ai"
        handle.display = self.hidden_pane is None
        if self.hidden_pane is not None:
            visible = ai if self.hidden_pane == "editor" else editor
            visible.styles.width = "100%"
            visible.styles.height = "1fr"
            return
        if self.has_class("narrow"):
            editor.styles.width = "100%"
            ai.styles.width = "100%"
            editor.styles.height = f"{self.editor_share}fr"
            ai.styles.height = f"{100 - self.editor_share}fr"
        else:
            editor.styles.height = "1fr"
            ai.styles.height = "1fr"
            editor.styles.width = f"{self.editor_share}fr"
            ai.styles.width = f"{100 - self.editor_share}fr"

    def update_split(self, narrow: bool) -> None:
        self.set_class(narrow, "narrow")
        if not narrow:
            self.query_one(".ai-pane").styles.min_height = None
        self.set_split(self.editor_share)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # Terminal drivers leave event.widget unset (unlike Textual's pilot).
        # Hit-test screen coordinates instead of relying on event.widget.
        if (
            self.hidden_pane is None
            and event.button == 1
            and self.screen.get_widget_at(event.screen_x, event.screen_y)[0] is self.query_one(".pane-handle")
        ):
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
