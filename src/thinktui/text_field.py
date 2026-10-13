"""A wrapping text field that grows with its text and can be resized by keyboard or mouse drag.

It stands in for ``Input`` on planning text fields. It posts ``Input.Changed`` and
``Input.Submitted`` so screens handle both widgets the same way, and offers ``value``
like ``Input``. Single-line fields keep Enter as submit; multiline fields insert newlines.
"""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.widgets import Input, TextArea

MIN_LINES = 1
MAX_LINES = 60


class TextField(TextArea):
    """Text that wraps and auto-sizes up to ``max-height``; drag the bottom edge or press Alt+↑/↓ to resize."""

    DEFAULT_CSS = """
    TextField {
        height: auto;
        min-height: 2;
        max-height: 12;
        border: none;
        border-bottom: solid $secondary;
        border-subtitle-color: $panel;
        border-subtitle-align: right;
        padding: 0 1;
    }
    TextField.-multiline { min-height: 4; }
    TextField:focus { border-bottom: solid $primary; border-subtitle-color: $text-muted; }
    TextField:hover { border-bottom: heavy $secondary; border-subtitle-color: $text-muted; }
    TextField.-resizing { border-bottom: heavy $primary; }
    """

    BINDINGS = [
        Binding("alt+down", "grow", "Taller field"),
        Binding("alt+up", "shrink", "Shorter field"),
    ]

    # Heights a person chose, by size_key, so a recomposed form keeps them.
    remembered: dict[str, int] = {}

    def __init__(
        self,
        value: str = "",
        *,
        placeholder: str = "",
        multiline: bool = False,
        size_key: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            value,
            soft_wrap=True,
            tab_behavior="focus",
            show_line_numbers=False,
            placeholder=placeholder,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.multiline = multiline
        self.size_key = size_key
        self._drag: tuple[int, int] | None = None
        self.border_subtitle = "⇕ drag · Alt+↑↓"
        if multiline:
            self.add_class("-multiline")

    def on_mount(self) -> None:
        if self.size_key and self.size_key in self.remembered:
            self.set_lines(self.remembered[self.size_key])

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        if self.multiline:
            self.text = text
            return
        text = " ".join(text.splitlines())
        if text == self.text:
            return  # like Input: no change, no message
        # Report this exact value now, as Input does, without a TextArea echo.
        with self.prevent(TextArea.Changed):
            self.text = text
        self.move_cursor(self.document.end)
        self.post_message(Input.Changed(self, text))  # type: ignore[arg-type]

    # Messages: present the field as an Input to the screens that own it.
    def _on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self.multiline:
            return  # multiline fields report TextArea.Changed, like the TextArea they replace
        event.stop()
        if "\n" in self.text:
            self.value = self.text  # pasted line breaks become spaces; posts a new change
            self.move_cursor(self.document.end)
            return
        self.post_message(Input.Changed(self, self.text))  # type: ignore[arg-type]

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not self.multiline:
            event.stop()
            event.prevent_default()
            self.post_message(Input.Submitted(self, self.text))  # type: ignore[arg-type]
            return
        await super()._on_key(event)

    # Sizing.
    def lines(self) -> int:
        return max(MIN_LINES, self.outer_size.height - 1)

    def set_lines(self, lines: int) -> None:
        lines = max(MIN_LINES, min(MAX_LINES, lines))
        # Inline min/max override the stylesheet's auto-size limits for a chosen height.
        self.styles.height = self.styles.min_height = self.styles.max_height = lines + 1  # plus the bottom edge
        if self.size_key:
            self.remembered[self.size_key] = lines

    def fit_text(self) -> None:
        """Return to automatic height within the stylesheet limits."""
        for rule in ("height", "min_height", "max_height"):
            self.styles.clear_rule(rule)
        self.refresh(layout=True)
        if self.size_key:
            self.remembered.pop(self.size_key, None)

    def action_grow(self) -> None:
        self.set_lines(self.lines() + 2)

    def action_shrink(self) -> None:
        self.set_lines(self.lines() - 2)

    def _on_bottom_edge(self, event: events.MouseEvent) -> bool:
        return event.y >= self.outer_size.height - 1

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if self._on_bottom_edge(event):
            event.stop()
            event.prevent_default()
            self._drag = (event.screen_y, self.lines())
            self.add_class("-resizing")
            self.capture_mouse()
            return
        await super()._on_mouse_down(event)

    def _on_click(self, event: events.Click) -> None:
        if event.chain >= 2 and self._on_bottom_edge(event):
            event.stop()
            self.fit_text()  # double-click the bottom edge to fit the text again

    async def _on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag is not None:
            event.stop()
            event.prevent_default()
            start_y, start_lines = self._drag
            self.set_lines(start_lines + event.screen_y - start_y)
            return
        await super()._on_mouse_move(event)

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is not None:
            event.stop()
            event.prevent_default()
            self._drag = None
            self.remove_class("-resizing")
            self.release_mouse()
            return
        await super()._on_mouse_up(event)
