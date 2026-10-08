"""Keyboard-accessible forms for structured methods; raw JSON remains an advanced view."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea

from .ai import connect, public_error, selected_provider, visible_text
from .core import METHODS, Session, timestamp
from .field_ai import stream_text_draft
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
from .reports import export


class FormContents(Vertical):
    """Recompose changing fields without tearing down the Header or Footer."""

    def __init__(self, owner: FormScreen) -> None:
        super().__init__(classes="form-contents", id="form-contents")
        self.owner = owner

    def compose(self) -> ComposeResult:
        yield from self.owner.compose_fields()


class FormScreen(Screen):
    BINDINGS = [
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+e", "export", "Export"),
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(classes="workspace-layout"):
            with VerticalScroll(classes="editor-pane"):
                yield FormContents(self)
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
        yield Input(
            value=self.session.problem_statement,
            placeholder="What question are you planning around?",
            id="planning-question",
        )
        yield Static(
            "Planning question · Define the decision or uncertainty. Why: keeps this analysis anchored.",
            classes="muted",
        )
        for field in schema_for(method.id):
            yield from self.render_field(field, (field.key,))
        with Horizontal(classes="actions"):
            yield Button("Save & calculate  Ctrl+S", id="form-save", variant="primary")
            yield Button("Mark finished", id="form-finish")
            yield Button("Load example", id="load-example")
            yield Button("Advanced JSON  F6", id="advanced")
            yield Button("Project", id="project")
        yield Input(placeholder="Export path: ~/decision.md or ~/decision.json", id="form-export-path")
        yield Button("Export  Ctrl+E", id="form-export")
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
            if not rows:
                yield Static("No entries yet. Choose Add row to begin.", classes="muted")
            for index, row in enumerate(rows):
                label = str(row.get("name", row.get("label", ""))) if isinstance(row, dict) else str(row)
                yield Label(f"{field.label} {index + 1}" + (f" · {label}" if label else ""), classes="heading")
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
            with Horizontal(classes="group-actions"):
                yield Button(f"Add {field.label.lower()} row", id=f"{group}-add")
                if any(child.kind in {"text", "long_text"} for child in field.children):
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
            yield Label(field.label, classes="heading")
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
                if field.multiline:
                    yield TextArea(current, id=ident)
                else:
                    yield Input(value=current, placeholder=field.help, id=ident)
                yield Button("Draft text", id=f"suggest-{ident}", classes="ai-trigger")
        elif field.multiline:
            yield TextArea(current, id=ident)
        else:
            yield Input(value=current, placeholder=field.help, id=ident)
        yield Static("", id=f"error-{ident}", classes="muted")

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

    def flush_save(self) -> None:
        if self.save_timer is not None:
            self.save_timer.stop()
            self.save_timer = None
        self.app.store.save(self.session, "Edited worksheet")

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
        except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError):
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
        self.query_one(".workspace-layout").set_class(self.size.width < 100, "narrow")

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
            elif action in {"up", "down"}:
                other = index + (-1 if action == "up" else 1)
                if 0 <= other < len(rows):
                    rows[index], rows[other] = rows[other], rows[index]
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
            self.app.store.save(self.session, f"Changed {title(str(path[-1]))} rows")
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
                self.app.store.save(self.session, "Removed prior keyed judgment by request")
                await self.recompose_fields()
        elif ident in {"form-save", "form-finish"}:
            self.action_save()
        elif ident == "load-example":
            if any(
                value
                for key, value in self.draft.items()
                if key not in {"change_mind", "_guided_step"} and not key.startswith("workflow_")
            ):
                self.notify(
                    "Example can only be loaded into an empty worksheet; create a new analysis first.",
                    severity="warning",
                )
                return
            self.draft = {**self.draft, **draft_from_example(self.session.method_id)}
            self.session.method_state = deepcopy(self.draft)
            self.app.store.save(self.session, "Loaded illustrative example by request")
            await self.recompose_fields()
            self.preview_result()
        elif ident == "advanced":
            self.action_advanced()
        elif ident == "form-export":
            self.action_export()
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
        if self.session.method_id == "monte_carlo":
            for index, row in enumerate(self.draft.get("variables", []), 1):
                if issue := validate_monte_variable(row):
                    self.query_one("#form-error", Static).update(f"Variable {index}: {issue}")
                    return
        if self.invalid_fields:
            self.query_one("#form-error", Static).update("Correct the highlighted entries before saving.")
            return
        if (
            self.session.method_id == "bottleneck"
            and isinstance(self.draft.get("proposal"), dict)
            and not any(self.draft["proposal"].values())
        ):
            self.draft.pop("proposal")
        if (
            self.session.method_id == "constraints"
            and isinstance(self.draft.get("throughput"), dict)
            and not any(self.draft["throughput"].values())
        ):
            self.draft.pop("throughput")
        issues = METHODS[self.session.method_id].validate(self.draft)
        if issues:
            self.query_one("#form-error", Static).update("Please review: " + " ".join(issues))
            return
        if self.save_timer is not None:
            self.flush_save()
        self.session.method_state = deepcopy(self.draft)
        self.session.completed_at = timestamp()
        self.app.store.save(self.session, "Completed " + METHODS[self.session.method_id].name)
        self.query_one("#form-error", Static).update("Saved · results calculated locally.")
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
            export(self.session, Path(value).expanduser(), store=self.app.store)
        except (ValueError, OSError) as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Exported {value}")

    def action_project(self) -> None:
        if self.save_timer is not None:
            self.flush_save()
        self.app.show_project()

    def suggest(self, ident: str) -> None:
        if ident not in self.fields:
            return
        self.ai_target, self.ai_group = ident, None
        self.request_ai(self.fields[ident][1].label, rows=False)

    def suggest_rows(self, group: str) -> None:
        if group not in self.groups:
            return
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
        except ValueError as exc:
            status.update(str(exc))
        except (RuntimeError, KeyError) as exc:
            status.update(f"AI unavailable: {public_error(exc)}. Your analysis is preserved.")

    def accept(self) -> None:
        if not self.ai_ready or any(w.group == "form-ai" and w.is_running for w in self.workers):
            return
        text = self.query_one("#form-preview", TextArea).text.strip()
        if not text:
            self.query_one("#form-ai-status", Static).update("Enter text before accepting.")
            return
        if self.ai_target and self.ai_target in self.fields:
            ident = self.ai_target
            self.change(ident, text)
            widget = self.query_one(f"#{ident}")
            if isinstance(widget, TextArea):
                widget.load_text(text)
            elif isinstance(widget, Input):
                widget.value = text
        elif self.ai_group and self.ai_group in self.groups:
            path = self.groups[self.ai_group]
            spec = self.group_specs[self.ai_group]
            child = next((child for child in spec.children if child.kind in {"text", "long_text"}), None)
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
            self.app.store.save(self.session, "Accepted edited text suggestions")
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
