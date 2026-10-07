# 01: The count command

Jira: no-ticket
Covers: AC-1, AC-2, AC-3
Blocked by: None
Status: in-progress
Tests: unit, integration

**What to build:** `tally count` prints the line count, the word count with `--words`, and the line count without blank lines with `--skip-blank`.

Acceptance criteria (copied from `../spec.md`):

- [ ] AC-1: `tally count FILE` prints the number of lines in FILE.
- [ ] AC-2: `tally count FILE --words` prints the number of words in FILE.
- [ ] AC-3: `tally count FILE --skip-blank` leaves blank lines out of the line count.

**Not in this ticket:**

- AC-4 (`--json`), AC-5 (standard input) and AC-6 (a missing file) are other tickets.
- Everything about exporting counts as CSV (the export spec).

Amended 2026-10-02 (owner): print the unit after the number, `5 lines` or `5 words`.
