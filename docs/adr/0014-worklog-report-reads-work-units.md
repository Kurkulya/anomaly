# ADR-0014: `worklog report` reads the work-unit file; an ad-hoc unit counts as one merged ticket

Status: Accepted · Date: 2026-10-07 · Owner: VK · Revisit-by: 2026-11-05

## Context

ADR-0011 said `measure` does not read `work-units.jsonl` and is meant to read it later, and
ADR-0012 left the join with the session metrics for the same reader ("`measure` does not read
these fields yet"). Track F needs the cost of one work unit per merged ticket (D4, D5), and
`measure` is the wrong place for it: it scans transcripts into `metrics.jsonl` and has no work
unit to ask about.

Ticket 02 wrote the report as the action `worklog report <work unit>`. Two things were left open.
An ad-hoc unit (the light path, `.anomaly/adhoc/`) has no ticket numbers, so its `build` line has
no `ticket` and the report found no merged ticket and printed no per-ticket numbers for a unit
that was built and merged. And ticket 02 AC-4 asks for "one line per ticket and stage", while the
report prints one line per work-unit line.

## Decision

- **`worklog report <work unit>` is the reader of `work-units.jsonl`.** It joins the unit's lines
  with `metrics.jsonl` by session id and writes nothing. `measure` stays a reader of transcripts
  and does not read the work-unit file. The one reader is `records.load_work_units`, and the
  merged-ticket rule and the build minutes are in `worklog.run_report` and `worklog.minutes_of`.
- **A merged ticket is a ticket number on a `build` line.** `ended` is on every line, so it does
  not mark a merge. A unit with no ticket number on any line (an ad-hoc unit) counts a `build` line
  as its one merged ticket, so its header says `merged tickets 1`, its line prints as `adhoc
  build`, and the `cost:` line gives the per-merged-ticket numbers. A unit with no `build` line
  has no merged ticket and prints no per-ticket numbers.
- **The report keeps one line per work-unit line, grouped by ticket**, with its times, minutes,
  review round, mode and doc bytes (VK, 2026-10-07). This is kept over the wording of ticket 02
  AC-4, "one line per ticket and stage": a ticket with two `build` lines (a rebuilt one, or two
  sessions) shows each line, with its own start, end and minutes, and no figure is merged away.
- **Partly supersedes ADR-0011**, the sentence that `measure` does not read `work-units.jsonl` and
  is meant to read it later. The rest of ADR-0011 stands. ADR-0011's status line names this ADR,
  as ADR-0008's names ADR-0013.
- **Partly supersedes ADR-0012**, the sentence (line 37) that `measure` does not read the new
  work-unit fields yet. The rest of ADR-0012 stands, and its status line names this ADR.

## Why

A work unit is the question, so the action that answers it takes the unit as its argument;
`measure` has nothing to filter by. Counting an ad-hoc build as one merged ticket gives the light
path the same per-ticket numbers as a numbered unit, where a header of 0 would say a built unit
produced nothing. One line per work-unit line keeps the numbers a reader can check against the file,
where one line per ticket and stage has to pick one start and one end out of several.

## Alternatives rejected

- Let `measure` read `work-units.jsonl`: it has no unit to report on, and it would need a second
  command shape for one question.
- Leave an ad-hoc unit with 0 merged tickets: the light path would never get a per-ticket cost.
- Merge the lines of one ticket and stage into one line: the earliest start and the latest end
  would hide the gap between two sessions, and the minutes would not add up.

## Accepted risks

- [ ] An ad-hoc unit counts as one merged ticket however many `build` lines it has, and the
  minutes add up over all of them. A unit built again after a review would show the total of both
  builds as the cost of one ticket. Owner: VK · Revisit: 2026-11-05.

## Revisit

When the minutes per merged ticket are registered as a verdict metric (G24), or after the first
track F dogfood, whichever comes first.

## Sources

Decisions D4 and D5 of track F; ticket 02 (`.anomaly/track-f/tickets/02-work-unit-report.md`, ACs 4
to 9) and its code, merge `2f37beb` on `feat/track-f-02`; the ad-hoc fix ticket
`.anomaly/adhoc/2026-10-07-fix-the-open-findings-of-track-f-ticket.md`, red test `a69c151`
and code `ca1c28b`; VK's decisions of 2026-10-07; ADR-0001, ADR-0011, ADR-0012.
