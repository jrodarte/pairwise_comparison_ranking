"""Opt-in AI tutor that explains an analysis's locally calculated results.

Explanations are display-only: nothing the AI says is saved or written into the
analysis. The AI may quote numbers that appear in the user's inputs or the local
calculation (rounding allowed), but any line carrying a number it produced itself
is withheld, so the AI never calculates on the user's behalf.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input

from .ai import (
    AIRequest,
    connect,
    context_for,
    describe,
    public_error,
    selected_provider,
    sharing_destination,
    visible_text,
)
from .ai_setup import AISetupRequired, prompt_ai_setup, prompt_missing_key, require_ai_setup
from .core import METHODS, Session
from .safe_widgets import Label, Static

DEFAULT_QUESTION = "Explain what these results mean and how to read them."
SHARING = (
    "method, title, problem, objective, assumptions, full method state and calculated results (not notes or history)"
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])([-−]?\d+(?:\.\d+)?)(\s*%)?")
_LIST_MARKER = re.compile(r"^\s*(?:[-*]\s+)?\d{1,2}[.)]\s+")


def calculated(session: Session) -> dict | None:
    try:
        return METHODS[session.method_id].calculate(session.method_state)
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


def derived(session: Session) -> dict:
    """Small local calculations a learner needs to read a result; computed here, never by AI."""
    state = session.method_state
    if session.method_id != "sensitivity":
        return {}
    try:
        weights = {row["name"]: float(row["weight"]) for row in state["criteria"]}
        total = sum(weights.values())
        return {"current_share_of_varied_criterion": weights[state["vary"]] / total} if total > 0 else {}
    except (KeyError, TypeError, ValueError):
        return {}


def explain_context(session: Session) -> dict:
    method = METHODS[session.method_id]
    return {
        **context_for(session),
        "title": session.title,
        "method_name": method.name,
        "method_description": method.description,
        "results": calculated(session),
        "derived_locally": derived(session),
    }


def _numbers(value: object) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            yield float(value)
    elif isinstance(value, str):
        for match in _NUMBER.finditer(value):
            yield float(match.group(1).replace("−", "-"))
    elif isinstance(value, dict):
        for key, entry in value.items():
            yield from _numbers(key)
            yield from _numbers(entry)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            yield from _numbers(entry)


def _matches(token: str, percent: bool, known: list[float]) -> bool:
    """A shown number is grounded when it equals, or rounds from, a known value (x100 for percentages)."""
    shown = float(token.replace("−", "-"))
    places = len(token.split(".", 1)[1]) if "." in token else 0
    for value in known:
        for candidate in (value, value * 100) if percent else (value,):
            if abs(candidate - shown) < 1e-9 or abs(round(candidate, places) - shown) < 1e-9:
                return True
    return False


def grounded(answer: str, context: dict) -> tuple[str, int]:
    """Keep lines whose numbers all come from the context; return the text and the count withheld."""
    known = list(_numbers(context))
    kept: list[str] = []
    withheld = 0
    for line in answer.splitlines():
        body = _LIST_MARKER.sub("", line)
        if all(_matches(m.group(1), bool(m.group(2)), known) for m in _NUMBER.finditer(body)):
            kept.append(line)
        else:
            withheld += 1
    return "\n".join(kept).strip(), withheld


def tutor_question(question: str, method_name: str, history: list[tuple[str, str]]) -> str:
    earlier = "".join(f"\nEarlier question: {q}\nYour earlier answer: {a}" for q, a in history[-4:])
    return (
        f"Act as a patient tutor helping me learn the {method_name} method using my own analysis. "
        "Explain using only my inputs and the locally calculated results in the context. "
        "Never calculate, estimate or invent numbers: quote any number exactly as it appears in the context "
        "(rounding is fine) or describe it in words. If 'results' is null, explain what is missing. "
        "Do not choose an option for me; explain what the results mean, how the method works, "
        "its limits, and what I could examine next. Plain text, short paragraphs, no tables."
        + (f"\nOur discussion so far:{earlier}" if earlier else "")
        + f"\nMy question: {question}"
    )


class ExplainDialog(ModalScreen[None]):
    """Ask the configured AI to explain this analysis; answers are shown, never saved."""

    DEFAULT_CSS = """
    ExplainDialog { align: center middle; background: $background 80%; }
    ExplainDialog .explain-dialog { width: 90%; max-width: 110; height: 90%; border: round $primary;
        background: $panel; padding: 1 2; }
    ExplainDialog #explain-transcript { height: 1fr; border: solid $secondary; padding: 0 1; }
    ExplainDialog #explain-transcript Static { margin-bottom: 1; }
    ExplainDialog .actions { height: auto; }
    """
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+g", "stop", "Stop AI", priority=True),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.history: list[tuple[str, str]] = []
        self.partial = ""

    def compose(self) -> ComposeResult:
        method = METHODS[self.session.method_id]
        with Vertical(classes="explain-dialog"):
            yield Label(f"Explain results · {self.session.title}", classes="hero")
            yield Static(
                f"Learning aid for {method.name}. Sent only when you ask: {SHARING}. "
                "Answers are never saved. Lines with numbers the AI did not take from your results are withheld.",
                classes="muted",
            )
            if calculated(self.session) is None:
                yield Static(
                    "No calculated result yet; the AI can explain what is missing or how the method works.",
                    classes="muted",
                )
            yield Static("", id="explain-status", classes="muted")
            with VerticalScroll(id="explain-transcript"):
                pass
            yield Input(placeholder="Ask about these results · Enter with nothing typed explains them", id="explain-q")
            with Horizontal(classes="actions"):
                yield Button("Ask", id="explain-ask", variant="primary")
                yield Button("Stop  Ctrl+G", id="explain-stop", disabled=True)
                yield Button("Close  Esc", id="explain-close")

    def on_mount(self) -> None:
        self.query_one("#explain-q", Input).focus()

    @property
    def running(self) -> bool:
        return any(worker.group == "explain" and worker.is_running for worker in self.workers)

    def busy(self, busy: bool) -> None:
        self.query_one("#explain-ask", Button).disabled = busy
        self.query_one("#explain-stop", Button).disabled = not busy

    def ask(self) -> None:
        if self.running:
            return
        if selected_provider(self.app.store) == "off":
            self.query_one("#explain-status", Static).update("AI is off; choose a provider in Settings.")
            return
        box = self.query_one("#explain-q", Input)
        question = box.value.strip() or DEFAULT_QUESTION
        box.value = ""
        transcript = self.query_one("#explain-transcript", VerticalScroll)
        transcript.mount(Static("You: " + question, classes="heading"))
        answer = Static("…", classes="explain-answer")
        transcript.mount(answer)
        self.busy(True)
        self.run_worker(self.stream(question, answer), group="explain", exclusive=True)

    async def stream(self, question: str, answer: Static) -> None:
        status = self.query_one("#explain-status", Static)
        context = explain_context(self.session)
        self.partial = ""
        try:
            provider, config = await connect(self.app.store)
            await require_ai_setup(self.app.store, provider, config)
            label = describe(config)
            status.update(f"{sharing_destination(config)} · asking {label}… Ctrl+G stops.")
            request = AIRequest(tutor_question(question, context["method_name"], self.history), context)
            async for chunk in provider.stream(request):
                self.partial += chunk
                text, _ = grounded(visible_text(self.partial), context)
                answer.update("AI: " + (text or "…"))
                self.query_one("#explain-transcript", VerticalScroll).scroll_end(animate=False)
            text, withheld = grounded(visible_text(self.partial).strip(), context)
            if not text:
                answer.update("AI: (no usable answer; nothing changed)")
                status.update(f"{label} returned no usable explanation.")
                return
            note = f"\n[{withheld} line(s) withheld: numbers not found in your results]" if withheld else ""
            answer.update("AI: " + text + note)
            self.history.append((question, text))
            status.update(f"✓ {label} · not saved · ask a follow-up or press Esc to close.")
        except AISetupRequired as exc:
            answer.update("Not sent. Your analysis is unchanged.")
            status.update(f"{exc.provider}: {exc.kind.replace('_', ' ')} required in Settings.")
            prompt_ai_setup(self.app, exc)
        except Exception as exc:
            answer.update("AI unavailable. Your analysis is unchanged.")
            if prompt_missing_key(self.app, exc):
                status.update("API key needed or rejected. Your analysis is unchanged.")
            else:
                status.update(f"AI unavailable: {public_error(exc)}")
        finally:
            self.busy(False)
            self.query_one("#explain-transcript", VerticalScroll).scroll_end(animate=False)

    def action_stop(self) -> None:
        if self.running:
            self.workers.cancel_group(self, "explain")
            self.busy(False)
            self.query_one("#explain-status", Static).update("AI stopped · partial answer shown, never saved.")

    def action_close(self) -> None:
        self.workers.cancel_group(self, "explain")
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "explain-q":
            self.ask()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "explain-ask":
            self.ask()
        elif event.button.id == "explain-stop":
            self.action_stop()
        elif event.button.id == "explain-close":
            self.action_close()
