# ADR-0021: A later lens apply in a session replaces that session's line

Status: Proposed; supersedes the ADR-0019 Decision sentence that a lens counts once per session · Date: 2026-10-11 · Owner: VK · Revisit-by: 2027-01-11

Decision: `observe apply` keeps one line per session and lens in `lenses.jsonl`, and a later record for the same session and lens replaces that line in place when none of its values is smaller and at least one is larger. Equal totals write nothing; any smaller value is refused.
Why: `lens tally sum` writes the session's cumulative totals, so the newest sum is the true count. Skipping it lost the counts of every review after the first apply in 7 multi-ticket sessions (anomaly lens-counts-lost-after-first-apply).
Revisit: when a second reader of `lenses.jsonl` needs the history of a session's sums, or 2027-01-11.

## Context

`observe apply` skipped a lens record when the session already had a line for that lens. This kept a repeated apply from inflating the counts. `lens tally sum` adds up every run of the session, and the build and review skills apply after a ticket's close. A session that builds more than one ticket applies more than once, and every apply after the first was skipped. On main at d33184f the rule lived in README.md, in docstrings (`observe.py`, `lens.py`) and, as a premise, in one ADR-0019 Decision sentence (`docs/adr/0019-slice-picks-the-implementer-model.md:18`: a lens counts once per session), which this ADR partly supersedes. The one reader, `lens_rates` in `flags.py`, sums the counts per lens over all lines and counts one session per line.

## Decision

- A record with accepted and rejected both 0 is skipped first.
- Same session and lens, no value smaller and at least one of accepted, rejected or `revised` larger: the line is replaced with one atomic whole-file write, and it takes the apply date.
- ADR-0019 says a lens counts once per session, so an earlier sum would drop the later tickets' tallies, and builds its sum timing on that; this ADR supersedes that sentence. The sum timing of ADR-0019 stays.
- Same totals: nothing is written, so a repeated apply leaves the file byte-identical.
- A smaller value (a missing `revised` counts as 0): the batch is refused with an error naming the session and the lens. A tally is never rewritten, so a session's sums only grow; a smaller one is an input error.

## Why

The newest cumulative sum is the session's true count, and replacing keeps one line per session per lens, so `lens_rates` keeps its meaning. A repeat still changes nothing.

## Alternatives rejected

- Numbered batches, where each sum covers only the runs since the last sum and observe keys on session, lens and batch: a second key, and the digest would have to merge batches to keep counting sessions.
- Summing only once per session: the build skill cannot know which ticket is the session's last, and the user may stop early.

## Accepted risks

- [ ] `lenses.jsonl` is no longer append-only; a crash during the whole-file write is covered by the atomic replace only. Owner: VK · Revisit: 2027-01-11.
- [ ] The rule assumes one apply at a time: the window from reading `lenses.jsonl` to the rename is not locked, and the write goes through a fixed temporary file name (`files.write_text`), so two applies at once can lose one replace. Owner: VK · Revisit: 2027-01-11.
