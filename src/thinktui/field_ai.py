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
    selected_provider,
    sharing_destination,
    visible_text,
)
from .ai_setup import AISetupRequired, prompt_ai_setup, prompt_missing_key, require_ai_setup
from .core import Session

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_JUDGMENT = r"(?:score|weight|probability|confidence|rating|likelihood|impact|cost|risk|odds)"
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
NUMERIC_JUDGMENT = re.compile(
    rf"(?:\b(?:{_JUDGMENT}|date|deadline)\b"
    rf"(?:\s+(?:is|was|of|at|about|around|equals|to|as|rated|score|rating|failure|success|event|outcome|the|a|an|our|your|its|this)){{0,5}}\s*[:=~]?\s*{_NUMBER}\b"
    rf"|(?<![A-Za-z]){_NUMBER}\b(?:\s+(?:is|was|the|a|an|of|for|as|at|about|around|estimated|your|its|this)){{0,4}}\s+{_JUDGMENT}\b"
    rf"|\b(?:scored?|scores|scoring|rated?|rates|rating)\b(?:\s+(?:it|as|at|about|around|the|option)){{0,3}}\s+{_NUMBER}\b"
    rf"|(?<![A-Za-z]){_NUMBER}\s*/\s*\d+\b"
    rf"|{_NUMBER}\s*(?:%|\bpercent(?:age)?\b|\bpct\b)"
    rf"|\b\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}\b|\b\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b(?:\s+\d{{4}}\b)?"
    rf"|\b{_MONTH}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{4}})\b"
    rf"|\b{_NUMBER}\s+out\s+of\s+\d+\b|^\s*{_NUMBER}\s*$)",
    re.IGNORECASE,
)


_NUMERIC_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"hundred|thousand|million|percent|half|quarter)\b|[\d\u00bc-\u00be\u2150-\u2189]",
    re.IGNORECASE,
)


_PROVENANCE_FIELDS = {
    "evidence",
    "source",
    "sources",
    "provenance",
    "observations",
    "cases",
    "supporting",
    "contradicting",
}


def can_draft_path(method_id: str, path: tuple[object, ...]) -> bool:
    """Evidence and source claims must originate with the user, not with AI."""
    return not any(str(part).casefold() in _PROVENANCE_FIELDS for part in path)


def text_only(answer: str) -> str:
    """Discard whole AI lines that could supply quantitative judgments."""

    def safe_line(line: str) -> bool:
        # Phase names and quarter labels are identifiers, not quantitative ratings.
        without_identifiers = re.sub(r"\b(?:Phase\s+\d+|Q[1-4])\b", "", line, flags=re.IGNORECASE)
        return not _NUMERIC_WORDS.search(without_identifiers)

    return "\n".join(line for line in answer.splitlines() if safe_line(line)).strip()


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
    await require_ai_setup(store, provider, config)
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
        except AISetupRequired as exc:
            self.query_one("#field-help-status", Static).update("AI request not sent. Complete setup in Settings.")
            prompt_ai_setup(self.app, exc)
        except ValueError as exc:
            self.query_one("#field-help-status", Static).update(str(exc))
        except Exception as exc:
            if prompt_missing_key(self.app, exc):
                self.query_one("#field-help-status", Static).update(
                    "API key needed or rejected. No draft was accepted."
                )
            else:
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
        if text_only(text) != text:
            self.query_one("#field-help-status", Static).update("Remove numeric judgments before accepting AI text.")
            return
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
