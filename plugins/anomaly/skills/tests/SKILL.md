---
name: tests
description: Audit a repo's tests, on any stack through a stack profile, and report cuts, each with a cover proven by a break. Read-only. Use for "test audit", "audit the tests", "which tests can we cut", "is our test suite too big".
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# tests

One audit of one repo's tests, a one-off clean-up. The output is a report of proposed
cuts, each with a cover. No source in the repo changes. Cut candidates are not traced
back to build tickets. The cuts happen later, by the path the report ends with (Phase 5).

Read before each phase:

- [reference/classes.md](reference/classes.md): the topic map, classes, verdicts and the cover rule
- [reference/stacks/](reference/stacks/): the stack profiles
- [reference/grep-recipes.md](reference/grep-recipes.md): the shared recipes
- [reference/timing.md](reference/timing.md): timings and CPU load
- [reference/agent-briefs.md](reference/agent-briefs.md): scopes and the agent briefs
- [reference/outputs.md](reference/outputs.md): output files, break probes, report shape
- [reference/pitfalls.md](reference/pitfalls.md): the rule each past mistake taught

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`. `<date>` is the run's `YYYY-MM-DD`; `<unit folder>` is `.anomaly/test-audit-<date>/` in the audited repo.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start test-audit-<date> tests --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature test-audit-<date> --stage tests --session ${CLAUDE_SESSION_ID} --docs <unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Ground rules

- **Writes: two things only.** Files under `.anomaly/test-audit-<YYYY-MM-DD>/research/`,
  and one `.anomaly/` line in the git exclude file (Phase 0). No source edit, no install,
  no commit. Never write `decisions.md`, `stories.md` or tickets: the anomaly stages own them.
- **File names.** Each file in `research/` is `NN-<slug>.md`, with the next free two-digit
  number. The main window picks every number and puts it in each brief. Below, a file is
  named by its slug (`facts`, `audit-<scope>`, …). Reporter output, logs and status
  snapshots go to `research/evidence/`.
- **Test runs leave files.** After each test run, compare `git status --porcelain` with
  the Phase 0 snapshot. Any difference (`.snap`, `test-results/`, `playwright-report/`,
  `coverage/`, `.dart_tool/`) goes in the report. Never revert or clean it; tell the user.
- **The repo's docs own the rules.** Cite a rule by the `file:line` the topic map found;
  never restate it. A topic with no source says "no rule found"; never invent a rule.
- **Facts from git at one tip.** Every `file:line` is at the Phase 0 sha. Before each
  phase: `git rev-parse HEAD` must equal it, and `git status --porcelain
  --untracked-files=no` must match `evidence/status-0-tracked.txt`. If not, stop and
  ask, or read files with `git show <sha>:<path>`. Untracked test outputs do not stop the
  run; they go in `timings`.
- **No cut without a cover** (rule in `classes.md`). No cover → a `keep` or `rewrite` verdict.
- **Every timing carries its CPU load.** A number a later step needs is marked
  `re-time isolated`.
- **Every count comes with the command that made it.**

## Phase 0 — setup

1. Find the repo root and run `worklog start`; find the stack profile in `reference/stacks/` by the repo's files:
   `package.json` with vitest/playwright → `fe`; `pubspec.yaml` with flutter_test/patrol →
   `flutter`; `test*.py` or pytest config → `python`; `go.mod` → `go`. Several stacks →
   audit each apart. No match → draft one from the runner config (the fields of a shipped
   stack profile), show it, use it only after the user's yes, and save it only in `research/`.
2. Resolve the topic map (`classes.md`): for each topic, search the repo's own docs
   (`CLAUDE.md`, `AGENTS.md`, `docs/`) and note the rule's `file:line`. No repo rule → the
   fallback the map names. No fallback → "no rule found".
3. Find the repo's e2e reason list (`grep-recipes.md` § Shared). None → say so;
   the topic map's fallback applies.
4. `mkdir -p .anomaly/test-audit-<date>/research/evidence`. If the file at
   `git rev-parse --git-path info/exclude` has no `.anomaly/` line, add one with the Edit
   tool, or create the file with the Write tool if it is missing. Use that command for the path: in a worktree `.git` is a file.
5. Save `git status --porcelain` to `evidence/status-0.txt`, and the same with
   `--untracked-files=no` to `evidence/status-0-tracked.txt`.
6. Write `facts`: tip sha, branch, stack profile, test files and static test count per top
   folder, the resolved topic map, reason-list location, CI file, hook files, install
   freshness.

## Phase 1 — scopes

Size by the test-file count (the stack profile's "Find tests"):

| Test files | Who audits |
|---|---|
| under 60 | the main session alone, no agents |
| 60–300 | 2 value agents; the main session does the runtime scope after them |
| over 300 | 3–5 value scopes of about 80–150 files, plus one runtime scope |

Write `scopes`; the split rules are in `agent-briefs.md`.

## Phase 2 — audit agents

When agents run: all value agents first, in one message. The runtime agent goes alone,
after every value agent has returned, because their greps add CPU load.

Each agent is `anomaly:survey` (`survey` role: model, effort if set), with its brief from
`agent-briefs.md` and the tip sha; the brief holds its exact output path and word limit. A
value agent writes `audit-<scope>` and returns a digest of at most 400 words. The runtime
agent writes `timings`, with the load next to every number.

## Phase 3 — cover check

Dispatch one fresh `anomaly:survey` agent (`survey` role: model, effort if set) with the
cover-check brief, which holds its exact output path and word limit (under 60 files, the
main session does it). It re-reads every cover and writes `covers-check` only. Then the
main window edits the `audit-<scope>` tables: each failed row gets a `keep` or `rewrite` verdict,
with a correction line (`outputs.md`).

## Phase 4 — break probes

Steps and table: `outputs.md` § Break probes. Ask the user once: break probes will run in
a scratchpad copy of the tip. After the yes, each
cut candidate gets 1 to 3 breaks (a break: one deliberate code change; a break probe: one
run against one break), written by hand. Use the repo's mutation tool only when
it is already installed; never install one. If the user says no, each cut candidate
that needs a break probe becomes `open`, reason "not probed", and goes to the report's Open questions.

- A cut needs its named cover to fail on the break. A test that catches none of its target's
  breaks is `cut` when its named cover fails, and `rewrite` (reason "useless") only when no
  named cover fails. A dev-only tooling cut needs its `file:line` proof instead of a break probe
  (`outputs.md`).
- Record the file and line of each break and the change made.

## Phase 5 — report and next step

Write `report` in the shape from `outputs.md`. Every judgement call, disagreement between
agents, missing reason-list entry and "no rule found" topic goes in its Open questions,
with a recommended answer. Do not ask them here; the interview stage does.

Run `worklog add` (stage `tests`, `--docs` the unit folder), also when nothing changes.
End the chat reply by what the report holds, and never run the line:

- 1 or more open choices → an `/anomaly:interview` line (shape in `outputs.md`) that
  names the summary file (the report). The summary also lists any clear defects.
- No open choice and 1 or more clear defects → one `/anomaly:diagnose` line per defect.
- Nothing to change → the reply ends at the report, with no next-step line.
