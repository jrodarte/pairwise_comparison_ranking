"""SQLite repository with versioned schema and append-only events."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import datetime
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from platformdirs import user_data_path

from .ai import EFFORT_LEVELS, EFFORT_PROVIDERS, PRESETS, PROVIDER_CHOICES, config_for, effort_levels
from .core import Session, timestamp


def _snapshot_json(value: object) -> None:
    """Bound imported JSON before it can reach recursive renderers or calculations."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 100_000 or depth > 60:
            raise ValueError("Snapshot is too large or deeply nested")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("Snapshot keys must be text")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif not (item is None or isinstance(item, (str, bool, int)) or isinstance(item, float) and isfinite(item)):
            raise ValueError("Snapshot contains a non-finite or invalid value")


def _date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _session_fields(row: dict) -> None:
    names = {field.name for field in fields(Session)}
    if set(row) != names:
        raise ValueError("Snapshot has missing or unknown analysis fields")
    for key in ("id", "project_id", "method_id", "title", "problem_statement", "objective", "context", "notes"):
        if not isinstance(row[key], str):
            raise ValueError(f"Snapshot analysis {key} must be text")
    for key in ("created_at", "updated_at"):
        if not _date(row[key]):
            raise ValueError(f"Snapshot analysis {key} must be a date")
    if row["completed_at"] is not None and not _date(row["completed_at"]):
        raise ValueError("Snapshot completion date is invalid")
    for key in ("stakeholders", "constraints"):
        if not isinstance(row[key], list) or any(not isinstance(item, str) for item in row[key]):
            raise ValueError(f"Snapshot analysis {key} must be a list of text")
    for key in ("assumptions", "evidence", "decisions"):
        if not isinstance(row[key], list) or any(not isinstance(item, dict) for item in row[key]):
            raise ValueError(f"Snapshot analysis {key} must be a list of objects")
    state = row["method_state"]
    if not isinstance(state, dict):
        raise ValueError("Snapshot method state must be an object")


SETTING_KEYS = {
    "ai_provider",
    "ai_consent",
    "ollama_host",
    "ollama_model",
    "openai_model",
    "theme",
    "export_dir",
    "coach_open",
}
CONSENT_SETTING = re.compile(r"ai\.([a-z_]+)\.consent")
PROVIDER_SETTING = re.compile(r"ai\.([a-z_]+)\.(model|base_url|consent_url|effort)")


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
            if (
                not old
                and not path
                and key not in {"id", "project_id", "method_id", "title"}
                and new.get(key) in ("", None, [], {})
            ):
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
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.migrate()
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError as exc:
                # A second instance may be upgrading under an exclusive schema lock.
                # DELETE journal mode is safe until a later connection enables WAL.
                if "locked" not in str(exc):
                    raise
            # Repository writes continue to use sqlite3's transactional `with db`.
            self.db.isolation_level = "DEFERRED"
        except Exception:
            self.db.close()
            raise

    @contextmanager
    def _migration(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def migrate(self) -> None:
        with self._migration():
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 7:
                raise ValueError("Database created by a newer ThinkTUI")
            if version == 0:
                schema = """
                    CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        created_at TEXT NOT NULL);
                    CREATE TABLE sessions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL
                        REFERENCES projects(id), method_id TEXT NOT NULL, data TEXT NOT NULL,
                        updated_at TEXT NOT NULL);
                    CREATE INDEX sessions_project ON sessions(project_id);
                    CREATE TABLE events (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL
                        REFERENCES sessions(id), timestamp TEXT NOT NULL, description TEXT NOT NULL);
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
                for statement in schema.split(";"):
                    if statement.strip():
                        self.db.execute(statement)
                self.db.execute("PRAGMA user_version=1")
                version = 1
            if version == 1:
                self.db.execute("ALTER TABLE events ADD COLUMN changes TEXT NOT NULL DEFAULT '[]'")
                self.db.execute("PRAGMA user_version=2")
                version = 2
            if version == 2:
                self.db.execute("ALTER TABLE projects ADD COLUMN planning_question TEXT NOT NULL DEFAULT ''")
                self.db.execute("PRAGMA user_version=3")
                version = 3
            if version == 3:
                # Keep original timestamps. Completion is inferred only from explicit
                # historical calculation/review events, never from opening a screen.
                for row in self.db.execute("SELECT id, data FROM sessions").fetchall():
                    data = json.loads(row["data"])
                    if data.get("completed_at"):
                        continue
                    event = self.db.execute(
                        """SELECT timestamp FROM events WHERE session_id=? AND
                        (description LIKE 'Calculated %' OR description LIKE 'Completed %'
                        OR description LIKE 'Guided %Reviewed%' OR description LIKE 'Finished %')
                        ORDER BY id DESC LIMIT 1""",
                        (row["id"],),
                    ).fetchone()
                    if event:
                        data["completed_at"] = event[0]
                        self.db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(data), row["id"]))
                self.db.execute("PRAGMA user_version=4")
                version = 4
            if version == 4:
                self.db.execute("""CREATE TABLE project_events (
                    id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    timestamp TEXT NOT NULL, before TEXT NOT NULL, after TEXT NOT NULL
                )""")
                self.db.execute("PRAGMA user_version=5")
                version = 5
            if version == 5:
                # Ordinary audit events cannot be rewritten. The only exception is
                # an explicitly requested destructive analysis/project deletion, and
                # its scoped permission lives only inside that transaction.
                self.db.execute("CREATE TABLE event_delete_permissions (session_id TEXT PRIMARY KEY)")
                self.db.execute("""CREATE TRIGGER events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'Audit events cannot be updated'); END""")
                self.db.execute("""CREATE TRIGGER events_no_delete BEFORE DELETE ON events
                    WHEN NOT EXISTS (SELECT 1 FROM event_delete_permissions
                                     WHERE session_id=OLD.session_id)
                    BEGIN SELECT RAISE(ABORT, 'Audit events cannot be deleted'); END""")
                self.db.execute("PRAGMA user_version=6")
                version = 6
            if version == 6:
                # Co-planner: user-approved memory shared across projects, and a conversation log.
                # Neither is part of analyses, events or snapshots.
                self.db.execute("""CREATE TABLE IF NOT EXISTS coach_memory (
                    id INTEGER PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL)""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS coach_messages (
                    id INTEGER PRIMARY KEY, project_id TEXT REFERENCES projects(id),
                    role TEXT NOT NULL CHECK (role IN ('user', 'coach')), text TEXT NOT NULL,
                    created_at TEXT NOT NULL)""")
                self.db.execute("PRAGMA user_version=7")

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
            before = self.project(project_id)["planning_question"]
            after = question.strip()
            if before == after:
                return
            self.db.execute("UPDATE projects SET planning_question=? WHERE id=?", (after, project_id))
            self.db.execute(
                "INSERT INTO project_events(project_id,timestamp,before,after) VALUES (?,?,?,?)",
                (project_id, timestamp(), before, after),
            )

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
            self.db.execute("DELETE FROM project_events WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM coach_messages WHERE project_id=?", (project_id,))
            self.db.execute(
                "INSERT OR IGNORE INTO event_delete_permissions SELECT id FROM sessions WHERE project_id=?",
                (project_id,),
            )
            self.db.execute(
                "DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE project_id=?)", (project_id,)
            )
            self.db.execute("DELETE FROM sessions WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM event_delete_permissions")
            self.db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def snapshot(self, project_id: str) -> dict:
        """Portable project backup, including events but never global settings/credentials."""
        project = self.project(project_id)
        analyses = self.sessions(project_id)
        return {
            "snapshot_version": 1,
            "project": dict(project),
            "sessions": [asdict(session) for session in analyses],
            "project_events": [
                dict(row)
                for row in self.db.execute(
                    "SELECT timestamp,before,after FROM project_events WHERE project_id=? ORDER BY id", (project_id,)
                )
            ],
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
        from .snapshot_validation import validate_state

        _snapshot_json(data)
        if not isinstance(data, dict) or data.get("snapshot_version") != 1:
            raise ValueError("Unsupported project snapshot")
        project = data.get("project", {})
        if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
            raise ValueError("Snapshot needs a named project")
        if not _date(project.get("created_at")):
            raise ValueError("Snapshot project creation date is invalid")
        if not isinstance(project.get("planning_question", ""), str):
            raise ValueError("Snapshot planning question must be text")
        analyses = data.get("sessions", [])
        events = data.get("events", [])
        project_events = data.get("project_events", [])
        if not isinstance(analyses, list) or not isinstance(events, list) or not isinstance(project_events, list):
            raise ValueError("Snapshot sessions and events must be arrays")
        events = [dict(row) if isinstance(row, dict) else row for row in events]
        try:
            original_project = str(UUID(project["id"]))
            if not isinstance(project.get("id"), str) or any(not isinstance(row, dict) for row in analyses):
                raise ValueError("Malformed project snapshot")
            for row in analyses:
                _session_fields(row)
                if not row["title"].strip():
                    raise ValueError("Snapshot has an unnamed analysis")
                if row["method_id"] not in METHODS:
                    raise ValueError("Snapshot contains an unknown method")
                validate_state(row["method_id"], row["method_state"])
                if row["completed_at"] and row["method_state"]:
                    try:
                        issues = METHODS[row["method_id"]].validate(row["method_state"])
                    except Exception as exc:
                        raise ValueError("Snapshot completed analysis has invalid inputs") from exc
                    if issues:
                        raise ValueError("Snapshot completed analysis has invalid inputs")
            sessions = [Session(**row) for row in analyses]
            for row in events:
                if isinstance(row, dict) and isinstance(row.get("session_id"), str):
                    row["session_id"] = str(UUID(row["session_id"]))
            old_ids = [str(UUID(session.id)) for session in sessions]
            for session, old_id in zip(sessions, old_ids, strict=True):
                session.id = old_id
                session.project_id = str(UUID(session.project_id))
            if len(set(old_ids)) != len(old_ids):
                raise ValueError("Duplicate analysis ID")
            if any(session.project_id != original_project or session.method_id not in METHODS for session in sessions):
                raise ValueError("Snapshot contains an invalid project or method reference")
            if any(
                not isinstance(row, dict)
                or not _date(row.get("timestamp"))
                or not all(isinstance(row.get(key), str) for key in ("before", "after"))
                for row in project_events
            ):
                raise ValueError("Snapshot contains an invalid planning event")
            if any(
                row["session_id"] not in old_ids
                or not isinstance(row["changes"], list)
                or any(
                    not isinstance(entry, dict) or not isinstance(entry.get("field"), str) for entry in row["changes"]
                )
                or not isinstance(row["description"], str)
                or not _date(row["timestamp"])
                for row in events
            ):
                raise ValueError("Snapshot contains an invalid event")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Malformed project snapshot") from exc
        new_id = str(uuid4())
        remapped = {old: str(uuid4()) for old in old_ids}
        audit_ids = {original_project: new_id, project["id"]: new_id, **remapped}
        audit_ids.update({row["id"]: remapped[str(UUID(row["id"]))] for row in analyses})
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
            for row in project_events:
                self.db.execute(
                    "INSERT INTO project_events(project_id,timestamp,before,after) VALUES (?,?,?,?)",
                    (new_id, row["timestamp"], row["before"], row["after"]),
                )
            for row in events:
                description = row["description"]
                for prefix in (
                    "Linked from analysis ",
                    "Created sensitivity analysis from ",
                    "Duplicated from analysis ",
                ):
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
        with self.db:
            previous = self.db.execute("SELECT data FROM sessions WHERE id=?", (session.id,)).fetchone()
            before = json.loads(previous[0]) if previous else {}
            if before and session.updated_at != before["updated_at"]:
                raise ValueError("Analysis changed in another window; reload before editing to avoid overwriting it")
            after = asdict(session)
            if before and not field_changes(before, after):
                return
            old_state = before.get("method_state", {})
            new_state = session.method_state
            meaningful = {k: v for k, v in old_state.items() if not k.startswith("_")} != {
                k: v for k, v in new_state.items() if not k.startswith("_")
            }
            if before and before.get("completed_at") == session.completed_at and meaningful:
                session.completed_at = None
            session.updated_at = timestamp()
            after = asdict(session)
            changes = field_changes(before, after)
            self.db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id, data=excluded.data, updated_at=excluded.updated_at",
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

    def delete_session(self, session_id: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO event_delete_permissions VALUES (?)", (session_id,))
            self.db.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            if self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,)).rowcount != 1:
                raise KeyError(session_id)
            self.db.execute("DELETE FROM event_delete_permissions WHERE session_id=?", (session_id,))

    def duplicate_session(self, session_id: str, target_project_id: str | None = None) -> Session:
        original = self.load(session_id)
        project_id = target_project_id or original.project_id
        self.project(project_id)
        existing = {row.title.casefold() for row in self.sessions(project_id)}
        title = original.title + " · copy"
        suffix = 2
        while title.casefold() in existing:
            title = f"{original.title} · copy {suffix}"
            suffix += 1
        state = deepcopy(
            {
                key: value
                for key, value in original.method_state.items()
                if not key.startswith("workflow_") and key != "_guided_step"
            }
        )
        duplicate = Session(
            project_id=project_id,
            method_id=original.method_id,
            title=title,
            problem_statement=original.problem_statement,
            objective=original.objective,
            context=original.context,
            stakeholders=deepcopy(original.stakeholders),
            constraints=deepcopy(original.constraints),
            assumptions=deepcopy(original.assumptions),
            evidence=deepcopy(original.evidence),
            decisions=deepcopy(original.decisions),
            notes=original.notes,
            method_state=state,
        )
        self.save(duplicate, "Duplicated from analysis " + session_id)
        return duplicate

    def move_session(self, session_id: str, target_project_id: str) -> None:
        self.project(target_project_id)
        session = self.load(session_id)
        if session.project_id == target_project_id:
            return
        if any(
            other.title.strip().casefold() == session.title.strip().casefold()
            for other in self.sessions(target_project_id)
        ):
            raise ValueError("Destination project already has an analysis with this title")
        session.project_id = target_project_id
        self.save(session, "Moved analysis to another project")

    def rename_session(self, session_id: str, title: str) -> None:
        if not title.strip():
            raise ValueError("Analysis title is required")
        session = self.load(session_id)
        if any(
            other.id != session_id and other.title.casefold() == title.strip().casefold()
            for other in self.sessions(session.project_id)
        ):
            raise ValueError("An analysis already has this title")
        session.title = title.strip()
        self.save(session, "Renamed analysis")

    def rename_project(self, project_id: str, name: str) -> None:
        if not name.strip():
            raise ValueError("Project name is required")
        with self.db:
            if self.db.execute("UPDATE projects SET name=? WHERE id=?", (name.strip(), project_id)).rowcount != 1:
                raise KeyError(project_id)

    def project_events(self, project_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT timestamp,before,after FROM project_events WHERE project_id=? ORDER BY id DESC", (project_id,)
        ).fetchall()

    def events(self, session_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT timestamp,description,changes FROM events WHERE session_id=? ORDER BY id DESC",
            (session_id,),
        ).fetchall()

    def setting(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def validate_setting(key: str, value: str) -> None:
        """Reject unsupported preferences and URL credentials before a transaction begins."""
        if not isinstance(value, str):
            raise ValueError("Setting values must be text")
        provider = PROVIDER_SETTING.fullmatch(key)
        consent = CONSENT_SETTING.fullmatch(key)
        if (
            key not in SETTING_KEYS
            and not (provider and provider.group(1) in PRESETS)
            and not (consent and consent.group(1) in PRESETS)
        ):
            raise ValueError("Unsupported setting")
        if (
            provider
            and provider.group(2) == "effort"
            and (value not in EFFORT_LEVELS or (value and provider.group(1) not in EFFORT_PROVIDERS))
        ):
            raise ValueError("Unsupported thinking level for provider")
        if key == "ai_provider" and value not in PROVIDER_CHOICES:
            raise ValueError("Unsupported provider")
        if key == "theme":
            from .themes import THEMES

            if value not in THEMES:
                raise ValueError("Unsupported theme")
        if (key == "ai_consent" or key == "coach_open" or consent) and value not in {"yes", "no"}:
            raise ValueError("Invalid consent")
        if (
            (key.endswith(("base_url", "consent_url")) or key == "ollama_host")
            and value
            and not value.startswith(("http://", "https://"))
        ):
            raise ValueError("Base URL must start with http:// or https://")
        if (key.endswith(("base_url", "consent_url")) or key == "ollama_host") and value:
            parts = urlsplit(value)
            if parts.username or parts.password or not parts.hostname:
                raise ValueError("URL must have a host and no embedded credentials")
        if len(value) > 500 or "\n" in value:
            raise ValueError("Invalid setting value")

    def set_settings(self, values: dict[str, str]) -> None:
        """Validate every non-secret preference, then commit all of them together."""
        for key, value in values.items():
            self.validate_setting(key, value)
        for preset_id in PRESETS:
            model_key, effort_key = f"ai.{preset_id}.model", f"ai.{preset_id}.effort"
            if model_key not in values and effort_key not in values:
                continue
            model = values.get(model_key, config_for(self, preset_id).model) or PRESETS[preset_id].default_model
            effort = values.get(effort_key, self.setting(effort_key))
            if effort not in effort_levels(preset_id, model):
                raise ValueError("Unsupported thinking level for provider model; choose Provider default")
        with self.db:
            self.db.executemany(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                values.items(),
            )

    def set_setting(self, key: str, value: str) -> None:
        """Non-secret preferences only; API keys belong to the OS keyring."""
        self.set_settings({key: value})

    def coach_memory(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT id, text, created_at FROM coach_memory ORDER BY id").fetchall()

    def add_coach_memory(self, text: str) -> None:
        """Only text the user typed or explicitly accepted; one short line per fact."""
        text = " ".join(text.split())
        if not text:
            raise ValueError("Memory text is required")
        if len(text) > 500:
            raise ValueError("Keep each memory under 500 characters")
        with self.db:
            self.db.execute("INSERT INTO coach_memory (text, created_at) VALUES (?, ?)", (text, timestamp()))

    def delete_coach_memory(self, memory_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM coach_memory WHERE id=?", (memory_id,))

    def clear_coach_memory(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM coach_memory")

    def coach_messages(self, limit: int = 40) -> list[sqlite3.Row]:
        rows = self.db.execute(
            "SELECT id, project_id, role, text, created_at FROM coach_messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return rows[::-1]

    def add_coach_message(self, role: str, text: str, project_id: str | None = None) -> None:
        if (
            project_id is not None
            and not self.db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
        ):
            project_id = None
        with self.db:
            self.db.execute(
                "INSERT INTO coach_messages (project_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                (project_id, role, text, timestamp()),
            )

    def clear_coach_messages(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM coach_messages")

    def close(self) -> None:
        self.db.close()
