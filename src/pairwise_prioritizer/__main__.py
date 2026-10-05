"""Command line entry point."""

from __future__ import annotations

import argparse

from . import __version__
from .app import PairRankApp
from .updater import check_and_pull


def main() -> None:
    """Launch the TUI, optionally on a particular workflow."""
    parser = argparse.ArgumentParser(
        prog="pairrank", description="PairRank — Pairwise Prioritization"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["home", "new", "resume", "history", "demo", "update"],
        default="home",
        help="Open a workflow directly (demo loads an unsaved sample in the setup form; "
        "update pulls the latest version from GitHub and exits)",
    )
    parser.add_argument("--version", action="version", version=f"PairRank {__version__}")
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="Do not check GitHub for updates in the background",
    )
    args = parser.parse_args()
    if args.command == "update":
        print(check_and_pull().message)
        return
    PairRankApp(initial=args.command, auto_update=not args.no_update).run()


if __name__ == "__main__":
    main()
