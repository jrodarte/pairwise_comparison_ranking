"""Keyboard-accessible forms for structured methods; raw JSON remains an advanced view."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea

from .core import METHODS, Session, timestamp
from .form_model import FormField, blank, draft_from_example, normalize_ids, parse, schema_for, title


class FormScreen(Screen):
    BINDINGS = [
        ("f6", "advanced", "Advanced JSON"),
        ("ctrl+s", "save", "Save"),
        ("escape", "project", "Project"),
        ("ctrl+g", "stop_ai", "Stop AI"),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.draft = deepcopy(session.method_state)
        self.fields: dict[str, tuple[tuple[Any, ...], FormField]] = {}
        self.groups: dict[str, tuple[Any, ...]] = {}
        self.ai_target: str | None = None
        self.invalid_fields: set[tuple[Any, ...]] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        method = METHODS[self.session.method_id]
        self.fields = {}
        self.groups = {}
        with VerticalScroll(classes="page"):
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
                yield Button("Load example", id="load-example")
                yield Button("Advanced JSON  F6", id="advanced")
                yield Button("Project", id="project")
            yield Static("", id="form-error", classes="muted")
            yield Static("", id="form-results", classes="muted", markup=False)
            yield Static("AI is optional · suggestions are never saved without Accept.", classes="muted")
            yield Static("", id="form-ai-status", classes="muted")
            yield TextArea(id="form-preview")
            with Horizontal(classes="actions"):
                yield Button("Accept edited text", id="form-accept")
                yield Button("Dismiss", id="form-dismiss")
                yield Button("Stop AI  Ctrl+G", id="form-stop")
        yield Footer()

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
            group = f"group-{len(self.groups)}"
            self.groups[group] = path
            yield Label(field.label, classes="heading")
            yield Static(field.help + " Why: " + field.why, classes="muted")
            rows = value if isinstance(value, list) else []
            if not rows:
                yield Static("No entries yet. Choose Add row to begin.", classes="muted")
            for index, row in enumerate(rows):
                label = str(row.get("name", row.get("label", ""))) if isinstance(row, dict) else str(row)
                yield Label(f"{field.label} {index + 1}" + (f" · {label}" if label else ""), classes="heading")
                for child in field.children:
                    if isinstance(row, (int, float, str)) and child.key == "value":
                        child_path = (*path, index)
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
                with Horizontal(classes="actions"):
                    for action, text in (("up", "↑ Move up"), ("down", "↓ Move down"), ("remove", "Remove")):
                        yield Button(text, id=f"{group}-{action}-{index}")
            yield Button(f"Add {field.label.lower()} row", id=f"{group}-add")
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
        current = "" if value is None else str(value)
        if field.kind in {"choice", "reference"}:
            options = [("— Choose —", "")] + [(choice, choice) for choice in field.choices]
            if field.kind == "reference":
                nodes = self.draft.get(field.reference, [])
                options += [
                    (str(node.get("label", node.get("name", node.get("id", "")))), str(node["id"]))
                    for node in nodes
                    if isinstance(node, dict) and node.get("id") and node.get("id") != self.row_id(path)
                ]
            if current and current not in [option[1] for option in options]:
                options.append((current, current))  # preserve historical values until edited
            yield Select(options, value=current, allow_blank=False, id=ident)
        elif field.multiline:
            yield TextArea(current, id=ident)
        else:
            yield Input(value=current, placeholder=field.help, id=ident)
        if field.kind in {"text", "long_text"}:
            yield Button("Suggest text", id=f"suggest-{ident}")
        yield Static("", id=f"error-{ident}", classes="muted")

    def row_id(self, path: tuple[Any, ...]) -> str | None:
        if len(path) >= 3 and isinstance(path[-2], int):
            row = self.value_at(path[:-1])
            if isinstance(row, dict):
                return row.get("id")
        return None

    def grid_heading(self, path: tuple[Any, ...], i: int, j: int) -> str:
        if path[-1] == "scores" and self.session.method_id == "matrix":
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
        node[path[-1]] = value

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "planning-question":
            self.session.problem_statement = event.value
            self.app.store.save(self.session, "Updated planning question")
        elif event.input.id in self.fields:
            self.change(event.input.id, event.value)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id in self.fields:
            self.change(event.text_area.id, event.text_area.text)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in self.fields:
            self.change(event.select.id, "" if event.value is Select.BLANK else str(event.value))

    def change(self, ident: str, raw: str) -> None:
        path, field = self.fields[ident]
        try:
            value = parse(field, raw)
        except ValueError as exc:
            self.invalid_fields.add(path)
            self.query_one(f"#error-{ident}", Static).update(str(exc))
            return
        self.invalid_fields.discard(path)
        self.query_one(f"#error-{ident}", Static).update("")
        self.put(path, value)
        normalize_ids(self.draft)
        self.session.method_state = deepcopy(self.draft)
        self.app.store.save(self.session, f"Updated {field.label}")
        self.preview_result()

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

    def on_mount(self) -> None:
        self.preview_result()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id or ""
        if ident.startswith("group-"):
            parts = ident.split("-")
            group = "-".join(parts[:2])
            action = parts[2]
            index = int(parts[3]) if len(parts) > 3 else None
            path = self.groups[group]
            spec = next(field for field in self.lookup_schema() if field[0] == path)[1]
            rows = self.value_at(path)
            rows = list(rows) if isinstance(rows, list) else []
            if action == "add":
                row = (
                    {child.key: blank(child) for child in spec.children if child.kind != "generated"}
                    if spec.children[0].key != "value"
                    else ""
                )
                if path[-1] == "scores":
                    row = [""] * len(self.draft.get("criteria", []))
                rows.append(row)
            elif action == "remove":
                rows.pop(index)
            elif action in {"up", "down"}:
                other = index + (-1 if action == "up" else 1)
                if 0 <= other < len(rows):
                    rows[index], rows[other] = rows[other], rows[index]
            self.put(path, rows)
            normalize_ids(self.draft)
            self.session.method_state = deepcopy(self.draft)
            self.app.store.save(self.session, f"Changed {title(str(path[-1]))} rows")
            await self.recompose()
            self.preview_result()
        elif ident == "form-save":
            self.action_save()
        elif ident == "load-example":
            self.draft = {**self.draft, **draft_from_example(self.session.method_id)}
            self.session.method_state = deepcopy(self.draft)
            self.app.store.save(self.session, "Loaded illustrative example by request")
            await self.recompose()
            self.preview_result()
        elif ident == "advanced":
            self.action_advanced()
        elif ident == "project":
            self.action_project()
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
        if self.invalid_fields:
            self.query_one("#form-error", Static).update("Correct the highlighted entries before saving.")
            return
        issues = METHODS[self.session.method_id].validate(self.draft)
        if issues:
            self.query_one("#form-error", Static).update("Please review: " + " ".join(issues))
            return
        self.session.method_state = deepcopy(self.draft)
        self.session.completed_at = timestamp()
        self.app.store.save(self.session, "Completed " + METHODS[self.session.method_id].name)
        self.query_one("#form-error", Static).update("Saved · results calculated locally.")
        self.preview_result()

    def action_advanced(self) -> None:
        self.app.open_session(self.session, advanced=True)

    def action_project(self) -> None:
        self.app.show_project()

    def suggest(self, ident: str) -> None:
        pass

    def accept(self) -> None:
        pass

    def action_stop_ai(self) -> None:
        pass
