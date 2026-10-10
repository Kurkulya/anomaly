# Topic map, classes, verdicts and the cover rule

## Topic map

Phase 0 resolves each topic to one source, in this order:

1. the audited repo's own test rules: `CLAUDE.md`, `AGENTS.md`, `docs/` — cite the `file:line`;
2. the fallback: this skill's own rule text in the table below; for the first two rows it
   is the rule that `plugins/anomaly/skills/build/TEST-WRITER.md:7` holds;
3. neither → "no rule found".

| Topic | Look in the repo's docs for | Fallback: this skill's own rule text |
|---|---|---|
| Decision rule | which layer tests a behaviour; one test per behaviour | "Extend an existing test of the behaviour first. Add a new test only when none exists, at the cheapest layer that proves it." (`TEST-WRITER.md:7`) |
| E2e reason list | the reasons that allow an e2e test, and the tag that names one | "An e2e test needs a stated reason" (`TEST-WRITER.md:7`); here: browser- or device-only behaviour |
| Bans | no real assertion, internals, mocked siblings, tests of dev-only tooling | none → "no rule found" |
| Characterization | when a test that pins behaviour for a refactor is deleted | "Delete characterization tests when the refactor ends" |

A class whose topic says "no rule found" gets no `cut` row. Its rows are `open`.

## The question

Each audit row answers: "What would break unnoticed if this test were gone?" The answer
names a behaviour. No verdict cites coverage as proof: a line that ran was not
necessarily checked. The proof is a test that fails on a break (`outputs.md` § Break probes).

## Classes

Label each test with one class. A file with mixed tests gets one row per verdict.

| Class | What it is | Topic |
|---|---|---|
| `KEEP` | The only test of a behaviour, at the cheapest layer that proves it | Decision rule |
| `DUPLICATE` | Another test proves the same behaviour, at the same or another layer | Decision rule |
| `EMPTY-ASSERTION` | No assertion, or only a check that a value exists. A check of what the user sees is real | Bans |
| `INTERNALS` | DOM or class-name snapshot, CSS text, goldens outside the design system, a suite that mostly mocks siblings | Bans |
| `CHARACTERIZATION-LEFT` | A test that pinned behaviour for a refactor that is now finished | Characterization |
| `TOOLING` | A test of dev or CI tooling, not of the product | Bans |
| `E2E-NO-REASON` | An e2e test with no reason from the repo's list | E2e reason list |

## Verdicts

| Verdict | When |
|---|---|
| `cut` | A named cover fails on a break (a break probe), or the rule says it needs no test (dev-only tooling) |
| `rewrite` | The behaviour matters, but the test is at the wrong layer, tests internals, or has no real assertion. Name the target: cheaper layer, public interface, real assertion, merge into `<file>`. A test that catches none of its target's breaks is `cut` when its named cover fails, and `rewrite` (reason "useless") only when no named cover fails |
| `keep` | No cover exists (or none fails on the break), or the class rule allows it; not a useless test (`rewrite`) |
| `open` | A judgement call, for example a higher-layer reason that is real but not on the repo's list. It goes to the report's Open questions, never straight to a cut |

## The cover rule (no cut without a cover)

Every `cut` row fills the cover column:

- `DUPLICATE`, `E2E-NO-REASON`, `CHARACTERIZATION-LEFT`, `EMPTY-ASSERTION`: the test that
  still proves the same behaviour, as `path:line — '<test title>'`. The agent opened that
  file at the tip sha (or with `git show <sha>:<path>`) and read that test. Not a guess
  from a name.
- `TOOLING` (dev-only): the evidence, read at the tip sha, that the tool never gates CI
  and never ships, as `file:line` (CI file, hook file, build config). A tool that gates
  CI or ships → `keep` one small fixture test per rule; cut only the extra tests, with a
  cover per rule.
- `INTERNALS`: the test that proves the same outcome without internals. None → `rewrite`.

A cover is not good enough when:

- it tests another component, widget or function, even with a similar name;
- it is an e2e test without a listed reason: keep the cheaper test;
- it asserts less than the cut test (fewer cases, looser match). Name what is lost, or
  make the row `rewrite` (merge the lost case into the cover);
- it is itself a `cut` row in any `audit-<scope>` file. Two cuts that name each other
  leave nothing. Phase 3 keeps the cheaper row as the cover (verdict `keep`) and
  re-points the other cut to it; if it does not cover that cut, demote the cut to `keep`
  or `rewrite`. A chain A→B→C is the same: the last link must be a kept test.

## Size, for ranking cuts

`size` = tests removed, then measured file time. A whole-file cut ranks above a partial
cut with the same test count: most suite time is per-file overhead.
