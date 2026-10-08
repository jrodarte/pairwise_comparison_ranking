"""Keyboard-first, autosaved steps for the five flagship analytical workflows."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea

from .context_offers import offers
from .core import METHODS, Session, timestamp
from .field_ai import FieldHelpMixin
from .guided_workflow import (
    GUIDED,
    LabelMappingRequired,
    MatrixMappingRequired,
    ScenarioMappingRequired,
    advance,
    definition,
    final_index,
    next_index,
    reachable_index,
)
from .label_mapping_screen import LabelMappingDialog
from .matrix_mapping_screen import MatrixMappingDialog
from .planning import planned_next, sensitivity_from_matrix, sensitivity_pair
from .reports import export, plain_result


class GuidedScreen(FieldHelpMixin, Screen):
    BINDINGS = [
        ("f8", "next", "Validate & next"),
        ("f7", "previous", "Previous"),
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "next", "Save step"),
        ("ctrl+e", "export", "Export"),
        Binding("ctrl+g", "stop_ai", "Stop AI", priority=True),
        ("escape", "project", "Project"),
    ]

    def __init__(self, session: Session) -> None:
        if session.method_id not in GUIDED:
            raise ValueError("No guided screen for this method")
        super().__init__()
        self.session = session
        state = session.method_state
        stored_step = state.get("_guided_step")
        if not isinstance(stored_step, int) or isinstance(stored_step, bool):
            stored_step = final_index(session.method_id, state) if not METHODS[session.method_id].validate(state) else 0
        self.index = max(0, min(stored_step, reachable_index(session.method_id, state)))
        # UI-only drafts. They never replace saved judgments until Validate & next.
        self.matrix_rows: list[dict[str, str]] | None = None
        self.matrix_bulk = ""
        self.matrix_mode = "rows"
        self.editing_index: int | None = None

    def compose(self) -> ComposeResult:
        method = METHODS[self.session.method_id]
        step = definition(self.session.method_id, self.session.method_state, self.index)
        yield Header()
        with Horizontal(classes="workspace-layout") as layout:
            layout.set_class(self.size.width < 100, "narrow")
            layout.set_class(self.size.width < 72, "very-narrow")
            with VerticalScroll(classes="editor-pane"):
                yield Label(f"{self.session.title} · {method.name}", classes="hero")
                yield Static(
                    f"Step {self.index + 1} of {final_index(method.id, self.session.method_state) + 1} · {step.title}",
                    classes="heading",
                    id="step-heading",
                )
                yield Static(step.help, classes="muted")
                if method.id == "matrix" and self.index == 0:
                    available = offers("matrix", self.app.store.sessions(self.session.project_id), self.session.id)
                    if available:
                        yield Static(
                            "Earlier value-focused analysis: "
                            + "; ".join(f"{key}: {', '.join(values)}" for key, values in available.items())
                            + ". Labels only; you supply weights and scores.",
                            classes="muted",
                        )
                        yield Button("Use these starting points", id="use-offer")
                if method.id == "matrix" and self.index == 2:
                    criteria = self.session.method_state.get("criteria", [])
                    alternatives = self.session.method_state.get("alternatives", [])
                    yield Static(
                        "Scores grid · rows are options, columns are your criteria. Use Tab to move between cells. "
                        "Why: each 0–10 score changes the ranking; for cost, higher means more costly.",
                        classes="muted",
                    )
                    with HorizontalScroll(classes="matrix-score-scroll"):
                        with Vertical(classes="matrix-score-table") as table:
                            column_width = max(18, min(50, max((len(c["name"]) + 8 for c in criteria), default=18)))
                            table.styles.width = 22 + column_width * len(criteria)
                            with Horizontal(classes="matrix-grid-row"):
                                yield Label("Option", classes="matrix-grid-name")
                                for criterion in criteria:
                                    direction = "↑" if criterion["direction"] == "benefit" else "↓"
                                    caption = (
                                        f"{criterion['name']} ({direction}, weight {criterion.get('weight', '?')})"
                                    )
                                    header = Label(caption, classes="matrix-grid-cell")
                                    header.styles.width = column_width
                                    header.tooltip = caption
                                    yield header
                            for i, alternative in enumerate(alternatives):
                                with Horizontal(classes="matrix-grid-row"):
                                    yield Label(str(alternative["name"]), classes="matrix-grid-name")
                                    for j, criterion in enumerate(criteria):
                                        field = next(field for field in step.fields if field.key == f"score_{i}_{j}")
                                        with Vertical(classes="matrix-grid-cell") as cell:
                                            cell.styles.width = column_width
                                            yield Input(
                                                value=field.value,
                                                placeholder="0–10",
                                                id=f"field-{field.key}",
                                                tooltip=f"{alternative['name']} · {criterion['name']}: your score matters to the ranking.",
                                            )
                                            yield Static("", id=f"guided-error-{field.key}", classes="muted")
                elif method.id == "matrix" and self.index in (0, 1):
                    yield from self.compose_matrix_rows(step)
                else:
                    if method.id == "forecasting" and self.index == 2:
                        forecasts = self.session.method_state.get("forecasts", [])
                        yield Label("Choose a saved forecast to resolve", classes="heading")
                        yield Select(
                            [(f"{i + 1}. {row['question']}", i) for i, row in enumerate(forecasts)],
                            value=len(forecasts) - 1,
                            allow_blank=False,
                            id="forecast-picker",
                        )
                    for field in step.fields:
                        yield Label(field.label, classes="heading")
                        yield Static(
                            (field.help or f"Enter your own {field.label.lower()}.")
                            + " Why: "
                            + (field.why or "This input explains or changes the local calculation."),
                            classes="muted",
                        )
                        with Horizontal(classes="field-editor"):
                            if field.multiline:
                                yield TextArea(field.value, id=f"field-{field.key}")
                            else:
                                yield Input(value=field.value, placeholder=field.label, id=f"field-{field.key}")
                            if self.can_suggest(field.key):
                                yield Button(
                                    "Draft text",
                                    id=f"help-suggest-{field.key}",
                                    classes="ai-trigger",
                                    tooltip=f"Draft text for {field.label}; review and Accept before use",
                                )
                        yield Static("", id=f"guided-error-{field.key}", classes="muted")
                if step.review:
                    try:
                        issues = method.validate(self.session.method_state)
                        result = (
                            "Complete the missing judgments:\n" + "\n".join(issues)
                            if issues
                            else plain_result(method.calculate(self.session.method_state))
                        )
                    except (ValueError, TypeError, KeyError) as exc:
                        result = "Review the analysis: " + str(exc)
                    yield Static(result, id="guided-results", classes="muted", markup=False)
                    if method.id in {"ach", "scenarios"}:
                        key = "evidence" if method.id == "ach" else "strategies"
                        saved = self.session.method_state.get(key, [])
                        if saved:
                            yield Label("Saved " + key + " · select a row to edit or delete", classes="heading")
                            yield Select(
                                [
                                    (f"{i + 1}. {row.get('title', row.get('name', 'Entry'))}", i)
                                    for i, row in enumerate(saved)
                                ],
                                value=0,
                                allow_blank=False,
                                id="saved-picker",
                            )
                            with Horizontal(classes="actions"):
                                yield Button("Edit selected " + key, id="edit-saved")
                                yield Button("Delete selected " + key, id="delete-saved")
                    if method.id == "matrix":
                        eligible = not issues and len(self.session.method_state.get("criteria", [])) >= 2
                        if eligible:
                            first, second = sensitivity_pair(self.session)
                            options = [
                                (f"{i + 1}. {row['name']}", i)
                                for i, row in enumerate(self.session.method_state["alternatives"])
                            ]
                            yield Static(
                                "Choose two options (top two ranked by default) for a separate sensitivity draft.",
                                classes="muted",
                            )
                            yield Select(options, value=first, allow_blank=False, id="sensitivity-first")
                            yield Select(options, value=second, allow_blank=False, id="sensitivity-second")
                        yield Button(
                            "Test sensitivity of two options",
                            id="sensitivity",
                            disabled=not eligible,
                            tooltip="Requires a scored matrix and at least two criteria",
                        )
                        if not eligible:
                            yield Static(
                                "Sensitivity requires a scored matrix and at least two criteria.", classes="muted"
                            )
                    yield Input(
                        placeholder="Export decision brief: /path/to/brief.md or analysis.json", id="guided-export-path"
                    )
                with Horizontal(classes="actions"):
                    yield Button("← Previous  F7", id="previous", disabled=self.index == 0)
                    yield Button(
                        "Finish & save" if step.review else "Validate & next  F8", id="next", variant="primary"
                    )
                    if step.review and self.session.method_id in {"ach", "forecasting", "scenarios"}:
                        yield Button(
                            "Add more evidence"
                            if method.id == "ach"
                            else "Add forecast"
                            if method.id == "forecasting"
                            else "Add strategy",
                            id="more",
                        )
                    if (
                        not step.review
                        and self.session.method_id in {"ach", "forecasting", "scenarios"}
                        and not method.validate(self.session.method_state)
                    ):
                        yield Button("Return to saved review (discard this step's edits)", id="review")
                    if step.review:
                        yield Button("Export  Ctrl+E", id="export")
                        if planned_next(self.session):
                            yield Button("Continue planned workflow", id="plan")
                    yield Button("Advanced JSON  F6", id="advanced")
                    yield Button("Project  Esc", id="project")
            with VerticalScroll(classes="ai-pane"):
                yield Static("AI draft · review before accepting", classes="heading")
                yield Static(
                    "REMOTE → selected provider unless local. Sharing: method, problem, objective, assumptions and full method state. Not notes or history.",
                    classes="muted",
                )
                yield Static(
                    "Suggestions are never saved without Accept. Numeric judgments are yours.", classes="muted"
                )
                yield Static("", id="field-help-status", classes="muted")
                yield TextArea(id="field-help-preview")
                with Horizontal(classes="ai-actions"):
                    yield Button("Accept", id="help-accept")
                    yield Button("Dismiss", id="help-dismiss")
                    yield Button("Stop  Ctrl+G", id="help-stop")
        yield Footer()

    def compose_matrix_rows(self, step) -> ComposeResult:
        """Editable rows are primary; the original text syntax remains an optional bulk import."""
        if self.matrix_rows is None:
            key = "alternatives" if self.index == 0 else "criteria"
            saved = self.session.method_state.get(key, [])
            self.matrix_rows = (
                [
                    {
                        "name": row["name"],
                        "weight": "" if row.get("weight") is None else str(row["weight"]),
                        "direction": row.get("direction", "benefit"),
                    }
                    for row in saved
                ]
                if saved
                else [{"name": "", "weight": "", "direction": ""} for _ in range(2 if self.index == 0 else 1)]
            )
            self.matrix_bulk = step.fields[0].value
            self.matrix_mode = "rows"
        if self.index == 0:
            yield Static(
                "Add at least two distinct options. Include doing nothing if it is a real choice.", classes="muted"
            )
        else:
            yield Static(
                "Weight: your relative importance (0 or greater; at least one positive). "
                "Benefit: higher score is better. Cost: lower score is better. Weights normalize automatically.",
                classes="muted",
            )
        if self.index == 1:
            with Horizontal(classes="matrix-entry-header"):
                yield Label("Criterion", classes="matrix-col-name")
                yield Label("Weight", classes="matrix-col-weight")
                yield Label("Better when…", classes="matrix-col-direction")
                yield Label("", classes="matrix-col-remove")
        for i, row in enumerate(self.matrix_rows):
            yield Label(f"{'Option' if self.index == 0 else 'Criterion'} {i + 1}", classes="heading")
            with Horizontal(classes="matrix-entry-row"):
                yield Input(value=row["name"], placeholder="Name", id=f"matrix-row-{i}-name")
                if self.index == 1:
                    yield Input(
                        value=row["weight"],
                        placeholder="Weight",
                        id=f"matrix-row-{i}-weight",
                        classes="matrix-weight",
                        tooltip="Your relative importance, zero or greater. At least one weight must be positive.",
                    )
                    yield Select(
                        [("— Choose direction —", ""), ("↑ Benefit", "benefit"), ("↓ Cost", "cost")],
                        value=row["direction"],
                        allow_blank=False,
                        id=f"matrix-row-{i}-direction",
                    )
                yield Button("Remove", id=f"matrix-remove-{i}")
        yield Button("Add option" if self.index == 0 else "Add criterion", id="matrix-add")
        yield Static("", id="matrix-rows-error", classes="muted")
        yield Static(
            (
                "Bulk paste (optional): one option per line. "
                if self.index == 0
                else "Bulk paste (optional): Name | weight | benefit or cost, one per line. "
            )
            + "Editing this box replaces the rows above when you continue; editing a row switches back.",
            classes="muted",
        )
        with Horizontal(classes="field-editor"):
            yield TextArea(self.matrix_bulk, id=f"field-{step.fields[0].key}")
            yield Button(
                "Suggest labels",
                id=f"help-suggest-{step.fields[0].key}",
                classes="ai-trigger",
                tooltip="Draft labels in the bulk paste editor; review before using",
            )
        yield Static("", id=f"guided-error-{step.fields[0].key}", classes="muted")

    def read_matrix_rows(self) -> bool:
        """Read mounted editors synchronously (F8 may precede Changed messages)."""
        assert self.matrix_rows is not None
        changed = False
        for i, row in enumerate(self.matrix_rows):
            for key in ("name",) if self.index == 0 else ("name", "weight"):
                value = self.query_one(f"#matrix-row-{i}-{key}", Input).value
                changed |= value != row[key]
                row[key] = value
            if self.index == 1:
                value = str(self.query_one(f"#matrix-row-{i}-direction", Select).value)
                changed |= value != row["direction"]
                row["direction"] = value
        if changed:
            self.matrix_bulk = self.query_one(
                "#field-alternatives" if self.index == 0 else "#field-criteria", TextArea
            ).text
            self.matrix_mode = "rows"
        return changed

    def matrix_uses_bulk(self) -> bool:
        key = "alternatives" if self.index == 0 else "criteria"
        # load_text() updates the widget before its Changed event is dispatched.
        self.read_matrix_rows()
        return self.matrix_mode == "bulk" or self.query_one(f"#field-{key}", TextArea).text != self.matrix_bulk

    def matrix_values(self) -> dict[str, str]:
        assert self.matrix_rows is not None
        key = "alternatives" if self.index == 0 else "criteria"
        if self.matrix_uses_bulk():
            return {key: self.query_one(f"#field-{key}", TextArea).text}
        if self.index == 0:
            return {key: "\n".join(row["name"].strip() for row in self.matrix_rows)}
        return {
            key: "\n".join(
                f"{row['name'].strip()} | {row['weight'].strip()} | {row['direction']}" for row in self.matrix_rows
            )
        }

    def can_suggest(self, key: str) -> bool:
        return key in {
            "alternatives",
            "criteria",
            "hypotheses",
            "title",
            "source",
            "question",
            "rationale",
            "narrative",
            "implications",
            "indicators",
            "name",
            "drivers",
            "axes",
        } or key.startswith("action_")

    def field_help_session(self) -> Session:
        draft = deepcopy(self.session)
        if self.index != final_index(self.session.method_id, self.session.method_state):
            draft.method_state = {**draft.method_state, "_draft_fields": self.current_values()}
        return draft

    def apply_field_help(self, target: str, text: str, rows: bool) -> None:
        if target not in {
            field.key for field in definition(self.session.method_id, self.session.method_state, self.index).fields
        }:
            return
        widget = self.query_one(f"#field-{target}")
        if isinstance(widget, (Input, TextArea)):
            current = widget.value if isinstance(widget, Input) else widget.text
            if self.session.method_id == "matrix" and self.index in (0, 1) and rows and not self.matrix_uses_bulk():
                # Keep existing user-entered rows when accepting an AI draft into the bulk editor.
                assert self.matrix_rows is not None
                if self.index == 0:
                    current = "\n".join(row["name"].strip() for row in self.matrix_rows if row["name"].strip())
                else:
                    current = "\n".join(
                        f"{row['name'].strip()} | {row['weight'].strip()} | {row['direction']}"
                        for row in self.matrix_rows
                        if row["name"].strip() or row["weight"].strip() or row["direction"]
                    )
            value = (current.rstrip() + "\n" + text).strip() if rows and current.strip() else text
            if isinstance(widget, TextArea):
                widget.load_text(value)
            else:
                widget.value = value

    def guided_issue(self, key: str, text: str) -> str:
        if not text.strip():
            return "Enter your own input before continuing."
        if key.startswith("score_"):
            try:
                value = float(text)
                if not 0 <= value <= 10:
                    raise ValueError
            except ValueError:
                return "Enter your own score from 0 to 10."
        if self.session.method_id == "matrix" and (self.index, key) in {(0, "alternatives"), (1, "criteria")}:
            try:
                advance("matrix", self.session.method_state, self.index, {key: text})
            except (ValueError, KeyError) as exc:
                return str(exc)
        return ""

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("matrix-row-") and self.matrix_rows is not None:
            _, _, index, key = event.input.id.split("-")
            if self.matrix_rows[int(index)][key] != event.value:
                self.matrix_rows[int(index)][key] = event.value
                self.matrix_bulk = self.query_one(
                    "#field-alternatives" if self.index == 0 else "#field-criteria", TextArea
                ).text
                self.matrix_mode = "rows"
                self.query_one("#matrix-rows-error", Static).update("")
        if event.input.id and event.input.id.startswith("field-"):
            key = event.input.id.removeprefix("field-")
            targets = self.query(f"#guided-error-{key}")
            if targets:
                targets.first().update(self.guided_issue(key, event.value))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "forecast-picker" and event.value is not Select.BLANK:
            forecast = self.session.method_state["forecasts"][int(event.value)]
            outcome = forecast.get("outcome")
            self.query_one("#field-outcome", Input).value = "?" if outcome is None else "yes" if outcome == 1 else "no"
        if event.select.id and event.select.id.startswith("matrix-row-") and self.matrix_rows is not None:
            _, _, index, key = event.select.id.split("-")
            value = str(event.value)
            if value != self.matrix_rows[int(index)][key]:
                self.matrix_rows[int(index)][key] = value
                self.matrix_bulk = self.query_one("#field-criteria", TextArea).text
                self.matrix_mode = "rows"
                self.query_one("#matrix-rows-error", Static).update("")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if (
            self.session.method_id == "matrix"
            and self.index in (0, 1)
            and event.text_area.id == ("field-alternatives" if self.index == 0 else "field-criteria")
            and event.text_area.text != self.matrix_bulk
        ):
            self.matrix_bulk = event.text_area.text
            self.matrix_mode = "bulk"
        if event.text_area.id and event.text_area.id.startswith("field-"):
            key = event.text_area.id.removeprefix("field-")
            targets = self.query(f"#guided-error-{key}")
            if targets:
                targets.first().update(self.guided_issue(key, event.text_area.text))

    def action_stop_ai(self) -> None:
        self.field_help_stop()

    def on_resize(self) -> None:
        layout = self.query_one(".workspace-layout")
        layout.set_class(self.size.width < 100, "narrow")
        layout.set_class(self.size.width < 72, "very-narrow")

    def on_mount(self) -> None:
        self.on_resize()
        self.focus_first()

    def focus_first(self) -> None:
        if self.session.method_id == "matrix" and self.index in (0, 1):
            self.query_one("#matrix-row-0-name", Input).focus()
            return
        fields = definition(self.session.method_id, self.session.method_state, self.index).fields
        if fields:
            self.query_one(f"#field-{fields[0].key}").focus()
        else:
            self.query_one("#next", Button).focus()

    def current_values(self) -> dict[str, str]:
        if self.session.method_id == "matrix" and self.index in (0, 1):
            return self.matrix_values()
        step = definition(self.session.method_id, self.session.method_state, self.index)
        values = {
            field.key: (
                self.query_one(f"#field-{field.key}", TextArea).text
                if field.multiline
                else self.query_one(f"#field-{field.key}", Input).value
            )
            for field in step.fields
        }
        if self.session.method_id == "forecasting" and self.index == 2:
            values["forecast_index"] = str(self.query_one("#forecast-picker", Select).value)
        return values

    async def action_next(self) -> None:
        method = self.session.method_id
        values = self.current_values()
        if self.editing_index is not None and (
            (method == "ach" and self.index == 1) or (method == "scenarios" and self.index == 6)
        ):
            values["edit_index"] = str(self.editing_index)
        try:
            if method == "matrix" and self.index in (0, 1) and not self.matrix_uses_bulk():
                assert self.matrix_rows is not None
                if any(not row["name"].strip() or "|" in row["name"] for row in self.matrix_rows):
                    raise ValueError("Give every row a name without |, or remove unused rows.")
                if self.index == 1 and any(not row["weight"].strip() for row in self.matrix_rows):
                    raise ValueError("Enter your own weight for every criterion (zero is allowed).")
                if self.index == 1 and any(row["direction"] not in {"benefit", "cost"} for row in self.matrix_rows):
                    raise ValueError("Choose Benefit (higher is better) or Cost (lower is better) for every criterion.")
            state = advance(method, self.session.method_state, self.index, values)
        except MatrixMappingRequired as request:
            self.app.push_screen(
                MatrixMappingDialog(self.session.method_state, request, values), self.mapping_confirmed
            )
            return
        except (LabelMappingRequired, ScenarioMappingRequired) as request:
            self.app.push_screen(LabelMappingDialog(self.session.method_state, request, values), self.mapping_confirmed)
            return
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            if method == "matrix" and self.index in (0, 1):
                self.query_one("#matrix-rows-error", Static).update(str(exc))
            self.notify(str(exc), severity="error")
            return
        await self.commit_next(state)

    def mapping_confirmed(self, state: dict | None) -> None:
        if state is not None:
            self.run_worker(self.commit_next(state), group="matrix-edit", exclusive=True)

    async def commit_next(self, state: dict) -> None:
        method = self.session.method_id
        is_review = self.index == final_index(method, state)
        self.index = next_index(method, state, self.index)
        state["_guided_step"] = self.index
        self.session.method_state = state
        self.session.completed_at = timestamp() if is_review else None
        self.app.store.save(
            self.session, f"Guided {method}: {self.index + 1} · " + ("Reviewed" if is_review else "Saved step")
        )
        self.field_help_stop()
        self.field_help_dismiss()
        self.editing_index = None
        self.matrix_rows = None
        await self.recompose()
        self.focus_first()
        if is_review:
            self.notify("Analysis saved; results are calculated locally")

    async def action_previous(self) -> None:
        if self.index:
            self.editing_index = None
            self.index -= 1
            self.matrix_rows = None
            self.session.method_state["_guided_step"] = self.index
            self.app.store.save(self.session, "Revisited guided step")
            self.field_help_stop()
            self.field_help_dismiss()
            await self.recompose()
            self.focus_first()

    async def action_edit_saved(self) -> None:
        if self.session.method_id not in {"ach", "scenarios"} or not self.query("#saved-picker"):
            return
        selected = self.query_one("#saved-picker", Select).value
        if selected is Select.BLANK:
            return
        self.editing_index = int(selected)
        if self.session.method_id == "ach":
            row = self.session.method_state["evidence"][self.editing_index]
            self.index = 1
            values = {
                "title": row["title"],
                "source": row.get("source", ""),
                "reliability": str(row["reliability"]),
                **{
                    f"rating_{i}": row["ratings"][label]
                    for i, label in enumerate(self.session.method_state["hypotheses"])
                },
            }
        else:
            from .guided_workflow import QUADRANTS

            row = self.session.method_state["strategies"][self.editing_index]
            self.index = 6
            values = {"name": row["name"], **{f"action_{q}": row["actions"][q] for q in QUADRANTS}}
        await self.recompose()
        for key, value in values.items():
            self.query_one(f"#field-{key}", Input).value = value
        self.focus_first()

    def action_delete_saved(self) -> None:
        if self.session.method_id not in {"ach", "scenarios"} or not self.query("#saved-picker"):
            return
        selected = self.query_one("#saved-picker", Select).value
        if selected is Select.BLANK:
            return
        key = "evidence" if self.session.method_id == "ach" else "strategies"
        index = int(selected)
        row = self.session.method_state[key][index]
        from .screens import AnalysisDialog

        def finish(value: str | None) -> None:
            if value != "DELETE":
                return
            self.session.method_state[key].pop(index)
            self.app.store.save(self.session, "Deleted guided " + key + " entry")
            self.run_worker(self.recompose(), group="guided-delete", exclusive=True)

        self.app.push_screen(AnalysisDialog(row.get("title", row.get("name", "Entry")), delete=True), finish)

    async def action_more(self) -> None:
        if self.index != final_index(self.session.method_id, self.session.method_state):
            return
        self.editing_index = None
        self.index = {"ach": 1, "forecasting": 0, "scenarios": 6}[self.session.method_id]
        self.session.method_state["_guided_step"] = self.index
        self.app.store.save(self.session, "Opened another guided entry")
        await self.recompose()
        self.focus_first()

    def action_sensitivity(self) -> None:
        if self.session.method_id != "matrix" or self.index != final_index("matrix", self.session.method_state):
            return
        try:
            pair = (
                self.query_one("#sensitivity-first", Select).value,
                self.query_one("#sensitivity-second", Select).value,
            )
            analysis = sensitivity_from_matrix(self.session, pair)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.app.store.save(analysis, "Created sensitivity analysis from " + self.session.id)
        self.app.open_session(analysis, guided=True)
        self.notify("Copied matrix judgments; change the varied criterion and range to explore tradeoffs")

    def action_plan(self) -> None:
        from .planning_screen import PlanningScreen

        self.app.switch_screen(PlanningScreen(self.session))

    async def action_review(self) -> None:
        self.editing_index = None
        self.index = final_index(self.session.method_id, self.session.method_state)
        self.matrix_rows = None
        self.session.method_state["_guided_step"] = self.index
        self.app.store.save(self.session, "Returned to guided review")
        await self.recompose()
        self.focus_first()

    def action_advanced(self) -> None:
        self.app.open_session(self.session)

    def action_export(self) -> None:
        if self.index != final_index(self.session.method_id, self.session.method_state):
            self.notify("Save this step and reach review before exporting", severity="warning")
            return
        value = self.query_one("#guided-export-path", Input).value.strip()
        if not value:
            self.query_one("#guided-export-path", Input).focus()
            self.notify("Enter an export path", severity="warning")
            return
        try:
            export(self.session, Path(value).expanduser(), store=self.app.store)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Exported {value}")

    def action_project(self) -> None:
        self.app.show_project()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "matrix-add":
            self.read_matrix_rows()
            self.matrix_rows.append({"name": "", "weight": "", "direction": ""})
            self.matrix_bulk = self.query_one(
                "#field-alternatives" if self.index == 0 else "#field-criteria", TextArea
            ).text
            self.matrix_mode = "rows"
            index = len(self.matrix_rows) - 1
            await self.recompose()
            self.query_one(f"#matrix-row-{index}-name", Input).focus()
        elif event.button.id and event.button.id.startswith("matrix-remove-"):
            self.read_matrix_rows()
            index = int(event.button.id.removeprefix("matrix-remove-"))
            self.matrix_rows.pop(index)
            if not self.matrix_rows:
                self.matrix_rows.append({"name": "", "weight": "", "direction": ""})
            self.matrix_bulk = self.query_one(
                "#field-alternatives" if self.index == 0 else "#field-criteria", TextArea
            ).text
            self.matrix_mode = "rows"
            await self.recompose()
            self.query_one(f"#matrix-row-{min(index, len(self.matrix_rows) - 1)}-name", Input).focus()
        elif event.button.id == "next":
            await self.action_next()
        elif event.button.id == "previous":
            await self.action_previous()
        elif event.button.id == "more":
            await self.action_more()
        elif event.button.id == "edit-saved":
            await self.action_edit_saved()
        elif event.button.id == "delete-saved":
            self.action_delete_saved()
        elif event.button.id == "advanced":
            self.action_advanced()
        elif event.button.id == "export":
            self.action_export()
        elif event.button.id == "plan":
            self.action_plan()
        elif event.button.id == "sensitivity":
            self.action_sensitivity()
        elif event.button.id == "review":
            await self.action_review()
        elif event.button.id and event.button.id.startswith("help-suggest-"):
            key = event.button.id.removeprefix("help-suggest-")
            if self.can_suggest(key):
                field = next(
                    field
                    for field in definition(self.session.method_id, self.session.method_state, self.index).fields
                    if field.key == key
                )
                self.field_help_request(field.label, key, rows=key in {"alternatives", "criteria", "hypotheses"})
        elif event.button.id == "help-accept":
            self.field_help_accept()
        elif event.button.id == "help-dismiss":
            self.field_help_dismiss()
        elif event.button.id == "help-stop":
            self.field_help_stop()
        elif event.button.id == "use-offer":
            available = offers("matrix", self.app.store.sessions(self.session.project_id), self.session.id)
            state = self.session.method_state
            if not state.get("alternatives"):
                state["alternatives"] = [{"name": label, "scores": []} for label in available.get("alternatives", [])]
            if not state.get("criteria"):
                state["criteria"] = [
                    {"name": label, "weight": None, "direction": "benefit"} for label in available.get("criteria", [])
                ]
            self.app.store.save(self.session, "Accepted text-only value-focused starting points")
            self.matrix_rows = None
            await self.recompose()
        else:
            self.action_project()
