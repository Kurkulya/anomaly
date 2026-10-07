# ADR-0009: Verdicts use a permutation test

Status: Accepted · Date: 2026-10-06 · Owner: VK · Revisit-by: 2026-12-01

## Context

ADR-0002 called a metric "moved" when it changed by 15% or more with at least 5 sessions on each
side. The sessions of one person vary far more than 15% by themselves. A check with no real
change at all (two disjoint groups of n sessions drawn from one pool, 20,000 draws) shows how often
the 15% gate still calls a move:

| Metric | Pool | Draws a 15% gate calls a move, n = 5 / 10 / 20 |
|---|---|---|
| weighted tokens, build | 67 sessions | 81% / 70% / 52% |
| active minutes, build | 67 | 81% / 72% / 58% |
| rework sightings per session, build, since the backlog began | 64 | 44% / 63% / 76% |
| late-catch sightings per session, build, since the backlog began | 64 | 67% / 76% / 83% |
| interrupts, median, build, since the backlog began | 64 | 0.1% / 0% / 0% |

So most `keep` and `revert` results were coin flips. Two more faults:

- The five open experiments count the sightings of their own anomaly (`sightings since the fix`),
  and each anomaly has only 1 or 2 sightings. No count can prove that a fix of so rare an event
  worked.
- The `interrupts` guard read the median, which is 0 in 92 to 95% of sessions. It never moved,
  even when interrupts rose.

The digest trend lines had the same fault: a bare "+50%" from 5 sessions on read as a trend when
it was mostly noise.

## Decision

- **Permutation test.** For a session metric, the pooled sessions from before and after the fix
  are split again at random with the real group sizes. **Chance alone** is the share of splits
  that change at least as much as the real one. Every split is counted when there are 10,000 or
  fewer; otherwise 10,000 random splits are drawn with a fixed seed, so the same data always
  gives the same answer, and the real split is counted too, `(hits + 1) / (10,000 + 1)`, so
  chance alone is never 0.
- **Primary metric, and active minutes next to weighted tokens:** a **real change** needs chance
  alone (two-way) at 10% or less, a change of 15% or more, and 5 sessions on each side. Anything
  else is **within noise**, so a change under 15% is within noise even when chance alone is
  small. From a zero baseline any rise meets the 15% floor. The reading says "N% of random splits
  change this much" and ends with `real change` or `within noise`.
- **Guard:** tested one way, for a rise only, at 10%, with the same 15% floor and 5 sessions. A
  sighting guard that would be worse with fewer than 2 sightings since the fix is `thin`. A guard
  is never `better`: it is `worse` or `same`.
- **Order of ADR-0002 unchanged:** a worse guard reverts first, then worse active minutes (when
  the primary is weighted tokens), then a worse primary. `keep` needs a real change for the
  better with the guard `same`, and time (for tokens) the same or better. Anything else is
  `inconclusive`.
- **Rare-event rule.** When the primary is `sightings since the fix`, there is no count test and
  no baseline. A worse guard gives `revert`; then one or more sightings of the anomaly after the
  fix day give `revert` (it came back); otherwise the result is the new `unproven`: kept, not
  proven. A guard that cannot be judged does not block, and the reason names it. `unproven` does
  not reopen the anomaly; a later sighting reopens it through the existing path.
- **`interrupts` is a mean** per session. `denials`, weighted tokens and active minutes stay
  medians.
- **An experiment is due after 20 sessions** of its kind since the fix day (was 5). The 21-day
  date is unchanged, and `declare` warns when the last 28 days hold fewer than 20 sessions of the
  kind.
- **The digest uses the same rule.** Each trend line with 5 sessions per window ends with
  `→ real change` or `→ within noise`. A new section `## Experiment results` always shows the
  count of each result, so `unproven` is never added to `keep`.
- **Every verdict reason names its rule:** `permutation test, ADR-0009` or `rare-event rule,
  ADR-0009`, so a result written under the old 15% rule can be told apart.

## Why

Power of the full rule, from `power.py` (67 build sessions, 40 before the fix, 300 trial
experiments per cell, the guard is late-catch sightings with no real quality loss). Share of
`keep` / `revert`, in percent:

| Real token cut | 5 after | 10 after | 20 after |
|---|---|---|---|
| none | 0 / 22 | 2 / 17 | 5 / 23 |
| -30% | 3 / 20 | 12 / 22 | 22 / 21 |
| -50% | 7 / 20 | 38 / 20 | 73 / 17 |
| -75% | 32 / 22 | 77 / 22 | 79 / 21 |

That run used a 25% guard. With the guard at 10%, a fix that did nothing is reverted about 15% of
the time, and a -50% cut with 20 sessions after gets `keep` about 80% of the time. About 10% false
reverts remain at any guard level, from the two-way 10% tests on tokens and time.

So the loop sees large effects (-50% and more, such as moving subagents to a cheaper model) and
cannot see small tweaks. Most verdicts on small tweaks honestly say `inconclusive`. With 5
sessions after the fix, even a real -50% is almost never seen, so an experiment waits for 20.

A rare event cannot be proven by a count, but it can be disproved: if the anomaly came back, the
fix failed. `unproven` keeps that difference visible. A wrong `keep` or `revert` can be undone:
the experiment is declared again. One reading at 10,000 splits takes about 0.09 s in plain Python,
so the spec estimated the digest at near 2 s; on the real home it took 2.7 s (see Accepted
risks).

## Alternatives rejected

- **A band from the baseline alone** (judge the later window against the spread of the earlier
  one): it ignores how the later window is spread. The test uses both windows and the real
  number of sessions on each side.
- **A higher fixed threshold** than 15%: the design session looked at raising it to about 100%
  (a 2× change), with more sessions. It is simple, but one number for every metric is the mistake
  being fixed. The noise table shows why: the share of false moves differs by metric and by n
  (tokens fall from 81% to 52% as n grows, sighting rates rise from 44% to 76%). That a bar high
  enough to stop false moves at 5 sessions would hide real changes at 20 follows from the
  same table and from the session's noise output (a 95% band of about +-204% at n = 5 and +-48%
  at n = 20 for build tokens); it is not a reason recorded in the session.
- **A 25% guard level:** this was the level of the power run. With it, 17 to 23% of fixes that
  did nothing were reverted in every cell, against about 15% with the guard at 10%.

## Accepted risks

- [ ] False verdicts: about 15% of fixes that did nothing are reverted, and about 10% remain at
  any guard level. Owner: VK · revisit 2026-12-01.
- [ ] The power of the guard against a real quality loss was not simulated; the power run used a
  guard with no loss. A real drop in quality may be missed. Owner: VK · revisit 2026-12-01.
- [ ] `GUARD_LEVEL` and `VERDICT_LEVEL` are both 0.10, so no test proves which one the guard
  reads: swapping them passes the suite. Owner: VK · revisit 2026-12-01.
- [ ] A median permutation test gives chance alone 1.0 when every session in both windows has the
  same value (5 sessions at 150 against 5 at 100 reads "+50% → within noise"). Owner: VK ·
  revisit 2026-12-01.
- [ ] The digest cost grows with the sessions per window: measured 0.06 s, 0.18 s and 0.48 s per
  trend line at 20, 60 and 150 sessions per window, and 2.7 s for the whole digest on the real
  home on 2026-10-06. Owner: VK · revisit 2026-12-01.

## Revisit

After the five experiments due on 2026-10-25 have a result under this rule, and at the latest on
2026-12-01: are the false-verdict rate and the guard level still acceptable?

## Sources

Spec `.scratch/verdict-noise-band/spec.md` (git-excluded) and its AC-1 to AC-17. Evidence scripts
in `.scratch/verdict-noise-band/evidence/`: `noise2.py`, `sighting_noise.py`, `power.py`. Merges
into `feat/no-ticket/verdict-noise-band`: a698430 (07, due after 20 sessions), b40600c (01,
readings carry samples), 52cac4d (02, permutation verdict), ec6fea4 (04, interrupts as a mean),
034f95c (03, one-way guard), ada2fcd (05, `unproven`), 5c46424 (06, digest verdict words).
Replaces the gate and the due count of ADR-0002.
