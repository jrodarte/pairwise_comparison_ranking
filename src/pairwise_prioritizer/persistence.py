"""Atomic, per-project JSON persistence in the OS application data directory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from platformdirs import user_data_path

from .models import Project


class ProjectStore:
    """Manage separately saved projects; atomic replace prevents truncated autosaves."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or user_data_path("PairRank", "PairRank") / "projects"
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, project_id: str) -> Path:
        """Return the safe on-disk path for a UUID identifier."""
        from uuid import UUID

        return self.directory / f"{UUID(project_id)}.json"

    def save(self, project: Project) -> None:
        """Flush and atomically replace a project file after every change."""
        payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, suffix=".tmp", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(self.path(project.id))
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def load(self, project_id: str) -> Project:
        """Load one ranking."""
        return Project.from_dict(json.loads(self.path(project_id).read_text(encoding="utf-8")))

    def list_projects(self) -> list[Project]:
        """List latest projects first; damaged files are left untouched and skipped."""
        projects = []
        for path in self.directory.glob("*.json"):
            try:
                projects.append(Project.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(projects, key=lambda project: project.modified_at, reverse=True)

    def delete(self, project_id: str) -> None:
        """Delete one saved project."""
        self.path(project_id).unlink()
