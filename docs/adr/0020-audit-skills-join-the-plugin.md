# ADR-0020: The audit skills join the plugin, with one survey agent and their scripts in the CLI

Status: Proposed · Date: 2026-10-10 · Owner: VK · Revisit-by: 2027-01-10

Decision: the three user-level audit skills become plugin pipeline skills `architecture`, `research` and `tests`. Their read-only fact lookups go to `anomaly:facts` on the `explore` model role; every research and tests dispatch goes to one new agent, `anomaly:survey`, on its own model role `survey` (core default sonnet). The two research scripts become the CLI commands `pkg-facts` and `terms-grep`.
Why: inside the plugin the skills get its text checks, model roles and worklog lines; ADR-0018 asks one agent and one model role per kind of dispatch, and ADR-0007 asks one CLI.
Revisit: when `anomaly:survey` dispatches show two clearly different costs or failure kinds per skill, or 2027-01-10.

## Context

The architecture audit, the evidence research and the test audit were user-level skills. They named `sonnet` and the built-in Explore agent in their text, ran two standard-library Python scripts by a path next to the skill, and handed off to `/anomaly:interview` and `/anomaly:diagnose`. Their dispatches had no agent name, so `measure` could not tell their cost apart (ADR-0018, Context). The scripts' tests were outside the repo's verify command. The `explore` model role belongs to `anomaly:facts` only (ADR-0018, Decision).

## Decision

- The skills move to `plugins/anomaly/skills/{architecture,research,tests}/` as pipeline skills: `allowed-tools` is only the CLI pattern, and each records its run with `worklog start` and `worklog add` (stages `architecture`, `research`, `tests`). The `.anomaly/` folder names stay `architecture-<date>`, `test-audit-<date>` and `<unit>/research/`.
- The architecture skill's bulk reads and ADR-drift check dispatch `anomaly:facts` on `explore`. Research topic and synthesis agents and the tests skill's value, runtime and cover-check agents dispatch `anomaly:survey` on `survey`. The survey agent has Read, Grep, Glob, Bash, Write, WebSearch and WebFetch, and no `model` key.
- `pkg-facts` and `terms-grep` become CLI modules in `anomaly_loop/`, tested by the suite with recorded fixtures; the neutrality check allows the two registry API hosts the code calls. The repo layer adds both module names to `risk_patterns`, so the security reviewer joins every change to them.
- The skills keep their rules; this is a move with edits, not a rewrite, so no switch-over experiment runs. ADR-0008 says each new pipeline skill replaces its old skill through one switch-over experiment; this ADR reads that rule as applying to rewrites only, because a moved skill keeps the old skill's rules and has no second version to compare with.
- TODO(VK, revisit 2026-10-17): `anomaly:survey` holds Bash, Write and the web tools together, so a research topic agent that reads a hostile page is a prompt-injection path; deferred.
- TODO(VK, revisit 2026-10-17): terms-grep accepts file: URLs, which read any local file, and follows redirects, which can reach loopback or internal hosts; deferred.

## Why

One agent for both web research and test probes keeps one metrics key with enough dispatches for a verdict; these skills run rarely, and per-skill agents would leave each key nearly empty (ADR-0018, Why). The scripts as CLI commands are pre-approved by the one CLI pattern, run under the verify command and give the research skill the CLI call every pipeline skill has.

## Alternatives rejected

- All dispatches on `explore` with a general-purpose agent: the role belongs to `anomaly:facts`, and an unnamed agent is no metrics key (ADR-0018).
- Two new agents, one for web topics and one for test probes: halves the few dispatches per key.
- The scripts as standalone files beside the skill: a second Python entry point, not pre-approved, and not found by test discovery.
- A separate class of pipeline skills without CLI calls: a new class in the tests and the glossary for no gain over a worklog call.

## Accepted risks

- [ ] The survey agent's tool set is broad: a tests brief could fetch pages, and a research brief could run commands. Owner: VK · Revisit: 2027-01-10.
- [ ] The rewritten fixture hosts no longer match the real API answers byte for byte; only the live test (`LIVE=1`) sees the real hosts. Owner: VK · Revisit: 2027-01-10.
