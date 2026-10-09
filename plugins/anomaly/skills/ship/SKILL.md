---
name: ship
description: Takes one MR from a clean tree to ready: docs gate, body, push, CI, tracker re-check. Model-invocable; acts only on an explicit request from the user or conduct (draft and ready).
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# ship

Explicit request only (user or `conduct`), draft or ready. `<target>`: a work unit folder or a light-path ticket.

## The CLI calls

One plain command each, exactly this form: no chains, inline code or redirection. No `python`: try `python3`. `<checkout>`: the integration branch's (light path: the start branch's). [N12]

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <key> ship --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" check pre-push <target> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr reviewed <work unit folder> <head> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr verified <work unit folder> <head> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket reviewed <ticket> <head> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket verified <ticket> <head> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" docs scan <base>...<head> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr body <target> --draft --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr body <target> --docs-gate '<result>' --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr put <target> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket amend <ticket> '<waiver>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ci watch <head> --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr ready <target> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr show <target> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage ship --session ${CLAUDE_SESSION_ID} --docs <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Steps

1. `worklog start` (key: the unit folder name, or the ticket file name without `.md`). `ports`: `repo base` is the base. `git -C <checkout> status --short` not empty: stop, no question. [PR1, OM11, PR14, PR4, AC-54]
2. `check pre-push`, before every push. [N3, AC-49] 0: go on. 2 with no `mr.md` at a draft's first push: go on; other 2: stop. 1 with `no Reviewed: line` or `no Verified: line`: stop, no question. [AC-54, OM14] 1 with `is not the head being pushed`: `anomaly:review` delta since the last reviewed sha and one verify (`command verify`); with no open Blocker or High and a green verify, record `<head>` (unit: `mr reviewed`, `mr verified`; light path: `ticket reviewed`, `ticket verified`) and check again, else stop. Any other 1: stop.
   Light path: build's `--no-ff` merge makes the head a merge commit: the first run exits 1, both stale. Do the same, delta `<ticket tip>...<head>`.
3. Draft: `mr body <target> --draft`. [OM1] Ready gate: follow [DOCS-GATE.md](DOCS-GATE.md) (docs gate, CI, tracker); it gives `<result>`. [CL4, AC-51] Then `mr body <target> --docs-gate '<result>'` (light path: no `--docs-gate`). [OM3] (pending verdict, 2026-11-05) Show a `warning:` line (body over 2.5 KB); never edit the body file. [PR11, D-23, OM4, CL2]
4. Push: a plain `git -C <checkout> push -u origin <branch>`, never the base or the default branch, never forced; a refused push is printed, not retried. No `origin`: no push. [PR13, PR15, CL1]
5. `mr put <target>` with the integration branch checked out: opens a draft MR, or replaces only the body. [N5]
6. Draft: `worklog add` (light path: no `--docs`), stop.
7. Ready, after `mr put`: the CI wait, then the tracker re-check, both in the file of step 3. [OM9, OM10, AC-56]
8. `mr ready`, `mr show` (skip both on the core default or with no `origin`: exit 2). The MR is the user's merge. [CL1, CL6]
9. One line each: offer `/anomaly:observe`, then `/clear`. [OM13, AC-57] `worklog add`.

`mr body` owns the body shape. [PR5, PR8, PR9, OM5, N1, N2, N6] A unit's:

```
Title: feat(no-ticket): Let customers repeat a bakery order

## Why

Customers retype the same bread order each week and want one tap to repeat it.

## What changed

- a Reorder button on each order history row

## Acceptance criteria

2 of 3 covered; missing: AC-3

## Still open

- the cart total is not updated (ticket 01)

## Tested

- Over the merged tickets: full suites 1, type-checks 1, reviewer passes 2, High 0
- Docs gate: clean
- no CI ran

## How to review

Review the merge commits one at a time, in order: 01-reorder-button.
```
