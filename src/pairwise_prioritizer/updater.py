"""Self-update from the GitHub checkout PairRank is running from.

Only fast-forward pulls are attempted, and only when the working tree is clean, so local
edits are never overwritten. Installed (non-git) copies are left alone.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

PROJECT_NAME = 'name = "pairwise-prioritizer"'
CHECK_INTERVAL_SECONDS = 30 * 60
GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of one update check."""

    updated: bool
    message: str


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
    )
    return completed.stdout.strip()


def find_repo(start: Path | None = None) -> Path | None:
    """Return the PairRank git checkout containing ``start``, if there is one."""
    start = start or Path(__file__).resolve().parent
    try:
        root = Path(_git(start, "rev-parse", "--show-toplevel"))
    except (OSError, subprocess.SubprocessError):
        return None
    # Guard against pulling an unrelated enclosing repository.
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file() or PROJECT_NAME not in pyproject.read_text(encoding="utf-8"):
        return None
    return root


def check_and_pull(repo: Path | None = None) -> UpdateResult:
    """Fetch the upstream branch and fast-forward to it when new commits exist."""
    repo = repo or find_repo()
    if repo is None:
        return UpdateResult(False, "Not running from a git checkout; auto-update disabled.")
    try:
        try:
            _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        except subprocess.CalledProcessError:
            return UpdateResult(False, "No upstream branch configured; auto-update disabled.")
        _git(repo, "fetch", "--quiet")
        behind = int(_git(repo, "rev-list", "--count", "HEAD..@{u}"))
        if behind == 0:
            return UpdateResult(False, "PairRank is up to date.")
        if _git(repo, "status", "--porcelain", "--untracked-files=no"):
            return UpdateResult(False, f"{behind} update(s) available, but local edits block pull.")
        _git(repo, "merge", "--ff-only", "--quiet", "@{u}")
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        return UpdateResult(False, f"Update failed: {detail[-1] if detail else error}")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return UpdateResult(False, f"Update failed: {error}")
    return UpdateResult(True, f"Pulled {behind} update(s). Restart PairRank to apply them.")
