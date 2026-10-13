"""CLI entry point."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from urllib.parse import quote

from platformdirs import user_data_path

from . import __version__
from .app import ThinkApp
from .core import METHODS


def main() -> None:
    parser = argparse.ArgumentParser(prog="thinktui", description="Structured Thinking & Decision Toolkit")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["new", "open", "methods", "journal", "settings", "doctor"],
        default="open",
    )
    parser.add_argument("--version", action="version", version=f"ThinkTUI {__version__}")
    args = parser.parse_args()
    if args.command == "doctor":
        path = user_data_path("thinktui") / "thinktui.db"
        print(f"Database: {path}\nMethods: {len(METHODS)}")
        if path.exists():
            try:
                db = sqlite3.connect(f"file:{quote(Path(path).as_posix())}?mode=ro", uri=True)
                try:
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                    print(f"Schema version: {version}")
                    if version > 7:
                        print("Warning: this database requires a newer ThinkTUI; do not open it with this version")
                finally:
                    db.close()
            except sqlite3.Error as exc:
                print(f"Database could not be read: {exc}")
        else:
            print("Database not created yet")
        print("AI: not probed (open Settings and press Ctrl+R to check providers)")
        return
    try:
        app = ThinkApp(
            initial={"new": "new", "methods": "methods", "settings": "settings", "journal": "journal"}.get(
                args.command, "home"
            )
        )
    except (sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Could not open ThinkTUI database: {exc}. Run `thinktui doctor` and check your backup.\n")
    try:
        app.run()
    finally:
        app.store.close()


if __name__ == "__main__":
    main()
