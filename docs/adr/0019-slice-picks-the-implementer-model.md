# ADR-0019: Slice picks the implementer's model by a fixed rule and writes it in the ticket

Status: Proposed · Date: 2026-10-10 · Owner: VK · Revisit-by: 2027-01-10

Decision: `slice` writes `Model: implement | implement_wide` on each ticket: `implement_wide` when the ticket has a `Restates:` line or its `Touches:` names a seam that another ticket owns (in `seams.md` or in slice's seam row → ticket table), else `implement`. Core defaults: `implement` sonnet, `implement_wide` opus. Build dispatches the implementer on that role; each `implement` ticket adds a `model_pick` lens line at its close, rejected when it took 2 or more fix rounds.
Why: the old core default, "sonnet for contained tickets, opus for cross-cutting ones", left the choice to the orchestrator's judgment at dispatch time, with no record, so it could not be checked or measured.
Revisit: when the `model_pick` lens shows more than a third of `implement` tickets rejected, when a ticket line names its size, or 2027-01-10.

## Context

README says the ticket says which model the implementer gets, but no ticket line says it. `seams.md` is written by `build` when a ticket closes, so at slice time a new unit's file is empty; slice itself builds a seam row → ticket table when the stories list seams. `ticket result` records the counts `High` and `fix rounds` per ticket.

## Decision

- `slice` writes the `Model:` line by the rule above; `anomaly:plan` (tickets mode) reports a line that breaks the rule as Medium; `check slice` refuses an unknown value; a ticket without the line runs on `implement`.
- `build` and `conduct` dispatch the implementer on the ticket's role; the test writer stays on `implement`.
- New lens `model_pick`: one tally line per `implement` ticket, accepted or rejected by `fix rounds` (2 or more is rejected). `implement_wide` tickets are not judged: a clean opus ticket does not prove sonnet would have passed, so over-picks are left to model experiments (ADR-0018).
- The tally is written at the close, after the last review. So when the user calls `build` directly, `review` no longer sums the session's lenses; `build` runs `lens tally sum` and `observe apply` after the close of the session's last ticket; when the user did not say whether it is the last, `build` asks at its close. Under `conduct`, its cumulative review sums after every close, as today; a one-ticket unit has no cumulative review, so build sums. A lens counts once per session, so an earlier sum would drop the later tickets' tallies.

## Why

The stage that sees the whole plan decides once, from facts in the ticket file, and the file keeps the choice. A rule can be checked by the plan review and judged by the lens; a judgment at dispatch time can be neither.

## Alternatives rejected

- Escalate on outcome (start on sonnet, switch to a fresh opus agent after a failed fix round): breaks "the same implementer fixes Blocker and High" in build and starts the new agent without context.
- Two roles picked by a repo risk pattern: personal repos have none, so the rule would never fire.
- A plain sonnet default with opus only from the profile: gives up the cross-cutting case.

## Accepted risks

- [ ] The rule only guesses "cross-cutting"; a hard ticket in one file gets `implement`. The lens shows it as a rejection. Owner: VK · Revisit: 2027-01-10.
- [ ] A rejection can come from a weak ticket or spec, not the model. Owner: VK · Revisit: 2027-01-10.
- [ ] The two implementer roles cannot be measured apart while the implementer port is the general-purpose agent: model-weighted tokens per dispatch keys on the agent type. The `model_pick` lens is the per-ticket signal. Owner: VK · Revisit: 2027-01-10.
