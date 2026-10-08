# Planning formats

The shapes the planning skills share. A skill links this file and does not repeat a shape. The CLI
reads the line names, so keep them exact.

## stories.md

One file per work unit, at `.anomaly/<work-unit>/stories.md`. Warn at 6 KB and hint at a split.

```
# <title>
Sources: <where the stories came from> · Gathered: <date>
Why: <what the work is for>
Rules for all stories: <rules that hold for every story>

## 1. As a <who>, I want <what>, so that <why>.
- AC-1: <criterion>
- AC-2: <criterion> (verbatim <source>)
Amended <date>: <what changed> — <why>

## Out of scope
- <item> — owner: <unit, ticket or ADR>
```

- A source criterion is kept word for word and tagged `(verbatim <source>)`.
- A scenario is added only when an AC is unclear.
- UI copy is in bold, endpoints in backticks; a scenario's steps follow `**Scenario N — <name>:**`.
- Each AC id is unique and is never renumbered. A withdrawn AC stays in place with an
  `Amended <date>:` line.
- An Out of scope line needs the marker `— owner:`. Only the first `— owner:` starts the owner. It is a unit, ticket or ADR that holds the item, never a `D-n`; a `D-n` in brackets after it, such as `(D-3)`, is a citation and is allowed. A plain `owner:` elsewhere is ignored. The owner must exist in the checkout (a unit folder under `.anomaly/` or `.scratch/` other than this unit, written with or without backticks, bare or as a path; a ticket file of this unit as `ticket NN` (or `issues/` in a `.scratch` unit), or of another unit as ``ticket NN of `<unit>` `` (the ticket is in that unit's `tickets/`, or its `issues/` in the old `.scratch` layout; "in `<unit>`" names no ticket), or the path of a ticket or ADR file; an ADR file as `ADR-NNNN`) or carry `TODO(<owner>, revisit YYYY-MM-DD)` with a real date. A unit is never the owner of its own item. A person or a skill needs the key; a placeholder is never an owner. `check stories` finds the owners from the folder `<root>/.anomaly/<unit>` or `<root>/.scratch/<unit>`; a work unit anywhere else gets one layout error.

## decisions.md

One line per entry, written after each round, settled items only. Numbers are never reused.

- `- D-n: <decision>. Why: <one line>. Source: <where>`, where `<where>` is a file:line, a commit, an ADR
  or the text "user, <date>".
- Add the tag ` ADR?` when the decision may need an ADR.
- Prefixes: `Test seam:`, `Open:`, `Risk:`.
- A changed line gets a second line `Amended <date>: <what changed>`.
- `- T-n: **<term>** — <meaning>. Avoid: <words>.` is one settled term, waiting to be written into
  the glossary.
- A decision that leaves an item out of scope ends its text with `— owner: <unit, ticket or ADR>`. Only the first `— owner:`
  counts, up to the first `. Why:` or `. Source:`. The owner is never a `D-n` (a bracketed `(D-n)` is allowed), and
  follows the same existence rule as an Out of scope owner.

## Ticket

One file per ticket, `tickets/NN-slug.md`. `slice` writes these lines:

```
# NN: <title>
Status: ready-for-agent | ready-for-human (<why>)
Blocked by: none | 01, 03
Covers: AC-2, AC-5 | none
Tests: <levels>
Jira: <key> | no-ticket
Gate: <date or outside step>

What to build: <behaviour, 1-3 sentences>
Touches: <paths and symbols, new ones marked, no line numbers>
Restates: <files that repeat a changed rule>
Out of scope: <one line, when a sibling ticket owns it>

- [ ] AC-2: <verbatim>
Decisions:
- D-3: <verbatim from decisions.md>
```

- `Jira:` holds a tracker key or `no-ticket`, until the tracker port (phase 2, D-11) names the key line.
- `Gate:` only when the ticket was gated. `Restates:` only on a ticket that changes a rule.
- `Result:`, `Metrics:`, `Reviewed:`, `Verified:`, `Red:` and `Red-changed:` are written later by the
  CLI; `Amended` by a later stage or a person. `slice` writes none of them.
- A light-path ticket from `diagnose` has `Blocked by: none` (`ticket show` warns without a `Blocked by:` line), `Covers: AC-1`, `Status: ready-for-agent`,
  the `Tests:` line, then `Repro: <command>` (runnable as written, red at hand-over). AC-1 is the exact symptom gone with the repro
  green. The body holds Symptom, Root cause, Fix, Risk, and the seam or a no-correct-seam finding, and a
  `## Hypotheses` section: 3 to 5 numbered lines, each `1. <hypothesis>: confirmed | refuted, probe <output>`.
  The section ends at the first line that is not a numbered item. `ticket adhoc --from` refuses a draft without it.

## log.md

Events only. Each line is `<YYYY-MM-DD HH:MM> <stage>: <text>`, written only by `anomaly log add`.

The `specify` line starts its text with `ACs: AC-1, AC-2, …;`: every AC id of `stories.md` at that
run, then the claim-check result. `check stories` reads those ids.

## Triage words

The `Status:` of a ticket:

- `ready-for-agent`: `build` can take it.
- `ready-for-human (<why>)`: a person does it; the reason is in the brackets.
- `needs-info`: waits for an answer.
- `wontfix`: closed without work.

`in-progress` and `done` are run states. The CLI sets them; a skill never writes them.

## Next-step offer

End a stage with one line naming the next skill: `/anomaly:<name> <work unit>`. Use a widget only when
the client has one; otherwise this plain line is the offer.

## ADR front block

An ADR starts with a block of about 1.5 KB, on top, before the long text:

- Decision: what was decided, in a sentence or two.
- Why: the reason, with the evidence.
- Revisit: the event or date that reopens it.
