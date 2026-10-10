# The six principles and the ladder of guards

Every area finding names the principle it breaks. Guards (area 6) and decision records (area 7)
are not principles; they are how the principles hold. For where each kind of knowledge
lives (CLAUDE.md, ADR, CONTEXT.md, comments), read the audited repo's own docs (its
`CLAUDE.md`, `docs/README.md`, `docs/adr/`, `CONTEXT.md`).

The words here are neutral. Stack wording is in `stacks/<stack>.md`.

1. **Dependency direction** — arrows point down; type-only imports count.
   *Broken:* a lower layer imports a higher one. *Why:* the lowest layers are tested and
   reused most; a utility that imports a page cannot be tested without the page.
2. **Module depth** — a boundary returns what callers need, not what the wire or the store
   looks like.
   *Broken:* many files read the raw wire shape; keys are loose strings kept in sync by
   memory; one wire quirk is copied in many places. *Why:* every leak breaks when the
   inside changes.
3. **State ownership** — one owner per fact, with a known lifetime.
   *Broken:* a store field mirrors a fetched result; a fact has two writers; a reset nobody
   calls; a field never written. *Why:* two owners mean hand-sync, and hand-sync is what
   people forget.
4. **Side effects** — below the UI layer, return decisions; a UI-layer part performs them.
   *Broken:* a utility or store opens a dialog, shows a message or navigates. *Why:* a
   function that returns a decision is tested with equality ("return, don't act"); one that
   acts needs a fake UI.
5. **Platform adapters** — each platform API (storage, network, clock) goes through one platform adapter.
   *Broken:* raw calls spread over layers, unguarded. *Why:* storage can be blocked, full
   or corrupt; fifteen raw sites are fifteen places that can crash, one platform adapter is one.
6. **Cohesion** — keep together what changes together (change-locality: one change, how
   many files open?).
   *Broken:* a top unit wires many parts; one component has many jobs; presentational code
   imports a store. *Why:* the cost of a change is the number of places you must read first.

## The ladder of guards (five rungs)

A rule is only as strong as what enforces it. Rate every non-functional rule, highest first:

| Rung | The rule is enforced by | Strength |
| --- | --- | --- |
| 1 | **Blocks CI** (lint at error, a test, a script the pipeline runs from inside the repo) | Holds without a reviewer |
| 2 | **Blocks pre-commit** (hook) | Holds unless the hook is skipped |
| 3 | **Warns** (lint at warn, an error log, a flag that is off) | A comment with a stack trace |
| 4 | **Documented** (CLAUDE.md, README, ADR) | Holds while people read it |
| 5 | **Tribal** (someone knows) | Holds while that person stays |

Named idea: **"a guard that warns is a comment."** The audit question for every guard:
which rung, and what would move it up one? A lint rule at warn is a **ratchet step**, not
a lock; the ticket that flips it to error is the lock.

Named idea: **"check the artifact, not the intent."** CI status, lint level, the flag's
current value, the deployed file: read the thing itself, not the sentence that says what
it should be.
