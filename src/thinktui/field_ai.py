"""Shared, opt-in text-only drafting for form, guided, and dedicated editors.

Only a user's explicit Accept may move proposed prose into an editor. Numerical
judgments, including dates, are never supplied by this helper.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.widgets import Static, TextArea

from .ai import AIRequest, connect, context_for, describe, is_local, selected_provider, visible_text
from .core import Session


async def stream_text_draft(
    store, session: Session, label: str, rows: bool, on_chunk: Callable[[str], None], connect_fn=None
) -> tuple[str, str]:
    if selected_provider(store) == "off":
        raise ValueError("AI is off. Enter your own text instead.")
    provider, config = await (connect_fn or connect)(store)
    if not is_local(config) and store.setting("ai_consent") != "yes":
        raise ValueError("Review AI privacy and consent in Settings before sharing this analysis.")
    question = (
        f"Suggest {'a few distinct lines for' if rows else 'one short draft for'} {label}. "
        "Return plain text only; no scores, weights, probabilities, confidence, impact, dates, "
        "numeric judgments, invented evidence, or JSON. The user must review and accept it."
    )
    partial = ""
    async for chunk in provider.stream(AIRequest(question, context_for(session))):
        partial += chunk
        on_chunk(visible_text(partial))
    answer = visible_text(partial).strip()
    if not answer or any(character.isdigit() for character in answer):
        raise ValueError("AI returned empty or numeric text. Nothing was changed.")
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
        self.query_one("#field-help-preview", TextArea).load_text("")
        self.query_one("#field-help-status", Static).update("Connecting to AI… Ctrl+G stops.")
        self.run_worker(self._field_help_stream(label), group="field-help", exclusive=True)

    async def _field_help_stream(self, label: str) -> None:
        def update(text: str) -> None:
            self._field_help_partial = text
            self.query_one("#field-help-preview", TextArea).load_text(text)
            self.query_one("#field-help-status", Static).update(
                f"AI suggestion streaming · {len(text.split())} words · not saved · Ctrl+G stops"
            )

        try:
            answer, provider = await stream_text_draft(
                self.app.store, self.field_help_session(), label, self._field_help_rows, update
            )
            self.query_one("#field-help-preview", TextArea).load_text(answer)
            self._field_help_ready = True
            self.query_one("#field-help-status", Static).update(f"{provider} · edit, Accept or Dismiss. Not saved.")
        except ValueError as exc:
            self.query_one("#field-help-status", Static).update(str(exc))
        except (RuntimeError, KeyError):
            self.query_one("#field-help-status", Static).update("AI unavailable. Your analysis is preserved.")

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
        if not text or any(character.isdigit() for character in text):
            self.query_one("#field-help-status", Static).update(
                "Enter text only; supply all numeric judgments yourself."
            )
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
