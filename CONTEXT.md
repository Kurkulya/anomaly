# anomaly — glossary

| Term | Meaning | Avoid |
|---|---|---|
| **anomaly** | One backlog record: a deviation from what was expected. Either a **problem** (friction, waste, a wrong turn) or a **win** (a step that demonstrably caught or saved something). | finding (for an anomaly; a reviewer's output line is a **finding line**), issue, ticket |
| **sighting** | One session in which an anomaly happened. | occurrence (that is the count) |
| **occurrences** | The number of sightings of an anomaly. | |
| **target** | The skill, agent, hook, rule or process an anomaly is about. | |
| **score** | `impact × occurrences`. Computed, never stored. | priority |
| **experiment** | A fix with an expected effect, a metric and a check date. | |
| **guard metric** | The quality signal an experiment must not make worse, declared before the change together with the primary metric. | |
| **chance alone** | The share of random splits of the pooled sessions, from before and after a fix, that change at least as much as the real change. Printed as "N% of random splits change this much". | p-value, significance, "the chance the fix worked" |
| **real change** | A change where chance alone is at or below its level, the change is at least the minimum change, and each side has enough sessions (the numbers are in ADR-0009). A guard is tested one way, for a rise only, so `→ real change` on a guard line means the guard got worse. | significant |
| **within noise** | A change that is not a real change, including a change below the minimum change whatever chance alone says. | not significant |
| **unproven** | The result of an experiment on a rare-event metric: the anomaly did not come back after the fix, which chance alone would also explain. Kept, not proven; the anomaly is not reopened. | keep (that is a proven result) |
| **rare-event metric** | `sightings since the fix` used as the primary metric. It is judged by whether the anomaly came back, not by a count test. | |
| **idea** | An assessed proposal from outside (a link, a text, an opinion) with a verdict: adopt, trial, park or reject. Not an anomaly. | suggestion |
| **lens** | One reviewer, one review axis, or the interview's recommendations, whose findings or answers are counted as accepted, rejected or revised: the accepted ones whose fix or answer differed from the one proposed (at most the accepted count). | |
| **needs-rework** | Computed flag on a target that changes or fails too often: redesign it, don't patch it. | |
| **profile** | The environment mapping (tracker, glossary file, agents, MR tool) kept outside the plugin. | config |
| **home** | The folder that holds all durable loop data. | data dir |
| **session kind** | `build`, `research`, `config`, `debug` or `unknown`. | session type |
| **measure / observe / calibrate** | The loop: extract numbers / capture wins and problems / review, fix as experiments, verify. | retro (only as a trigger word) |
| **assess** | Judge a link, text or opinion against the backlog and the metrics, and keep the verdict as an idea. | review (that is calibrate) |
| **nudge** | The one line a new session prints at most once per ISO week when an open problem has score 4 or more or an experiment is due. | reminder |
| **stage** | One step of the feature pipeline, named by its skill: `interview`, `specify`, `slice`, `build`, `conduct`, `review`, `ship` (plus `diagnose` for bugs, and the audit stages `architecture`, `research`, `tests`). | phase (that is a delivery part of the rewrite) |
| **loop skill** | One of the four skills of the feedback loop: `measure`, `observe`, `calibrate`, `assess` (`LOOP_SKILLS` in `anomaly_loop/constants.py`). The pipeline's size and permission checks leave them out. | |
| **pipeline skill** | Any plugin skill that is not a loop skill: the skill of one stage (`build`, `review` and the later ones). Its `SKILL.md`, extra docs and agent files get the static checks: size budgets, the one CLI pattern in `allowed-tools`, no command shape a deny rule matches. | workflow skill |
| **work unit** | One piece of work that goes through the pipeline: a feature, kept in the folder `.anomaly/<work-unit>/` (ADR-0011), or one light-path (ad-hoc) ticket in `.anomaly/adhoc/`. Its tickets are in `tickets/`. `worklog add` records each stage run on it in `<home>/work-units.jsonl`. | job, task, issues (for tickets) |
| **work-unit key** | The work-unit folder name under `.anomaly/`, or the ad-hoc ticket's file name without `.md` for light-path work; every pipeline stage appends one line, with its times when known, so the cost of one piece of work can be read per stage. The JSON field is `feature`. | ticket id |
| **stories** | A work unit's `stories.md`: what the work is for, as user stories with acceptance criteria. | spec |
| **decisions** | A work unit's `decisions.md`: the choices made while shaping it, one per entry. | spec |
| **log** | A work unit's `log.md`: events only, for people and agents, with no cost numbers. Written only by `anomaly log add`. | journal, digest |
| **risk area** | A kind of change that makes the security review join a ticket's review: auth; input parsing and execution; secrets or config; dependencies; network calls (core globs in `constants.RISK_AREAS`), plus the extra `risk_patterns` of the repo layer. `risk <range>` names the matched areas and files. | security zone |
| **port** | A named extension point of the pipeline with one fixed mode (add, extend or replace) and a core default that works with an empty profile. | hook (that is a Claude Code feature) |
| **adapter** | The org value or tool the profile injects into a port, such as an org implementer agent or MR tool. | plugin, integration |
| **core default** | What a port does when the profile names no adapter, written in the plugin's own words. | fallback |
| **model role** | A kind of dispatch that the `models` key maps to one model, and optionally an effort. | role (alone), agent model |
| **base branch** | The branch a work unit's integration branch is cut from: the repo layer's `base` key, else the branch `origin/HEAD` points at, else `main`. `ports` prints it as `repo base`. | a ticket's `Base:` line (that holds the **integration branch**) |
| **ticket key** | The key line of a ticket: `Key: <KEY>` in core, or the line the `key_line` port names. It holds a tracker key or `no-ticket`. The `commit` and `branch` ports use it where their pattern holds `<key>`. Not the work-unit key. | ticket id, ticket number (that is the two-digit NN) |
| **integration branch** | The one branch per work unit that each ticket branch merges into with `--no-ff`: the ticket's `Base:` line, else the `branch` port pattern with the work-unit key as slug. `build` never commits on it directly and never pushes it. | feature branch (that is a ticket's) |
| **start branch** | The branch a light-path run starts from (the current head's branch) and merges back into. It stands in for the integration branch, which a light-path run does not create. | integration branch (that is a work unit's) |
| **repo layer** | The commands a repository documents itself (scripts, build files, its own instructions), plus a personal override file in home; never committed to the repo. | repo config |
| **invariant** | A pipeline rule no adapter can remove. **Enforced** when the CLI checks it from ticket files and git; **briefed** when it can only be asked for in an agent's brief. | guarantee |
| **switch-over** | The experiment that replaces an old skill with its rewrite. It is due after `EXPERIMENT_CHECK_SESSIONS` sessions of its kind in which the new skill ran end to end with no fall-back (ADR-0013), with the guard not worse; then the old skill is deleted. | migration, cutover |
| **fall-back** | A switch-over session that ran the new skill beside another build skill: it is in neither side of the comparison and is counted apart. | mixed session |
| **rule ledger** | Per skill, every rule of the old text with its evidence and a verdict (keep, merge, drop, pending verdict); the input to a rewrite brief. | |
| **finding line** | One line of a reviewer agent's output in the shape `- [<severity>] <path>:<line> — <problem> — fix: <fix> — <observed\|unverified>`, severity from `FINDING_SEVERITIES` (in `anomaly_loop/constants.py`). `bench score` reads these; anything else in the output is prose. | anomaly |
| **planted defect** | A fault put on purpose into a seeded-defect fixture (`tests/bench/<agent>/`), listed in its `defects.json` with a place or a rule id and a minimum severity. A reviewer **finds** it with a finding of at least `BENCH_FOUND_FLOOR` in its place (plus or minus `BENCH_WINDOW` lines) or quoting its rule id. | seeded bug |
| **decoy** | Correct code in a fixture that looks wrong. A High on a decoy counts as a false High. | false positive (that is the result) |
| **false High** | A Blocker or High finding that matches no planted defect; one that matches a decoy is named. | |
| **seam ledger** | A work unit's `seams.md` (`.anomaly/<work-unit>/seams.md`): one line per seam, `- <name> · <owner file> · replaces <old way> (ticket NN)`, naming the single owner of a rule, helper or constant; a second copy of an owned seam is a review High. Kept true after each merge by `seams prune` and `seams add`. | owner list, registry |
| **term line** | A `T-n:` line in `decisions.md`: one settled term, its meaning and the words to avoid, waiting for the ticket that writes it into the glossary. | glossary entry (for the line) |
| **red commit** | The commit that holds a ticket's acceptance test alone, before any code commit; recorded as `Red: <sha> · <test path>`. `check pre-merge` requires the test file to be unchanged since it, unless a `Red-changed:` line says why. | test commit |
| **plan gate** | The `spec` or `tickets` review mode that ends `specify` or `slice`; it stops only on a Blocker. | plan-sanity, claim check (for the whole gate) |
| **frontier** | The tickets of a work unit whose blockers are all done, that are neither done nor in progress, and that wait for no person; only a `ready-for-agent` ticket counts. | queue, backlog (that is the anomaly list) |
| **wave** | One round of frontier tickets run together, one after another or in parallel. | batch, round (that is a review round) |
| **wave report** | The 5-line chat summary `conduct` prints after a wave: done, failed, open, next, cost. | digest (that is the backlog digest command and an Avoid word for **log**) |
| **MR** | The one merge request of a work unit (a pull request on GitHub), opened as a draft and made ready through `ship`. | PR (in plugin text) |
| **stack profile** | One file per stack (language and test runner) in a skill's `reference/stacks/` that gives the commands and greps the skill runs on that stack; a stack with no file gets a drafted one. | profile (alone; that is the environment mapping) |
| **lock** | A guard that stops an architecture finding from coming back: an import or lint rule at error level, or a failing test. | guard rail |
| **cover** | The kept test that a test cut relies on: it must fail on each break of the cut test's behaviour. | replacement |
| **break** | One deliberate code change, written by hand, that a cut's cover must fail on; one run against one break is a **break probe**. | mutant (unless the repo's mutation tool made it), probe (alone; the README uses "mutation probe" and "probe edit") |
