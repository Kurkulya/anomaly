---
name: review
description: Reviews one diff in a named mode (ticket, delta, cumulative, combined or rules) by dispatching the anomaly reviewer agents, and returns their findings per axis. The build and conduct skills call it; the user may too.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# review

The machine review of each ticket; the one human review is the MR, owned by `conduct`. [O2] Findings go back to the caller, never to a report file in the repo. Ids in brackets are for the rule trace.

The caller passes: mode, range, reviewed checkout, work-unit key, ticket number, ticket path (or spec path or task text), the implementer's known items; for ticket mode, the open tickets that will call the reviewed code; for rules mode, the brief path and the new SKILL.md.

## The CLI calls

One plain command each, in exactly this form, none of: chains, inline code, a pipe into an interpreter, redirection. [N10, N11] No `python`: try `python3`. Leave out `--ticket` with no ticket number. Always pass `--revised`, 0 included.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <key> review --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --ticket <NN>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" risk <range> --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket reviewed <ticket> <head sha> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" lens tally add --session ${CLAUDE_SESSION_ID} --lens <lens> --accepted <n> --rejected <n> --revised <n> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage review --session ${CLAUDE_SESSION_ID} --mode <mode> --ticket <NN> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" lens tally sum --session ${CLAUDE_SESSION_ID} --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" observe apply --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --file <printed path>
```

## Modes

| Mode | Range | Agents | Security joins |
|---|---|---|---|
| ticket | `<integration>...<ticket tip>` | `anomaly:code` + `anomaly:feature` | when `risk` matches |
| delta | `<last reviewed sha>..HEAD`, tip merges ignored | only the agent whose Blocker or High was fixed, warm by SendMessage | only if its own High was fixed |
| cumulative | `<target>...<integration>`: always, whole branch, before the MR [N3] | code + feature + security | always |
| combined | ticket range, or light path `<start branch>...<ticket tip>` | one `anomaly:code` in combined mode | when `risk` matches |
| rules | brief + new SKILL.md | `anomaly:feature` in rules mode; it loads [rules-mode.md](rules-mode.md) itself [N7] | never |

A docs-only diff (no source, config, script or test file) uses combined mode. [I22] Ticket or combined mode, when the ticket's `Tests:` line (`ticket show`) names `rule trace <brief path> <SKILL.md path>` (SKILL.md in the checkout; brief absolute or relative to the main checkout), also dispatches `anomaly:feature` in rules mode on that pair, budgets from the brief; its High findings go back to the caller, its counts join the `feature` lens. No rule trace: reviewed as before. [AC-1]

## Steps

1. `worklog start`. Run `risk` on the range (error: unresolved range) and `git diff --name-only <range>` in the checkout (no files: empty diff). Rules mode skips both. Rules mode or a rule trace: check the brief and the SKILL.md exist. On any failure, stop before dispatch and tell the caller.
2. `ports`: `reviewers` lists the agents (the core three and each org reviewer). From `conventions`, load only the org sections for the touched areas, for `anomaly:code` only. [R5, I23] `model review` is every dispatch's model. [R1, N2]
3. Security joins when the first line of `risk` starts with `risk areas:`; its brief gets the `<area>: <path>` lines as printed. [N4]
4. Fill [BRIEFS.md](BRIEFS.md) per agent; send the first round in one message, in the background. [R1] Each agent file owns read-only git and the finding shape. [R2, I25, R3]
5. Present findings per axis, one heading per agent, as reported; never merge or re-rank across axes. [N6] An unverified finding is Medium at most; an unrun test outcome is never High. [R4, N8]
6. After each round run `git status --short` on the reviewed checkout and report files a reviewer left [X6]; show the user each command a reviewer proposes; run it only after a yes ([BRIEFS.md](BRIEFS.md), last section). Re-read a reviewer's `file:line` before it goes into a ticket line. [X7]
7. Only when no Blocker or High is open (in the rules pass too), `ticket reviewed` writes `Reviewed: <head sha>` (on the light path, in the adhoc ticket). [N12]
8. `worklog add` with the mode, once per round.
9. Once per agent, when done (after its last delta round, or its first if it had no Blocker or High): `lens tally add` under its lens (`code`, `feature`, `security`, or an org reviewer's adapter name), counts over all its rounds, 0/0 included. Accepted = fixed or kept as an `Open:` item; rejected = judged wrong, with one reason; revised = accepted, but fixed differently than proposed. [N5, N14]
10. Once, at the end of the session's last review (the caller says so): `lens tally sum`, then `observe apply --file <printed path>`; a lens already applied in the session is skipped, so a later run is lost.

## Delta rounds [R8, R9]

On the caller's request, after every fix round that touches source or a rule trace's SKILL.md (delta row). A clean agent is done. The fix loop belongs to `build`. On a rule trace ticket, the delta round also reruns the rules pass on the fixed SKILL.md (rules mode has no diff range) while it has an open High.

A conflict-merge round (the caller merged the integration tip into the ticket branch): `anomaly:code` warm by SendMessage on `<old tip>..<new tip>`, naming the conflicted files, whose merge resolution it reviews; the tip-merge rule does not apply.

Every delta and conflict-merge round: `worklog start` before its dispatch, `worklog add --mode delta` after. [N18]

## When an agent's read fails

Keep no copy here; SendMessage the one copy to the same agent:

- `anomaly:code` in combined mode, `${CLAUDE_PLUGIN_ROOT}/agents/feature.md`: send its Ticket-mode checklist and Severity sections.
- `anomaly:feature` in rules mode, `${CLAUDE_PLUGIN_ROOT}/skills/review/rules-mode.md`: send that file.

`build` dispatches the UI walkthrough (`ui_check` port, `browse` model role). [R10, R11, N13]
