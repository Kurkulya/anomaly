# Scopes and agent briefs

## Splitting into scopes

- Scopes follow the test-file count (SKILL.md Phase 1). 60–300 files: 2 value scopes.
  Over 300: 3–5 value scopes of about 80–150 files, plus one runtime scope.
- Split by folder, so each agent owns whole files and the tables do not overlap.
- Keep a layer's tests together with the code they test, and give e2e to the
  scope that holds the logic it may duplicate. A cross-layer duplicate is found by the
  agent that sees both sides; the other agents grep for it.
- Tooling tests (`scripts/`, `tool/`, mocks, fixtures) go to one scope.

Write `scopes`: one line per scope with its folders, file count, agent and file name
(`NN-audit-<scope>.md`, `NN-timings.md`). Dispatch order: SKILL.md Phase 2. Without an
agent, the main session follows the brief itself.

## Filling a brief

`<skill folder>` is the absolute path of this skill's folder. `<research>` is
`<repo>/.anomaly/test-audit-<date>/research`. `<facts>` is the `facts` file there.

## Brief for a value scope

```text
You audit the tests in <folders> of <repo root> at tip <sha>. You are read-only on the
repo. You write exactly one file: <research>/<NN>-audit-<scope>.md. Nothing else.

1. Read the topic map in <facts>: each topic's source file:line. Read those lines, and
   <skill folder>/reference/classes.md (classes, verdicts, the cover rule). The repo's
   reason list: <path, or "none: the topic map's fallback">.
2. Find candidates with the recipes in <skill folder>/reference/grep-recipes.md and the
   stack profile <stack profile file>. A grep hit is a candidate, not a verdict. Read every candidate test. Also skim
   each file in scope once: some classes do not grep well. Read at tip <sha>: first
   check `git rev-parse HEAD` is <sha>; if not, read each file with `git show <sha>:<path>`.
3. For every proposed cut, open the cover at the tip and read that test. Write it as
   path:line — '<title>'. If the cover tests another unit, is an e2e test with
   no listed reason, or asserts less: the row gets the keep verdict or rewrite, not cut. A dev-only
   tooling cut cites file:line evidence that the tool neither gates CI nor ships.
4. Write a table: | file:line | tests | class | verdict | cover (path:line — title) |
   rule (file:line from the topic map, or "no rule found") | what would break unnoticed
   if this test were gone | reason, with evidence lines | size |. Never cite coverage as
   proof. One row per file; split the row when tests in one file get different
   verdicts. KEEP files get one short row. A class whose topic has no rule gets open,
   never cut.
5. List judgement calls separately under "Open", one line each, with your recommendation.
6. Do not run the test suite. Do not time anything. Do not restate the rules.

Return a digest of at most 400 words: counts per class and verdict (static, with the
command), the 5 biggest cuts with cover, the open items, and anything that surprised you.
No tables in the digest.
```

## Brief for the runtime scope

```text
You measure test run time, setup cost, hooks and CI for <repo root> at tip <sha>.
Read-only on the repo. You write <research>/<NN>-timings.md and files in
<research>/evidence/, nothing else. Follow <skill folder>/reference/timing.md exactly:
install freshness first (stale -> stop and report), git status --porcelain after each
run compared with evidence/status-0.txt (record untracked outputs in the timings file; a
tracked change stops the run; never revert or clean),
CPU load at start / mid / end of every run, a band per number, [M]/[C]/[E]/[NM] tags.
Measure: full unit suite wall and phase split, the 25 slowest files, e2e
wall if runnable, the global test setup cost, pre-commit hook cost (in a copy), and
the CI test jobs (read <CI file>; do not trigger a pipeline). Mark "re-time isolated:
yes" on any number a cut or a setup change would be judged by.
Return a digest of at most 400 words: the load band, the headline numbers with load,
where the time goes, and what you could not measure.
```

## Brief for the cover check (Phase 3)

```text
Read every row with verdict "cut" in <research>/*-audit-*.md.
For each, open the named cover and the cut test at tip <sha> (if HEAD is not <sha>,
use `git show <sha>:<path>`). Answer: does the cover fail if the behaviour the cut test
pins breaks? A cover that is itself a "cut" row in any audit file does not hold:
follow the chain to its last link, which must be a kept test. For a pair that names each
other, propose keeping the cheaper row and re-pointing the other cut to it. For a
dev-only tooling cut, check instead that the cited file:line shows the tool neither
gates CI nor ships. Use the "not good enough" list in
<skill folder>/reference/classes.md. Write <research>/<NN>-covers-check.md:
| cut row | cover | holds? yes/no | why, with lines |. Do not edit the audit files; the
main window does. Read-only on the repo.
Return at most 300 words: rows checked, rows that fail, and the pattern behind them.
```
