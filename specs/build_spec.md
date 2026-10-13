You are a senior Python architect, TUI product designer, decision scientist, and AI application engineer.

Build a polished, production-quality open-source terminal application named:

# ThinkTUI

Subtitle:

**Structured Thinking & Decision Toolkit**

The application is an interactive toolkit for rigorous:

- decision making
- planning
- prioritization
- forecasting
- problem decomposition
- strategy
- risk analysis
- systems thinking
- root-cause analysis
- structured analytic techniques

It should not be a collection of simple calculators.

The core product idea is:

> Walk the user through high-quality thinking processes step-by-step, preserve the reasoning and assumptions, optionally use AI as an active planning partner, and generate an auditable decision record at the end.

The application must work fully without AI.

When AI is enabled, it should become dramatically more useful.

AI should act as:

- thinking partner
- Socratic challenger
- brainstorming partner
- assumption finder
- red-team critic
- evidence synthesizer
- scenario generator
- decision-quality reviewer
- structured-analysis assistant

AI must NOT silently make decisions for the user.

The human remains responsible for judgments, weights, probabilities, rankings, and final decisions.

---

# 1. TECHNOLOGY STACK

Use:

- Python 3.12+
- Textual
- Rich where useful
- uv
- pytest
- ruff
- mypy or pyright if practical
- SQLite
- SQLAlchemy 2.x or a lightweight explicit repository layer
- platformdirs
- pydantic v2 where validation/configuration benefits from it
- scipy/numpy only where mathematically justified

Prefer small, explicit dependencies.

Do not use a web frontend.

This is a native terminal application.

It should work well in:

- Ghostty
- Linux terminals
- macOS Terminal/iTerm
- Windows Terminal

---

# 2. PROJECT ARCHITECTURE

Use a maintainable package structure.

A reasonable starting point:

```text
thinktui/
├── pyproject.toml
├── README.md
├── LICENSE
├── AGENTS.md
├── src/
│   └── thinktui/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       │
│       ├── core/
│       │   ├── models.py
│       │   ├── sessions.py
│       │   ├── projects.py
│       │   ├── workflow.py
│       │   ├── events.py
│       │   └── exceptions.py
│       │
│       ├── methods/
│       │   ├── base.py
│       │   ├── pairwise/
│       │   ├── decision_matrix/
│       │   ├── ahp/
│       │   ├── premortem/
│       │   ├── assumptions/
│       │   ├── ach/
│       │   ├── issue_tree/
│       │   ├── expected_value/
│       │   ├── decision_tree/
│       │   ├── sensitivity/
│       │   ├── monte_carlo/
│       │   ├── reference_class/
│       │   ├── forecasting/
│       │   ├── scenarios/
│       │   ├── backcasting/
│       │   ├── fmea/
│       │   └── constraints/
│       │
│       ├── ai/
│       │   ├── base.py
│       │   ├── service.py
│       │   ├── context.py
│       │   ├── prompts.py
│       │   ├── safety.py
│       │   ├── providers/
│       │   │   ├── openai_chatgpt.py
│       │   │   ├── openai_api.py
│       │   │   ├── ollama.py
│       │   │   └── disabled.py
│       │   └── agents/
│       │       ├── facilitator.py
│       │       ├── challenger.py
│       │       ├── analyst.py
│       │       ├── forecaster.py
│       │       └── reviewer.py
│       │
│       ├── persistence/
│       │   ├── database.py
│       │   ├── repositories.py
│       │   ├── migrations.py
│       │   └── settings.py
│       │
│       ├── import_export/
│       │   ├── csv.py
│       │   ├── json.py
│       │   ├── markdown.py
│       │   └── report.py
│       │
│       ├── screens/
│       │   ├── home.py
│       │   ├── method_library.py
│       │   ├── project.py
│       │   ├── workspace.py
│       │   ├── results.py
│       │   ├── settings.py
│       │   └── history.py
│       │
│       └── widgets/
│           ├── method_card.py
│           ├── ai_panel.py
│           ├── progress.py
│           ├── evidence_table.py
│           ├── matrix.py
│           ├── tree.py
│           └── help.py
│
└── tests/
```

Adjust this structure where appropriate.

Do not create giant files or God classes.

---

# 3. APPLICATION PHILOSOPHY

ThinkTUI should answer:

> “I have a messy problem. What structured thinking method should I use, and can you guide me through it?”

It should help turn:

```text
vague problem
    ↓
structured problem
    ↓
assumptions
    ↓
evidence
    ↓
alternatives
    ↓
analysis
    ↓
decision
    ↓
action
```

The application should feel like a professional analytical workstation.

---

# 4. HOME SCREEN

Create a polished dashboard.

Example:

```text
┌───────────────────────────────────────────────────────────────┐
│ ThinkTUI                                      Structured Work │
│ Structured Thinking & Decision Toolkit                       │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  New Analysis                                                 │
│  Continue Analysis                                            │
│  Method Library                                               │
│  Decision Journal                                             │
│  AI Planning Session                                          │
│  History                                                      │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│ Recent Work                                                   │
│                                                               │
│ Q4 Feature Priorities        Pairwise Ranking       Complete  │
│ API Migration Risks         Premortem              76%       │
│ Metadata Strategy           Scenario Planning      Complete   │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│ N New   C Continue   M Methods   J Journal   , Settings   ?   │
└───────────────────────────────────────────────────────────────┘
```

Keyboard-first.

---

# 5. METHOD LIBRARY

Create a searchable method catalog grouped by category.

## Decision & Prioritization

Implement or architect for:

1. Pairwise Comparison
2. Bradley-Terry Ranking
3. Weighted Decision Matrix
4. Analytic Hierarchy Process
5. Expected Value Analysis
6. Decision Trees
7. Value of Information
8. Sensitivity Analysis
9. Opportunity Cost Analysis
10. Reversibility Analysis

## Problem Analysis

11. Issue Tree
12. Hypothesis Tree
13. Key Assumptions Check
14. Assumption Mapping
15. Root Cause Analysis
16. Five Whys
17. Fishbone / Ishikawa
18. Analysis of Competing Hypotheses
19. Evidence Matrix

## Risk

20. Premortem
21. FMEA
22. Risk Matrix
23. Fault Tree Analysis
24. Bow-Tie Analysis

## Forecasting

25. Probability Forecast
26. Calibration / Brier Score
27. Reference-Class Forecasting
28. Fermi Estimation
29. Bayesian Updating
30. Monte Carlo Simulation

## Strategy

31. Scenario Planning
32. Backcasting
33. Indicators & Signposts
34. Strategy Stress Test
35. Value-Focused Thinking
36. Objectives Hierarchy

## Systems

37. Theory of Constraints
38. Causal Loop Analysis
39. Bottleneck Analysis
40. Stock-and-Flow conceptual modeling

Not every method must be fully implemented in the first release.

However, the architecture must allow new methods to be added as independent modules.

---

# 6. METHOD PLUGIN INTERFACE

Create a formal interface.

Conceptually:

```python
class ThinkingMethod(Protocol):
    id: str
    name: str
    category: MethodCategory
    description: str

    def create_session(...) -> AnalysisSession:
        ...

    def next_step(...) -> WorkflowStep:
        ...

    def validate(...) -> list[ValidationIssue]:
        ...

    def calculate(...) -> MethodResult:
        ...

    def summarize(...) -> MethodSummary:
        ...
```

A method should define:

- metadata
- inputs
- workflow steps
- calculations
- views/widgets
- AI capabilities
- outputs

Adding a method should not require modifying the entire application.

---

# 7. METHOD DISCOVERY

The user may not know which method to use.

Provide:

```text
Help Me Choose
```

Ask questions such as:

```text
What are you trying to do?

[ ] Rank alternatives
[ ] Choose between alternatives
[ ] Understand why something happened
[ ] Identify risks
[ ] Forecast an outcome
[ ] Plan for uncertainty
[ ] Explore a complex system
[ ] Challenge an existing plan
```

Then:

```text
Recommended methods

1. Weighted Decision Matrix
   Good when multiple criteria matter.

2. Pairwise Ranking
   Good when relative preference is easier than absolute scoring.

3. AHP
   Good when both criteria and alternatives require pairwise judgments.
```

If AI is enabled, AI may assist with method recommendation.

It must explain *why* the method fits.

---

# 8. UNIVERSAL ANALYSIS SESSION

All methods should run inside an AnalysisSession.

Store:

```python
id
project_id
method_id
title
problem_statement
objective
context
stakeholders
constraints
assumptions
evidence
notes
decisions
method_state
created_at
updated_at
completed_at
```

Autosave after meaningful changes.

---

# 9. PROJECT CONCEPT

Allow related analyses to live inside a project.

Example:

```text
Project: Data Governance FY27 Strategy

├── Objectives Hierarchy
├── Scenario Planning
├── Feature Pairwise Ranking
├── Architecture Decision Matrix
├── Premortem
└── Final Decision Review
```

Analyses should be able to reuse prior results.

Example:

An Objectives Hierarchy can feed criteria into a Decision Matrix.

A Premortem can feed risks into FMEA.

A Scenario Planning session can feed scenarios into Strategy Stress Testing.

---

# 10. AI MUST BE OPTIONAL

The entire application must work with:

```text
AI: OFF
```

Never make AI a dependency of core calculations.

All mathematical methods must be deterministic Python logic.

For example:

- Bradley-Terry ranking
- expected values
- sensitivity analysis
- Monte Carlo
- AHP calculations
- Brier scores

must work independently of an LLM.

---

# 11. AI PROVIDERS

Create a provider abstraction.

Example:

```python
class AIProvider(Protocol):
    async def complete(
        self,
        request: AIRequest,
    ) -> AIResponse: ...

    async def stream(
        self,
        request: AIRequest,
    ) -> AsyncIterator[AIChunk]: ...

    async def models(self) -> list[AIModel]: ...

    async def health_check(self) -> ProviderHealth: ...
```

Implement:

## Provider A — ChatGPT Account

Preferred UX:

```text
AI Provider

● ChatGPT Account
  Continue with ChatGPT

○ OpenAI API Key

○ Ollama

○ Disabled
```

Use the official documented OpenAI **Sign in with ChatGPT** flow for open-source applications.

Do NOT scrape ChatGPT credentials.

Do NOT read browser cookies.

Do NOT reuse undocumented Codex authentication files.

Do NOT copy tokens from another application.

Use documented OAuth/client registration and token handling only.

When available, this should allow eligible users to use their ChatGPT plan for AI requests.

If direct Responses API integration using the official OAuth flow is practical, prefer it.

If the official recommended architecture uses Codex app-server for the open-source token flow, use that documented integration.

Keep this provider isolated behind `AIProvider`.

The rest of ThinkTUI must not know whether the response came from ChatGPT OAuth, API key, or Ollama.

## Provider B — OpenAI API Key

Support:

```text
OPENAI_API_KEY
```

and secure interactive configuration.

Never store the raw API key inside:

- SQLite
- JSON project files
- exports
- logs
- Git repositories

Prefer:

1. environment variable
2. OS keyring
3. explicit session-only entry

If storing credentials is implemented, use the OS credential/keyring facility.

## Provider C — Ollama

Support local inference.

Allow:

```text
Host:
http://localhost:11434

Model:
qwen...
llama...
devstral...
```

Query available local models.

Allow the user to select one.

Support remote Ollama URLs as an advanced option.

## Provider D — Disabled

Always available.

---

# 12. AI SETTINGS

Settings screen:

```text
AI
──────────────────────────────────────────

Provider
● ChatGPT Account
○ OpenAI API
○ Ollama
○ Disabled

Model
[ automatic / model selector ]

Reasoning
[ Low | Medium | High ]

Planning Partner
[x] Enabled

Automatic suggestions
[x] Enabled

Challenge my assumptions
[x] Enabled

Ask before sending project context
[x] Enabled

Show AI reasoning summary
[x] Enabled

Token / usage display
[x] Enabled
```

Do not expose hidden model chain-of-thought.

“Reasoning summary” means a concise explanation of conclusions and considerations.

---

# 13. AI PANEL

Every analytical workflow should optionally have an AI side panel.

Example:

```text
┌────────────────────── Analysis ─────────────────────┐
│                                                     │
│ Current hypothesis:                                 │
│ Database connection pooling is causing latency.     │
│                                                     │
│ Evidence                                            │
│ • latency increased after deployment                │
│ • database CPU unchanged                            │
│ • connection count increased                        │
│                                                     │
├────────────────────── AI Partner ───────────────────┤
│                                                     │
│ I see two assumptions worth testing:                │
│                                                     │
│ 1. Increased connections are causal rather          │
│    than merely correlated.                          │
│                                                     │
│ 2. The deployment changed connection behavior.      │
│                                                     │
│ Suggested evidence to collect:                      │
│ • pool configuration before/after                   │
│ • connection wait time                              │
│ • rollback comparison                               │
│                                                     │
│ [A] Add assumptions   [E] Add evidence prompts      │
│ [C] Challenge me      [Chat] Ask question           │
└─────────────────────────────────────────────────────┘
```

AI responses should be actionable.

---

# 14. AI OPERATING MODES

Provide explicit modes.

## Facilitator

Guides the user through the method.

Example:

> “You have identified the objective. Now distinguish fundamental objectives from means objectives.”

## Challenger

Looks for:

- weak assumptions
- confirmation bias
- missing alternatives
- contradictions
- unsupported claims
- overconfidence
- ignored stakeholders
- framing errors

## Analyst

Synthesizes:

- evidence
- notes
- comparisons
- quantitative results

## Forecaster

Helps:

- identify base rates
- decompose uncertainty
- create probability estimates
- design reference classes

It must never fabricate reference-class data.

## Red Team

Actively attacks the plan.

Example:

```text
Assume this project fails in 12 months.

What are the strongest reasons?

Which current assumptions would have been wrong?
```

## Reviewer

Reviews the completed analysis for decision quality.

---

# 15. AI COMMAND PALETTE

Inside any analysis:

```text
Ctrl+K
```

opens:

```text
Ask AI

> Challenge my assumptions
> Find missing alternatives
> Suggest criteria
> Improve problem statement
> Generate counterarguments
> Identify missing evidence
> Run premortem
> Explain current results
> Find contradictions
> Suggest next analytical method
> Summarize analysis
> Draft decision brief
> Custom question...
```

---

# 16. AI CONTEXT CONTROL

This is critical.

Before AI receives information, build a structured context object.

Example:

```python
AIContext(
    project_summary=...,
    current_method=...,
    problem_statement=...,
    objective=...,
    assumptions=[...],
    evidence=[...],
    alternatives=[...],
    current_results=...,
)
```

Do not dump the entire database into every prompt.

Use only relevant context.

Display what categories are being shared.

Allow:

```text
Context sent to AI

[x] Problem statement
[x] Alternatives
[x] Assumptions
[x] Evidence
[x] Current calculations
[ ] Private notes
[ ] Historical projects
```

---

# 17. DATA PRIVACY

This application may be used at work.

Therefore make privacy obvious.

Before first AI use:

```text
AI PRIVACY

AI assistance may send selected analysis content
to the configured AI provider.

Local calculations and saved projects remain local.

You control which information is included.

[Review Settings]   [Continue]
```

Provide a persistent status indicator:

```text
AI: ChatGPT
```

or:

```text
AI: Ollama / Local
```

or:

```text
AI: Off
```

For Ollama local use, clearly identify it as local.

Never claim enterprise confidentiality guarantees the application itself cannot verify.

---

# 18. AI MUST DISTINGUISH FACTS FROM SUGGESTIONS

AI generated content must carry provenance.

Represent entries as:

```python
source = USER
source = AI_SUGGESTED
source = IMPORTED
source = CALCULATED
```

AI suggestions do not automatically become analysis facts.

Example:

```text
AI suggestion

Potential assumption:
"The source system APIs will remain stable."

[A] Accept
[E] Edit
[D] Dismiss
```

Accepted suggestions become user-approved entries.

---

# 19. CORE MODULE 1 — PAIRWISE PRIORITIZATION

Port the previously defined PairRank concept into ThinkTUI.

Features:

- complete pair generation
- random pair ordering
- randomized left/right placement
- ties
- skip
- undo
- autosave
- Bradley-Terry scoring
- raw wins/losses/ties
- pairwise matrix
- rankings
- export
- revisit decision

AI capabilities:

```text
Explain why these two are difficult to compare
Suggest comparison criteria
Challenge inconsistent choices
Detect preference cycles
Summarize top-ranked items
Identify surprising outcomes
```

AI must not choose between the two unless specifically asked for an advisory opinion.

---

# 20. CORE MODULE 2 — WEIGHTED DECISION MATRIX

Workflow:

```text
Define decision
      ↓
Define alternatives
      ↓
Define criteria
      ↓
Weight criteria
      ↓
Score alternatives
      ↓
Calculate ranking
      ↓
Sensitivity analysis
```

Allow criteria:

```text
Business Value        30%
Risk Reduction        25%
Customer Impact       20%
Engineering Effort    15%
Strategic Alignment   10%
```

Support benefit and cost criteria.

Automatically normalize weights.

AI:

- suggest missing criteria
- detect overlapping criteria
- explain double counting
- challenge arbitrary weights
- suggest measurable definitions

---

# 21. CORE MODULE 3 — AHP

Implement Analytic Hierarchy Process.

Workflow:

```text
Goal
 ↓
Criteria
 ↓
Pairwise criteria comparisons
 ↓
Alternatives
 ↓
Pairwise alternative comparisons
 ↓
Priority calculation
```

Calculate:

- pairwise matrices
- principal priority vectors
- consistency index
- consistency ratio

Warn on poor consistency.

Show:

```text
Consistency Ratio: 0.18

⚠ Your judgments may be inconsistent.
Consider reviewing:
Security vs Cost
Cost vs Time-to-Market
Security vs Time-to-Market
```

AI may explain inconsistencies but not rewrite them automatically.

---

# 22. CORE MODULE 4 — KEY ASSUMPTIONS CHECK

Workflow:

```text
Claim / Plan
     ↓
Extract assumptions
     ↓
Rate confidence
     ↓
Rate impact if wrong
     ↓
Prioritize assumptions
     ↓
Define validation actions
```

Matrix:

```text
                     IMPACT
                Low       High

CONFIDENCE High   Watch     Important

           Low    Monitor   TEST FIRST
```

AI should be particularly useful here.

Prompt AI to:

- surface hidden assumptions
- distinguish assumptions from known facts
- propose falsification tests
- identify what evidence would change confidence

---

# 23. CORE MODULE 5 — PREMORTEM

Workflow:

```text
Describe plan
     ↓
Assume catastrophic failure
     ↓
Generate failure explanations
     ↓
Cluster causes
     ↓
Estimate likelihood/impact
     ↓
Choose preventive actions
```

AI should provide a strong Red Team capability.

Example:

```text
Imagine it is 12 months from now.

The initiative has failed badly.

What happened?
```

Keep AI suggestions separate from user-generated ones.

---

# 24. CORE MODULE 6 — ANALYSIS OF COMPETING HYPOTHESES

Support ACH.

Workflow:

```text
Question
 ↓
Hypotheses
 ↓
Evidence
 ↓
Consistency matrix
 ↓
Diagnosticity
 ↓
Inconsistency analysis
 ↓
Hypothesis ranking
```

Matrix:

```text
Evidence                 H1   H2   H3   H4

Deployment preceded issue +    ?   ++   -
DB CPU normal            --    ?    +   +
Network latency high      -   ++    ?   +
Traffic unchanged         ?    ?    ?   --
```

Values:

```text
++
+
0
-
--
?
```

Emphasize evidence that contradicts hypotheses.

AI:

- generate alternative hypotheses
- identify duplicated hypotheses
- suggest disconfirming evidence
- point out confirmation bias
- propose discriminating tests

---

# 25. CORE MODULE 7 — ISSUE TREE

Interactive tree builder.

Example:

```text
Why is API adoption low?

├── Awareness
│   ├── Documentation
│   └── Communication
│
├── Ability
│   ├── Authentication
│   ├── SDK support
│   └── Integration effort
│
└── Value
    ├── Missing capabilities
    └── Performance
```

Keyboard controls:

```text
Enter      Edit
A          Add child
S          Add sibling
D          Delete
Tab        Expand/collapse
AI         Suggest branches
```

AI should help make trees:

- mutually exclusive where possible
- collectively exhaustive where reasonable
- logically coherent

Do not pretend perfect MECE decomposition always exists.

---

# 26. CORE MODULE 8 — DECISION TREE / EXPECTED VALUE

Support:

- decisions
- chance nodes
- terminal outcomes

Example:

```text
Build
├── Success 70% → +$2M
└── Failure 30% → -$500K

Do Not Build
└── $0
```

Calculate expected values.

Validate child probabilities sum to 1.

AI:

- identify missing outcomes
- challenge probability estimates
- suggest useful sensitivity ranges

---

# 27. CORE MODULE 9 — SENSITIVITY ANALYSIS

This should be available as both:

1. standalone method
2. companion analysis for other methods

Allow selecting parameters and ranges.

Example:

```text
Business Value Weight

10%  ─────────────────────────── 50%

Current: 30%
```

Show when rankings change.

Calculate:

```text
Decision switches at 27.4%.
```

This is extremely useful.

Support tornado-style data output even if TUI visualization is simple.

---

# 28. CORE MODULE 10 — MONTE CARLO

Support uncertain variables.

Distributions:

- uniform
- triangular
- normal
- log-normal
- discrete
- custom samples

Example:

```text
Implementation Cost
Distribution: Triangular

Minimum:     $400K
Most likely: $650K
Maximum:     $1.1M
```

Output:

```text
Expected ROI             41%
Probability ROI > 0      78%
P10                      ...
P50                      ...
P90                      ...
```

Use deterministic random seeds where useful for reproducibility.

Do not let AI perform the simulation.

Python performs calculations.

AI interprets results.

---

# 29. CORE MODULE 11 — REFERENCE-CLASS FORECASTING

Workflow:

```text
Forecast question
 ↓
Choose reference class
 ↓
Enter historical cases
 ↓
Calculate distribution
 ↓
Make inside-view forecast
 ↓
Compare outside view
 ↓
Adjust forecast
```

Example:

```text
Historical migration projects

Estimate   Actual

3 mo       5 mo
4 mo       8 mo
6 mo       11 mo
```

Calculate:

- median overrun
- mean overrun
- distribution
- percentile ranges

AI can help identify what would constitute a valid reference class.

Never fabricate historical observations.

---

# 30. CORE MODULE 12 — FORECASTING JOURNAL

Allow probability forecasts.

Example:

```text
Question:
Will project X launch before December 1?

Probability:
72%

Resolution:
December 1

Rationale:
...
```

Once resolved:

```text
Outcome:
YES
```

Calculate Brier score.

Maintain calibration statistics.

Show:

```text
Your 70–79% forecasts:

Predictions: 32
Occurred:    23
Observed:    71.9%
```

This should become a long-term decision skill trainer.

---

# 31. CORE MODULE 13 — SCENARIO PLANNING

Workflow:

```text
Strategic question
 ↓
Driving forces
 ↓
Critical uncertainties
 ↓
Select major axes
 ↓
Generate scenarios
 ↓
Implications
 ↓
Strategies
 ↓
Indicators/signposts
```

AI is extremely useful here.

Use AI to suggest:

- driving forces
- uncertainty dimensions
- plausible scenario narratives
- implications
- indicators

But require user approval.

---

# 32. CORE MODULE 14 — BACKCASTING

Start with desired future state.

Example:

```text
December 2028

90% of enterprise datasets have automated lineage.
```

Ask:

```text
What must be true immediately before this?

2028 Q3
2028 Q2
2028 Q1
...
Today
```

Build backward milestones.

AI assists with missing dependencies.

---

# 33. CORE MODULE 15 — FMEA

Fields:

```text
Failure Mode
Effect
Cause
Existing Controls
Severity
Occurrence
Detectability
Recommended Action
Owner
```

Calculate risk priority information.

Do not blindly treat traditional RPN as universally authoritative.

Expose individual dimensions as well.

Allow configurable scoring scales.

---

# 34. THEORY OF CONSTRAINTS MODULE

Workflow:

```text
Define system goal
 ↓
Map throughput
 ↓
Identify bottleneck
 ↓
Exploit constraint
 ↓
Subordinate
 ↓
Elevate
 ↓
Reassess
```

AI may question whether the identified constraint is truly system-limiting.

---

# 35. CROSS-METHOD WORKFLOWS

ThinkTUI's biggest advantage should eventually be composing methods.

Example:

```text
New Initiative
     ↓
Value-Focused Thinking
     ↓
Objectives Hierarchy
     ↓
Decision Matrix
     ↓
Sensitivity Analysis
     ↓
Premortem
     ↓
Final Decision Review
```

Another:

```text
Production Incident
     ↓
Issue Tree
     ↓
Competing Hypotheses
     ↓
Evidence Matrix
     ↓
Root Cause
```

Allow:

```text
Recommended next method
```

AI can recommend the next method based on current state.

---

# 36. DECISION JOURNAL

Implement a persistent decision journal.

Every important decision can store:

```text
Decision
Date
Context
Alternatives
Chosen option
Expected outcome
Confidence
Important assumptions
Risks
What would change my mind?
Review date
Actual outcome
Lessons learned
```

At the review date, surface the decision.

Later compare:

```text
Decision quality
vs.
Outcome quality
```

A good decision can produce a bad outcome.

A bad decision can produce a good outcome.

Preserve this distinction.

---

# 37. UNIVERSAL “WHAT WOULD CHANGE YOUR MIND?” FIELD

For major conclusions, support:

```text
What evidence would cause you to change this conclusion?
```

This should become a recurring ThinkTUI pattern.

AI can challenge answers such as:

```text
"Nothing would change my mind."
```

---

# 38. CONFIDENCE

Allow important claims to optionally carry confidence.

Example:

```text
Claim:
Vendor API will support our required throughput.

Confidence:
65%
```

Later confidence may be updated.

Store historical confidence changes.

---

# 39. EVIDENCE OBJECTS

Use structured evidence.

```python
Evidence(
    id=...,
    title=...,
    description=...,
    source=...,
    source_type=...,
    reliability=...,
    relevance=...,
    date=...,
    notes=...,
)
```

Allow evidence to be reused between analyses.

---

# 40. ASSUMPTION OBJECTS

```python
Assumption(
    statement=...,
    confidence=...,
    impact_if_wrong=...,
    validation_status=...,
    evidence_ids=[...],
)
```

Possible status:

```text
Untested
Testing
Supported
Weak
Falsified
```

---

# 41. AI DECISION REVIEW

When analysis is completed, offer:

```text
Run Decision Quality Review
```

AI should examine:

- framing
- objectives
- alternatives
- assumptions
- evidence
- uncertainty
- tradeoffs
- risks
- reversibility
- missing stakeholders
- confirmation bias
- unsupported certainty

Output:

```text
Decision Quality Review

Strong
✓ Alternatives are meaningfully distinct.
✓ Major cost uncertainty was modeled.

Needs Attention
⚠ Security impact depends on an untested assumption.
⚠ Only one external alternative was considered.
⚠ Probability estimates lack a reference class.

Suggested next actions
1. Validate authentication throughput.
2. Add "do nothing" as an explicit alternative.
3. Run sensitivity analysis on adoption.
```

Do not create a fake scientific “decision score” unless its methodology is explicit and defensible.

---

# 42. AI SOCRATIC MODE

Add:

```text
Socratic Mode
```

Rather than giving answers, AI asks one question at a time.

Example:

```text
You said the migration is "high priority."

What observable outcome makes it high priority?
```

After response:

```text
If that outcome does not occur, would you still consider the migration successful?
```

This mode should be deliberately probing.

---

# 43. AI BIAS CHECK

Command:

```text
Bias Check
```

AI examines current reasoning for possible:

- confirmation bias
- anchoring
- availability bias
- sunk-cost reasoning
- status quo bias
- survivorship bias
- base-rate neglect
- planning fallacy
- framing effect
- motivated reasoning
- premature closure

Do not simply accuse the user of biases.

Phrase findings as hypotheses:

```text
Possible anchoring:

The original 6-month estimate appears to remain the planning baseline
despite three comparable projects taking 9–12 months.

Consider comparing against the historical reference class.
```

---

# 44. AI COUNTERFACTUALS

Provide:

```text
Generate Counterfactuals
```

Examples:

```text
What if the opposite assumption were true?

What if budget were unlimited?

What if budget were cut in half?

What if this had to ship in 30 days?

What if adoption were only 20%?

What if our strongest competitor released this first?
```

---

# 45. AI ALTERNATIVE GENERATION

Users routinely compare too few alternatives.

Command:

```text
Find Missing Alternatives
```

AI should search conceptually across categories such as:

```text
Do nothing
Delay
Build
Buy
Partner
Automate
Simplify
Remove requirement
Partial implementation
Pilot
Outsource
Process change instead of technology
```

---

# 46. AI EVIDENCE CHALLENGE

For each major assertion, optionally ask:

```text
What supports this?

What contradicts this?

What evidence is missing?

How reliable is the source?

Is this fact, inference, or assumption?
```

---

# 47. AI OUTPUT FORMAT

Prefer structured JSON-schema outputs from models whenever practical.

For example:

```python
class AssumptionSuggestion(BaseModel):
    statement: str
    why_it_matters: str
    impact_if_wrong: str
    suggested_test: str
```

Then render it beautifully.

Avoid parsing arbitrary prose when structured output is available.

---

# 48. MODEL SELECTION

Allow:

```text
Automatic
Fast
Balanced
Deep
```

Map these profiles to actual provider capabilities/configuration.

Do not hard-code assumptions about model names throughout the application.

Use provider-discovered models where possible.

Persist provider-independent capability preferences.

---

# 49. STREAMING

AI responses should stream into the TUI.

Show:

```text
AI Partner is analyzing...
```

Then progressively render.

The UI must remain responsive.

AI calls must be asynchronous.

Allow cancellation:

```text
Esc   Stop
```

---

# 50. AI COST / USAGE

Where provider data makes it available, show:

```text
Tokens
Usage
Estimated API cost
```

Do not fabricate cost when unavailable.

For ChatGPT-plan mode, distinguish it from API billing.

---

# 51. PROMPT ARCHITECTURE

Do not scatter huge prompt strings throughout screen classes.

Create central prompt templates.

Use:

```text
SYSTEM ROLE
METHOD INSTRUCTIONS
CURRENT CONTEXT
USER REQUEST
OUTPUT SCHEMA
```

Version prompts.

Example:

```python
prompt_id = "assumption_challenger"
version = "1.0"
```

This supports testing and future improvement.

---

# 52. AI BEHAVIOR PRINCIPLES

Every AI method prompt should reinforce:

1. Do not make up evidence.
2. Separate facts from assumptions.
3. State uncertainty.
4. Generate alternatives before converging.
5. Look for disconfirming evidence.
6. Ask what would change the conclusion.
7. Prefer measurable claims.
8. Distinguish reversible from irreversible decisions.
9. Use base rates when available.
10. Do not silently alter user data.
11. Recommendations must explain why.
12. User approval is required before AI-generated content becomes part of the analysis.

---

# 53. COMMAND PALETTE

Use:

```text
Ctrl+P
```

or:

```text
Ctrl+K
```

for global commands.

Example:

```text
New Analysis
Open Analysis
Switch Method
Ask AI
Challenge Assumptions
Run Premortem
Add Evidence
Add Assumption
Export
Search
Settings
Help
```

Implement fuzzy search if reasonable.

---

# 54. GLOBAL SEARCH

Search across:

- projects
- analyses
- decisions
- assumptions
- evidence
- forecasts

Example:

```text
/ lineage
```

results:

```text
Data Governance Strategy
  Assumption: lineage APIs remain stable

Q4 Feature Ranking
  Item: Automated Data Lineage
```

---

# 55. TUI VISUAL DESIGN

Aim for:

- clean
- dense but readable
- professional
- modern
- restrained

Avoid:

- excessive gradients
- ASCII art
- dozens of colors
- blinking UI
- cluttered borders

Use consistent semantic styling for:

```text
information
warning
risk
success
AI suggestion
user decision
calculated result
```

Support dark terminals well.

---

# 56. KEYBOARD-FIRST

The entire app should be usable without a mouse.

Global:

```text
Ctrl+P     Command palette
Ctrl+K     AI commands
Ctrl+S     Save
Ctrl+O     Open
Ctrl+N     New
/          Search
?          Help
Q          Quit
Esc        Back / Cancel
```

Contextual shortcuts should appear in the footer.

---

# 57. HELP

Each method should contain:

```text
What is this?
When should I use it?
When should I NOT use it?
How does it work?
What are common mistakes?
```

Keep explanations concise.

Provide deeper documentation in README/docs.

---

# 58. DATA STORAGE

Use SQLite.

Suggested tables:

```text
projects
analysis_sessions
method_states
items
assumptions
evidence
decisions
forecasts
ai_interactions
events
settings
```

Use migrations from the beginning.

Do not persist secrets.

---

# 59. EVENT HISTORY

Maintain an append-only event/history layer where useful.

Example:

```text
10:04  Added alternative "Build"
10:07  Changed Security weight 20% → 30%
10:09  AI suggested assumption
10:10  User accepted assumption
10:16  Ranking changed #2 → #1
```

This enables auditability and undo.

---

# 60. UNDO / REDO

Implement robust undo for editable analysis state.

Prefer:

```text
Ctrl+Z
Ctrl+Shift+Z
```

Do not try to undo external AI calls themselves.

Undo accepted changes resulting from AI.

---

# 61. AUTOSAVE

Autosave continuously.

Never require users to manually save routine work.

Manual Ctrl+S may still provide explicit reassurance.

If application crashes, recover current state.

---

# 62. EXPORTS

Support:

- Markdown
- JSON
- CSV where applicable

Eventually support:

- HTML report
- PDF report

Reports should distinguish:

```text
User input
Calculated results
AI-generated suggestions
Accepted AI content
```

---

# 63. DECISION BRIEF EXPORT

Create a particularly useful Markdown export:

```text
# Decision Brief

## Decision

## Objective

## Context

## Alternatives

## Criteria

## Assumptions

## Evidence

## Analysis

## Risks

## Uncertainty

## Decision

## Why

## What Would Change Our Mind?

## Next Actions

## Review Date
```

AI may draft prose from structured data.

The calculations remain authoritative.

---

# 64. PROJECT SNAPSHOT

Allow:

```text
Export Project Snapshot
```

JSON should contain the complete analytical state.

This should allow backup/import onto another machine.

Do not include API keys or OAuth tokens.

---

# 65. SECURITY

Never:

- log credentials
- serialize credentials
- include secrets in tracebacks
- expose authorization headers
- commit `.env`
- export credentials

Use redaction utilities.

---

# 66. CONFIGURATION

Use something such as:

```text
~/.config/thinktui/
```

through platformdirs.

Data:

```text
~/.local/share/thinktui/
```

or OS equivalent.

Logs:

appropriate platform directory.

---

# 67. CLI

Launch:

```bash
thinktui
```

Also support:

```bash
thinktui new
thinktui open
thinktui methods
thinktui journal
thinktui settings
thinktui --version
thinktui --help
```

Useful additions:

```bash
thinktui export PROJECT
thinktui doctor
```

`doctor` should check:

```text
Python
database
configuration
AI provider
Ollama connectivity
ChatGPT authentication
OpenAI API connectivity
terminal capabilities
```

---

# 68. FIRST-RUN EXPERIENCE

First launch:

```text
Welcome to ThinkTUI

ThinkTUI helps structure difficult decisions,
plans, forecasts, and investigations.

AI assistance is optional.

Choose AI setup:

[1] Continue with ChatGPT
[2] OpenAI API key
[3] Ollama / Local AI
[4] No AI
```

Then offer:

```text
Take the 2-minute guided tour?
```

Allow skip.

---

# 69. DEMO WORKSPACE

Include optional demo projects.

Example:

```text
Feature Prioritization
Pairwise + Decision Matrix

Cloud Migration
Premortem + Decision Tree

Production Incident
Issue Tree + ACH

FY27 Strategy
Scenario Planning + Backcasting
```

This makes testing easy.

Do not pollute normal projects automatically.

---

# 70. TESTING

Testing must be serious.

## Unit tests

Test mathematical engines independently.

### Pairwise

- unique pairs
- no duplicates
- no self-pairs
- Bradley-Terry ordering
- cycles
- ties

### Decision Matrix

- weighted totals
- cost criteria
- normalization
- ranking

### AHP

Test known matrices.

Validate:

- priority vector
- consistency index
- consistency ratio

### Expected Value

Test tree calculations.

### Sensitivity

Test known decision-switch thresholds.

### Monte Carlo

Use fixed seed.

Check statistical ranges rather than exact random samples where appropriate.

### Forecasting

Test Brier scores and calibration bins.

### FMEA

Test configured scoring calculations.

---

# 71. AI TESTING

AI functionality must be mockable.

Never require live API calls for unit tests.

Create:

```python
FakeAIProvider
```

Support deterministic fixtures.

Test:

- request construction
- context filtering
- structured outputs
- cancellation
- failure
- timeout
- rate limit
- malformed output
- provider unavailable

---

# 72. TUI TESTING

Use Textual's testing/pilot capabilities.

Test key workflows:

```text
launch
new analysis
select method
enter data
navigate
save
resume
finish
export
```

Test keyboard shortcuts.

---

# 73. AI FAILURE GRACEFULLY

If AI fails:

```text
AI unavailable

Your analysis has been preserved.
You can continue without AI.

[R] Retry
[P] Change provider
[Esc] Continue
```

The application must never become unusable because AI is down.

---

# 74. OBSERVABILITY

Add useful local logging.

Debug mode:

```bash
thinktui --debug
```

Do not log sensitive prompts by default.

Allow optional verbose AI request logging only after explicit user opt-in and with secret redaction.

---

# 75. PERFORMANCE

Startup should feel immediate.

Do not initialize an AI provider until required.

Use async for network work.

Large analyses should not freeze the TUI.

---

# 76. METHOD MATURITY LABELS

Methods can have:

```text
Stable
Beta
Experimental
```

Display this in the library.

Do not imply mathematically incomplete tools are production-ready.

---

# 77. INITIAL RELEASE SCOPE

Do NOT attempt to fully implement all 40 methods at once.

Build the platform correctly, then implement the highest-value modules.

## V0.1

Infrastructure:

- Textual shell
- SQLite
- projects
- sessions
- method architecture
- AI provider architecture
- settings
- exports

Methods:

1. Pairwise Ranking
2. Weighted Decision Matrix
3. Key Assumptions Check
4. Premortem
5. Issue Tree

AI:

- ChatGPT account
- OpenAI API
- Ollama
- AI panel
- Challenger
- Facilitator

## V0.2

6. Analysis of Competing Hypotheses
7. Decision Tree
8. Expected Value
9. Sensitivity Analysis
10. Decision Journal

## V0.3

11. Forecasting Journal
12. Brier/Calibration
13. Reference-Class Forecasting
14. Monte Carlo

## V0.4

15. Scenario Planning
16. Backcasting
17. Objectives Hierarchy
18. Value-Focused Thinking
19. FMEA
20. Theory of Constraints

---

# 78. DEVELOPMENT APPROACH

Build vertically.

Do not create 60 empty Python files and call that progress.

Recommended order:

### Phase 1

Create:

- package
- Textual shell
- navigation
- configuration
- database
- migrations
- project model

Run it.

### Phase 2

Implement one method completely:

```text
Pairwise Ranking
```

Including:

- UI
- storage
- calculations
- resume
- export
- tests

This proves the method architecture.

### Phase 3

Implement AI abstraction.

Start with:

```text
Ollama
OpenAI API
ChatGPT account
```

as supported by official/current interfaces.

Create FakeAIProvider tests.

### Phase 4

Add AI to Pairwise.

Verify the abstraction works.

### Phase 5

Implement:

```text
Key Assumptions Check
Premortem
Decision Matrix
Issue Tree
```

### Phase 6

Implement cross-method project functionality.

### Phase 7

Implement Decision Journal.

### Phase 8

Polish UI, documentation, exports, recovery and packaging.

---

# 79. IMPORTANT: CURRENT API DOCUMENTATION

AI provider integrations are external APIs and may change.

Before implementing:

- inspect the current official OpenAI documentation
- inspect the current Sign in with ChatGPT open-source documentation
- inspect the current Responses API documentation
- inspect current Codex app-server documentation if using that path
- inspect current Ollama API documentation

Do not rely on stale examples embedded in this specification when official interfaces differ.

Prefer current documented APIs.

---

# 80. CHATGPT AUTHENTICATION REQUIREMENT

For the ChatGPT provider:

Use official Sign in with ChatGPT support for open-source apps where available.

The target UX is:

```text
Continue with ChatGPT
```

Then browser/OAuth authentication.

Store tokens securely using recommended mechanisms.

Support refresh and expiration.

Provide:

```text
Sign Out
```

Do not ask the user to manually find OAuth tokens.

Do not scrape authentication from Codex CLI.

Do not inspect private credential files belonging to other apps.

---

# 81. API KEY EXPERIENCE

When API provider selected:

```text
OpenAI API

API key:
[stored securely]

Model:
[select]

Connection:
✓ Connected

[Test Connection]
```

Allow environment-only mode.

If `OPENAI_API_KEY` already exists, detect it but do not display it.

Show:

```text
OPENAI_API_KEY detected
```

not the key itself.

---

# 82. OLLAMA EXPERIENCE

Example:

```text
Local AI

Server
http://localhost:11434

Status
✓ Connected

Models

● qwen...
○ llama...
○ devstral...
```

Allow refresh.

The application should work particularly well with coding/reasoning-capable local models.

---

# 83. PROVIDER SWITCHING

The user may change provider mid-project.

This must not affect analytical data.

Example:

```text
ChatGPT
   ↓
Ollama
```

AI interaction history should record:

```text
provider
model
timestamp
prompt version
```

Do not require a project migration.

---

# 84. AI MEMORY INSIDE PROJECTS

AI should understand the current project by reading structured project context.

Do not create a hidden opaque memory system initially.

Project state itself is the memory.

Optional AI session messages may be persisted separately.

User should be able to clear AI conversation history without deleting the actual analytical project.

---

# 85. “PLANNING PARTNER” MODE

This should become one of ThinkTUI's signature experiences.

From home:

```text
AI Planning Partner
```

The user can enter:

```text
"We need to decide whether to build our own metadata
quality system or buy a vendor product."
```

AI should NOT simply answer.

Instead it should say, structurally:

```text
I recommend a decision workflow:

1. Clarify objective
2. Identify constraints
3. Generate alternatives
4. Build decision criteria
5. Run weighted decision matrix
6. Test key assumptions
7. Run sensitivity analysis
8. Perform premortem

Start?
```

Then create linked analyses.

This is the key difference between ThinkTUI and a generic chatbot.

The AI knows the library of thinking tools and orchestrates them.

---

# 86. METHOD ORCHESTRATOR

Implement a service that can recommend sequences of methods.

Example:

```python
PlanningWorkflow(
    goal="select architecture",
    steps=[
        ObjectivesHierarchy,
        DecisionMatrix,
        SensitivityAnalysis,
        Premortem,
    ],
)
```

Initially use rule-based recommendations.

AI can enhance recommendations.

Do not make workflow orchestration entirely dependent on LLM output.

---

# 87. “THINK DEEPER” ACTION

Add a universal:

```text
Think Deeper
```

AI should respond with:

```text
Missing assumptions
Missing alternatives
Contradictory evidence
Important uncertainty
Potential second-order effects
Questions worth answering
Recommended analytical tool
```

This should not merely produce a longer generic answer.

---

# 88. “WHAT AM I MISSING?” ACTION

Global command:

```text
What am I missing?
```

AI performs a structured gap analysis against the current method.

---

# 89. “ARGUE THE OTHER SIDE”

Command:

```text
Argue the Other Side
```

AI should produce the strongest good-faith counterargument to the current favorite option.

Use steelmanning.

---

# 90. “MAKE THIS MEASURABLE”

Command:

```text
Make This Measurable
```

Given:

```text
Improve developer experience
```

AI proposes operationalizations such as:

```text
Median onboarding time
Deployment lead time
Support requests per developer
Self-service completion rate
Developer satisfaction
```

User selects which to accept.

---

# 91. “DECOMPOSE THIS”

Command:

```text
Decompose
```

AI can create:

- issue tree
- hypothesis tree
- work breakdown
- causal factors

Ask the user which structure is appropriate when ambiguity matters.

---

# 92. “RUN A PREMORTEM” ANYWHERE

Premortem should be callable from any project.

Results can either:

```text
Create separate Premortem Analysis
```

or:

```text
Attach risks to current analysis
```

---

# 93. “CREATE DECISION BRIEF”

One keypress generates a professional decision record.

It should use:

- structured analysis
- calculations
- user decisions
- accepted AI suggestions

AI may improve readability.

Never let AI alter numeric results.

---

# 94. UX PRINCIPLE: CALCULATE FIRST, EXPLAIN SECOND

Whenever deterministic mathematics exist:

```text
Python calculation
      ↓
structured results
      ↓
AI interpretation
```

Never:

```text
Ask AI to calculate everything
```

This principle must hold throughout the application.

---

# 95. UX PRINCIPLE: DIVERGE THEN CONVERGE

Many workflows should explicitly separate:

```text
DIVERGE
Generate possibilities

CONVERGE
Evaluate possibilities
```

This prevents premature commitment.

AI is particularly valuable during divergence.

---

# 96. UX PRINCIPLE: ASSUMPTIONS ARE FIRST-CLASS

Assumptions should not live buried inside notes.

They must be objects that can be:

- viewed
- tested
- linked to evidence
- scored
- invalidated
- reused

---

# 97. UX PRINCIPLE: UNCERTAINTY IS FIRST-CLASS

Avoid forcing false precision.

Support:

```text
60–80%
```

or distributions where appropriate.

Encourage:

```text
confidence
ranges
base rates
sensitivity
```

---

# 98. UX PRINCIPLE: TRACEABILITY

At the end of an analysis, a user should be able to answer:

```text
Why is this ranked #1?

Why did we choose this?

What assumptions matter most?

What evidence supports the decision?

What could reverse it?

What risks did we identify?

Who made which judgment?

When did the judgment change?
```

---

# 99. DOCUMENTATION

README should include:

- philosophy
- screenshots
- installation
- uv setup
- first-run setup
- AI setup
- ChatGPT login
- API key configuration
- Ollama configuration
- privacy model
- keyboard shortcuts
- method catalog
- example workflows
- architecture
- adding a new method
- testing
- contribution guide

Also add:

```text
docs/methods/
```

with one Markdown document per method.

---

# 100. AGENTS.md

Create an AGENTS.md for future Codex work.

Include:

- architecture rules
- testing expectations
- directory responsibilities
- dependency rules
- formatting commands
- how new methods are added
- AI-provider rules
- security requirements

This repository will likely continue being developed with coding agents.

Make it agent-friendly.

---

# 101. QUALITY COMMANDS

At completion run:

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```

If mypy is configured:

```bash
uv run mypy src
```

Run the TUI manually as well.

Do not report success without launching the application.

---

# 102. ACCEPTANCE CRITERIA FOR INITIAL BUILD

The first usable milestone must allow me to:

1. Launch ThinkTUI.
2. Create a project.
3. Choose Pairwise Ranking.
4. Enter features.
5. Complete comparisons.
6. Receive Bradley-Terry results.
7. Save/resume the project.
8. Export the result.
9. Configure AI OFF.
10. Configure Ollama.
11. Configure OpenAI API.
12. Configure ChatGPT sign-in if current official integration permits it.
13. Ask AI to challenge the ranking.
14. Start a Key Assumptions Check.
15. Accept/edit/reject AI-generated assumptions.
16. Run a Premortem.
17. Export a Decision Brief.
18. Quit and reopen without losing anything.

If ChatGPT sign-in requires external registration/setup that cannot be fully automated, implement the clean provider interface and documentation, complete every locally implementable part, and clearly state the remaining registration step.

Do not block the entire application on this integration.

---

# 103. WHAT NOT TO DO

Do not:

- build a generic chatbot with some buttons around it
- make AI mandatory
- depend on AI for mathematical calculations
- hide reasoning inputs
- overwrite user judgments
- generate fake data
- create fake confidence statistics
- overengineer microservices
- use a web server unless an OAuth callback specifically requires a local callback endpoint
- put everything in app.py
- create dozens of empty TODO modules
- stop after scaffolding
- expose secrets
- rely on undocumented authentication
- create excessive modal dialogs
- require the mouse

---

# 104. PRODUCT IDENTITY

ThinkTUI should feel like:

```text
A terminal-based analytical workbench
+
a structured decision-science toolkit
+
a decision journal
+
an AI planning partner
```

It should NOT feel like:

```text
ChatGPT inside a terminal.
```

The methods are the product.

AI makes the methods substantially more powerful.

---

# 105. LONG-TERM VISION

Eventually ThinkTUI should let a user start with:

```text
"We're deciding whether to replace our internal
data lineage platform."
```

and progressively create:

```text
Problem Frame
   ↓
Objectives
   ↓
Alternatives
   ↓
Assumptions
   ↓
Evidence
   ↓
Decision Matrix
   ↓
Pairwise Validation
   ↓
Sensitivity Analysis
   ↓
Scenario Stress Test
   ↓
Premortem
   ↓
Decision
   ↓
Forecast
   ↓
Review Date
   ↓
Actual Outcome
   ↓
Lessons Learned
```

At every point AI helps the user think better.

At no point does the AI silently become the decision maker.

---

# 106. IMPLEMENTATION INSTRUCTIONS TO CODEX

Do not just return an architecture document.

Actually build the repository.

Begin by inspecting the current directory.

If no application exists:

1. initialize the Python project
2. establish package architecture
3. add Textual shell
4. add SQLite persistence
5. implement project/session model
6. implement method registry
7. fully implement Pairwise Ranking
8. test Pairwise mathematics
9. add AI provider abstraction
10. implement Fake/Ollama/OpenAI provider paths
11. investigate and implement the current official ChatGPT open-source sign-in flow where feasible
12. add AI panel
13. implement Key Assumptions Check
14. implement Premortem
15. implement Weighted Decision Matrix
16. implement Issue Tree
17. add project history
18. add exports
19. add Decision Brief
20. polish keyboard workflow
21. test
22. run application
23. fix runtime issues
24. update README
25. create AGENTS.md

Make sensible engineering decisions without repeatedly asking me for approval.

If a feature depends on external credentials or registration, implement everything else and document the exact remaining setup.

Do not stop after producing skeleton code.

Prioritize a working vertical slice over broad unfinished scaffolding.

When finished, report:

```text
ThinkTUI Build Summary

Implemented
- ...

Core methods
- ...

AI providers
- ...

Architecture
- ...

Database
- ...

Tests
- X passed

Remaining
- ...

Run
uv sync
uv run thinktui
```

Also include the most useful next 5 implementation tasks in priority order.
