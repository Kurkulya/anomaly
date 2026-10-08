---
name: build
description: Takes one ticket from a red acceptance test to a reviewed, verified --no-ff merge into the integration branch. Model-invocable; acts only on an explicit request from the user or conduct.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# build

Explicit request only (user or `conduct`). [I35] Read only the ticket and `seams.md`, never the spec or stories file. [AC-86]

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes, where nothing runs; write a ' as ’. No `python`: try `python3`. `<checkout>` is the integration branch's checkout. Every `.scratch` or `.anomaly` edit goes through the CLI, never Write, Edit or the shell, except the `<key>-repro` script `diagnose` writes. [N12, I39]

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <work-unit key> build --ticket <NN> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <a repo checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket adhoc '<task>' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket gate <ticket>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket set-status <ticket> in-progress
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket red <ticket> <sha> <test path> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket verified <ticket> <tip sha> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ci log <integration tip> --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" check pre-merge <ticket> --head <ticket tip> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" seams prune <seams.md> --merge <merge sha> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" seams add <seams.md> --name '<seam>' --owner '<owner>' --replaces '<old way>' --ticket <NN>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket result <ticket> --branch <ticket branch> --merge <merge sha> --open '<items>' --suites <n> --type-checks <n> --reviewer-passes <n> --high <n> --fix-rounds <n> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <work-unit key> --stage build --session ${CLAUDE_SESSION_ID} --docs <work-unit folder> --ticket <NN> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Start

1. Resolve "build 01" to `tickets/01-*.md` in `.anomaly/<work unit>/`, or `issues/01-*.md` in `.scratch/<feature>/`; or take a path. Work-unit key = that folder's name. `worklog start`. [I1]
2. `ports`. If its `commit` or `branch` value holds `<key>`, use the ticket key from the key line (`ticket show`); stop if missing or a placeholder. [I2]
3. `ticket gate`: exit 1 blocked, 2 error: stop. Already `Status: done`: stop. Resume: `git log --first-parent --format=%H%x20%s <integration>` (step 6) lists `merge <NN-slug>`: skip to the Close with that sha, after Merge step 5 if the branch exists. Skip a step whose ticket line exists (`Red:`; `Reviewed:`, `Verified:` only if it names the current ticket tip). [I5, I6]
4. Under-specified ticket: stop and ask; never widen the scope. [I37] Stack and size come from the ticket, else ask. [K2]
5. `ticket set-status in-progress`. [I7]
6. Integration branch = `Base:` from `ticket show`, else the `branch` pattern with the work-unit key as slug. Create it once: fetch, then branch from `origin/<repo base>` (no origin: the local base). [I3, I4]
7. Ticket branch = the `branch` pattern with the ticket's slug, from the integration tip; if it exists, `git switch` to it. [I6] Never commit on the base or the integration branch. [I8]

## Light path: a free-text task [N8, N9, AC-39]

Start as above, but:
1. `ticket adhoc` prints the ticket's path. Work-unit key = that file name without `.md`. `worklog start`/`add` take no `--ticket` or `--docs`. Resume by that path.
2. A `branch` or `commit` value that holds `<key>`: ask the user; never guess. [I2]
3. Start branch = the current head's branch; read it for the integration branch, `<integration>` and `<checkout>` below (no step 6). Detached head, the head on the base branch, or (resuming) not on the start branch: ask the user. [I8] The ticket-branch slug and the merge subject use the adhoc file stem.
4. Then Red first, Implement and the Shared close, with a combined-mode review and no `seams prune` or `seams add`.

## Red first, always [N7, AC-32]

1. Dispatch the `test_writer` port for the stack, model `model implement`; the core default's brief is [TEST-WRITER.md](TEST-WRITER.md).
2. Run it; confirm red for the right reason (a missing feature).
3. Commit it alone, then `ticket red <sha> <path>`.

Docs-only ticket: no red step; `ticket red --changed '<why>'`. A later test-file change needs `ticket red --changed '<reason>'` first.

## Implement [I10-I14]

Dispatch the `implementer` port for the stack with [BRIEFS.md](BRIEFS.md) filled, model `model implement`. In a worktree also follow [WORKTREE.md](WORKTREE.md) and pass it on. Follow-ups, and resuming a stopped agent at once: SendMessage to the same agent. An "interim" notice: check the branch. [N3]

## Shared close

Review → one verify → CI check → merge → close. `conduct`'s parallel path enters here with a branch. [P7]

**Review** [I20, I21]. `anomaly:review` in ticket mode (combined if docs-only) on `<integration>...<ticket tip>`, with its inputs, the open tickets calling this code, and "last review of the session" when so. The same implementer fixes Blocker and High, then a delta round, until none is open.

**Verify**, after the last review fix (pending verdict, I15). Each step that applies:
1. The agent's touched tests.
2. One full verify: `command verify`, no changed-only selection, in the foreground, even after agent green. [I16, I18]
3. `Tests:` says e2e: `command e2e` on the area specs plus `--only-changed`; full e2e only in CI. [I17]
4. `Tests:` says UI: the `ui_check` port, `browse` model role; the core default's brief is [UI-CHECK.md](UI-CHECK.md), loaded only then. Pass it the `app` lines of `ports`. [N16, I27]
5. The ticket asks: one real-data probe on a copy. [N2]

No `Tests:` line: 1-2, 3 if the area has e2e specs, 4 for a UI ticket. [N10] Failure only in untouched files: re-run them alone once; green = a flake for `--open`, red = real (pending verdict, I19). A real failure: the same agent fixes it, a delta round, verify again. Then `ticket verified`.

**CI check** [I29, O20, O21]. `ci log` on the integration tip. Exit 0: merge (say "no CI gate" if printed); 1: stop; 3 running or 5 no pipeline: merge, say so; 2 or 4: stop, report, never green.

**Merge** [I30, P8, P9, I31], on the integration branch:
1. `check pre-merge`. Any failed line or exit 2: do not merge.
2. `git merge --no-ff -F <msg file> <ticket branch>`, subject `chore(<scope>): merge <NN-slug>`.
3. Conflict: `git merge --abort`; the same agent merges the integration tip into its branch; then verify, the review's conflict-merge round (name the conflicted files) and `ticket verified` on the new tip; back to 1.
4. Lockfile changed: name each new dependency to the user, then `command install`. Codegen inputs changed: `command codegen` (pending verdict, I38).
5. `git branch -d <ticket branch>`. Never push.

**Close** [I32-I34, N9], seams pending verdict (I34):
1. `seams prune`. An `ambiguous:` line: ask the user.
2. `seams add` per new single-owner seam, after grepping for a second owner; owner as `` `<path>` (`name`, …) ``.
3. `ticket result` with `--branch` and every count, 0 included (resuming: only the counts you know); `--open` lists flakes and kept findings, if any.
4. `worklog add`.

Only these ticket lines and `seams.md` change. [O47]

## Commits [I28, P14, P16, O24]

The `commit` port format, atomic, no AI trailers. Write each commit or merge message with the Write tool to `msg-<NN>-<n>.txt` (light path: the adhoc stem for `<NN>`) in the session scratchpad, then `-F <file>`. Never `--no-verify`.
