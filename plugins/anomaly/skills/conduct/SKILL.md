---
name: conduct
description: Drives every ticket of one work unit through anomaly:build on one integration branch, then to the ready gate. Model-invocable; acts only on an explicit request from the user.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# conduct

Explicit request only. [AC-15] One work unit = one branch = one MR, none per ticket. [O2] State lives in ticket files and git: resume from them. [O1] The tracker is read-only. [O46] A user change to a ticket that is not done is a `ticket amend`. [O51]

`<unit>`: the unit folder by absolute path in the main checkout (`.anomaly/<unit>/`, or `.scratch/<feature>/`); it is not in the worktree. `<main>`: the main checkout. `<wt>`: the integration worktree.

## The CLI calls

One plain command each, exactly this form: no chains, inline code, heredoc or redirection. Free text in single quotes; write a ' as ’. No `python`: try `python3`. [N12]

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <key> conduct --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <main>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" frontier <unit>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket show <ticket>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket gate <ticket>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket amend <ticket> '<claim and what is true now>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" log add <unit> --stage conduct '<event>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ci watch <tip> --home '${user_config.home}' --repo <wt>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage conduct --session ${CLAUDE_SESSION_ID} --docs <unit> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" conduct status <unit> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr reviewed <unit> <tip> --repo <wt>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr verified <unit> <tip> --repo <wt>
```

## Start

1. `worklog start` (key: the unit folder name). `ports`: `repo base` is the base; `repo name` with source `origin` means a remote exists. No remote: no push, MR or CI step and no override question; the `ports` lines alone decide. [N4, N6, AC-24]
2. `frontier`: show its `warning:` lines. [O3] Exit 1: name the blockers, stop. [O48, AC-14] Finished line: go to Finish. An in-progress ticket: ask the user to confirm no other session runs it, then resume it. [O4, O12, AC-12]
3. Integration branch: the first ticket's `Base:` (`ticket show`), else the `branch` port with the unit key as slug. Once: `git -C <main> worktree add <wt> -b <branch> <start>`; `<wt>` beside `<main>`, named `<repo name>-<key>`; `<start>` is `origin/<repo base>` after `git fetch` (no remote: the local base). Existing: reuse it. `<main>` stays on the base branch. Then `command install` from `ports`, once, in `<wt>`. [O5, O6, O7, AC-13]

## Plan, before each wave

4. The wave is the startable tickets in frontier order. `ticket gate` each: exit 0 runs; 1 waits, never built ahead. A held ticket becomes a `-2` part (its `Base:`) only on the user's word, as a `ticket amend` line. [AC-26, D-20, O33]
5. One agent on `model explore` checks the wave's code claims and returns only the claims that are false or moved, one line each, nothing else. [O14, L3, AC-16] A long check: say it takes minutes first; a stated tool limit cites its source and a workaround. [N7]
6. Each such claim: `ticket amend`, no `--after`. A claim whose fix changes the scope goes to the user; the wave waits. [O14, AC-17]
7. Research the wave needs: an agent writes `<unit>/research/NN-slug.md`; the build call gets the path, not the text. [O13, D-6, AC-20]
8. Show the plan: one line per ticket, `<NN-slug> | touches: <paths of its Touches: line>`. [N7, AC-18] A sequential wave starts without a question. [N1]

## Run

9. One chapter per wave (`mark_chapter`, if the tool exists). [O18] `anomaly:build` once per ticket in frontier order: the ticket's absolute path, `<wt>` as the checkout, the research path. A stop of build stops the wave. [AC-21]
10. With a remote, after each merge: `git -C <wt> push -u origin <branch>`, never forced, never the base branch; a refused push is printed, not retried. [O19, AC-23] The unit's first push, and `<unit>/mr.md` has no `MR:` line: `anomaly:ship` for the draft MR, with `<wt>` as the checkout and the integration branch checked out. [O22, AC-25]
11. `ci` port off its core default: after each push, `ci watch <tip>` in the background. Never hold the report for it; its result line becomes a later event. Exit 1, 2 or 4 is a red tip. [O20, O28, AC-23]

## Report

12. `log add`: one line per merge, push and stop; no cost numbers. The wave number is the `wave` lines of `log.md` plus 1. [O16, AC-28]
13. A run's first wave: `worklog add` before `conduct status`, which exits 2 without it. [N6, AC-32] Print the five lines of `conduct status`. With an MR, one more line: `MR size: <n> changed lines` from `git -C <wt> diff --shortstat <repo base>...HEAD`, never a question; without one, nothing about size. [N2, N3, AC-29]

## Go on or stop

14. A sequential wave with no open decision and a tip that is not red: next wave. Stop for a parallel pick, a scope change, a red tip, the ready gate. While the user decides, prepare the next claim check. [N1, O44, O43, AC-30]
15. Under 200k tokens of context: same window. Past it: stop after the report and offer a fresh session. [N13, L4, AC-31]

## Chip mode

16. Fill KICKOFF.md (unit folder, branch, `<wt>`, base, next tickets). Desktop app: a chip (`spawn_task`) with the text; plain CLI: print it. Never `/clear`. [O11, K1, AC-31, AC-60]

## Finish: `frontier` says the unit is finished

17. `anomaly:review` cumulative on `<repo base>...<branch>` in `<wt>`. One ticket: skip. [O36c, AC-38]
18. One fix branch off the tip (`branch` port, slug `<key>-fixes`), the `implementer` port: every fix, and every open Low and Nit whose fix needs no decision; list the others to the user. Merge `--no-ff`; the message goes through a scratchpad file and `-F`. [O38, N9, AC-39]
19. One full `command verify` in `<wt>`, foreground; the `ui_check` port (`browse` model, the `app` lines) for UI ACs. With no Blocker or High open and green: `mr reviewed`, `mr verified` on the tip. [O39, AC-40]
20. `anomaly:ship` for the ready gate, with the integration branch checked out in `<wt>`; hand it every proof that cannot run here as an accepted risk. Stop: ship offers `/anomaly:observe`. [O41, N15, O42, AC-41]
