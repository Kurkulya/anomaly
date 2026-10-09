---
name: slice
description: Slash-only skill, started as /anomaly:slice. Cuts stories.md and decisions.md into self-contained tickets after the owner approves a numbered list, checks the set and ends at the tickets gate.
disable-model-invocation: true
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# slice

Started by the user as `/anomaly:slice <work unit>`; the model never starts it. Ids in brackets are for the rule trace. The ticket shape, the status words and the next-step line are in [formats.md](../../docs/formats.md); the stage end and `/clear` are in [boundaries.md](../../docs/boundaries.md). Repeat neither. The issue source and the tracker are read only; a page the user wants there is handed over as markdown, never written. [N11, T15]

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <work unit> slice --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" check slice <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket gate <ticket> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" log add <work unit folder> --stage slice '<text>' --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <work unit> --stage slice --session ${CLAUDE_SESSION_ID} --docs <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Before it writes

1. The argument is the work unit key. Read `.anomaly/<work unit>/stories.md` and `decisions.md` in full. No `stories.md`: stop and offer `/anomaly:specify <work unit>`. [T3] `worklog start`, then `ports`. Make sure `.anomaly/` is in `.git/info/exclude`. [C8]
2. Read the glossary file (default `CONTEXT.md`) and the ADRs of every branch, and use their words. [T4] Read the code through the `gather` port; one search per ticket shows whether it is already built. [Q6]
3. When the stories or decisions list the rows of a ledger (rules, seams, migrations), make the row → ticket table first, one owning ticket per row. [N5]
4. Draft the slices.
   - A prefactor or a spike goes first; the tickets that need it are blocked by it. [T5]
   - Each slice is vertical, through every layer, and checkable alone. [T6, T7]
   - A wide refactor: expand, migrate in batches, contract. [T10]
   - A docs repo: a slice is one complete change with its `Tests:` check. [N10]
5. Show a numbered list: title, blocked by, covers, tests. Ask about the size, the edges, and what to merge or split. Iterate until the user approves it; nothing is written before the approval. [T11]

## Write the tickets

Write each `tickets/NN-slug.md` with Write, from 01, in dependency order, in the shape of [formats.md](../../docs/formats.md), the key line included (the line the `key_line` port names). [T12, T16, C1]

- Self-contained: `build` reads only the ticket and `seams.md`. Copy every AC it covers, verbatim, and the `D-n` lines it needs. [N1, C4]
- Every `Covers:` AC has a `Tests:` level; every story AC is in some `Covers:`. [N2, P5]
- No line numbers: write no `path:NN` anchor outside a copied `- D-n:` line and fenced code. Use paths and symbols. A copied decision keeps its `Source:` word for word, `file:line` included. [N3, T17]
- A prototype snippet that encodes a decision may go in fenced code. [T18]
- `Status:` only `ready-for-agent`, or `ready-for-human` with its reason, for work only a person can do. [Q1, Q4, Q10]
- Add `Gate:` when a date or an outside step blocks the ticket. [N6]
- A ticket that changes a rule gets `Restates:`, the files that repeat it, found by grep. [N4]
- `Out of scope:` names the sibling ticket that owns the next thing. [Q13]
- Each `T-n` term line and each ADR draft (`.anomaly/<work unit>/adr/…`, written by `specify`) lands in the first ticket that needs it, named in its `Touches:`. [AC-23]
- It never writes the lines formats.md lists as written later (`Result:` and the rest). [T16]
- A ticket over 5 KB is a warning: suggest a split. [N7]

## The checks and the gate

1. `check slice`. Exit 1 stops the skill before the review: fix each error line. `warning:` lines go into the handoff. [N8]
2. Run `anomaly:review` in mode `tickets` with the work unit folder. [N8]
3. A Blocker stops the skill before it offers the next build step. List every other finding in the handoff. After a fix, ask `anomaly:review` for a delta round with the work unit folder, and say when this is the session's last review so `lens tally sum` runs.

## After the gate

1. `log add`, stage `slice`: one line per gate result (the `check slice` result, the review verdict). `log.md` lines carry no cost numbers. [G17]
2. `worklog add`, stage `slice`. [N9]
3. Run `ticket gate` on the tickets in order. Offer `/anomaly:build <work unit> <NN>` for the first ticket with no open blocker; one ticket per session. [C6]
4. Offer `/clear` once, as boundaries.md says; never run it.
