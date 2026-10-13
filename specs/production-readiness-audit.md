# ThinkTUI production-readiness audit — 2026-10-09

Scope: all 40 methods (validate/calculate), 31 schema forms, 5 guided workflows, planner/handoffs, all main screens and
keybindings, reports, storage/migrations/import, AI providers/credentials. Every item below was reproduced (Textual pilot
or direct calls against scratch DBs) unless marked *(code review)*. Repro scripts: session scratchpad
(`mathA/ mathB/ forms/ guided/ screens/ storage/`).

Baseline: `ruff format`/`ruff check` clean; 279 tests pass via `uv run python -m pytest`. **None of the existing tests
catch any finding below.** Core math is correct (AHP eigenvector/CR, Bradley–Terry, Brier, EV, decision-tree rollback,
VOI/EVPI, Bayes, RPN, Monte Carlo moments all match independent references) — the problems are robustness, data safety,
UI and AI-guardrail gaps.

Severity: **P0** = crash that persists across launches / data loss / guardrail breach · **P1** = app crash or wrong saved
data in normal use · **P2** = wrong/misleading behavior, keyboard dead-ends · **P3** = polish.

---

## P0 — release blockers

1. **Rich-markup injection crashes the app, permanently.** User text is rendered with markup enabled everywhere.
   A project/analysis/row named `[/]` → `MarkupError`; since it's already saved, *every later launch crashes at Home*.
   Ordinary text like `Phase [draft]` / `TODO [x]` silently loses words.
   Sites: `screens.py:369-374` (Home table), `:533` ProjectView, `:745` History, `:800` JournalList, `:947-948` workspace
   title/problem, `:1323` tree rows, `:1417-1452` pairwise/results, `DeleteProjectDialog`; `form_screen.py:99,167,233,264`;
   `label_mapping_screen.py:132`; `matrix_mapping_screen.py:36`.
   Fix: `markup=False` on Label/Static, `Text(...)` for DataTable cells, or `rich.markup.escape` at one helper; add a
   regression test rendering every screen with `[/]` names.

2. **Snapshot import accepts data that bricks startup or crashes on open.** `storage.import_snapshot` (`storage.py:238-246`)
   only checks `method_state` is a dict and doesn't type-check timestamps/names.
   - `updated_at: 123` → Home `TypeError` on every launch (`screens.py:372`).
   - journal `decision: 5`, `problem_statement: ["x"]`, pairwise `ranking: "zzz"`, issue-tree parent cycle, premortem
     `entries: "zzz"`, monte_carlo `variables: [1]` → crash when opened.
   - Deeply nested JSON → uncaught `RecursionError` (`screens.py:414-416`). No file-size limit.
   - NaN/Infinity import and re-export as invalid JSON. "Duplicated from analysis <id>" event text isn't remapped.
   Fix: strict schema check on every field + run each method's `validate` on import, reject on failure; catch
   `RecursionError`/`Exception` around parse; cap file size; `allow_nan=False` on export.

3. **Migrations are not atomic.** `storage.py:99, 112-144`: Python sqlite3 auto-commits DDL/PRAGMA outside the `with`
   block, so an interruption between `ALTER`/`CREATE` and `PRAGMA user_version` leaves a DB that fails every subsequent
   `Store()` (`duplicate column name: changes`, `table project_events already exists`).
   Also: two instances starting on a fresh install crash 40/40 (`table projects already exists`, `:98-111`); a DB from a
   newer version is switched to WAL before being rejected (`:90` vs `:96`); a corrupt/newer DB gives a raw traceback
   (`app.py:97`, `__main__.py`). Fix: `isolation_level=None` + explicit `BEGIN IMMEDIATE … COMMIT` per migration step,
   re-read `user_version` inside the lock, version check before any PRAGMA write, friendly error + `doctor` hint.

4. **Edits lost on navigation/quit; quit can traceback.**
   - Ctrl+O / Ctrl+N / Ctrl+P from a workspace kill the 0.5 s autosave timer without flushing (`screens.py:1277-1287`).
   - `Q` only flushes journal workspaces (`app.py:311-315`); "What would change your mind?" lost elsewhere.
   - App closes the store before screens unmount (`app.py:162-166, 314`) → `ProgrammingError: Cannot operate on a closed
     database` from `form_screen.py:415-417` and `ProjectView.save_question` (`screens.py:560`); edit lost.
   Fix: flush pending saves in `on_unmount`/`on_screen_suspend`; pop all screens before closing the store.

5. **AI numeric judgments leak into saved data** (violates AGENTS.md "AI must never calculate numbers or silently change
   judgments"). `field_ai.py:28-47` filter misses:
   - Decision Matrix criteria bulk format `Quality | 9 | benefit` → Accept → saved `weight: 9.0`
     (`guided_screen.py:391-414`). **Confirmed end-to-end.**
   - `**Probability:** 0.7`, `Weight = .4`, `P(success) = 0.7`, `≈ 0.7`, `Weights: 0.4, 0.6`, `Cost: $5000`, `5k`,
     `Severity: 9`, `RPN 120`, `Prior: 0.3`, `Expected value: 1200`, `seventy percent`, `7 of 10`, `eight out of ten`,
     `½`, `Source reliability: 0.8`.
   - AI "Draft text" is offered for ACH evidence title *and source* (`guided_screen.py:369-383`) — AI can fabricate
     evidence/provenance.
   Fix: invert to an allow-list per field (text fields only; reject any line containing digits/number words/fraction
   glyphs in judgment-bearing contexts); never offer AI on evidence/source fields; parse bulk-paste AI output through a
   path that drops numeric columns.

6. **Unchanged example can be saved as a completed analysis** (all 31 form methods). `form_screen.py:570-599` lacks the
   example check that the JSON view has (`screens.py:1511-1519`); `completed_at` is set and the analysis can feed a
   planned handoff. Also the F6 view on an empty worksheet is pre-filled with the example, so editing one name stores
   all example numbers as user data. AGENTS.md: "Never treat examples as user evidence."

7. **Credentials and "local" traffic leak over the network.**
   - Local endpoints honor `http_proxy` → full chat payload sent to a proxy with no consent while labelled LOCAL
     (`ai.py:31, 186-191, 352`). Fix: `ProxyHandler({})` for local hosts.
   - API keys forwarded on cross-host redirects (`Authorization` / `x-api-key`) (`ai.py:344-353`). Fix: disable redirects
     or strip auth on host change.
   - `http://user:pw@host` base URLs are saved and shown in errors (`ai.py:339`, `storage.py:468-473`, `public_error`).
   - Ollama `*-cloud` models are used in Auto/local mode, sending prompts to ollama.com without remote consent *(needs
     decision)*.

## P1 — crashes and wrong data in normal use

8. **Validation lets non-ValueError exceptions escape → app exits.** `StructuredMethod.validate`
   (`advanced_decisions.py:18-23`) catches only Value/Key/TypeError; JSON worksheet (`screens.py:1478, 1537`), Monte Carlo
   worker (`:1681`), form save (`form_screen.py:591`), and unguarded `calculate` calls (`screens.py:1422, 1432`) catch
   even less. Reproduced crashes:
   - Wrong-shape rows: ACH/VOI/Stress Test/Evidence Matrix/Scenarios `ratings|payoffs|likelihoods|scores|actions` given
     as a list → `.items()` AttributeError; `forecasts:["q"]`, `variables:["x"]`, `nodes:["x"]`, matrix criteria as
     strings, `scores: null`, journal `decision: null`.
   - `OverflowError` from `float(huge_int)` in `number()` (`advanced_decisions.py:36`) — hits 13 methods.
   - Lognormal Monte Carlo `mean: 1000` → `OverflowError` (`forecasting.py:123-126`). Easy to hit: the form says "Enter
     your own mean" while the parameter is log-scale. Relabel or switch to real-space parameters.
   - `nested()` unbounded recursion (`issue_tree.py:40-45`): `id: null` self-parent → infinite recursion; chains
     ≥1,000 deep → `RecursionError`. Also O(n²).
   - `Pairwise.validate` only checks the `ranking` key exists (`methods.py:23-24`); `ranking: null` / `{}` / 0 items
     pass then crash in `calculate`.
   - `IssueTree.validate` catches only Key/ValueError; legacy entries without `statement` KeyError before the try.
   Fix: one shared shape validator (type-check lists/dicts/strings before access), `validate` returns messages for any
   `Exception`, every UI caller wraps `validate`/`calculate`/workers with a broad catch → notification.

9. **Raw Python text as validation messages.** `'question'`, `'tree'`, `'vary' must name one`, `string indices must be
   integers`, `object of type 'NoneType' has no len()`, "between any and any", "finite and at least None"
   (`advanced_decisions.py:21-22, 39-40`, `form_model.py:530`). Affects ACH, EV, decision tree, sensitivity, AHP,
   reference class, Monte Carlo, hypothesis tree, root cause, five whys, fishbone, fault tree, bow-tie, Fermi, Bayes,
   backcasting, constraints. "Correct the highlighted entries" names no field and highlights nothing
   (`form_screen.py:577`).

10. **No `sqlite3.Error` handling on writes** (`screens.py:449-451, 1203`, `form_screen.py:413`): read-only DB or "database
    is locked" crashes the UI. Two instances silently overwrite each other's edits (lost update, `storage.py:334-364`) —
    add a version/`updated_at` check or a single-instance lock.

11. **AI provider responses can crash the app.** Handlers catch only Runtime/KeyError (`screens.py:1909`,
    `field_ai.py:133`, `form_screen.py:678`):
    - Malformed SSE/NDJSON (`{"choices":["x"]}`, `content: 5`) → AttributeError/TypeError (`ai.py:502, 553-555, 591-593`).
    - Ollama `/api/tags` returning `[]`, `{"models":null}` → crash in Auto mode on Ctrl+K and Settings Ctrl+R
      (`ai.py:467, 815`).
    - CLI path (`ai.py:650-670`): stdin write happens outside `asyncio.timeout` (hangs indefinitely on a 300 KB prompt);
      `BrokenPipeError` escapes; `proc.kill()` leaves grandchildren; >16 MB line raises `ValueError` (`:633, 660`);
      cancelling `_run` leaves the CLI running (`:638-648`).
    - Model id passed as separate argv (`--model <value>`) — a value starting with `-` becomes a flag (`ai.py:690, 742`).
      Use `--model=value` and validate.

12. **Guided ACH/AHP: adding a label after judgments crashes.** `label_mapping_screen.py:28-45, 120-138` sets Select to `-1`
    (not an option) → `InvalidSelectValueError`. AHP also demands a mapping when only criteria judgments exist
    (`guided_workflow.py:488-496`). Removing labels is a dead end (count must match, `:306-316`).

13. **Guided keybindings dead in text areas.** F7 (back) and F6 (JSON) are swallowed by TextArea when it has focus — the
    default focus on several steps (`guided_screen.py:36-43`; mark bindings `priority=True`). Ctrl+E export doesn't fire
    from the path Input (Input uses Ctrl+E = end-of-line), and Enter has no handler (`:40, 208-210`).

14. **Forecast Journal guided flow.** Back to probability + F8 → `KeyError '_draft'` dead end, also after restart
    (`guided_workflow.py:569`). Back to question creates a *duplicate* forecast instead of editing (`:175-187, 564-570`).
    `_draft` is exported as "Method inputs (user-supplied)" (`reports.py:84`).

15. **Planned workflows stall on form-based stages.** `form_screen.py:115-121` has no "Continue planned workflow" button
    (11 of 24 planned stages; "Explore a complex system" is forms-only). Only reachable via F6 → JSON.

16. **Forms: judgments moved or lost.**
    - Keyed-grid judgment cells render off-screen at every size (VOI payoffs/likelihoods, stress test, evidence matrix) —
      no CSS for `.keyed-grid-row` (`form_screen.py:237-244`).
    - Renaming a grid column while typing transfers another column's judgments (`Rain`→`Rainy season` steals `Rainy`'s
      data) (`form_screen.py:386-392`, `form_model.py:570`).
    - AI Accept writes into the wrong field after rows change — positional IDs `form-field-N` (`form_screen.py:262, 627,
      688-690`).
    - Load example overwrites user `0`/`No` answers (falsy = empty, `:521-524`); bottleneck/constraints drop legitimate
      zero `proposal`/`throughput`.
    - Invalid numeric text silently reverted on redraw, then save succeeds (`:125-129`).
    - `action_save` mutates the draft before validating *(code review)* (`:579-590`).
    - Hidden data from switched node type / distribution is kept and exported (`:354-357`).

17. **Causal Loop hangs the UI.** Loop search (`catalog_systems.py:132-145`) is exponential with no early exit; 50 vars /
    300 links (within documented limits) runs >60 s on the UI thread (also from form preview `form_screen.py:433`). Use
    Johnson's algorithm or a time/step budget in a worker; report `truncated: true` when the 100-loop cap hits.

18. **Assumptions & Premortem invent judgments.** Missing ratings default to confidence 50/impact 5 and
    likelihood 1/impact 1 (`methods.py:116, 139`) while the table shows 0/0 (`screens.py:1398`); out-of-range values
    (`confidence: 500`) and string numbers are accepted, then `calculate` TypeErrors.

## P2 — incorrect or misleading behavior

19. **Math/validation correctness.**
    - Fault tree treats a repeated basic event as independent: `OR(AND(A,B),AND(A,C))` = 0.4375, should be 0.375; same
      name with different probabilities accepted (`catalog_risk_forecast.py:73-91`).
    - Overflow to ±inf silently saved/exported: Fermi, Stock-and-Flow, reference class (inf/NaN p10/p90), weighted matrix
      weights `1e308` → all scores 0 (`methods.py:84-85`). Add finite-result checks.
    - AHP rejects normal reciprocals (`0.333` vs 3 fails at `rel_tol=1e-5`; `"1/3"` rejected) and doesn't enforce the
      1–9 scale (`advanced_decisions.py:288`).
    - Ranking ties: equal-strength items get ranks 1/2/3; float noise defeats the name tie-break
      (`pairwise_prioritizer/ranking.py:121-132`). Round before sorting / assign equal ranks.
    - Stock-and-flow lets small negative stocks through (`catalog_systems.py:237`).
    - Weighted matrix: duplicate/blank names, missing `name` (KeyError in calculate), mixed int/str names crash sort,
      `True` accepted as 1 (`methods.py:57-93`).
    - Strings accepted as lists (`"hypotheses":"AB"` → A, B; sensitivity `"range":"01"`; scenarios drivers; fishbone
      causes; Monte Carlo `values:"123"`); `number()` accepts numeric strings incl. non-ASCII digits; ToC returns string
      throughput unconverted; mixed `1`/`"1"` ids produce duplicate keys.
    - Decision tree ignores (and doesn't validate) probabilities on decision branches; ties not flagged.
    - Duplicate checks are case/whitespace sensitive (ACH, AHP); VOI/Opportunity Cost trim mismatch gives `'Demand'`
      error.
    - Forecast probability `0.6` means 0.6 %, `60%` rejected; outcome `1.0` rejected but `"0.5"` accepted.

20. **Guided workflow state.**
    - F7 then F8 with no change un-finishes the analysis (`guided_screen.py:558`), blocking "Continue planned workflow".
    - "Test sensitivity of two options" creates a new duplicate-titled analysis on every press (`:643-657`); planner
      stages also create duplicate titles (`planning.py:56, 87, 242`) though create/rename reject them.
    - Planned matrix→sensitivity handoff auto-picks the top two, ignoring the review's pair selectors
      (`planning.py:76`), while the docstring says "explicitly selected".
    - "Use these starting points" discards unsaved typed rows without confirmation (`:753-764`).
    - Help-me-choose from Home offers "Start linked workflow" which always fails (no project)
      (`planning_screen.py:293-296, 340-342`).
    - Deleting one ACH evidence item / scenario strategy / assumption row shows "Delete analysis permanently… deletes its
      history too" (`guided_screen.py:631`, `screens.py:1607`).

21. **Reports.**
    - Markdown tables don't escape `|` or newlines → columns shift / table doesn't render (`reports.py:551, 561-567`).
    - Nested result sections render as one run-on paragraph (`:504-527`).
    - Pairwise brief dumps engine internals (UUIDs, seed, undo stack, audit log) as "user-supplied" inputs; unrounded
      scores (`:573-579`).
    - Journal text `## Fake` injects headings (`:593`).
    - Key Assumptions brief omits computed risk priority.

22. **Monte Carlo form never shows results** after a successful save (`form_screen.py:429-431`).

23. **Performance on the UI thread.** Monte Carlo re-parses `samples`/`discrete` per draw (5k values × 50k iterations =
    22–25 s, twice) (`forecasting.py:125-134`); pairwise engine rebuilds pair sets each decision (150 items ≈ 89 s total,
    `comparison_engine.py:48, 65`); Bradley–Terry with 400 items 1.7 s; no size caps outside Causal Loop. Precompute and
    move heavy calculation to workers; add documented size limits.

24. **Settings save is non-atomic.** A failed save still persists some keys and clears legacy host/model
    (`screens.py:2151-2181`). Validate all, then write in one transaction.

25. **Small-terminal layout.** At 60×20 the form editor is 4 rows (AI pane 9); 0 rows at 40×15; Load example / Advanced
    JSON / Project buttons clipped at 60 cols, Remove at 40 (`app.py:75-77`, `form_screen.py:114-120`). Collapse the AI
    pane below a width/height threshold.

26. **F6 JSON view has no way back to the form** for the 31 form methods (`screens.py:987-988`).

27. **Journal due-review logic.** Whitespace-only `actual_outcome` counts as reviewed; malformed dates (`2020-1-1`) silently
    never come due and aren't flagged.

## P3 — polish / hygiene

28. Issue tree hint says "Tab folds" (`screens.py:975`); `F` outside the tree moves focus (`:1823-1824`); Shift+Enter
    doesn't reach most terminals — README should say so or add an alternative.
29. Enter does nothing in New Analysis inputs (`screens.py:871-910`).
30. Export toasts show unexpanded `~`/relative paths and raw `[Errno 17]`; snapshot export path not stripped
    (`screens.py:685`). Expand `~`, show the resolved path, offer overwrite confirmation instead of refusing.
31. Duplicate project names allowed (indistinguishable in Home/Move dialog); Home "Recent work" sorted by `created_at`,
    not the "Updated" column; history detail shows titles as "id".
32. Editing a row then typing a new statement overwrites the edited row (no cancel-edit).
33. `doctor` builds a SQLite URI from an unencoded path (`#`, `?`, `%` in path break it) and prints a newer schema version
    without warning (`__main__.py:30`).
34. Events are append-only only by convention — add `BEFORE UPDATE/DELETE` triggers on `events` (via a migration).
35. Keyring write failure leaves the old keyring key, which returns on the next launch; Settings Test/Refresh send the
    typed key to any host pre-consent (no analysis content).
36. Other providers' API keys are inherited by `claude`/`codex` subprocesses — pass a minimal env.
37. Packaging: add `[tool.hatch.build.targets.sdist]` include list (sdist currently picks up `AGENTS.md`, `feature.md`,
    `specs/` with a second `pyproject.toml`); add upper bounds for `keyring`, `platformdirs`.
38. Docs: `docs/methods/catalog.md` says catalog methods use the JSON worksheet; README says schema forms. README
    "autosave", "readable Markdown reports" and "Shift+Enter" claims are currently false (see 4, 21, 28).
39. Local env only (not a repo bug): `.venv/bin/pytest` shebang points at the old
    `pairwise_comparison_ranking/.venv`, so `uv run pytest` fails — `rm -rf .venv && uv sync`.

---

## Suggested fix order

1. One shared rendering helper for user text (P0-1) + import hardening (P0-2) — these alone stop all "app won't launch".
2. Migration transactions + friendly startup errors (P0-3); unmount flush ordering (P0-4).
3. AI guardrails: numeric filter allow-list, example-as-evidence check, proxy/redirect/URL-credential fixes (P0-5..7).
4. Shared shape validator + broad exception boundary at every UI → validate/calculate/worker/AI/sqlite call (P1-8..11).
5. Guided/form flow bugs (P1-12..16), Causal Loop algorithm (P1-17), judgment defaults (P1-18).
6. P2 correctness and reports; then P3.

For each fix add a regression test (AGENTS.md requires it); a property/fuzz test that feeds random JSON shapes to every
method's `validate`/`calculate` and every screen's mount would have caught most of P0–P1.
