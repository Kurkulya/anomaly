# Plan reviewer, tickets mode

For `anomaly:plan` in `tickets` mode only. Inputs: the work unit's `tickets/` folder, `stories.md` and `decisions.md` (shapes in `docs/formats.md`), and the main checkout path. Print the AC coverage table first: `AC | ticket | Tests: level`.

1. Ordering. Draw the producer and consumer graph from `Blocked by:`. A ticket that uses what a later or unrelated ticket creates, or any cycle, is a Blocker. [slice P1]
2. Invented paths. Every path and symbol in `Touches:` either exists (prove it with Read, Glob or `git ls-files`) or is marked new and created by this ticket or a blocker. A path that exists nowhere is a Blocker. [slice P2]
3. Hidden dependencies between parallel tickets. For each pair not blocked on each other, the two must not touch the same file, symbol, migration, translation file or shared helper, and their `Restates:` lists must not share a file. A shared one is High: add a `Blocked by:` or split. [slice P3]
4. Sizing. More than 5 files, or more than one subsystem, is too big; a ticket that is a few lines is too small to stand alone. Medium. [slice P4]
5. `Restates:` overlap. A ticket that changes a rule lists, in `Restates:`, every file that repeats it. Run a grep for the rule's words; a hit not listed is Medium. [slice N4]
6. AC coverage. Every story AC appears in some `Covers:`, `Covers:` is complete, and the AC text is copied exactly. An AC covered by no ticket is a Blocker. [slice P5]
7. `Tests:` level per AC. Every AC has a `Tests:` level: unit, integration, e2e, UI walkthrough, real-data probe or mutation probe. A missing level is Medium. [slice P5]
8. Report with specifics, propose no other plan, and say so when a check is clean. This gate runs last; only a Blocker stops it and the rest go in the handoff. [slice P8, N8]
