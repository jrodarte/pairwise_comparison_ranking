"""CLI entry point."""

from __future__ import annotations

import argparse
import asyncio

from . import __version__, ai, credentials
from .app import ThinkApp
from .core import METHODS
from .storage import Store


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
        store = Store()
        print(f"Database: {store.path}\nMethods: {len(METHODS)}\nAI setting: {ai.status_label(store)}")
        try:
            config = asyncio.run(ai.resolve(store))
            print(f"AI active: {ai.describe(config)}")
            if status := ai.key_status(config.preset_id):
                print(status)
        except RuntimeError as exc:
            print(f"AI active: none ({exc})")
        ollama = asyncio.run(ai.detect_ollama(ai.config_for(store, "ollama").base_url))
        print("Ollama: " + (f"running, {len(ollama)} model(s)" if ollama is not None else "not detected"))
        print("Keyring: " + ("available" if credentials.keyring_available() else "unavailable (keys kept per session)"))
        store.close()
        return
    ThinkApp(
        initial={"new": "new", "methods": "methods", "settings": "settings", "journal": "journal"}.get(
            args.command, "home"
        )
    ).run()


if __name__ == "__main__":
    main()
