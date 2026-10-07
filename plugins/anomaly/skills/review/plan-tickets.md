# Plan reviewer, tickets mode

For `anomaly:plan` in `tickets` mode only. Inputs: the work unit's `tickets/` folder, `stories.md` and `decisions.md` (shapes in `docs/formats.md`), and the main checkout path. Print the AC coverage table first: `AC | ticket | Tests: level`.

1. Ordering. Draw the producer and consumer graph from `Blocked by:`. A ticket that uses what a later or unrelated ticket creates, or any cycle, is a Blocker. [P1]
2. Invented paths. Every path and symbol in `Touches:` either exists (prove it with Read, Glob or `git ls-files`) or is marked new and created by this ticket or a blocker. A path that exists nowhere is a Blocker. [P2]
3. Hidden dependencies. For each pair of tickets that are not blocked on each other, parallel work must not touch the same file, symbol, migration, translation file or shared helper. A shared one is High: add a `Blocked by:` or split. [P3]
4. Sizing. More than 5 files, or more than one subsystem, is too big; a ticket that is a few lines is too small to stand alone. Over 5 KB of text: warn only. Medium. [P4, N7]
5. Restates. A ticket that changes a rule lists, in `Restates:`, every file that repeats it. Run a grep for the rule's words; a hit not listed is Medium. [N4]
6. AC coverage. Every story AC appears in some `Covers:`, with `Covers:` complete, and the AC text is copied exactly. An AC covered by no ticket is a Blocker. [P5]
7. Tests level. Every AC has a `Tests:` level: unit, integration, e2e, UI walkthrough, real-data probe or mutation probe. A missing level is Medium. [P5]
8. Report with specifics, propose no other plan, and say so when a check is clean. This gate runs last; only a Blocker stops it and the rest go in the handoff. [P8, N8]
