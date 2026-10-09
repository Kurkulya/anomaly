# ADR-0008: A rewritten skill is judged as one experiment at its switch-over

Status: Accepted; partly superseded by ADR-0013 (the sessions compared, the metric and the five sessions of a switch-over); the first rewrite ran no switch-over (2026-10-09, see Consequences) · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-12-01

## Context

Every fix is an experiment with one metric and one guard (ADR-0002), and one change per
experiment. A fresh `build` changes many things at once (about eight upgrades from the workflow
audit), and the owner runs about 41 build sessions every 14 days on the old skills, so the old
and new skills must run side by side for a while. Four experiments on the old `implement` skill
were declared on 2026-10-04 with checks due 2026-10-25.

## Decision

- Each new pipeline skill replaces its old skill through one **switch-over** experiment: the old
  skill's last 28 days against the new skill's sessions; metric tokens per merged ticket, guard
  late-catch sightings. Upgrades inside the skill are not judged one by one.
- **Switch-over rule:** five sessions of the right kind in which the new skill ran end to end
  with no fall-back, and the guard not worse. Then the old skill is deleted, recorded as a
  `calibrate fix`.
- A worse guard leads to bisecting the suspect upgrades as separate experiments.
- New coverage is not part of the comparison: the security reviewer is judged on its own as a
  lens (findings accepted against its cost), and its tokens are left out of the metric.
- Rules from experiments still running enter the new skill as "pending verdict"; a reverted rule
  is removed through the rule trace review. The new `build` takes over no real tickets before the
  2026-10-25 verdicts, so those experiments keep measuring `implement`.

## Why

Judging eight upgrades one by one would take months. One comparison per skill still holds the
change to a pre-declared metric and guard, and the old skill stays available to compare against
and to fall back to.

## Alternatives rejected

- Roll the upgrades onto the new skill one at a time: about three weeks each.
- Switch over on a date, without a session count: no evidence the new skill works.

## Accepted risks

- [ ] Several upgrades are confounded in one result. Owner: VK · revisit after the first
  switch-over (bisect if the guard got worse).
- [ ] Five sessions is a small sample. Owner: VK · revisit 2026-12-01 together with ADR-0002's
  thresholds.

## Revisit

After the first switch-over reaches a result.

## Sources

Design decisions 2026-10-04 (`.scratch/anomaly-workflow/decisions.md`, git-excluded); calibrate
run 2026-10-04 (experiments on `implement`). Applies ADR-0002 to rewrites.

## Consequences

- 2026-10-09: when phases 1 to 3 had merged, the owner found no old build skill left in use to compare
  against, so the first rewrite ran no switch-over and is not judged against the old skills. Its
  upgrades stay unmeasured as a set; later fixes are judged one by one as ADR-0002 says. The
  compatibility kept for the switch-over is dropped: the `.scratch` layout (ADR-0011) and the `Jira:`
  key line (ADR-0017). The switch-over method itself (ADR-0013, `calibrate declare --skill`) stays for a
  later rewrite.
