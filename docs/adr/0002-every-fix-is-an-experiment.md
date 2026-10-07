# ADR-0002: Every fix is an experiment: declared first, one metric, one quality guard, dated fix

Status: Accepted; partly superseded by ADR-0009 (its gate of 15% with 5 sessions and the median for every metric, and its due-by-5-sessions rule) · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-12-01

## Context

"It helped" was not checkable. Picking whichever number moved after a change fools the owner,
and tuning for cost alone makes quality worse.

## Decision

- `calibrate declare` writes the experiment before the change: the expected effect, exactly
  one primary metric, exactly one guard from `QUALITY_GUARDS` (`rework sightings`,
  `late-catch sightings`, `interrupts`), an optional session kind, and `declared_on`.
- `calibrate fix` writes `fixed_by` as `YYYY-MM-DD · <ref>`; `check_by` defaults to the fix
  day + 21 days. A fix may not be dated before `declared_on`.
- An experiment is due when the fix has landed, there is no result yet, and the check date has
  passed or 5 sessions of its kind have run since the fix. One owner: `trends.experiment_due`.
- The verdict compares the 28 days before the fix with the days since. The fix day is in neither
  window. A metric has moved only with a change of at least 15% and 5 sessions on each side.
- A sighting guard counts as worse only with 5 or more sessions on both sides and at least 2
  sightings since the fix. A baseline that the backlog does not cover is unknown, so the result
  is inconclusive.
- Order when goals conflict: the quality guard, then active time, then weighted tokens. An
  `inconclusive` result moves the check date out once; after that the user decides.

## Why

Declaring the metric and the guard first removes the choice after the fact. A date is the
finest grain a transcript row gives, so a session on the fix day cannot be placed before or
after the change. One sighting is noise, so it must not revert a fix.

## Alternatives rejected

- Choosing the metric after the change: picks whichever number moved.
- Reverting on one guard sighting: noise.
- Counting the fix day in the "after" window: cannot tell before from after.
- Dollar cost: on a seat plan, cost is usage-limit pressure plus time.

## Accepted risks

- [ ] The weighted-token weights (input 1, cache write 1.25, cache read 0.1, output 5) are
  list-price ratios that are not re-checked (`plugins/anomaly/anomaly_loop/metrics.py`).
  Owner: VK · revisit 2026-12-01.
- [ ] Sighting-metric verdicts read "unknown" until 2026-10-20, because the backlog starts on
  2026-09-22. Owner: VK · revisit 2026-10-20.
- [ ] Small samples: medians over fewer than 5 sessions are shown, not acted on.
  Owner: VK · revisit 2026-12-01.

## Revisit

After the first three experiments reach `keep`, `revert` or `inconclusive`: are the guards and
the 15% gate sensible?

## Sources

Commits cd08c1f, e0bbb0c, 990aa71, 0ce07cc, b94daa6, c2edf78, bff9a27, 891a419. Design spec
AC-26, AC-27, AC-31 (kept outside git, in `.scratch/anomaly-loop/spec.md`).
