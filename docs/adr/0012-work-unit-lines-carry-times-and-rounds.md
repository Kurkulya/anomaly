# ADR-0012: Work-unit lines carry times, doc size and review rounds; the start is stamped by the CLI

Status: Accepted; partly superseded by ADR-0014 (`worklog report` now reads these fields, not `measure`) · Date: 2026-10-06 · Owner: VK · Revisit-by: 2026-11-05

## Context

ADR-0011 fixed a work-unit line as `{feature, stage, session, date}`. Track F judges speed as
wall-clock minutes per merged ticket, with fix rounds per ticket and Blocker/High per work unit as
the guards (G8). A line with only a date cannot give minutes, and `ticket result` made two
numbers worse than missing: a count it was not given was written as `0`, and a ticket with no
start time took the merge time as its start, so it looked as if it took no time.

A start time also cannot come from the model. It has no clock it can trust, and a time typed into
a command line is a value a model can get wrong (G34).

## Decision

- **A work-unit line gains fields, and none is renamed.** Every new line has `ended` (the CLI
  clock, `TICKET_TIME_FORMAT`). It has `started` when a start was stamped, `doc_bytes` when
  `worklog add --docs <folder>` was given (the bytes of the `.md` files below the folder, summed in
  Python), and, on stage `review`, `ticket` and `mode` (the modes of the review skill), so one
  review line is one review round. `--ticket` is also allowed on stage `build`. Lines written
  before this stay valid; `feature` stays `feature`.
- **`worklog start <key> <stage> [--ticket NN]` stamps the start.** The record lives in the plugin
  data folder (`worklog-starts.jsonl`), not in home: it is throwaway state (ADR-0001). The file is
  append-only: `worklog add` writes a `consumed` line before the work-unit line, and a start counts
  only when no consumed line follows it, so one start measures one `add`. A start and an `add`
  belong together when their key, stage and ticket are equal. The model never passes a time.
- **No start record is a warning, not an error.** The line is still written, without `started`, and
  `worklog add` prints `warning: no start time` on stdout and exits 0.
- **`Metrics:` leaves out what was not measured.** A count flag of `ticket result` that is not
  passed is not written (it was `0`); `--fix-rounds` is new. A ticket with no start time gets
  `started unknown` and the same warning. Reopening such a ticket with `set-status in-progress`
  replaces only `started unknown` and keeps the counts.
- **Cost is still found by joining.** The line holds minutes, bytes and rounds, no tokens or money.
  Cost comes from joining work-unit lines with the session metrics (G17), as ADR-0011 says;
  `measure` does not read these fields yet.
- **Partly supersedes ADR-0011**, the sentence that `work-units.jsonl` holds only
  `{feature, stage, session, date}` per stage run. The rest of ADR-0011 stands.

## Why

The CLI has the clock and the folder, so it can stamp and measure without a model typing a number.
Putting the start in the data folder keeps a half-finished stage out of the durable file: only the
finished line goes to home. An append-only start file cannot lose a record to a failed rewrite or
to two calls at once, and a line that is not JSON stays visible. Matching by ticket keeps two
parallel tickets of one feature, which share a key and a stage, from reading each other's start.
Leaving a number out says "not measured" where `0` said "measured, none", and `started unknown`
says it where the merge time hid it. Adding fields keeps every reader of an old line working.

## Alternatives rejected

- A `--started <time>` flag on `worklog add`: the model would pass a time, and G34 settled that it
  does not.
- Keep the start in home: a start that is never followed by an `add` would sit in a committed
  file.
- Rewrite the start file to remove a consumed record: a failed rewrite, a lost parallel `start` and
  a dropped corrupt line are all worse than a longer throwaway file.
- Match a start by key and stage only: parallel tickets would read each other's start.
- Keep a count default of `0`: it cannot tell "measured none" from "never measured".

## Accepted risks

- [ ] An abandoned start: a `start`, then the session dies, and days later an `add` for the same
  key, stage and ticket with no new `start` reads the old start and reports a far too long time.
  A later `start` replaces it, so only a stage that is never restarted is affected. Owner: VK ·
  Revisit: 2026-11-05 (after the first track F dogfood; a maximum age of a start is the likely fix).
- [ ] `worklog add` writes the consumed line before the work-unit line. If the home write fails
  after that, the start is lost: the command exits 2, and the retry writes the line without
  `started` and prints the warning. A failed home write loses the start; the retry warns. Owner:
  VK · Revisit: 2026-11-05.
- [ ] Two parallel stages of one feature with the same stage name and no `--ticket` share a start.
  Owner: VK · Revisit: 2026-11-05.

## Revisit

When `measure` reads these fields (the join with session metrics), or after the first track F
dogfood, whichever comes first.

## Sources

Decisions G8, G17, G23 and G34 in `.scratch/workflow-build/status-2026-10-06.md`
§ 6 (git-excluded); the `workflow-build` spec § Work-unit measurement fields (ACs 91 to 95;
`.scratch/workflow-build/spec.md`); ticket 14
(`.scratch/workflow-build/issues/14-work-unit-measurement-fields.md`); commits on branch
`feat/no-ticket/work-unit-measurement-fields`: `c07588b`, `859ea83`, `3ae415a`, `2ede54d`,
`fa2f4bc`, `6128b4a`, `b35d7e2`, `ffceb9c`, `a73938e` and `aae60b8` (the commit that added this
change to the ADR is not listed); ADR-0001, ADR-0011.
