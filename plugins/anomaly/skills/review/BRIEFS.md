# Reviewer briefs

Loaded at dispatch; the last section is for the main window after each round. Fill one brief per agent; leave out a line that has no value. Never paste an org name or path into core text: it comes from the ports line.

## Every agent

- Mode: <mode>. Range: <range>, explicit; ignore tip merges. Tip: <tip sha>.
- Main checkout: <path>. Read files at the tip with `git show <tip>:<path>`.
- Seam ledgers: every `.scratch/*/seams.md` and `.anomaly/*/seams.md`. [R6, I26]
- A CI log is read only through the CLI's `ci log`, never by piping the CI tool's output.
- Word limit: 500 words (delta: 250).

## anomaly:code

- Repo docs, and the org conventions sections for the touched areas only. [R5, I23]
- Combined mode: also apply the ticket-mode checklist of <the `agents/feature.md` path in SKILL.md § When an agent's read fails> to <ticket path or task text>. [I22]

## anomaly:feature

- Ticket: <ticket path>, its dated `Amended` lines count as later decisions. Spec: <spec path>. Docs drift is in scope. [R7, I24]
- Known items the implementer reported: <items>. [R7]
- Ticket mode: the open tickets that will call the reviewed code: <paths>. [X1]
- No-behaviour-change ticket (main window first clones the main checkout at the base into the session scratchpad; paste only what follows): base copy at <that path>, or propose the byte-diff commands. [X2]
- Cumulative mode: the spec is `spec.md`, else `stories.md` + `decisions.md`; one keep / rewrite / delete verdict per characterization test file. [O36, O37]
- Rules mode: brief <path>, new SKILL.md <path> and its extra docs, budgets <bytes>. [N7]
- Check every "X owns Y" deferral against X's own text. [N1]

## anomaly:security

- Matched risk areas and files: the `<area>: <path>` lines as `risk` printed them. [N4]
- Cumulative mode: all ten categories.

## anomaly:plan

- Mode: spec or tickets. Work-unit folder: <path>, in place of Range and Tip. Main checkout: <path>. Ports line, word limit.

## An org reviewer

- The same range and tip as the core agents; its findings go under its own heading and its own lens.

## Delta round (SendMessage to the same agent)

- Range <last reviewed sha>..HEAD, tip merges ignored. (a) Is each earlier finding fixed? (b) The new code: <names>. (c) New problems. [R8]

## Commands a reviewer proposes (main window, after a round) [X2, N15]

A reviewer proposes a mutation probe, or byte-diff commands when it has no base copy, as plain commands and never runs them. Show each to the user and run it only after a yes, on a scratchpad copy (of the tip; for a byte diff, of the base and of the tip), never in the worktree; send the result back to that reviewer's finding.
