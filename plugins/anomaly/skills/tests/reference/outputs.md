# Output files and their shapes

All under the target repo's `.anomaly/test-audit-<YYYY-MM-DD>/research/`. Each file is
`NN-<slug>.md` with the next free number; the order below is the usual one.

```
NN-facts.md            tip sha, branch, stack profile, counts per folder, topic map, reason list, CI, hooks
NN-scopes.md           the split, each agent and its file name
NN-audit-<scope>.md    one per value scope (agent-briefs.md)
NN-timings.md          the runtime scope's numbers, each with its CPU load (timing.md)
NN-covers-check.md     Phase 3: every cut's cover, re-read
NN-break-probes.md     Phase 4: the break probes, one row per break
NN-report.md           the summary and the open questions
evidence/              status snapshots, reporter JSON and logs
```

## A cut row, done right

```text
| src/forms/x/tests/fieldProps.test.tsx:12 | 6 | DUPLICATE | cut |
  src/test/consoleGuard.test.tsx:25 — 'fails a test that leaks a DOM prop' |
  docs/testing.md:40 | would break unnoticed: nothing; the global guard already fails
  any test that leaks these props (vitest.setup.ts:15), and this file silences
  console.error (:37) and so hides them | 6 tests, whole file |
```

(The paths are made up.)

## Correction line

After the cover check, the main window edits each failed row in its `audit-<scope>` file
and adds a line under the table, for example: "Correction: 14 cuts; the cover check
demoted 3, so 11." The report repeats it.

## Break probes

Every `cut` candidate with a behaviour cover gets 1 to 3 breaks. Skip a dev-only tooling
cut: there is no behaviour to break.

- A break probe runs only after the user's yes, and only in a scratchpad copy of the tip
  (`git archive`, `timing.md`). Never in the worktree, and never with `git checkout --`.
  No yes: each cut candidate that needs a break probe is `open`, reason "not probed", in Open questions.
- Write each break by hand: one change to the code the cut test checks. Use the repo's
  mutation tool only when it is already installed; never install one.
- One break probe at a time. Apply the break, run the cover (the stack profile's "Break code"), and
  restore the file. A passing cover does not hold: `keep`, unless the test is useless (below).
- Run the cut test on the same break. A cut needs its named cover to fail on the break. A test that
  catches none of its target's breaks is `cut` when its named cover fails, and `rewrite`
  (reason "useless") only when no named cover fails.
- Record the failing test name and output line.

| # | Cut | Break (file:line — change) | Cover that failed | Cut test failed? | Verdict |
|---|---|---|---|---|---|
| 1 | `a.test.ts:10-40` | `src/a.ts:31` — `>=` to `>` | `b.test.ts:22` — '…' | yes | cut |

## `report`

```text
# Test audit — <repo>
Date · tip <sha> · branch · writes only research/ and the .anomaly/ exclude line.
Per-scope detail: <list of audit files>.
Tags (the one legend, timing.md): [M] measured, [C] counted, [E] estimated, [NM] not measured.

## 1. Summary numbers
| Scope | Tests (static) | cut | rewrite | open | keep |   + unit total, e2e total
Two or three lines: is the suite too big, and where.

## 2. Rule sources
The topic map: each topic with its file:line, the fallback, or "no rule found".

## 3. Per class
One table per class (DUPLICATE, EMPTY-ASSERTION, INTERNALS, CHARACTERIZATION-LEFT,
TOOLING, E2E-NO-REASON): | test file:line | verdict | cover file:line — title | rule file:line | size |.
Only cut and rewrite rows; KEEP stays in the audit files.

## 4. Break probes
Each break, one line: file:line — the change made — the cover that failed, or none.

## 5. Timings
| What | Value | Load band | Re-time isolated |   + where the time goes (per-file overhead vs bodies)

## 6. Cover check
Rows checked, rows demoted, and why. The correction lines.

## 7. Problems found on the way
Untested branches, tests that test the wrong function, flaky tests, stale installs.
List each clear defect (one fix, no choice) on its own line.

## 8. Open questions
One line each: <question> · options: a / b · recommended: a, because … · source: <file:line>
```

Typical open questions: a duplicate whose higher-layer reason is real but not on the
list; a characterization test whose refactor may not be finished; a tooling test that may
gate CI; a whole file whose tests are half `keep`, half `cut`; a number that needs an isolated
re-time first; a topic with "no rule found".

## The next step

The last line of the chat reply is one of these (SKILL.md Phase 5), never run:

- `/anomaly:interview Work unit test-audit-<date>. Idea: settle the open questions in .anomaly/test-audit-<date>/research/<NN>-report.md`
- `/anomaly:diagnose <the defect, with file:line>`, one line per defect
- none: the reply ends at the report
