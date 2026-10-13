"""Keyboard-accessible forms for structured methods; raw JSON remains an advanced view."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Input, TextArea

from .ai import connect, public_error, selected_provider, visible_text
from .ai_setup import AISetupRequired, prompt_ai_setup, prompt_missing_key
from .coach import CoachHost
from .core import METHODS, Session, timestamp
from .explain import ExplainDialog
from .field_ai import can_draft_path, stream_text_draft
from .form_model import (
    ENUM_CHOICES,
    FormField,
    blank,
    conditional_node_fields,
    draft_from_example,
    normalize_ids,
    parse,
    rename_grid_label,
    schema_for,
    title,
    validate_monte_variable,
)
from .guided_workflow import QUADRANTS
from .path_picker import ExportPicker, suggested_filename, user_path
from .planning import planned_next
from .planning_screen import PlanningScreen
from .reports import export
from .safe_widgets import Label, Select, Static
from .text_field import TextField
from .workspace_layout import WorkspaceLayout


def _example_numbers_remain(current, example) -> bool:
    """Illustrative numbers cannot silently become user judgments after a label edit."""
    if isinstance(example, dict) and isinstance(current, dict):
        return any(_example_numbers_remain(current.get(key), value) for key, value in example.items())
    if isinstance(example, list) and isinstance(current, list):
        return any(_example_numbers_remain(item, value) for item, value in zip(current, example, strict=False))
    return type(example) in (int, float) and current == example


class FormContents(Vertical):
    """Recompose changing fields without tearing down the Header or Footer."""

    # Vertical defaults to height: 1fr with hidden overflow, which clips long forms inside the scroll pane.
    DEFAULT_CSS = "FormContents { height: auto; }"

    def __init__(self, owner: FormScreen) -> None:
        super().__init__(classes="form-contents", id="form-contents")
        self.owner = owner

    def compose(self) -> ComposeResult:
        yield from self.owner.compose_fields()


class FormScreen(CoachHost, Screen):
    BINDINGS = [
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+e", "export", "Export"),
        ("f9", "explain", "Explain results"),
        ("escape", "project", "Project"),
        Binding("ctrl+g", "stop_ai", "Stop AI", priority=True),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.draft = deepcopy(session.method_state)
        self.fields: dict[str, tuple[tuple[Any, ...], FormField]] = {}
        self.groups: dict[str, tuple[Any, ...]] = {}
        self.group_specs: dict[str, FormField] = {}
        self.extra_keys: dict[str, tuple[Any, ...]] = {}
        self.pending_labels: dict[tuple[Any, ...], str] = {}
        self.ai_target: str | None = None
        self.ai_group: str | None = None
        self.ai_partial = ""
        self.ai_ready = False
        self.invalid_fields: set[tuple[Any, ...]] = set()
        self.save_timer = None
        # Collapsed rows by (group path, row index); kept across recomposition.
        self.collapsed_rows: set[tuple[tuple[Any, ...], int]] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with WorkspaceLayout():
            with VerticalScroll(classes="editor-pane"):
                yield FormContents(self)
            yield Static("⋮", classes="pane-handle")
            with VerticalScroll(classes="ai-pane"):
                yield Static("AI draft · review before accepting", classes="heading")
                yield Static(
                    "REMOTE → selected provider unless local. Sharing: method, problem, objective, assumptions, full method state (not notes or history). Ask only when ready.",
                    classes="muted",
                )
                yield Static(
                    "Suggestions are never saved without Accept. Numeric judgments are yours.", classes="muted"
                )
                yield Static("", id="form-ai-status", classes="muted")
                yield TextArea(id="form-preview")
                with Horizontal(classes="ai-actions"):
                    yield Button("Accept", id="form-accept")
                    yield Button("Dismiss", id="form-dismiss")
                    yield Button("Stop  Ctrl+G", id="form-stop")
        yield Footer()

    def compose_fields(self) -> ComposeResult:
        method = METHODS[self.session.method_id]
        self.fields = {}
        self.groups = {}
        self.group_specs = {}
        self.extra_keys = {}
        yield Label(f"{self.session.title} · {method.name}", classes="hero")
        yield Static(
            method.description + " · Your entries are saved as you work. Examples are optional.", classes="muted"
        )
        yield Label("Planning question", classes="heading")
        yield Static(
            "Define the decision or uncertainty. Why: keeps this analysis anchored.",
            classes="muted",
        )
        yield TextField(
            self.session.problem_statement,
            placeholder="What question are you planning around?",
            id="planning-question",
        )
        yield Label("Objective · decision purpose (optional)", classes="heading")
        yield Static(
            "What decision should this analysis inform?"
            + (
                " Separate from the outcomes in the hierarchy and from a node's parent."
                if method.id in {"objectives", "hypothesis_tree", "value_focused"}
                else ""
            ),
            classes="muted",
        )
        yield TextField(
            self.session.objective,
            placeholder="Decision this analysis should inform (optional)",
            id="analysis-objective",
        )
        for field in schema_for(method.id):
            yield from self.render_field(field, (field.key,))
        # The overall test comes after the analysis rows: you can only say what would
        # change a conclusion once you have one.
        yield Label("Overall: what would change your mind? (optional)", classes="heading")
        yield Static(
            "What observation would support or disconfirm your overall assessment? Your own test, not evidence "
            "supplied by an example.",
            classes="muted",
        )
        yield TextField(
            str(self.draft.get("change_mind", "")),
            placeholder="Observation that would change your assessment (optional)",
            id="form-change-mind",
        )
        with Horizontal(classes="actions"):
            yield Button("Save & calculate  Ctrl+S", id="form-save", variant="primary")
            yield Button("Mark finished", id="form-finish")
            if planned_next(self.session):
                yield Button("Continue planned workflow", id="form-plan")
            yield Button("Load example", id="load-example")
            yield Button("Advanced JSON  F6", id="advanced")
            yield Button("Project", id="project")
        yield Input(placeholder="Export path: ~/decision.md or ~/decision.json", id="form-export-path")
        with Horizontal(classes="actions"):
            yield Button("Export  Ctrl+E", id="form-export")
            yield Button("Choose location…", id="form-export-browse")
            yield Button("Explain results  F9", id="form-explain")
        yield Static("", id="form-error", classes="muted")
        yield Static("", id="form-results", classes="muted", markup=False)

    async def recompose_fields(self) -> None:
        await self.query_one(FormContents).recompose()
        # Recomposition replaces editors. Invalid raw text was never saved and may
        # belong to a now-hidden distribution (or a removed/reordered row).
        self.invalid_fields.clear()

    def value_at(self, path: tuple[Any, ...]) -> Any:
        item: Any = self.draft
        for part in path:
            if isinstance(item, dict):
                if part not in item:
                    return None
            elif not isinstance(item, list) or not isinstance(part, int) or part >= len(item):
                return None
            item = item[part]
        return item

    def render_field(self, field: FormField, path: tuple[Any, ...]) -> ComposeResult:
        value = self.value_at(path)
        if field.kind == "generated":
            return
        if field.kind == "rows":
            if self.session.method_id == "sensitivity" and path == ("range",):
                yield Label("Varied weight interval", classes="heading")
                yield Static(
                    "Enter the lower and upper bounds as decimals from 0 to 1. "
                    "For example, 0.25 to 0.75 tests 25%–75%; lower must be less than upper.",
                    classes="muted",
                )
                for index, label in enumerate(("Minimum weight (0–1)", "Maximum weight (0–1)")):
                    yield from self.render_field(replace(field.children[0], label=label), ("range", index))
                return
            group = f"group-{len(self.groups)}"
            self.groups[group] = path
            self.group_specs[group] = field
            yield Label(field.label, classes="heading")
            yield Static(field.help + " Why: " + field.why, classes="muted")
            rows = value if isinstance(value, list) else []
            item = field.item_label or field.label
            if not rows:
                yield Static(f"No entries yet. Choose + Add {item.lower()} to begin.", classes="muted")
            if len(rows) > 1:
                with Horizontal(classes="actions group-actions"):
                    yield Button("▸ Collapse all", id=f"{group}-collapseall")
                    yield Button("▾ Expand all", id=f"{group}-expandall")
            for index, row in enumerate(rows):
                with Collapsible(
                    title=Content(self.row_title(item, index, row)),  # Content(): user text is never markup
                    collapsed=(path, index) in self.collapsed_rows,
                    id=f"{group}-row-{index}",
                    classes="form-row",
                ):
                    yield from self.render_row(field, path, index, row, group)
            with Horizontal(classes="group-actions"):
                yield Button(f"+ Add {item.lower()}", id=f"{group}-add")
                if can_draft_path(self.session.method_id, path) and any(
                    child.kind in {"text", "long_text"} and can_draft_path(self.session.method_id, (*path, child.key))
                    for child in field.children
                ):
                    yield Button(
                        "Suggest rows",
                        id=f"suggest-rows-{group}",
                        classes="ai-trigger",
                        tooltip=f"Suggest text rows for {field.label}",
                    )
            if path in {("states",), ("scenarios",), ("hypotheses",)}:
                yield Button("Update columns from these names", id="refresh-keyed-grid")
            elif path in {("criteria",), ("alternatives",), ("items",), ("variables",), ("stocks",), ("stages",)}:
                yield Button("Update reference choices from these names", id=f"refresh-references-{group}")
            return
        if field.kind == "keyed_grid":
            sources = self.draft.get(field.reference, [])
            labels = list(
                dict.fromkeys(
                    str(row.get("name", "")).strip() if isinstance(row, dict) else str(row).strip()
                    for row in sources
                    if isinstance(row, (str, dict))
                )
            )
            labels = [label for label in labels if label]
            values = value if isinstance(value, dict) else {}
            extras = [key for key in values if key not in labels]
            yield Label(field.label + " · " + " × ".join(labels), classes="heading")
            yield Static(field.help + " Why: " + field.why, classes="muted")
            if not labels and not extras:
                yield Static("Name your " + field.reference + " first, then enter your own judgments.", classes="muted")
            with Horizontal(classes="keyed-grid-row"):
                for key in [*labels, *extras]:
                    cell = replace(field.children[0], label=key + (" · previous name" if key in extras else ""))
                    yield from self.render_field(cell, (*path, key))
                    if key in extras:
                        ident = f"extra-key-{len(self.extra_keys)}"
                        self.extra_keys[ident] = (*path, key)
                        yield Button("Remove previous judgment", id=ident)
            return
        if field.kind == "conditional_node":
            yield Label(field.label, classes="heading")
            yield Static(field.help + " Why: " + field.why, classes="muted")
            node = value if isinstance(value, dict) else {}
            if len(path) > 100:
                yield Static("This tree is too deep to edit safely.", classes="muted")
                return
            for child in field.children or conditional_node_fields(self.session.method_id):
                if not child.show_for or node.get("type") in child.show_for:
                    yield from self.render_field(child, (*path, child.key))
            return
        if field.kind == "object":
            yield Label(self.quadrant_label(field.key) or field.label, classes="heading")
            for child in field.children:
                yield from self.render_field(child, (*path, child.key))
            return
        ident = f"form-field-{len(self.fields)}"
        self.fields[ident] = (path, field)
        yield Label(field.label, classes="heading")
        yield Static(field.help + " Why: " + field.why, classes="muted")
        current = "" if value is None else ("Yes" if value else "No") if isinstance(value, bool) else str(value)
        if field.choices == ENUM_CHOICES[("forecasting", "outcome")]:
            current = {None: "Unresolved", 0: "No", 1: "Yes"}.get(value, current)
        if field.choices == ENUM_CHOICES[("causal_loop", "polarity")]:
            current = {1: "Reinforcing (+1)", -1: "Balancing (-1)"}.get(value, current)
        if field.kind in {"choice", "reference"}:
            options = [("— Choose —", "")] + [(choice, choice) for choice in field.choices]
            if field.kind == "reference":
                nodes = self.draft.get(field.reference, [])
                if field.reference == "nodes":
                    options += [
                        (str(node.get("label", node.get("name", node.get("id", "")))), str(node["id"]))
                        for node in nodes
                        if isinstance(node, dict) and node.get("id") and node.get("id") != self.row_id(path)
                    ]
                else:
                    options += [
                        (name, name)
                        for row in nodes
                        if (name := str(row.get("name", "") if isinstance(row, dict) else row).strip())
                    ]
            if current and current not in [option[1] for option in options]:
                options.append((current, current))  # preserve historical values until edited
            yield Select(options, value=current, allow_blank=False, id=ident)
        elif field.kind in {"text", "long_text"}:
            with Horizontal(classes="field-editor"):
                yield TextField(
                    current,
                    placeholder=field.help,
                    multiline=field.multiline,
                    size_key=self.size_key(path),
                    id=ident,
                )
                if can_draft_path(self.session.method_id, path):
                    yield Button("Draft text", id=f"suggest-{ident}", classes="ai-trigger")
        elif field.multiline:
            yield TextField(current, multiline=True, size_key=self.size_key(path), id=ident)
        else:
            yield Input(value=current, placeholder=field.help, id=ident)
        yield Static("", id=f"error-{ident}", classes="muted")

    @staticmethod
    def row_title(item: str, index: int, row: Any) -> str:
        """Row heading; the row's own name or statement identifies it when collapsed."""
        if isinstance(row, dict):
            keys = ("name", "label", "statement", "title", "claim", "mode", "question")
            label = next((str(row[key]) for key in keys if row.get(key) not in (None, "")), "")
        else:
            label = "" if isinstance(row, list) else str(row)
        label = " ".join(label.split())
        if len(label) > 70:
            label = label[:69] + "…"
        return f"{item} {index + 1}" + (f" · {label}" if label else "")

    def render_row(self, field: FormField, path: tuple[Any, ...], index: int, row: Any, group: str) -> ComposeResult:
        for child in field.children:
            if child.show_for:
                if path == ("variables",) and isinstance(row, dict):
                    owner = row.get("distribution")
                else:
                    parent = self.value_at(path[:-1])
                    owner = parent.get("type") if isinstance(parent, dict) else None
                if owner not in child.show_for:
                    continue
            if child.key == "value" and child.kind == "conditional_node":
                child_path = (*path, index)
            elif isinstance(row, (int, float, str)) and child.key == "value":
                child_path = (*path, index)
                if self.session.method_id == "sensitivity" and path[-1] == "scores":
                    child = replace(child, label=self.grid_heading(path, path[-2], index))
            elif isinstance(row, list) and child.key == "value":
                for j in range(len(row)):
                    heading = self.grid_heading(path, index, j)
                    yield from self.render_field(
                        FormField(
                            "score",
                            heading,
                            kind="float",
                            minimum=0,
                            maximum=10,
                            help="Enter your score, 0–10.",
                            why="Scores determine the ranking.",
                        ),
                        (*path, index, j),
                    )
                continue
            else:
                child_path = (*path, index, child.key)
            yield from self.render_field(child, child_path)
        if self.session.method_id == "monte_carlo" and path == ("variables",):
            yield Static("", id=f"monte-error-{index}", classes="muted")
        with Horizontal(classes="actions"):
            for action, text in (("up", "↑ Move up"), ("down", "↓ Move down"), ("remove", "Remove")):
                yield Button(text, id=f"{group}-{action}-{index}")

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        self.remember_collapsed(event.collapsible)

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        self.remember_collapsed(event.collapsible)

    def remember_collapsed(self, row: Collapsible) -> None:
        ident = row.id or ""
        group, _, index = ident.partition("-row-")
        if group in self.groups and index.isdigit():
            key = (self.groups[group], int(index))
            if row.collapsed:
                self.collapsed_rows.add(key)
            else:
                self.collapsed_rows.discard(key)

    def set_rows_collapsed(self, group: str, collapsed: bool) -> None:
        for row in self.query(Collapsible).filter(".form-row"):
            if (row.id or "").startswith(f"{group}-row-"):
                row.collapsed = collapsed

    def move_collapsed(self, path: tuple[Any, ...], moves: dict[int, int], drop: int | None = None) -> None:
        """Keep each row's collapsed state with the row when rows move or one is removed."""
        mine = {index for owner, index in self.collapsed_rows if owner == path}
        self.collapsed_rows -= {(path, index) for index in mine}
        self.collapsed_rows |= {(path, moves.get(index, index)) for index in mine if index != drop}

    def size_key(self, path: tuple[Any, ...]) -> str:
        return f"{self.session.id}:{'.'.join(map(str, path))}"

    def quadrant_label(self, key: str) -> str:
        """Name a scenario quadrant by the user's own axis poles once they exist."""
        if self.session.method_id != "scenarios" or key not in QUADRANTS:
            return ""
        axes = self.draft.get("axes", [])
        if not isinstance(axes, list) or len(axes) < 2 or not all(isinstance(axis, dict) for axis in axes[:2]):
            return ""
        poles = []
        for axis, side in zip(axes[:2], key.split("_"), strict=True):
            pole = str(axis.get(side) or "").strip()
            poles.append(pole or f"{str(axis.get('name') or 'axis').strip()} {side}")
        return "Scenario · " + " × ".join(poles)

    def row_id(self, path: tuple[Any, ...]) -> str | None:
        if len(path) >= 3 and isinstance(path[-2], int):
            row = self.value_at(path[:-1])
            if isinstance(row, dict):
                return row.get("id")
        return None

    def grid_heading(self, path: tuple[Any, ...], i: int, j: int) -> str:
        if path[-1] == "scores" and self.session.method_id in {"matrix", "sensitivity"}:
            criteria = self.draft.get("criteria", [])
            if j < len(criteria):
                return f"{title('score')} · {criteria[j].get('name', j + 1)}"
        return f"Score {j + 1}"

    def put(self, path: tuple[Any, ...], value: Any) -> None:
        node: Any = self.draft
        for i, part in enumerate(path[:-1]):
            following = path[i + 1]
            if isinstance(node, dict):
                if part not in node or node[part] is None:
                    node[part] = [] if isinstance(following, int) else {}
                node = node[part]
            else:
                node = node[part]
        if isinstance(node, list) and isinstance(path[-1], int) and path[-1] >= len(node):
            node.extend([""] * (path[-1] - len(node) + 1))
        node[path[-1]] = value

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "planning-question":
            if event.value != self.session.problem_statement:
                self.session.problem_statement = event.value
                self.schedule_save()
        elif event.input.id == "analysis-objective":
            if event.value != self.session.objective:
                self.session.objective = event.value
                self.schedule_save()
        elif event.input.id == "form-change-mind":
            if event.value != self.draft.get("change_mind", ""):
                if event.value:
                    self.draft["change_mind"] = event.value
                else:
                    self.draft.pop("change_mind", None)
                self.session.method_state = deepcopy(self.draft)
                self.schedule_save()
        elif event.input.id in self.fields:
            self.change(event.input.id, event.value)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id in self.fields:
            self.change(event.text_area.id, event.text_area.text)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in self.fields:
            path, _ = self.fields[event.select.id]
            previous = self.value_at(path)
            self.change(event.select.id, "" if event.value is Select.BLANK else str(event.value))
            changed_distribution = (
                self.session.method_id == "monte_carlo"
                and len(path) == 3
                and path[0] == "variables"
                and path[-1] == "distribution"
            )
            changed_node = self.session.method_id in {"decision_tree", "fault_tree"} and path[-1] == "type"
            if (changed_distribution or changed_node) and self.value_at(path) != previous:
                await self.recompose_fields()
                self.update_monte_feedback()

    def change(self, ident: str, raw: str) -> None:
        path, field = self.fields[ident]
        try:
            value = parse(field, raw)
            if (
                self.session.method_id == "risk_matrix"
                and path[-1] in {"likelihood", "impact"}
                and value not in ("", None)
            ):
                scale = self.draft.get("scale_max", 5)
                if type(scale) is int and value > scale:
                    raise ValueError(f"{field.label}: enter a value from 1 to your scale maximum ({scale})")
        except ValueError as exc:
            self.invalid_fields.add(path)
            self.query_one(f"#error-{ident}", Static).update(str(exc))
            return
        self.invalid_fields.discard(path)
        self.query_one(f"#error-{ident}", Static).update("")
        previous = self.value_at(path)
        if previous is None and not raw.strip():
            return  # Empty optional select mounted over an absent legacy field.
        # Mounting a form is not a user edit. Keep legacy integer/float types and audit untouched.
        if previous == value and (
            type(previous) is type(value) or type(previous) in (int, float) and type(value) in (int, float)
        ):
            return
        self.put(path, value)
        if (path[0] == "states" and path[-1] == "name") or (path[0] in {"scenarios", "hypotheses"} and len(path) == 2):
            if not value and previous:
                self.pending_labels[path] = str(previous)
            elif value:
                old = str(previous or self.pending_labels.get(path, ""))
                rename_grid_label(self.draft, self.session.method_id, str(path[0]), old, str(value))
                self.pending_labels.pop(path, None)
        normalize_ids(self.draft)
        self.session.method_state = deepcopy(self.draft)
        widget = self.query_one(f"#{ident}")
        if path[0] == "range" or not widget.has_focus:
            self.flush_save()  # programmatic/selection edits and bounds are discrete judgments
        else:
            self.schedule_save()
        self.preview_result()
        self.update_monte_feedback()

    def schedule_save(self) -> None:
        if self.save_timer is None:
            self.save_timer = self.set_timer(0.6, self.flush_save)
        else:
            self.save_timer.reset()

    def _save_draft(self, description: str) -> bool:
        try:
            self.app.store.save(self.session, description)
        except (sqlite3.Error, ValueError):
            self.notify(
                "Could not save; database is busy or changed elsewhere. Your draft remains in this editor.",
                severity="error",
            )
            return False
        return True

    def flush_save(self) -> None:
        if self.save_timer is not None:
            self.save_timer.stop()
            self.save_timer = None
        try:
            self.app.store.save(self.session, "Edited worksheet")
        except (sqlite3.Error, ValueError) as exc:
            self.notify(
                f"Could not save: {exc}. Keep this screen open until database access is restored.", severity="error"
            )

    def on_unmount(self) -> None:
        if self.save_timer is not None:
            self.flush_save()

    def update_monte_feedback(self) -> None:
        if self.session.method_id != "monte_carlo":
            return
        for index, row in enumerate(self.draft.get("variables", [])):
            targets = self.query(f"#monte-error-{index}")
            if targets:
                targets.first().update(validate_monte_variable(row))

    def preview_result(self) -> None:
        method = METHODS[self.session.method_id]
        if method.id == "monte_carlo":
            self.query_one("#form-results", Static).update("Run the simulation only when you save.")
            return
        try:
            result = method.calculate(self.draft)
        except Exception:
            self.query_one("#form-results", Static).update("Add the required details to see a local preview.")
            return
        if self.session.method_id in {"assumptions", "premortem"}:
            rows = result.get("priorities", result.get("risks", []))
            summary = "\n".join(
                f"{i}. {row.get('statement', row.get('cause', 'Entry'))}" for i, row in enumerate(rows, 1)
            )
        else:
            summary = method.summarize(self.draft)
        self.query_one("#form-results", Static).update("Local result preview · your inputs:\n" + summary)

    def on_resize(self) -> None:
        self.query_one(WorkspaceLayout).update_split(self.size.width < 100)

    def on_mount(self) -> None:
        self.on_resize()
        self.preview_result()
        self.update_monte_feedback()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id or ""
        if ident.startswith("group-"):
            parts = ident.split("-")
            group = "-".join(parts[:2])
            action = parts[2]
            index = int(parts[3]) if len(parts) > 3 else None
            path = self.groups[group]
            if action in {"collapseall", "expandall"}:
                self.set_rows_collapsed(group, action == "collapseall")
                return
            spec = self.group_specs[group]
            rows = self.value_at(path)
            rows = list(rows) if isinstance(rows, list) else []
            if action == "add":
                if (
                    self.session.method_id == "sensitivity"
                    and path[-1] == "scores"
                    and len(rows) >= len(self.draft.get("criteria", []))
                ):
                    self.notify("Add another criterion before adding another score", severity="warning")
                    return
                row = (
                    {child.key: blank(child) for child in spec.children if child.kind != "generated"}
                    if spec.children[0].key != "value"
                    else ""
                )
                if path[-1] == "scores" and self.session.method_id == "matrix":
                    row = [""] * len(self.draft.get("criteria", []))
                if self.session.method_id == "monte_carlo" and path == ("variables",):
                    row = {"name": "", "distribution": "", "coefficient": ""}
                if spec.children[0].kind == "conditional_node":
                    row = {"type": ""}
                rows.append(row)
            elif action == "remove":
                rows.pop(index)
                self.move_collapsed(path, {i: i - 1 for i in range(index + 1, len(rows) + 1)}, drop=index)
            elif action in {"up", "down"}:
                other = index + (-1 if action == "up" else 1)
                if 0 <= other < len(rows):
                    rows[index], rows[other] = rows[other], rows[index]
                    self.move_collapsed(path, {index: other, other: index})
            self.put(path, rows)
            if self.session.method_id == "sensitivity" and path == ("criteria",):
                for alternative in self.draft.get("alternatives", []):
                    scores = alternative.get("scores", [])
                    if action == "add":
                        scores.append("")
                    elif action == "remove" and index < len(scores):
                        scores.pop(index)
                    elif action in {"up", "down"} and 0 <= other < len(rows) and max(index, other) < len(scores):
                        scores[index], scores[other] = scores[other], scores[index]
            self.pending_labels.clear()  # row indices changed; never reuse a stale rename target
            normalize_ids(self.draft)
            self.session.method_state = deepcopy(self.draft)
            if not self._save_draft(f"Changed {title(str(path[-1]))} rows"):
                return
            await self.recompose_fields()
            self.preview_result()
            self.update_monte_feedback()
        elif ident == "refresh-keyed-grid" or ident.startswith("refresh-references-"):
            await self.recompose_fields()
        elif ident in self.extra_keys:
            path = self.extra_keys[ident]
            values = self.value_at(path[:-1])
            if isinstance(values, dict):
                del values[path[-1]]  # explicit user action; never discard a judgment during a rename
                self.session.method_state = deepcopy(self.draft)
                if not self._save_draft("Removed prior keyed judgment by request"):
                    return
                await self.recompose_fields()
        elif ident in {"form-save", "form-finish"}:
            self.action_save()
        elif ident == "load-example":
            if any(
                value is not None and value != "" and value != [] and value != {}
                for key, value in self.draft.items()
                if key not in {"change_mind", "_guided_step"} and not key.startswith("workflow_")
            ):
                self.notify(
                    "Example can only be loaded into an empty worksheet; create a new analysis first.",
                    severity="warning",
                )
                return
            self.draft = {**self.draft, **draft_from_example(self.session.method_id), "_example_loaded": True}
            self.session.method_state = deepcopy(self.draft)
            if not self._save_draft("Loaded illustrative example by request"):
                return
            await self.recompose_fields()
            self.preview_result()
        elif ident == "form-plan":
            self.app.switch_screen(PlanningScreen(self.session))
        elif ident == "advanced":
            self.action_advanced()
        elif ident == "form-export":
            self.action_export()
        elif ident == "form-export-browse":
            self.browse_export("#form-export-path")
        elif ident == "form-explain":
            self.action_explain()
        elif ident == "project":
            self.action_project()
        elif ident.startswith("suggest-rows-"):
            self.suggest_rows(ident.removeprefix("suggest-rows-"))
        elif ident.startswith("suggest-"):
            self.suggest(ident.removeprefix("suggest-"))
        elif ident == "form-accept":
            self.accept()
        elif ident == "form-dismiss":
            self.ai_target = None
            self.query_one("#form-preview", TextArea).load_text("")
        elif ident == "form-stop":
            self.action_stop_ai()

    def lookup_schema(self) -> list[tuple[tuple[Any, ...], FormField]]:
        result = []

        def walk(field: FormField, path: tuple[Any, ...]) -> None:
            result.append((path, field))
            if field.kind == "object":
                for child in field.children:
                    walk(child, (*path, child.key))
            elif field.kind == "rows":
                for child in field.children:
                    walk(child, (*path, 0, child.key))

        for field in schema_for(self.session.method_id):
            walk(field, (field.key,))
        return result

    def action_save(self) -> None:
        # Ctrl+S saves the draft, including common analysis fields, even when
        # method rows are incomplete and cannot yet produce a result.
        if self.save_timer is not None:
            self.flush_save()
        if self.session.method_id == "monte_carlo":
            for index, row in enumerate(self.draft.get("variables", []), 1):
                if issue := validate_monte_variable(row):
                    self.query_one("#form-error", Static).update(f"Variable {index}: {issue}")
                    return
        if self.invalid_fields:
            self.query_one("#form-error", Static).update("Correct the highlighted entries before saving.")
            return
        user_inputs = {
            key: value
            for key, value in self.draft.items()
            if key != "change_mind" and not key.startswith(("workflow_", "_"))
        }
        if user_inputs == draft_from_example(self.session.method_id) or (
            self.draft.get("_example_loaded")
            and _example_numbers_remain(self.draft, draft_from_example(self.session.method_id))
        ):
            self.query_one("#form-error", Static).update(
                "Replace every illustrative numeric judgment with your own inputs before marking this complete."
            )
            return
        candidate = deepcopy(self.draft)
        if (
            self.session.method_id == "bottleneck"
            and isinstance(candidate.get("proposal"), dict)
            and all(value is None or value == "" for value in candidate["proposal"].values())
        ):
            candidate.pop("proposal")
        if (
            self.session.method_id == "constraints"
            and isinstance(candidate.get("throughput"), dict)
            and all(value is None or value == "" for value in candidate["throughput"].values())
        ):
            candidate.pop("throughput")
        try:
            issues = METHODS[self.session.method_id].validate(candidate)
            result = METHODS[self.session.method_id].calculate(candidate) if not issues else None
        except Exception:
            issues = ["Input has an invalid shape or an out-of-range value; review the worksheet."]
        if issues:
            self.query_one("#form-error", Static).update("Please review: " + " ".join(issues))
            return
        candidate.pop("_example_loaded", None)
        self.draft = candidate
        self.session.method_state = deepcopy(candidate)
        self.session.completed_at = timestamp()
        try:
            self.app.store.save(self.session, "Completed " + METHODS[self.session.method_id].name)
        except (sqlite3.Error, ValueError) as exc:
            self.query_one("#form-error", Static).update(f"Could not save: {exc}. Keep this screen open.")
            return
        self.query_one("#form-error", Static).update("Saved · results calculated locally.")
        if self.session.method_id == "monte_carlo":
            from .reports import plain_result

            self.query_one("#form-results", Static).update(
                "Simulation results · calculated locally:\n" + plain_result(result)
            )
        else:
            self.preview_result()

    def action_advanced(self) -> None:
        self.app.open_session(self.session, advanced=True)

    def action_export(self) -> None:
        value = self.query_one("#form-export-path", Input).value.strip()
        if not value:
            self.query_one("#form-export-path", Input).focus()
            self.notify("Enter an export path", severity="warning")
            return
        try:
            export(self.session, user_path(value), store=self.app.store)
        except (ValueError, OSError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Exported {value}")

    def action_explain(self) -> None:
        if self.save_timer is not None:
            self.flush_save()
        self.app.push_screen(ExplainDialog(self.session))

    def browse_export(self, input_id: str) -> None:
        def chosen(path: Path | None) -> None:
            if path is not None:
                self.app.last_export_dir = path.parent
                self.query_one(input_id, Input).value = str(path)
                self.action_export()

        self.app.push_screen(ExportPicker(suggested_filename(self.session.title), self.app.last_export_dir), chosen)

    def action_project(self) -> None:
        if self.save_timer is not None:
            self.flush_save()
        self.app.show_project()

    def suggest(self, ident: str) -> None:
        if ident not in self.fields or not can_draft_path(self.session.method_id, self.fields[ident][0]):
            return
        self.ai_path = self.fields[ident][0]
        self.ai_target, self.ai_group = ident, None
        self.request_ai(self.fields[ident][1].label, rows=False)

    def suggest_rows(self, group: str) -> None:
        if group not in self.groups or not can_draft_path(self.session.method_id, self.groups[group]):
            return
        self.ai_path = self.groups[group]
        self.ai_target, self.ai_group = None, group
        self.request_ai(title(str(self.groups[group][-1])), rows=True)

    def request_ai(self, label: str, *, rows: bool) -> None:
        if selected_provider(self.app.store) == "off":
            self.query_one("#form-ai-status", Static).update("AI is off. You can enter everything yourself.")
            return
        if any(w.group == "form-ai" and w.is_running for w in self.workers):
            return
        self.ai_partial = ""
        self.ai_ready = False
        self.ai_destination = ""
        self.query_one("#form-preview", TextArea).load_text("")
        self.query_one("#form-ai-status", Static).update(
            "Sharing: method, problem, objective, assumptions, full method state · connecting to AI… Ctrl+G stops."
        )
        self.run_worker(self.ask_ai(label, rows), group="form-ai", exclusive=True)

    async def ask_ai(self, label: str, rows: bool) -> None:
        status = self.query_one("#form-ai-status", Static)

        def update(text: str) -> None:
            self.ai_partial = text
            self.query_one("#form-preview", TextArea).load_text(text)
            status.update(f"{self.ai_destination} · AI suggestion streaming · {len(text.split())} words · Ctrl+G stops")

        def start(message: str) -> None:
            self.ai_destination = message
            status.update(message)

        try:
            answer, provider = await stream_text_draft(
                self.app.store,
                self.session,
                label,
                rows,
                update,
                connect_fn=connect,
                on_start=start,
            )
            self.query_one("#form-preview", TextArea).load_text(answer)
            self.ai_ready = True
            status.update(f"{self.ai_destination}\n{provider} · edit, Accept or Dismiss. Not saved.")
        except AISetupRequired as exc:
            status.update("AI request not sent. Complete setup in Settings.")
            prompt_ai_setup(self.app, exc)
        except ValueError as exc:
            status.update(str(exc))
        except Exception as exc:
            if prompt_missing_key(self.app, exc):
                status.update("API key needed or rejected. No draft was accepted.")
            else:
                status.update(f"AI unavailable: {public_error(exc)}. Your analysis is preserved.")

    def accept(self) -> None:
        if not self.ai_ready or any(w.group == "form-ai" and w.is_running for w in self.workers):
            return
        text = self.query_one("#form-preview", TextArea).text.strip()
        from .field_ai import text_only

        if text_only(text) != text:
            self.query_one("#form-ai-status", Static).update("Remove numeric judgments before accepting AI text.")
            return
        if not text:
            self.query_one("#form-ai-status", Static).update("Enter text before accepting.")
            return
        if self.ai_target and self.ai_target in self.fields:
            ident = self.ai_target
            if self.fields[ident][0] != getattr(self, "ai_path", None) or not can_draft_path(
                self.session.method_id, self.fields[ident][0]
            ):
                self.query_one("#form-ai-status", Static).update(
                    "Fields changed; request a fresh draft before accepting."
                )
                return
            self.change(ident, text)
            widget = self.query_one(f"#{ident}")
            if isinstance(widget, TextArea):
                widget.load_text(text)
            elif isinstance(widget, Input):
                widget.value = text
        elif self.ai_group and self.ai_group in self.groups:
            path = self.groups[self.ai_group]
            if path != getattr(self, "ai_path", None) or not can_draft_path(self.session.method_id, path):
                self.query_one("#form-ai-status", Static).update(
                    "Rows changed; request a fresh draft before accepting."
                )
                return
            spec = self.group_specs[self.ai_group]
            child = next(
                (
                    child
                    for child in spec.children
                    if child.kind in {"text", "long_text"}
                    and can_draft_path(self.session.method_id, (*path, child.key))
                ),
                None,
            )
            if child is None:
                return
            rows = list(self.value_at(path) or [])
            for line in text.splitlines():
                if line.strip():
                    if child.key == "value":
                        rows.append(line.strip())
                    else:
                        row = {field.key: blank(field) for field in spec.children if field.kind != "generated"}
                        row[child.key] = line.strip()
                        rows.append(row)
            self.put(path, rows)
            normalize_ids(self.draft)
            self.session.method_state = deepcopy(self.draft)
            if not self._save_draft("Accepted edited text suggestions"):
                return
            self.run_worker(self.recompose_fields())
        else:
            return
        self.ai_target = self.ai_group = None
        self.ai_ready = False
        self.query_one("#form-preview", TextArea).load_text("")
        self.query_one("#form-ai-status", Static).update("Accepted edited text; add your own judgments separately.")

    def action_stop_ai(self) -> None:
        if any(w.group == "form-ai" and w.is_running for w in self.workers):
            self.workers.cancel_group(self, "form-ai")
            self.ai_ready = False
            self.ai_target = self.ai_group = None
            self.query_one("#form-ai-status", Static).update(
                "AI stopped · partial answer visible, not accepted or saved."
            )
            self.query_one("#form-preview", TextArea).load_text(visible_text(self.ai_partial))
