# ADR-0013: A switch-over compares old-skill sessions with new-skill sessions

Status: Accepted; not yet used: the first rewrite ran no switch-over (ADR-0008, Consequences) · Date: 2026-10-07 · Owner: VK · Revisit-by: 2026-11-25

## Context

ADR-0008 judges a rewritten skill by one switch-over experiment: "the old skill's last 28 days
against the new skill's sessions", five clean sessions, security tokens left out. The verdict
could not do that. It split sessions by date only (`trends.fix_windows`), and a session's kind
comes from `build_skills`. With the new name added beside the old ones, the after window mixes in
old-skill sessions, because the old skill keeps running. With the old names removed, the baseline
is empty. No metric left the security reviewer's tokens out. ADR-0009 later set the session check
at 20.

## Decision

- **`calibrate declare --kind build --skill <new skill>`** records `skill` in the experiment
  (written only when set). The profile's `build_skills` names the new skill beside the old one, and
  both stay until the old skill is deleted.
- **The skill splits, not the date.** Before: every build session that did not run the new skill,
  from 28 days before the fix day to today, so old-skill sessions beside the new one count. After:
  build sessions since the fix that ran the new skill and nothing else a `build_skills` name
  matches. The fix day, a new-skill session before it (a dogfood run) and a **fall-back** (the new
  skill beside another build skill) are in neither side; `verify` counts fall-backs. A sighting
  counts only for a session on its side; one of no measured session, or of the fix day, is on
  neither. One owner: `trends.fix_windows` with `skill_side`, through `metrics.skills_used_each`.
- **The fix day.** The switch-over's `calibrate fix` is recorded with `--date` the day after the
  last dogfood session and `--ref` the merge into `main`, before the first real-ticket session.
  So dogfood runs, deliberate negative runs included, are in neither side.
- **Due after 20 new-skill sessions** (`EXPERIMENT_CHECK_SESSIONS`) and only then: the check date
  alone never makes a switch-over due, and old-skill sessions do not count.
- **`weighted tokens without security`**: a new registered metric, a session's weighted tokens less
  the `anomaly:security` entry of `tokens_by_agent` (VK 2026-10-07). It is the switch-over metric,
  per build session (G24). Existing metrics keep their meaning.
- **Supersedes in ADR-0008** the selection line ("the old skill's last 28 days against the new
  skill's sessions"), the metric line (tokens per merged ticket) and the "five sessions". ADR-0008's
  text stays; its status line names this ADR.

## Why

Old and new skills run in the same weeks, so a skill split compares like with like and a date
split cannot. A new metric, not a changed `weighted tokens`, keeps every running experiment's
meaning.

## Alternatives rejected

- Replace the old names in `build_skills`: an empty baseline.
- Leave security in `weighted tokens`: changes existing experiments.
- Count fall-backs as new-skill sessions: they are not end-to-end runs (ADR-0008).

## Accepted risks

- [ ] No CLI step records the old skill's deletion as a `calibrate fix`, as ADR-0008 says. After
  `keep` the anomaly is `fixed`, so `declare` refuses it (the anomaly is not active), and `fix`
  refuses it (no open experiment, and the fix is already recorded). The AC-78 wording goes to the
  to-spec pass: a closing note that cites the verify result, or a new CLI step. Owner: VK ·
  Revisit: 2026-10-25.
- [ ] A switch-over that stalls below 20 new-skill sessions is never due; the progress line
  (`n/20 <skill> sessions, m fall-backs`, listed as stalled once its check date has passed) shows
  it, and VK closes it by hand. Owner: VK · Revisit: 2026-11-25.
- [ ] The `anomaly:security` key is inferred from other plugin agents' keys; no live row has it
  yet. Owner: VK · Revisit: 2026-10-25 (first live review).
- [ ] The global CLAUDE.md (18.4 KB to about 8 KB) and three memory indexes shrink during the
  first 20 `anomaly:build` sessions. They load into every turn, so new-skill sessions get cheaper
  for a reason that is not the skill, and the verdict credits that saving to `anomaly:build`.
  Before reading the verdict, compare the old-skill sessions after the shrink with those before
  it, and take that difference off. Owner: VK · Revisit: 2026-11-25.

## Revisit

When the first switch-over reaches a result.

## Sources

`workflow-build` ticket 12 (AC-78, AC-100); `.scratch/workflow-loop/briefs/calibrate.md` change 5;
decisions G24, G33; red tests `e3ccaae`; code `1d2f4f1`; ADR-0008, ADR-0009.
