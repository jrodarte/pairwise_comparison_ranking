"""Portable imports and audit-friendly exports."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from . import __version__
from .models import Item, Project
from .ranking import RankingResult

CANDIDATES = ("name", "title", "feature", "item")


def import_items(path: Path, column: str | None = None) -> list[Item]:
    """Read newline-separated text, CSV or JSON items; preserve optional descriptions."""
    text = path.expanduser().read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        fields = reader.fieldnames or []
        candidates = [field for field in fields if field.strip().lower() in CANDIDATES]
        if column is None and len(candidates) > 1:
            raise ValueError("Choose a CSV column: " + ", ".join(candidates))
        selected = column or (candidates[0] if candidates else None)
        if selected not in fields:
            raise ValueError("CSV needs a name/title/feature/item column")
        entries: list[Any] = [dict(row, name=row[selected]) for row in reader]
    elif suffix == ".json":
        loaded = json.loads(text)
        entries = loaded.get("items", []) if isinstance(loaded, dict) else loaded
        if not isinstance(entries, list):
            raise ValueError("JSON must be an array or an object with an items array")
    elif suffix == ".txt":
        entries = text.splitlines()
    else:
        raise ValueError("Supported import formats: .txt, .csv, .json")
    items = []
    for entry in entries:
        if isinstance(entry, str):
            name, description, metadata = entry.strip(), None, {}
        elif isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry["description"]).strip() if entry.get("description") else None
            metadata = {k: v for k, v in entry.items() if k not in ("name", "description")}
        else:
            raise ValueError("Each JSON item must be a string or object")
        if not name:
            raise ValueError("Imported item names cannot be blank")
        items.append(Item(name=name, description=description, metadata=metadata))
    return items


def export_csv(results: list[RankingResult]) -> str:
    """Create a spreadsheet-ready leaderboard."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "rank",
            "name",
            "priority_score",
            "wins",
            "losses",
            "ties",
            "win_percentage",
            "points",
            "points_percentage",
            "total_comparisons",
        ]
    )
    for row in results:
        writer.writerow(
            [
                row.rank,
                row.item.name,
                f"{row.score:.1f}",
                row.wins,
                row.losses,
                row.ties,
                f"{row.win_percentage:.1f}",
                f"{row.points:g}",
                f"{row.points_percentage:.1f}",
                row.total,
            ]
        )
    return stream.getvalue()


def export_json(project: Project, results: list[RankingResult]) -> str:
    """Export the full project, effective comparisons and immutable audit events."""
    data = project.to_dict()
    data["application_version"] = __version__
    data["ranking_methodology"] = (
        "L2-regularized Bradley–Terry; ties 0.5 each; "
        "100 × logistic(strength), relative not percent"
    )
    data["results"] = [
        {
            "rank": row.rank,
            "item_id": row.item.id,
            "name": row.item.name,
            "priority_score": round(row.score, 1),
            "wins": row.wins,
            "losses": row.losses,
            "ties": row.ties,
            "points": row.points,
            "win_percentage": round(row.win_percentage, 1),
            "points_percentage": round(row.points_percentage, 1),
            "total_comparisons": row.total,
        }
        for row in results
    ]
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def export_markdown(project: Project, results: list[RankingResult]) -> str:
    """Create a compact GitHub/Jira-compatible Markdown report."""
    escape = lambda value: value.replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = [
        f"# {escape(project.name)}",
        "",
        f"Date: {project.modified_at[:10]}",
        "",
        "Ranking methodology: Complete pairwise comparison using L2-regularized "
        "Bradley–Terry scoring (ties = 0.5). Priority scores are relative, not percentages.",
        "",
        "| Rank | Feature | Priority Score | Wins | Losses | Ties | Win % |",
        "|-----:|---------|---------------:|-----:|-------:|-----:|------:|",
    ]
    for row in results:
        lines.append(
            f"| {row.rank} | {escape(row.item.name)} | {row.score:.1f} | "
            f"{row.wins} | {row.losses} | {row.ties} | {row.win_percentage:.1f} |"
        )
    return "\n".join(lines) + "\n"


def export_project(project: Project, results: list[RankingResult], path: Path) -> None:
    """Write an export in the format implied by its extension."""
    formatters = {
        ".csv": lambda: export_csv(results),
        ".json": lambda: export_json(project, results),
        ".md": lambda: export_markdown(project, results),
    }
    suffix = path.suffix.lower()
    if suffix not in formatters:
        raise ValueError("Export path must end in .csv, .json or .md")
    path.expanduser().write_text(formatters[suffix](), encoding="utf-8")
