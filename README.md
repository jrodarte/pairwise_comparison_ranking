# PairRank

**Pairwise Prioritization** · A keyboard-first terminal application for deciding what matters most.

PairRank presents two features, ideas, projects, or other work items at a time. Choose the higher priority (or a tie); it autosaves each decision and produces an evidence-based leaderboard. No spreadsheets or arbitrary 1–10 ratings required.

> Screenshot placeholder: `docs/pairrank-screenshot.png` — capture your own terminal session with your preferred screenshot tool.

## Why compare pairs?

Choosing between *two* options is often easier than assigning absolute scores to a long backlog. Complete pairwise comparison gives every item exactly one matchup with every other item: **n × (n − 1) / 2** decisions (5 → 10, 20 → 190, 50 → 1,225, 100 → 4,950). PairRank shows this workload before you start and warns for sets over 30 items. It does not estimate how long decisions will take.

## Install and run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pairrank
```

After installing the package with pip/uv, run `pairrank` directly. Other launch modes:

```bash
uv run pairrank new       # create a ranking
uv run pairrank resume    # resume the latest incomplete ranking
uv run pairrank history   # manage saved rankings
uv run pairrank demo      # prefill an unsaved 8-item example in the setup form
uv run pairrank --help
uv run pairrank --version
```

Demo mode **does not create a project** until you select Start comparisons. Regular startup never creates demo data. Rankings are stored under the OS-appropriate PairRank application data directory (via `platformdirs`); each decision is written to disk atomically. Restart and select Resume after an interruption.

## Automatic updates

When PairRank runs from a git clone of its GitHub repository, it checks for new commits in the
background at startup and every 30 minutes. New commits are fast-forward pulled and a
notification asks you to restart to use them. Updates are skipped (never forced) when you have
uncommitted edits to tracked files or your branch has diverged.

```bash
uv run pairrank update        # check and pull now, then exit
uv run pairrank --no-update   # launch without the background check
```

## Workflow and keyboard controls

| Where | Keys | Action |
| --- | --- | --- |
| Everywhere | `?`, `Q`, `Ctrl+C` | Help, safe exit, safe exit |
| Home | `N`, `R`, `H`, `I` | New, resume, saved rankings, import workflow |
| Comparison | `A` / `←`, `D` / `→`, `T` | Choose option A, choose option B, tie |
| Comparison | `U`, `S`, `P` | Undo last decision, defer this pair, project info |
| Results | `↑` / `↓`, `Enter`, `S` | Select, open details, cycle sort |
| Results | `M`, `R`, `E`, `Esc` | Matrix, revisit decisions, export, home |
| Saved rankings | `R`, `N`, `D`, `E`, `Delete` | Open, rename, fresh duplicate, export, delete (confirmed) |

Mouse selection is also supported for cards, buttons, and tables. Decisions require **one keypress** and move directly to the next pair. Skipped pairs return at the end of the queue. Undo restores the latest decision and puts a newly undecided pair at the front. The number of decisive choices, ties, skipped pairs, remaining pairs, and completion percentage stay visible. A project copy retains the item list but starts with fresh decisions.

## Import items

Paste one item per line into the setup editor, or supply a file path and select Import:

- `.txt`: one name per line.
- `.csv`: header `name`, `title`, `feature`, or `item` (case-insensitive); when multiple candidates exist, choose the desired column. An optional `description` field is retained; other fields become item metadata.
- `.json`: an array of strings or objects with `name`, optional `description`, and arbitrary metadata; also accepts `{ "items": [...] }`.

Review and edit imported names before starting. Names are trimmed; blank or case-insensitive duplicate names are rejected, and at least two are required. Additional file imports append to the existing editor contents.

## Ranking methodology

PairRank's **primary ranking** is an L2-regularized Bradley–Terry model. Rather than assuming that the item with the most raw wins is automatically strongest, it estimates the relative latent strength of each item using *all* head-to-head outcomes. If item A beats B, the model adjusts their strengths to make that observation more likely. Ties allocate half a result to each item. A small L2 penalty (0.15) keeps estimates finite for perfect records, cycles, and incomplete/disconnected results. The fitting algorithm uses stable logistic probabilities and coordinate Newton updates; no ML framework is required.

The displayed **Priority Score** is `100 × logistic(fitted strength)`, a convenient 0–100 **relative scale, not a percentage** and not an estimated probability of a specific match outcome. Equal-strength items receive 50. Scores can change when decisions change; rankings are sorted by this score, then by name. A cyclic outcome (A > B > C > A) is valid and does not need to be “fixed.” Near-adjacent scores (difference < 1 point) are flagged as nearly tied; this is **not** a statistical confidence interval.

Supporting figures: wins, losses, ties, total matches, pairwise points (1 for a win, 0.5 for a tie, 0 for a loss), win percentage / points percentage (`100 × points / played`). Win % therefore credits half a win for a tie. Results allow sorting by score, wins, *fewest* losses, win percentage, or name. Select an item for all its wins/losses/ties; the scrollable matrix shows W/L/T/— for every pairing. From results choose **Revisit** to filter by item and replace any saved matchup; the updated leaderboard appears immediately. History includes revisions and undos.

## Exports

In Results or Saved rankings press `E` and enter a file path ending in:

- `.csv` — leaderboard, score and all supporting statistics.
- `.json` — version, metadata, items, randomized order/seed, effective comparisons, original decision/revision/skip/undo audit events, timestamps, ranking results and methodology.
- `.md` — Markdown leaderboard with date and methodology (suitable for GitHub, Jira, or internal notes).

Use a path to an existing directory; exports overwrite an existing file at that path. Each saved comparison is identified by its canonical unordered pair, while preserving the original card orientation and actual choice. Randomized presentation order and left/right flips are reproducible from the saved seed, and the saved order itself is retained.

## Development and tests

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Architecture:

- `models.py`: typed item/project/comparison objects, reversible decision records and serialization.
- `comparison_engine.py`: seeded full round-robin scheduling, skip, decide, undo, fresh duplicate.
- `ranking.py`: UI-independent `RankingStrategy` protocol, Bradley–Terry estimator, statistics and matchup evidence.
- `persistence.py`: atomic per-project JSON autosaves in the OS application data directory.
- `import_export.py`: text/CSV/JSON ingestion and CSV/JSON/Markdown reports.
- `screens/`: independent Textual screens and modal dialogs; `app.py` contains styling and navigation.
- `tests/`: engine, numerical, round-trip, exports and Textual interaction tests.

Pair scheduling and ranking are separate interfaces, leaving room for future adaptive match selection or alternative ranking estimators without changing the saved outcome model.
