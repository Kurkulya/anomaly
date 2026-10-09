---
name: conduct
description: Drives every ticket of one work unit through anomaly:build on one integration branch, then to the ready gate. Model-invocable; acts only on an explicit request from the user.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# conduct

Explicit request only. [AC-15] One work unit = one branch = one MR. [O2] State lives in ticket files and git: resume from them. [O1] The tracker is read-only. [O46] A user change to a ticket that is not done is a `ticket amend`; a changed AC or decision: `ticket amend` with `--after` on `<unit>/stories.md` or `<unit>/decisions.md`, no hand edit. [O51, N5]

`<unit>`: the unit folder by absolute path in the main checkout (`.anomaly/<unit>/`); it is not in the worktree. `<main>`: the main checkout. `<wt>`: the integration worktree.

## The CLI calls

One plain command each, exactly this form: no chains, inline code, heredoc or redirection. Free text in single quotes; write a ' as ’. No `python`: try `python3`. [N12]

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <key> conduct --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <main>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" frontier <unit>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket show <ticket> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket gate <ticket>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket amend <ticket> '<claim and what is true now>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket amend <file> --after <AC-n> '<text>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" log add <unit> --stage conduct '<event>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ci watch <tip> --max-min 30 --home '${user_config.home}' --repo <wt>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage conduct --session ${CLAUDE_SESSION_ID} --docs <unit> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" conduct status <unit> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr reviewed <unit> <tip> --repo <wt>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr verified <unit> <tip> --repo <wt>
```

## Start

1. `worklog start` (key: the unit folder name). `ports`: `repo base` is the base; `<base>` is `origin/<repo base>` when `repo name` has source `origin` (a remote exists), else `<repo base>`. No remote: no push, MR or CI step, no override question; `ports` alone decides. [N4, N6, AC-24]
2. `frontier`: show its `warning:` lines. [O3] Exit 1: name the blockers, stop. [O48, AC-14] Exit 2: print the `anomaly:` line, stop. A finished line, or only "waits for a person" or "is not ready-for-agent" lines: name those, step 3, then Finish. An in-progress ticket: ask the user to confirm no other session runs it, then resume it. [O4, O12, AC-12]
3. Integration branch: the first ticket's `Base:` (`ticket show`), else the `branch` port with the unit key as slug. A key placeholder in the port value is the `<ticket key>` from the key line of `ticket show`; stop if it is missing or a placeholder. Once: `git -C <main> worktree add <wt> -b <branch> <start>`; `<wt>` beside `<main>`, named `<repo name>-<key>`; `<start>` is `<base>` after `git fetch` (no remote: the local base). Existing: reuse it. `<main>` stays on the base branch. Then `command install` from `ports`, once, in `<wt>`. [O5, O6, O7, AC-13]

## Plan, before each wave

4. The wave is the startable tickets in frontier order. `ticket gate` each: exit 0 runs; 1 waits, never built ahead; 2 prints the `anomaly:` line, stop. A held ticket becomes a `-2` part (its `Base:`) only on the user's word, as a `ticket amend` line. [AC-26, D-20, O33]
5. One agent on `model explore` checks the wave's code claims and returns only the claims that are false or moved, one line each. [O14, L3, AC-16] A long check: say it takes minutes first; a stated tool limit cites its source and a workaround. [N7]
6. Each such claim: `ticket amend`, no `--after`. A claim whose fix changes the scope goes to the user; the wave waits. [O14, AC-17]
7. Research the wave needs: an agent writes `<unit>/research/NN-slug.md`; `ticket amend <ticket> 'research notes: <path>'` puts the path, not the text, on the ticket build reads. [O13, D-6, AC-20]
8. Show the plan: one line per ticket, `<NN-slug> | touches: <paths of its Touches: line>`. [N7, AC-18] Two or more tickets whose touches are pairwise disjoint: ask once, parallel or sequential; only a parallel pick reads PARALLEL.md. [O44, AC-19] Any other wave is sequential and starts without a question. [N1]

## Run

9. One chapter per wave (`mark_chapter`, if the tool exists). [O18] `log add` `wave <n>: <tickets>`, n = the `wave` lines of `log.md` plus 1. [O16] `anomaly:build` once per ticket in frontier order: the ticket's absolute path, `<wt>` as the checkout, "last review: no" (a one-ticket unit: "yes"). A stop of build stops the wave. [AC-21, C1, Amended 2026-10-09]
10. With a remote, after each merge: a plain `git -C <wt> push -u origin <branch>`, never the base or the default branch, never forced; a refused push is printed, not retried. Then `log add` `push <sha>`. `check pre-push` is skipped: the gate lines are written at step 19. [O19, AC-23, Amended 2026-10-09] With no `push` line before this one in `log.md`: `anomaly:ship` for the draft MR, with `<wt>` as the checkout and the integration branch checked out. [O22, AC-25]
11. `ci` port off its core default: after each push, `ci watch <tip> --max-min 30` in the background. Never hold the report for it; its result is a later event. Exit 3: run it again; 5: once more, still 5: say so, go on; 1, 2 or 4: a red tip. [O20, O28, AC-23]

## Report

12. `log add`: `merge <NN-slug>` and `stop <why>`, one line each; no cost numbers. [AC-28]
13. `conduct status`; on its exit 2 "no lines for work unit" only: `worklog add`, then it again. [N6, AC-32] Print its five lines. With an MR, one more line: `MR size: <n> changed lines`, n = insertions + deletions of `git -C <wt> diff --shortstat <base>...HEAD`, never a question; without one, nothing about size. [N2, N3, AC-29]

## Go on or stop

14. A sequential wave with no open decision and a tip that is not red: next wave. Stop for a parallel pick, a scope change, a red tip, the ready gate. At a stop, offer the next steps as buttons if a question tool exists, else as text. [C2, Amended 2026-10-09] While the user decides, prepare the next claim check. [N1, O44, O43, AC-30] Every stop of a run (a blocker, an `anomaly:` line, a red tip, a scope change, a failed verify) first writes `worklog add` if this run wrote none. [AC-32]
15. Under 200k tokens of context: same window. Past it: stop after the report and offer a fresh session. [N13, L4, AC-31]

## Chip mode

16. Fill KICKOFF.md (unit folder, branch, `<wt>`, base, last wave, next tickets, open decisions). Desktop app: a chip (`spawn_task`) with the text; plain CLI: print it. Never `/clear`. [O11, K1, AC-31, AC-60]

## Finish: `frontier` says the unit is finished

17. `anomaly:review` cumulative on `<base>...<branch>` in `<wt>`, "last review: yes". One ticket: skip. [O36c, AC-38]
18. One fix branch off the tip (`branch` port, slug `<key>-fixes`), the `implementer` port: every fix, and every open Low and Nit whose fix needs no decision; list the others to the user. Merge `--no-ff`; the message goes through a scratchpad file and `-F`. [O38, N9, AC-39]
19. One full `command verify` in `<wt>`, foreground; the `ui_check` port (`browse` model, the `app` lines) for UI ACs. With no Blocker or High open and green: `mr reviewed`, `mr verified` on the tip; else stop and report. [O39, AC-40]
20. `anomaly:ship` for the ready gate, with the integration branch checked out in `<wt>`; list every proof that cannot run here to the user in chat. This run wrote no `worklog add` yet: write it now. Stop: ship offers `/anomaly:observe`. [O41, N15, O42, AC-32, AC-41]
