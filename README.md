# ThinkTUI

**Structured Thinking & Decision Toolkit** — a local-first Textual workbench for auditable decisions. Python 3.12+ and [uv](https://docs.astral.sh/uv/) required.

```bash
uv sync
uv run thinktui
uv run pytest
```

Create a project, choose a method, name your analysis, and work through it. Resume from the home dashboard. Highlight any project and press **D** (or use Delete highlighted project); you can also delete from inside a project. The confirmation lists its analysis count and defaults to **Cancel**. Confirmed deletion permanently removes that project, its analyses, and their events; other projects and settings are unaffected. Data is stored in a versioned SQLite database in your OS application-data directory (`uv run thinktui doctor` prints its location). Workspace edits autosave when the database is writable; guided methods save after each validated step (unsaved text in the current step is not persisted). Export `.md` decision briefs or `.json` analysis records by entering an export path in the workspace and pressing **Ctrl+E**, or with **Choose location…**, a keyboard folder picker (arrows move, Enter opens a folder, Backspace goes up) that suggests a filename from the analysis title, remembers the last folder between sessions, and never overwrites an existing file. **Explain results** (**F9**, in forms, guided screens and workspaces) is an optional AI tutor for learning a method: ask what your results mean and follow up in a short discussion. It shares the method, title, problem, objective, assumptions, method state and locally calculated results only when you press Ask, never notes or history. Answers are shown, never saved, and any line containing a number that is not in your inputs or calculated results is withheld, so the AI cannot calculate for you.

**AI co-planner (optional).** Press **P** on Home (Plan with AI co-planner) for a step-by-step walkthrough, or **F10** anywhere to show or hide the co-planner panel. It stays docked beside every screen, keeps one continuous conversation as you move between screens, and remembers whether it was open. It teaches, advises and explains; it cannot change analyses. Paste multiline specifications, user stories or long paragraphs into the question editor; **Enter** adds a line and **Ask** sends the full text. Memory facts are separate short entries. When you press Ask it shares the current screen, the open project's name, planning question and analysis titles, the open analysis's inputs and locally calculated results, your approved memory and the recent conversation, never notes or history. Like Explain results, lines with numbers the AI did not take from that context are withheld. **Memory** persists across projects but holds only facts you typed (or `/remember …`) or explicitly accepted from a REMEMBER proposal; review, delete or clear it with the Memory button, which also clears the conversation. Memory and the conversation are stored locally (schema v7), never in exports or snapshots; deleting a project deletes its co-planner messages. Never put secrets in memory. Do not put confidential information in exports you intend to share.

**Implemented methods:** The initial Pairwise Ranking, Weighted Decision Matrix, Key Assumptions Check, Premortem, Issue Tree and Decision Journal remain available. The staged V0.2–V0.4 methods now also run locally: ACH, Decision Tree, Expected Value, Sensitivity Analysis, AHP, Probability Forecast Journal with Brier/calibration, Reference-Class Forecasting, Monte Carlo, Scenario Planning, Backcasting, Objectives Hierarchy, Value-Focused Thinking, FMEA and Theory of Constraints. Search the method library by name, category or problem. Decision Matrix, AHP, ACH, Forecast Journal and Scenario Planning open dedicated, keyboard-first guided steps by default when created or resumed; **F8** validates and saves the current step, **F7** goes back, **F6** opens the optional advanced JSON worksheet, **Ctrl+E** exports from review. Other staged and catalog methods open blank, schema-driven forms with repeatable rows and inline guidance. **Load example** is available only on an empty worksheet; it never replaces entered data and is never evidence. **F6** opens the advanced JSON view; forms save, calculate and export without JSON. Resume and export work as with other analyses. See [staged method input guide and limitations](docs/methods/staged.md). The remaining catalog methods are now also available: standalone Bradley–Terry, Value of Information, Opportunity Cost, Reversibility, Hypothesis Tree, Assumption Mapping, Root Cause, Five Whys, Fishbone, Evidence Matrix, Risk Matrix, Fault Tree, Bow-Tie, Fermi, Bayesian Updating, Indicators & Signposts, Strategy Stress Test, Causal Loop, Bottleneck and Stock-and-Flow. All **40 catalog entries** are selectable; most use schema-driven forms rather than guided method-specific screens. See the [remaining catalog input guide](docs/methods/catalog.md).

**Planning fields per entry:** Key Assumptions Check records, for each assumption, the statement, why you believe it (optional), your 0–100 confidence, your 1–10 impact if wrong, a validation test, **Disproved if…** (the result that would show *that* assumption is wrong, decided before testing), and a **Test result**: Not yet tested, Testing now, Held, Mixed result or Disproved (saved as Untested, Testing, Supported, Weak, Falsified). Results open with a test summary (for example "3 of 5 tested (2 held, 1 disproved)"), list disproved assumptions to revisit, and list TEST FIRST assumptions not yet tested. The summary only counts your recorded results; it never changes a rating. Ranked assumptions show the spec's quadrant: **TEST FIRST** (confidence below 50, impact 6+), **Important** (confident, impact 6+), **Monitor** (unsure, impact below 6) and **Watch** (confident, impact below 6). These are screening labels, not measurements. Premortem records each failure cause with an optional cause cluster, your likelihood and impact, preventive action, owner and early warning sign; results group causes by cluster. In both editors, **+ New** (or `+` when the list is focused) starts a blank entry. `Enter` on a ranked row, or **Edit selected**, loads it; the heading says whether you are adding or editing, and **Cancel edit** leaves the saved row unchanged. The field at the bottom is the analysis-wide "what would change your conclusion", separate from the per-entry field. Decision Journal also records the decision date, context, important assumptions (separately from risks), and has an "At the review date" section for the actual outcome and lessons. The review date cannot precede the decision date. Schema forms add rows with **+ Add ‹item›** buttons. They mark optional fields, and put the overall "what would change your mind?" after the analysis rows.

**Long text stays readable:** Planning text fields wrap and grow with what you type, up to 11 lines, and scroll inside beyond that. To resize a field, drag its bottom edge with the mouse, or press **Alt+↓** (taller) and **Alt+↑** (shorter) while it is focused. Double-click the bottom edge to fit the text again. A form remembers a chosen height while it is open, even after rows are added. One-line fields still submit with Enter and turn pasted line breaks into spaces; multi-line fields (rationale, lists, JSON) keep Enter for new lines. Numeric ratings, dates and paths stay compact one-line inputs. In schema forms, each repeatable row (a cause, hypothesis, milestone and so on) can be collapsed to its heading: click it, or press Enter on it. The heading names the row by its own text. **Collapse all** and **Expand all** act on a whole list, and a collapsed row stays collapsed when rows are added, moved or removed. In Key Assumptions Check and Premortem, the ranked list shows one line per row; **Space** on a highlighted row shows its full wrapped text, and **Show full text** expands every row.

**Method discovery & handoff:** Home → **Help me choose (H)** asks what you need to do and explains rule-based recommendations. Within a project → **Plan workflow** lets you enter a problem and start a curated, multi-step workflow; it creates only the first draft. Complete and review each stage, then choose **Continue planned workflow** to explicitly approve the next linked draft. Project View shows stage progress, status and the most recent edit. Select an analysis and press **F2** to rename or **Delete** to delete it (with confirmation). You can also choose an independent recommendation; no stage is silently run. From any analysis → **Recommended next method** suggests one-step handoffs. Handoffs copy only disclosed, user-approved problem/objective/selected labels; missing ratings, probabilities and evidence stay blank for you to fill. Links are snapshots, not live synchronizations; the source session ID is included in the new record and its audit event. On Decision Matrix review, choose two scored options (the top two ranked options are preselected) to start a linked sensitivity companion when there are at least two criteria. In a project, **Export project snapshot** writes the project, analyses and event history to JSON; Home → **Import snapshot** creates a new project and remaps linked analysis IDs. Settings, API keys and keyring credentials are not exported. Backups may still contain confidential *analysis content*: review before sharing.

**Shortcuts:** `Ctrl+N` new project, `Ctrl+O` home, `Ctrl+P` method library, `Q` quit; inside a pairwise workspace `A` left, `D` right, `T` tie, `S` skip, `U` undo. In an Issue Tree, select a row and type a new label, then `A` add child or `S` add sibling; `Enter` adds a child from the label input, the Add sibling button works on every terminal (`Shift+Enter` works only where the terminal sends it distinctly); use Edit to change a selected row's label; `F` folds/unfolds when the tree is focused; `Tab` always moves focus. `D` opens a confirmation dialog before deleting a subtree. Mark an analysis Finished to offer its `?`-ending leaf questions to Key Assumptions. Add root with the button. From a project, `H` opens event history; select an event to see its saved field-level before/after changes (pre-v2 events have descriptions only). Schema v6 blocks ordinary updates/deletes of audit events; confirmed deletion of an analysis or project removes its history deliberately. `J` from home opens decision records across projects; create a new record inside a project. In any workspace `Ctrl+S` save, `Ctrl+E` export, `Ctrl+K` challenge, `Esc` project. In guided screens `F7` previous, `F8` validate/save and next, `Ctrl+S` save the current step, `F6` advanced JSON, `Ctrl+E` export from review, `Esc` project. Inputs have normal text-entry priority; focus the tree table to use tree shortcuts.

**Pane visibility and Vim-like navigation:** On analysis screens, `Ctrl+1` toggles the editor pane, `Ctrl+2` toggles the AI pane, and `Ctrl+0` restores both. One pane always remains visible; hidden panes retain their contents. `F10` separately toggles the co-planner dock. Outside text fields, `J/K` move focus (or the selected list/table row), and `H/L` move between editor and AI panes (or table columns). In other screens, `H/L` move focus. Text inputs keep normal typing; `Tab` / `Shift+Tab` always navigate focus. Screen-specific shortcuts still take precedence.

**Clipboard and pane resizing:** Select text in an input or multiline editor and press `Ctrl+C` / `Ctrl+X`; `Ctrl+V` pastes from the desktop clipboard where supported, or from the app's own clipboard otherwise. In single-line inputs, `Ctrl+Shift+A` selects all; in multiline editors use mouse selection or `Shift` with the arrow keys (on screens without an `F7` shortcut, `F7` selects all). Drag-select displayed text and press `Ctrl+C` to copy it. Your terminal's native paste (often `Ctrl+Shift+V` or right-click Paste) also supports multiline text. Desktop clipboard integration uses macOS `pbcopy`/`pbpaste`, Windows PowerShell, or Linux `wl-copy`/`wl-paste`, `xclip`, or `xsel` when installed; terminal OSC 52 copy is a fallback subject to terminal support. On analysis screens, drag the highlighted divider between the editor and AI pane to resize them; on narrow terminals it becomes a horizontal divider. Drag the highlighted left edge of the F10 co-planner to resize its dock too (its width stays in effect when switching screens during this run). If your terminal does not forward mouse-drag events, **F3/F4** shrink/grow the editor (on narrow screens, its height), and the co-planner has **− Width / + Width** buttons; these controls are also reachable by Tab/Enter. On small terminals, dock width starts within the available range and the buttons disable at their limits; if there is no room to resize, the co-planner displays a notice. Terminal clipboard behavior depends on terminal settings (including remote SSH/tmux clipboard forwarding).

**AI and privacy:** AI is optional; every calculation works with it off. The default provider is **Auto**: if Ollama is running locally, ThinkTUI uses it with your saved model or the first installed chat model, and otherwise AI stays off. Open **Settings** (`S` on the home screen) to choose a provider:

| Provider | How it authenticates |
| --- | --- |
| Ollama (local or remote host) | none; models listed from the server |
| Claude subscription | your installed, signed-in `claude` CLI (Claude Code print mode; `ANTHROPIC_API_KEY` is removed from its environment so your Pro/Max plan is used) |
| ChatGPT subscription | your installed `codex` CLI (OpenAI Codex, `codex exec` in a read-only sandbox which can still READ local files if the model uses tools; avoid this provider if that risk is unacceptable; `OPENAI_API_KEY` is removed from its environment so your ChatGPT plan is used) |
| Cursor subscription | your installed official [Cursor Agent CLI](https://cursor.com/docs/cli/installation) (`agent`); sign in with `agent login`. ThinkTUI runs print mode in read-only Ask mode from a temporary workspace, removes `CURSOR_API_KEY`, and requires explicit remote consent. The CLI can still read files outside that workspace or use network tools; do not use it if you cannot accept that risk. Cursor's documented print mode takes the prompt as a command-line argument, potentially visible to other local processes while it runs. Your Cursor plan's usage limits/pricing apply. |
| Anthropic API | `ANTHROPIC_API_KEY` or a saved key |
| OpenAI, OpenRouter, Google Gemini, Groq, Mistral, DeepSeek, xAI, Together | the provider's usual env var (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, …) or a saved key |
| LM Studio / llama.cpp / vLLM, or any custom OpenAI-compatible endpoint | optional key; set the base URL |

Settings also offers 12 switchable palettes (ThinkTUI, Catppuccin Mocha/Latte, Tokyo Night, Nord, Dracula, Gruvbox Dark, Solarized Dark, Rosé Pine, Kanagawa, Everforest and One Dark). Preview one, then Save to keep it; Esc cancels the preview. In Settings you can edit the base URL and model independently for each provider (including Claude Sonnet, Opus, Haiku or Fable via the Claude CLI), refresh available models (`Ctrl+R`), test the connection (`Ctrl+T`), and paste an API key. Thinking effort (Provider default, Low, Medium, High) is saved **independently per service**. Explicit effort is sent only on AI requests, not the connection test. Mappings: Claude CLI `--effort`, Codex CLI `model_reasoning_effort`, Anthropic API adaptive thinking + `output_config.effort`, Ollama string `think`, OpenAI reasoning models and Groq GPT-OSS 20B/120B `reasoning_effort`, OpenRouter `reasoning: {effort: …}`. OpenAI GPT-4.1/4o/3.5 and other Groq models are default-only here. Local LM Studio/llama.cpp/vLLM and custom OpenAI-compatible endpoints offer an **opt-in** `reasoning_effort` control *only* if your specific server and model support that field. Gemini 2.5 maps Low/Medium/High to `extra_body.google.thinking_config.thinking_budget` (1024/8192/24576); Gemini 3 maps them to `thinking_level`. Mistral's documented adjustable models offer High; DeepSeek Flash/V4 Pro uses `thinking: {type: enabled}` plus High `reasoning_effort`; xAI Grok 4.5–4.7 and Together GPT-OSS 120B accept `reasoning_effort`. Models without a verified mapping show default-only controls. Cursor's official [CLI parameters](https://cursor.com/docs/cli/reference/parameters) expose `--model` but no documented effort flag, so Cursor remains default-only; if you need Cursor-specific effort controls, please specify a documented CLI option or confirm an alternative interface. [Gemini](https://ai.google.dev/gemini-api/docs/openai), [Mistral](https://docs.mistral.ai/studio/conversations/reasoning), [DeepSeek](https://api-docs.deepseek.com/guides/reasoning_model), [xAI](https://docs.x.ai/developers/model-capabilities/text/reasoning), and [Together](https://docs.together.ai/docs/inference/chat/reasoning) document their respective mappings. Not every model within a supported service accepts effort (e.g. OpenRouter Auto may route to a model without reasoning support); if rejected, choose Provider default. Effort requests do not guarantee how long or deeply the model reasons. ThinkTUI checks remote-sharing permission and subscription sign-in before sending anything, and prompts you to open Settings when setup is needed. Missing API keys and sanitized HTTP 401 authentication failures (including optional-key custom endpoints) also prompt for a key; a rejected request has already reached the provider, but the co-planner keeps your draft. It never signs in or grants consent automatically. For subscription providers, **Sign in** (`Ctrl+L`) temporarily hands the terminal to the vendor's own login command (`codex login`, `claude auth login --claudeai`, or `agent login`) and checks your login status when it finishes. Saved keys go to the OS keyring (Secret Service, macOS Keychain or Windows Credential Manager). If you untick *Remember* or no keyring is available, the key is kept only for the current session. Keys are never written to SQLite, exports or logs. A key you entered takes precedence over a keyring key, which takes precedence over the environment variable. `uv run thinktui doctor` reads the database schema version without migrations or probing the network or keyring. Open Settings and press `Ctrl+R` to refresh models explicitly.

Sending analysis to a remote provider requires consent for that *specific provider* in Settings; changing providers requires fresh consent. Local endpoints (`localhost`) do not. Only the current method, problem, objective, assumptions and method state are sent; private notes and other projects are excluded. AI suggestions never enter analysis data automatically. Key Assumptions, Premortem, guided screens and forms offer text-only drafts: review, edit, accept or dismiss them. Numeric judgments remain yours. The subscription options only run the vendors' official CLIs and never read their credential files; they are intended for your own personal use under each vendor's terms. Answers stream into the workspace as they arrive (Ollama, Claude, Cursor and API providers stream deltas; the Codex CLI delivers each message whole). While a request runs, a status line under the AI buttons shows a spinner, elapsed seconds and the current step: connecting, loading the model (Ollama reports when a model is not yet in memory), waiting for the first response, or receiving the answer with a word count. It ends with ✓ or ✗. The AI buttons are disabled until the request finishes. `Ctrl+G` or **Stop AI** cancels a request and keeps the partial answer on screen, unsaved. Failures preserve local work. Never include secrets in an analysis sent to AI.

**Current scope:** Decision Journal shows due reviews when you open ThinkTUI; it does not send scheduled notifications outside the app. Event changes are field-level (arrays are recorded as a whole), not a full version-control/revert facility. The catalog methods have deterministic validation/calculation or explicitly non-scoring structural outputs through schema-driven forms. This is **not** a dedicated guided step-by-step screen for every method; complex nested or dynamic maps still need tailored controls, and F6 remains available for advanced edits. Five flagship methods have guided step-by-step screens. See [six form walkthrough screenshots](docs/ux-screenshots/README.md). The rule-based planner also supports a small set of explicit, sequential, human-approved multi-method plans; it does not automatically run methods, chain all 40 methods, maintain live cross-analysis synchronization or generate a finished plan. Simulation, fault tree and causal loop calculations document their independence, model and size limits in the method guides. Additional method-specific visualizations, deep AI roles and comprehensive guided workflows remain UX work; do not confuse a selectable worksheet with a fully guided interface. Outstanding full-app audit work: dedicated per-method help prose and a browsable `?` help screen. Markdown reports still use generic nested sections for many methods and do not escape table delimiters in all user text; linked sources outside a loaded project may show their ID. Exports refuse to replace existing files rather than offering an overwrite dialog.

**Architecture:** `src/thinktui/core.py` defines sessions and a method protocol; `methods.py`, `advanced_decisions.py`, `forecasting.py`, `strategy_risk.py`, and `catalog_*.py` register deterministic methods; `planning.py` owns rule-based recommendations, curated plans and explicit handoffs; `planning_screen.py` presents the planner; `guided_workflow.py` and `guided_screen.py` implement the five stepwise methods; `storage.py` also owns atomic project deletion and portable project snapshots; `issue_tree.py` owns tree structure and traversal; `storage.py` owns SQLite and migrations; `ai.py` contains the provider registry and adapters; `credentials.py` handles API-key lookup and keyring storage; `screens.py` is Textual presentation; `reports.py` exports decision records. `src/pairwise_prioritizer/` remains available as the original full-featured PairRank TUI and is reused for the comparison engine. Existing PairRank data is not migrated automatically. Run `uv run pairrank` to access its original history, CSV imports, comparison matrix, and revision UI.

---

### Release-readiness follow-up

The 2026-10-09 production audit is **not fully resolved**. Before treating ThinkTUI as production-ready, finish and test: comprehensive semantic checks of *incomplete* worksheets beyond their imported field shapes; remaining UI error boundaries for read-only/locked SQLite and malformed provider responses; Forecast Journal restart and form judgment preservation; remaining report formatting and method-specific math/finite-result checks; worker-based heavy calculations and small-terminal layout. Snapshot imports are limited to 10 MB via the UI (direct `Store.import_snapshot` callers must also enforce their own byte limit). Keep backup copies of project snapshots and do not use the current release as the sole record of a critical decision.

## Original PairRank application

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
