---
name: ship
description: Takes one MR from a clean tree to ready: docs gate, body, push, CI, tracker re-check. Model-invocable; acts only on an explicit request from the user or conduct, which calls it at the draft and at ready.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# ship

Explicit request only (user or `conduct`), draft or ready. `<target>`: a work unit folder or a light-path ticket. Ids are for the rule trace.

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
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ci watch <head> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr ready <target> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" mr show <target> --repo <checkout> --home '${user_config.home}'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage ship --session ${CLAUDE_SESSION_ID} --docs <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Steps

1. `worklog start` (key: the folder or ticket file name). `ports`: `repo base` is the base; the `mr` port names the tool. `git status --short` not empty: stop, ask nothing. [PR1, OM11, PR14, PR4, AC-54]
2. `check pre-push`, before every push. [N3, AC-49] 0: go on. 2 with no `mr.md` at a draft's first push: go on; other 2: stop. 1 with `no Reviewed: line` or `no Verified: line`: stop, ask nothing. [AC-54, OM14] 1 with `is not the head being pushed`: `anomaly:review` delta since the last reviewed sha, one verify (`command verify`), record `<head>` (unit: `mr reviewed`, `mr verified`; light path: `ticket reviewed`, `ticket verified`), check again.
   Light path: build's `--no-ff` merge makes the head a merge commit, so the first run exits 1, both stale: delta review `<ticket tip>...<head>`, one verify, both `ticket` writes, check again.
3. Draft: `mr body <target> --draft`. [OM1] Ready gate: follow [DOCS-GATE.md](DOCS-GATE.md), which gives `<result>`; [CL4, AC-51] then `mr body <target> --docs-gate '<result>'` once (light path: no `--docs-gate`). [OM3] Show a `warning:` line (body over 2.5 KB); never hand-edit the body file. [PR11, D-23, OM4, CL2]
4. Push: a plain `git push -u origin <branch>`, never the base branch, never forced; a refused push is printed, not retried. No `origin`: no push. [PR13, PR15, CL1]
5. `mr put <target>` with the integration branch checked out: opens a draft MR, or replaces only the body. [N5]
6. Draft: `worklog add` (light path: no `--docs`); stop.
7. `ci watch <head>`: 0 go on ("no CI gate" if printed); 3 or 5: run again, twice at most, then stop; 1, 2, 4: stop, never green. [OM9]
8. Tracker re-check (read-only, `tracker` port): one line per AC added, removed or changed since the stories' `Gathered:` date; any such line stops the gate until the user answers. No tracker, no stories or unreadable: one line, skipped and why. [OM10, AC-56]
9. `mr ready`, `mr show` (skip both on the core default or with no `origin`: exit 2). The MR is the user's merge. [CL1, CL6]
10. One line each: offer `/anomaly:observe`, then `/clear`. [OM13, AC-57] `worklog add`.

## Body [PR5, PR8, PR9, OM5, N1, N2, N6]

`mr body` writes it from files: title under 70, Why first, a line per ticket, `n of m` ACs, Still open, Breaking, counts; empty sections left out; no commit id, table or trailer.

```
Title: feat(no-ticket): let customers repeat a bakery order

## Why
Customers retype the same bread order each week and want one tap to repeat it.

## What changed
- Order history: a Reorder button on each row.
- Cart: a reorder fills it.

## Tested
2 full suites, 3 reviewer passes. Docs gate: clean. no CI ran
```
