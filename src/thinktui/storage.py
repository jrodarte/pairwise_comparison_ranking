"""SQLite repository with versioned schema and append-only events."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from platformdirs import user_data_path

from .ai import PRESETS, PROVIDER_CHOICES
from .core import Session, timestamp

SETTING_KEYS = {"ai_provider", "ai_consent", "ollama_host", "ollama_model", "openai_model"}
PROVIDER_SETTING = re.compile(r"ai\.([a-z_]+)\.(model|base_url)")


def remap_audit_changes(changes: list, ids: dict[str, str]) -> list:
    """Remap identifiers in audited session fields without rewriting arbitrary user prose.

    Creation events can contain a whole method_state dictionary; subsequent edits
    normally contain a dotted field path. Both forms need their links remapped.
    """

    def rewrite(value: object, path: str) -> object:
        if path in {"id", "project_id", "method_state.source_session_id"} and isinstance(value, str):
            return ids.get(value, value)
        if isinstance(value, dict):
            return {key: rewrite(child, f"{path}.{key}" if path else key) for key, child in value.items()}
        if isinstance(value, list):
            return [rewrite(child, path) for child in value]
        return value

    return [
        {
            **entry,
            "before": rewrite(entry.get("before"), entry.get("field", "")),
            "after": rewrite(entry.get("after"), entry.get("field", "")),
        }
        for entry in changes
    ]


def field_changes(before: dict, after: dict) -> list[dict]:
    """Structured before/after changes for saved fields; lists are atomic values."""
    changes: list[dict] = []

    def walk(old: dict, new: dict, path: str = "") -> None:
        for key in sorted(old.keys() | new.keys()):
            if not path and key == "updated_at":  # the save timestamp is not a user edit
                continue
            field = f"{path}.{key}" if path else key
            old_exists, new_exists = key in old, key in new
            if old_exists and new_exists and isinstance(old[key], dict) and isinstance(new[key], dict):
                walk(old[key], new[key], field)
            elif not old_exists or not new_exists or old[key] != new[key]:
                changes.append(
                    {
                        "field": field,
                        "before": old.get(key),
                        "after": new.get(key),
                        "before_exists": old_exists,
                        "after_exists": new_exists,
                    }
                )

    walk(before, after)
    return changes


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_path("thinktui") / "thinktui.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def migrate(self) -> None:
        with self.db:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise ValueError("Database created by a newer ThinkTUI")
            if version == 0:
                self.db.executescript("""
                    CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        created_at TEXT NOT NULL);
                    CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL
                        REFERENCES projects(id), method_id TEXT NOT NULL, data TEXT NOT NULL,
                        updated_at TEXT NOT NULL);
                    CREATE INDEX sessions_project ON sessions(project_id);
                    CREATE TABLE events (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL
                        REFERENCES sessions(id), timestamp TEXT NOT NULL, description TEXT NOT NULL);
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)
                version = 1
            if version == 1:
                self.db.execute("ALTER TABLE events ADD COLUMN changes TEXT NOT NULL DEFAULT '[]'")
                self.db.execute("PRAGMA user_version=2")
                version = 2
            if version == 2:
                self.db.execute("ALTER TABLE projects ADD COLUMN planning_question TEXT NOT NULL DEFAULT ''")
                self.db.execute("PRAGMA user_version=3")

    def new_project(self, name: str) -> str:
        if not name.strip():
            raise ValueError("Project name is required")
        project_id = str(uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO projects (id,name,created_at) VALUES (?, ?, ?)", (project_id, name.strip(), timestamp())
            )
        return project_id

    def set_planning_question(self, project_id: str, question: str) -> None:
        with self.db:
            if (
                self.db.execute(
                    "UPDATE projects SET planning_question=? WHERE id=?", (question.strip(), project_id)
                ).rowcount
                != 1
            ):
                raise KeyError(project_id)

    def projects(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()

    def project(self, project_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return row

    def delete_project(self, project_id: str) -> None:
        """Permanently remove one project, its sessions and their events atomically."""
        with self.db:
            self.project(project_id)  # refuse stale selections without touching other projects
            self.db.execute(
                "DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE project_id=?)", (project_id,)
            )
            self.db.execute("DELETE FROM sessions WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def snapshot(self, project_id: str) -> dict:
        """Portable project backup, including events but never global settings/credentials."""
        project = self.project(project_id)
        analyses = self.sessions(project_id)
        return {
            "snapshot_version": 1,
            "project": dict(project),
            "sessions": [asdict(session) for session in analyses],
            "events": [
                {
                    "session_id": session.id,
                    "timestamp": row["timestamp"],
                    "description": row["description"],
                    "changes": json.loads(row["changes"]),
                }
                for session in analyses
                for row in reversed(self.events(session.id))
            ],
        }

    def import_snapshot(self, data: dict) -> str:
        """Import as a new project with remapped IDs; reject invalid input atomically."""
        from uuid import UUID

        from . import methods as _methods  # noqa: F401 - ensure method registry is available
        from .core import METHODS

        if not isinstance(data, dict) or data.get("snapshot_version") != 1:
            raise ValueError("Unsupported project snapshot")
        project = data.get("project", {})
        if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
            raise ValueError("Snapshot needs a named project")
        if not isinstance(project.get("planning_question", ""), str):
            raise ValueError("Snapshot planning question must be text")
        analyses = data.get("sessions", [])
        events = data.get("events", [])
        if not isinstance(analyses, list) or not isinstance(events, list):
            raise ValueError("Snapshot sessions and events must be arrays")
        try:
            original_project = str(UUID(project["id"]))
            sessions = [Session(**row) for row in analyses]
            old_ids = [str(UUID(session.id)) for session in sessions]
            if len(set(old_ids)) != len(old_ids):
                raise ValueError("Duplicate analysis ID")
            if any(session.project_id != original_project or session.method_id not in METHODS for session in sessions):
                raise ValueError("Snapshot contains an invalid project or method reference")
            if any(
                row["session_id"] not in old_ids
                or not isinstance(row["changes"], list)
                or any(
                    not isinstance(entry, dict) or not isinstance(entry.get("field"), str) for entry in row["changes"]
                )
                or not isinstance(row["description"], str)
                or not isinstance(row["timestamp"], str)
                for row in events
            ):
                raise ValueError("Snapshot contains an invalid event")
        except (KeyError, TypeError) as exc:
            raise ValueError("Malformed project snapshot") from exc
        new_id = str(uuid4())
        remapped = {old: str(uuid4()) for old in old_ids}
        audit_ids = {original_project: new_id, **remapped}
        with self.db:
            self.db.execute(
                "INSERT INTO projects (id,name,created_at,planning_question) VALUES (?,?,?,?)",
                (new_id, project["name"], timestamp(), project.get("planning_question", "")),
            )
            for session in sessions:
                old_id = session.id
                session.id = remapped[old_id]
                session.project_id = new_id
                source = session.method_state.get("source_session_id")
                if source in remapped:
                    session.method_state["source_session_id"] = remapped[source]
                self.db.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?)",
                    (session.id, new_id, session.method_id, json.dumps(asdict(session)), session.updated_at),
                )
            for row in events:
                description = row["description"]
                for prefix in ("Linked from analysis ", "Created sensitivity analysis from "):
                    if description.startswith(prefix):
                        description = prefix + remapped.get(description[len(prefix) :], description[len(prefix) :])
                self.db.execute(
                    "INSERT INTO events(session_id,timestamp,description,changes) VALUES (?,?,?,?)",
                    (
                        remapped[row["session_id"]],
                        row["timestamp"],
                        description,
                        json.dumps(remap_audit_changes(row["changes"], audit_ids)),
                    ),
                )
        return new_id

    def sessions(self, project_id: str | None = None) -> list[Session]:
        if project_id:
            rows = self.db.execute(
                "SELECT data FROM sessions WHERE project_id=? ORDER BY updated_at DESC",
                (project_id,),
            )
        else:
            rows = self.db.execute("SELECT data FROM sessions ORDER BY updated_at DESC")
        return [Session(**json.loads(row[0])) for row in rows]

    def load(self, session_id: str) -> Session:
        row = self.db.execute("SELECT data FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return Session(**json.loads(row[0]))

    def save(self, session: Session, description: str = "Updated analysis") -> None:
        session.updated_at = timestamp()
        with self.db:
            previous = self.db.execute("SELECT data FROM sessions WHERE id=?", (session.id,)).fetchone()
            before = json.loads(previous[0]) if previous else {}
            after = asdict(session)
            changes = field_changes(before, after)
            self.db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (
                    session.id,
                    session.project_id,
                    session.method_id,
                    json.dumps(after),
                    session.updated_at,
                ),
            )
            self.db.execute(
                "INSERT INTO events(session_id,timestamp,description,changes) VALUES (?,?,?,?)",
                (session.id, session.updated_at, description, json.dumps(changes)),
            )

    def events(self, session_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT timestamp,description,changes FROM events WHERE session_id=? ORDER BY id DESC",
            (session_id,),
        ).fetchall()

    def setting(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Non-secret preferences only; API keys belong to the OS keyring (see credentials.py)."""
        provider = PROVIDER_SETTING.fullmatch(key)
        if key not in SETTING_KEYS and not (provider and provider.group(1) in PRESETS):
            raise ValueError("Unsupported setting")
        if key == "ai_provider" and value not in PROVIDER_CHOICES:
            raise ValueError("Unsupported provider")
        if key == "ai_consent" and value not in {"yes", "no"}:
            raise ValueError("Invalid consent")
        if (
            (key.endswith("base_url") or key == "ollama_host")
            and value
            and not value.startswith(("http://", "https://"))
        ):
            raise ValueError("Base URL must start with http:// or https://")
        if len(value) > 500 or "\n" in value:
            raise ValueError("Invalid setting value")
        with self.db:
            self.db.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def close(self) -> None:
        self.db.close()
