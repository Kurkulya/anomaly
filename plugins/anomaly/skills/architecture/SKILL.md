---
name: architecture
description: Audit the architecture of this repo in 7 areas against six principles; each area gets area findings, an area score, lock and "why"; ends in an interview, diagnose lines or the report. Use on "audit the architecture", "what is good and bad here".
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# architecture

Pass one reports 7 areas, with no theory block. Pass two
shows the fix per area and writes the locks as files. Nothing is implemented.

A **lock** is a guard that stops an area finding from coming back: an import or lint rule at error
level, or a failing test. Say "lock", never "guard rail".

**Scope.** Read-only on source. Writes only under `.anomaly/architecture-<YYYY-MM-DD>/research/`, plus
the exclude line of Setup 2. Never writes `decisions.md`, `stories.md`, tickets or ADRs.

Read first: [principles](reference/principles.md) and the stack profile in `reference/stacks/`.
Per area: [lesson-outline](reference/lesson-outline.md). Before pass two:
[pitfalls](reference/pitfalls.md).

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`. `<date>` is the run's `YYYY-MM-DD`; `<unit folder>` is `.anomaly/architecture-<date>/` in the audited repo.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start architecture-<date> architecture --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature architecture-<date> --stage architecture --session ${CLAUDE_SESSION_ID} --docs <unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Ground rules

- **Facts from git, never from the filesystem alone**: `git ls-files`, `git grep`,
  `git log`, repo scripts. Untracked docs are not repo debt.
- **Every claim carries `file:line` and a count.** Count first; show the command.
- **Import greps run twice**, alias and relative spelling, then union.
- **Check the artifact, not the intent.** Read the CI file, lint level, flag value and
  its age (`git log -S`), not the sentence about them.
- **State corrections openly**: "Correction: pass one said 3; the right number is 11."
- **Bulk reads**: `anomaly:facts` (`explore` role: model, effort if set) with exact paths and a ≤900-word cap. Never a
  root-wide search.

Every output file is `research/NN-<slug>.md` or a lock `NN-lock-<area>.<ext>`, `NN` the
next free two-digit number. Write with Write, never with shell redirection.

## Setup

1. Confirm the repo root and run `worklog start`; pick the stack profile from its files: `package.json` with
   react → `react-ts`; `pubspec.yaml` with a `flutter:` section → `flutter`; `go.mod` → `go`; `pyproject.toml`,
   `setup.py` or `*.py` → `python`. Several matches → audit each stack apart, with its own stack profile and counts and its stack in each area slug (`NN-area-1-<stack>-layers.md`). No match → draft a stack profile with the fields of a shipped
   one, show it, use it only after the user's yes, and save it only in `research/`.
2. Before any write, make sure the file at `git rev-parse --git-path info/exclude` has a `.anomaly/` line; add it with the Edit tool, or create the file with the Write tool if it is missing.
3. Gather the base facts (files per layer, commits, scripts, CI file) with the outline and stack profile commands into `NN-facts.md`.
4. Read `CLAUDE.md`, `docs/README.md`, `docs/adr/*.md`, `CONTEXT.md` if any. Note
   what the repo *says* about itself; areas 6 and 7 compare that with the artifact.
5. Re-run: continue in today's `architecture-<date>` folder at the next free `NN`.
   The delta uses the latest earlier `*pass-one-summary.md`, here or in an earlier folder.

## Pass one — the 7 areas

All 7 areas in order; each to `NN-area-<n>-<slug>.md`, same text in chat.
1 layers and dependency direction (1) · 2 module depth (2) · 3 state ownership
(3) · 4 side effects and platform adapters (4, 5) · 5 cohesion in the biggest feature (6) · 6 guards
on the five-rung ladder · 7 decision records (five docs checks, inline).

Area shape:

1. **Area findings**: each `file:line` + count + principle broken. Good things count: what
   is right and what locks it.
2. **Area score:** `N/5 — <one reason>`, from the rubric.
3. **Lock:** one line naming it.
4. **Why:** one sentence, with the named idea if any ("return, don't act", "a
   guard that warns is a comment").

### Area score rubric

| Area score | Meaning |
| --- | --- |
| 5 | No violation found; a rung 1 or 2 guard locks it. |
| 4 | A few isolated violations, or none but the guard is rung 3 or lower. |
| 3 | The rule holds in most places; violations sit in one area; no guard. |
| 2 | Violations in several layers or features; a competing pattern exists. |
| 1 | The rule is not followed; no place shows the good pattern. |

Write `NN-pass-one-summary.md`: a table: area, area score, headline count,
cheapest lock. With an earlier summary (step 5), add a table: area, old area score, new area score; with none, no
table. Ask: "Pass two now?" On a no, do the Hand-off from pass one: no lock files, no `Red command:` in diagnose lines.

## Pass two — the fix and the lock per area

Per area, `NN-fix-<n>-<slug>.md`, after its lock file when the area has an area finding and no
error-level guard yet, or no area finding and only a warn-level guard (its lock flips that guard to error).
An area at 5/5 says `Lock: already held by <file:line>`.

1. **One bad snippet** from this repo, ≤15 lines, with `file:line`.
2. **One good rewrite**, in a fenced block, not applied. Say "no behavior change" or name
   the change.
3. **The lock**, a file the user can apply: an import
   or lint rule at error level matching both import spellings, or a test that fails before
   the fix, passes after. A clear defect's lock is its failing test.
4. **Proposed work**, as bullets: what to change, how wide (call sites, files), and
   whether it is a wide refactor (expand → migrate → contract) or holds a bug (a separate
   fix, so the refactor keeps behaviour).

## Hand-off

Write `NN-summary.md`: one line per area (area score, headline count, cheapest lock); the
proposed order (cheapest lock first: dependency direction → seam edges → state → side
effects → cohesion → guards → records); each lock not tied to a clear defect as an "adopt lock X" choice; the
clear defects; the words with two meanings (pitfall 4); the research files.
Show it. Then `worklog add` (stage `architecture`, `--docs` the unit folder), also when nothing changes. End with the case that fits. An open choice needs a decision; a clear defect has
one obvious fix.

- **1 or more open choices:** one line, `/anomaly:interview Work unit architecture-<date>. Idea: act on the findings in .anomaly/architecture-<date>/research/<NN>-summary.md`.
  Interview reads only typed text, so the line names the summary file; it lists
  the defects too.
- **No open choice, 1 or more clear defects:** one line per defect, `/anomaly:diagnose <defect>. Red command: <command that runs research/<NN>-lock-<area>.<ext>>`.
- **Nothing to change:** stop at the report; no next-step line.
