"""Shared, opt-in text-only drafting for form, guided, and dedicated editors.

Only a user's explicit Accept may move proposed prose into an editor. Numerical
judgments, including dates, are never supplied by this helper.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from textual.widgets import Static, TextArea

from .ai import (
    AIRequest,
    connect,
    context_for,
    describe,
    public_error,
    remote_consent,
    selected_provider,
    sharing_destination,
    visible_text,
)
from .core import Session

NUMERIC_JUDGMENT = re.compile(
    r"(?:\b(?:score|weight|probability|confidence|rating|likelihood|impact|cost|risk|date|deadline|odds)\s*[:=]?\s*[-+]?\d|\d+(?:\.\d+)?\s*%|\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b|^\s*[-+]?\d+(?:\.\d+)?\s*$)",
    re.IGNORECASE,
)


def text_only(answer: str) -> str:
    """Omit numeric judgments, not harmless prose such as 'Phase 2'."""
    return "\n".join(line for line in answer.splitlines() if not NUMERIC_JUDGMENT.search(line)).strip()


async def stream_text_draft(
    store,
    session: Session,
    label: str,
    rows: bool,
    on_chunk: Callable[[str], None],
    connect_fn=None,
    on_start: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    if selected_provider(store) == "off":
        raise ValueError("AI is off. Enter your own text instead.")
    provider, config = await (connect_fn or connect)(store)
    if not remote_consent(store, config):
        raise ValueError(
            f"Review remote AI consent for {config.preset.label} in Settings before sharing this analysis."
        )
    if on_start:
        on_start(
            f"{sharing_destination(config)} · Sharing: method, problem, objective, assumptions, full method state (not notes or history)"
        )
    question = (
        f"Suggest {'a few distinct lines for' if rows else 'one short draft for'} {label}. "
        "Return plain text only; no scores, weights, probabilities, confidence, impact, dates, "
        "numeric judgments, invented evidence, or JSON. The user must review and accept it."
    )
    partial = ""
    async for chunk in provider.stream(AIRequest(question, context_for(session))):
        partial += chunk
        on_chunk(text_only(visible_text(partial)))
    answer = text_only(visible_text(partial))
    if not answer:
        raise ValueError("AI returned no text without numeric judgments. Nothing was changed.")
    return answer, describe(config)


class FieldHelpMixin:
    """Shared preview/stream/Stop lifecycle. Screens implement apply_field_help()."""

    def field_help_request(self, label: str, target: str, *, rows: bool = False) -> None:
        if selected_provider(self.app.store) == "off":
            self.query_one("#field-help-status", Static).update("AI is off. All fields work without AI.")
            return
        if any(worker.group == "field-help" and worker.is_running for worker in self.workers):
            return
        self._field_help_target = target
        self._field_help_rows = rows
        self._field_help_ready = False
        self._field_help_partial = ""
        self._field_help_destination = ""
        self.query_one("#field-help-preview", TextArea).load_text("")
        self.query_one("#field-help-status", Static).update(
            "Sharing: method, problem, objective, assumptions, full method state · connecting to AI… Ctrl+G stops."
        )
        self.run_worker(self._field_help_stream(label), group="field-help", exclusive=True)

    async def _field_help_stream(self, label: str) -> None:
        def update(text: str) -> None:
            self._field_help_partial = text
            self.query_one("#field-help-preview", TextArea).load_text(text)
            self.query_one("#field-help-status", Static).update(
                f"{self._field_help_destination} · AI suggestion streaming · {len(text.split())} words · not saved · Ctrl+G stops"
            )

        def start(message: str) -> None:
            self._field_help_destination = message
            self.query_one("#field-help-status", Static).update(message)

        try:
            answer, provider = await stream_text_draft(
                self.app.store,
                self.field_help_session(),
                label,
                self._field_help_rows,
                update,
                on_start=start,
            )
            self.query_one("#field-help-preview", TextArea).load_text(answer)
            self._field_help_ready = True
            self.query_one("#field-help-status", Static).update(
                f"{self._field_help_destination}\n{provider} · edit, Accept or Dismiss. Not saved."
            )
        except ValueError as exc:
            self.query_one("#field-help-status", Static).update(str(exc))
        except (RuntimeError, KeyError) as exc:
            self.query_one("#field-help-status", Static).update(
                f"AI unavailable: {public_error(exc)}. Your analysis is preserved."
            )

    def field_help_session(self) -> Session:
        raise NotImplementedError

    def apply_field_help(self, target: str, text: str, rows: bool) -> None:
        raise NotImplementedError

    def field_help_accept(self) -> None:
        if not getattr(self, "_field_help_ready", False) or any(
            worker.group == "field-help" and worker.is_running for worker in self.workers
        ):
            return
        text = self.query_one("#field-help-preview", TextArea).text.strip()
        if not text:
            self.query_one("#field-help-status", Static).update("Enter text before accepting.")
            return
        self.apply_field_help(self._field_help_target, text, self._field_help_rows)
        self.field_help_dismiss()
        self.query_one("#field-help-status", Static).update("Edited text accepted; numeric judgments remain yours.")

    def field_help_dismiss(self) -> None:
        self._field_help_ready = False
        self._field_help_target = ""
        self.query_one("#field-help-preview", TextArea).load_text("")

    def field_help_stop(self) -> None:
        if any(worker.group == "field-help" and worker.is_running for worker in self.workers):
            self.workers.cancel_group(self, "field-help")
            self._field_help_ready = False
            self._field_help_target = ""
            self.query_one("#field-help-preview", TextArea).load_text(getattr(self, "_field_help_partial", ""))
            self.query_one("#field-help-status", Static).update(
                "AI stopped · partial text visible, never accepted or saved."
            )
