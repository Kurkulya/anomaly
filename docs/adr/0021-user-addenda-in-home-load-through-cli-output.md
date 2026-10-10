# ADR-0021: User addenda live in home and load through CLI output

Status: Proposed; partly supersedes ADR-0010 (the CLI reads the settings files at run time for the write-time deny check) · Date: 2026-10-11 · Owner: VK · Revisit-by: 2027-01-11

Decision: a user with an installed copy tunes a plugin skill or agent with an addenda file in home (`<home>/addenda/<skill>.md`, `<home>/addenda/agents/<agent>.md`): plain markdown, at most 5 lines, each line one declared experiment. A call the skill already makes prints the addenda: `worklog start`, `assess check`, `observe list`, and `digest` for calibrate. Each line carries a stamp, a short sha256 of its target skill folder or agent file, and the calibrate digest lists a line whose target changed for a re-check; `calibrate drop` removes it. `measure` takes no addenda.
Why: an installed copy has no checkout to change, and new calls or SKILL.md lines cost every user context, with no budget left (`build` SKILL.md is 9,216 B of its 9 KB cap, `plugins/anomaly/tests/test_cli.py:42`). Plain markdown read through the CLI keeps the layer open for other agents.
Revisit: when the plugin is ported to a second agent, when a user hits the 5-line cap on one file, or 2027-01-11.

## Context

The calibrate loop fixes a problem by editing its target and recording the change as an experiment (ADR-0002). A target inside the plugin needs a checkout, which `plugin_repo` finds, and the `--approved` gate. A user who installed the plugin from a marketplace has neither, so a problem found in a plugin skill stays open. All data stays in home (ADR-0001), and the profile already lets each user choose tools through ports (ADR-0007). Nothing yet lets a user change how a skill behaves. The CLI builds no part of any agent brief: skills write the briefs.

## Decision

- Routing: with no checkout, `calibrate plan` sends a target `anomaly:<skill>`, `anomaly:<agent>`, or a path inside one skill folder or agent file to its addenda file. A target in plugin code or docs becomes a defect report (ADR-0022). With a checkout, nothing changes.
- Writing: `calibrate fix --addendum '<line>'` appends the line with `[exp: <signature> · <stamp>]` and refuses it without a declared experiment, over the cap, on a failed `check_text`, or when it fully matches a live deny rule. A revert result removes exactly that line; `calibrate drop` removes a line whose experiment has a result. `declare` keeps its `--approved` gate.
- Loading: the call prints the skill's addendum last, then the addendum of each agent the skill dispatches, with a line asking the skill to add it to that agent's brief. A header says the lines add or narrow, and that the core rules and invariants win on a clash. With no file, the output is unchanged.
- Stamp: 8 hex characters of sha256 over the target's files, on each line, so only a changed skill asks for a re-check and an append never hides an older line. A missing target is listed too.
- Removal: `calibrate drop <signature>` removes a line whose experiment has a result and keeps that result; re-check, a full file and an upstreamed line use it.
- The deny-shape matcher and the org-marker list move from the tests into the CLI, and the tests import them back.
- **Partly supersedes ADR-0010**, its rejected alternative "a CLI subcommand that reads the settings at run time": the CLI now reads the settings files at run time for the write-time deny check of an addendum line. It reads them and never writes them; only `anomaly_loop/scans.py` names them, and the settings guard in the tests exempts that one file by path. The rest of ADR-0010 stands.

## Why

The first call already runs and already prints, so the addendum costs nothing for a user without one. A line cap matches "one line, one experiment" better than a byte cap: skill and agent sizes range from 1,378 B to 12,868 B. A hash of the target is agent-neutral and marks only the skills that changed. A version field would need a manual bump, and a commit id marks every line after every update. One stamp per file would be rewritten by each append and hide older lines.

## Alternatives rejected

- Each agent reads its own addenda file: one new line in each of 8 agent files.
- Skills only, with agent addenda deferred: the reviewer briefs are where most tuning lands.
- A byte or percentage cap: it fits small and large skills badly.
- The installed commit as the stamp: every update marks every line for a re-check.
- A fixed phrase list against weakening lines: easy to word around.

## Accepted risks

- [ ] The model must copy agent lines into each brief, and no test proves it does so each time. Owner: VK · Revisit: 2027-01-11.
- [ ] A plain-words line such as "skip the security review" passes both scans, and only the header precedence holds it. Owner: VK · Revisit: 2027-01-11.
- [ ] Skills pass an unfilled home value, so addenda in a custom home load only through `CLAUDE_PLUGIN_OPTION_HOME` (ADR-0001). Owner: VK · Revisit: 2027-01-11.
