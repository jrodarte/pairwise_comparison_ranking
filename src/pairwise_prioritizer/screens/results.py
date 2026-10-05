"""Leaderboard, detailed evidence, matrix, and editable matchup history."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from ..comparison_engine import decide
from ..import_export import export_project
from ..models import Comparison, Outcome, pair_key
from ..ranking import BradleyTerry, RankingResult, matchup_groups
from .common import BaseScreen, PromptDialog

SORTS = ("Score", "Wins", "Losses", "Win %", "Name")


class DetailDialog(ModalScreen[None]):
    """Selected item's results and the head-to-head evidence behind them."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, result: RankingResult, groups: dict[str, list[str]]) -> None:
        super().__init__()
        self.result = result
        self.groups = groups

    def compose(self) -> ComposeResult:
        row = self.result
        with Container(classes="dialog detail-dialog"):
            yield Label(row.item.name, classes="section-title")
            yield Static(row.item.description or "", classes="muted")
            yield Static(
                f"Rank  #{row.rank}       Priority score  {row.score:.1f}\n"
                f"Wins  {row.wins}       Losses  {row.losses}       Ties  {row.ties}\n"
                f"Points  {row.points:g}       Win %  {row.win_percentage:.1f}"
            )
            with VerticalScroll(classes="detail-scroll"):
                for category in ("Beat", "Lost to", "Tied"):
                    yield Label(category.upper(), classes="field-label")
                    yield Static("\n".join(self.groups[category]) or "—", classes="detail-list")
            yield Button("Close", id="close", variant="primary")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()


class RevisionDialog(ModalScreen[Outcome | None]):
    """Replace one matchup result; no change until an explicit choice."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("a", "left", "Choose A"),
        ("d", "right", "Choose D"),
        ("t", "tie", "Tie"),
    ]

    def __init__(self, left: str, right: str, current: str) -> None:
        super().__init__()
        self.left, self.right, self.current = left, right, current

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label("Reconsider comparison", classes="section-title")
            yield Static(f"{self.left}   vs   {self.right}\nCurrent: {self.current}")
            with Horizontal(classes="dialog-buttons"):
                yield Button(f"A  {self.left}", id="left", variant="primary")
                yield Button("T  Tie", id="tie")
                yield Button(f"D  {self.right}", id="right", variant="primary")
            yield Button("Cancel  [Esc]", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        getattr(self, f"action_{event.button.id}")()

    def action_left(self) -> None:
        self.dismiss(Outcome.A_WINS)

    def action_right(self) -> None:
        self.dismiss(Outcome.B_WINS)

    def action_tie(self) -> None:
        self.dismiss(Outcome.TIE)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ResultsScreen(BaseScreen):
    """Sortable Bradley–Terry leaderboard."""

    BINDINGS = [
        ("m", "matrix", "Matrix"),
        ("r", "revisit", "Revisit"),
        ("e", "export", "Export"),
        ("s", "sort", "Sort"),
        ("escape", "home", "Home"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.sort_index = 0
        self.displayed: list[RankingResult] = []

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page"):
            yield Label("Leaderboard", classes="hero")
            yield Static("", id="summary", classes="muted")
            yield Static("", id="sort-label", classes="field-label")
            yield DataTable(id="leaderboard", cursor_type="row", zebra_stripes=True)
            yield Static("", id="insight", classes="muted")
            with Horizontal(classes="actions"):
                yield Button("Revisit comparisons  R", id="revisit")
                yield Button("Matrix  M", id="matrix")
                yield Button("Export  E", id="export", variant="primary")
                yield Button("Sort  S", id="sort")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Rank", "Item", "Score", "W", "L", "T", "Win %")
        self.refresh_results()
        table.focus()

    def refresh_results(self) -> None:
        project = self.pairrank.project
        if project is None:
            return
        results = BradleyTerry().calculate(project.items, list(project.comparisons.values()))
        key = SORTS[self.sort_index]
        sorts = {
            "Score": lambda r: (r.rank,),
            "Wins": lambda r: (-r.wins, r.rank),
            "Losses": lambda r: (r.losses, r.rank),
            "Win %": lambda r: (-r.win_percentage, r.rank),
            "Name": lambda r: (r.item.name.casefold(),),
        }
        self.displayed = sorted(results, key=sorts[key])
        table = self.query_one(DataTable)
        table.clear()
        for row in self.displayed:
            badge = "◆" if row.rank <= 3 else " "
            table.add_row(
                f"{badge} {row.rank}",
                row.item.name,
                f"{row.score:.1f}",
                str(row.wins),
                str(row.losses),
                str(row.ties),
                f"{row.win_percentage:.1f}",
                key=row.item.id,
            )
        self.query_one("#sort-label", Static).update(
            f"SORTED BY {key.upper()}    ·    ↑↓ select    ·    Enter details"
        )
        self.query_one("#summary", Static).update(
            f"{project.name}    ·    {len(project.comparisons):,} / {project.total:,} "
            f"comparisons    ·    {project.status}    ·    scores are relative, not percentages"
        )
        close = [
            (a, b) for a, b in zip(results, results[1:], strict=False) if a.score - b.score < 1
        ]
        self.query_one("#insight", Static).update(
            f"Nearly tied: ranks #{close[0][0].rank} and #{close[0][1].rank} "
            f"(gap {close[0][0].score - close[0][1].score:.1f})."
            if close
            else "Strengths reflect all matchups, not just raw win totals."
        )

    def selected(self) -> RankingResult | None:
        table = self.query_one(DataTable)
        index = table.cursor_row
        return self.displayed[index] if 0 <= index < len(self.displayed) else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = next((r for r in self.displayed if r.item.id == event.row_key.value), None)
        project = self.pairrank.project
        if row and project:
            self.app.push_screen(
                DetailDialog(
                    row, matchup_groups(row.item, project.items, list(project.comparisons.values()))
                )
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "matrix": self.action_matrix,
            "revisit": self.action_revisit,
            "export": self.action_export,
            "sort": self.action_sort,
        }
        if event.button.id in actions:
            actions[event.button.id]()

    def action_sort(self) -> None:
        self.sort_index = (self.sort_index + 1) % len(SORTS)
        self.refresh_results()

    def action_matrix(self) -> None:
        self.pairrank.switch_screen(MatrixScreen())

    def action_revisit(self) -> None:
        chosen = self.selected()
        self.pairrank.switch_screen(RevisitScreen(chosen.item.id if chosen else None))

    def action_export(self) -> None:
        def export(value: str | None) -> None:
            if not value or self.pairrank.project is None:
                return
            try:
                project = self.pairrank.project
                rows = BradleyTerry().calculate(project.items, list(project.comparisons.values()))
                from pathlib import Path

                export_project(project, rows, Path(value).expanduser())
                self.notify(f"Exported to {value}")
            except (OSError, ValueError) as error:
                self.notify(str(error), severity="error")

        self.app.push_screen(
            PromptDialog("Export to a file", "~/rankings.csv, ~/rankings.json or ~/rankings.md"),
            export,
        )

    def action_home(self) -> None:
        self.pairrank.home()


class MatrixScreen(BaseScreen):
    """Scrollable all-versus-all outcome grid (W/L/T/—)."""

    BINDINGS = [("escape", "back", "Results")]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page"):
            yield Label("Head-to-head matrix", classes="hero")
            yield Static(
                "W win    ·    L loss    ·    T tie    ·    — not decided / same item",
                classes="muted",
            )
            yield DataTable(id="matrix", cursor_type="cell", zebra_stripes=True)
            yield Static(
                "Column numbers refer to the numbered item rows. Scroll to explore large sets.",
                classes="muted",
            )

    def on_mount(self) -> None:
        project = self.pairrank.project
        if not project:
            return
        table = self.query_one(DataTable)
        table.add_columns("Item", *[str(i) for i in range(1, len(project.items) + 1)])
        for i, item in enumerate(project.items, 1):
            cells = []
            for other in project.items:
                comparison = (
                    project.comparisons.get(pair_key(item.id, other.id))
                    if item.id != other.id
                    else None
                )
                if comparison is None:
                    cells.append("—")
                elif comparison.outcome == Outcome.TIE:
                    cells.append("T")
                else:
                    won = (item.id == comparison.item_a_id) == (
                        comparison.outcome == Outcome.A_WINS
                    )
                    cells.append("W" if won else "L")
            table.add_row(f"{i}  {item.name}", *cells)
        table.focus()

    def action_back(self) -> None:
        self.pairrank.results()


class RevisitScreen(BaseScreen):
    """Filter matchups by item and revise a prior decision in place."""

    BINDINGS = [("escape", "back", "Results")]

    def __init__(self, item_id: str | None = None) -> None:
        super().__init__()
        self.item_id = item_id
        self.pairs: list[Comparison] = []

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Container(classes="page"):
            yield Label("Revisit comparisons", classes="hero")
            yield Static(
                "Select an item, then select a matchup to change the decision. "
                "Changes recalculate scores immediately.",
                classes="muted",
            )
            yield DataTable(id="items", cursor_type="row")
            yield DataTable(id="matchups", cursor_type="row", zebra_stripes=True)
            yield Button("Back to leaderboard  Esc", id="back")

    def on_mount(self) -> None:
        project = self.pairrank.project
        if not project:
            return
        items_table = self.query_one("#items", DataTable)
        items_table.add_column("Filter by item")
        items_table.add_row("All items", key="all")
        for item in project.items:
            items_table.add_row(item.name, key=item.id)
        matches = self.query_one("#matchups", DataTable)
        matches.add_columns("Option A", "Option B", "Decision", "Decided at")
        self.refresh_matches()
        matches.focus()

    def refresh_matches(self) -> None:
        project = self.pairrank.project
        if not project:
            return
        names = {item.id: item.name for item in project.items}
        self.pairs = sorted(
            (
                c
                for c in project.comparisons.values()
                if self.item_id is None or self.item_id in (c.item_a_id, c.item_b_id)
            ),
            key=lambda c: c.sequence,
        )
        table = self.query_one("#matchups", DataTable)
        table.clear()
        for comparison in self.pairs:
            outcome = {
                Outcome.A_WINS: names[comparison.item_a_id],
                Outcome.B_WINS: names[comparison.item_b_id],
                Outcome.TIE: "Tie",
            }[comparison.outcome]
            table.add_row(
                names[comparison.item_a_id],
                names[comparison.item_b_id],
                outcome,
                comparison.decided_at[:16],
                key=comparison.key,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "items":
            self.item_id = None if event.row_key.value == "all" else str(event.row_key.value)
            self.refresh_matches()
            self.query_one("#matchups", DataTable).focus()
            return
        project = self.pairrank.project
        if not project:
            return
        comparison = project.comparisons[str(event.row_key.value)]
        names = {item.id: item.name for item in project.items}
        current = (
            "Tie"
            if comparison.outcome == Outcome.TIE
            else names[
                comparison.item_a_id
                if comparison.outcome == Outcome.A_WINS
                else comparison.item_b_id
            ]
        )

        def revise(outcome: Outcome | None) -> None:
            if outcome is None or self.pairrank.project is None:
                return
            decide(project, (comparison.item_a_id, comparison.item_b_id), outcome)
            self.pairrank.store.save(project)
            self.pairrank.results()
            self.notify("Decision updated. Leaderboard recalculated.")

        self.app.push_screen(
            RevisionDialog(names[comparison.item_a_id], names[comparison.item_b_id], current),
            revise,
        )

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.action_back()

    def action_back(self) -> None:
        self.pairrank.results()
