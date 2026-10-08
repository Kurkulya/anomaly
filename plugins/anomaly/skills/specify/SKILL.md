---
name: specify
description: Slash-only skill, started as /anomaly:specify. Turns the interview's decisions into the stories.md the owner reads, adds cited D-n facts, drafts agreed ADRs, and ends at the spec gate.
disable-model-invocation: true
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# specify

Started by the user as `/anomaly:specify <work unit>`; the model never starts it. Ids in brackets are for the rule trace. Shapes of `stories.md`, `D-n`, `log.md` and the ADR front block are in [formats.md](../../docs/formats.md); the stage end, the next-step line and `/clear` are in [boundaries.md](../../docs/boundaries.md). Repeat neither. This skill writes no code, makes no commit and writes nothing to a tracker (read only); a page the user wants there is handed over as markdown. [C14, C15]

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <work unit> specify --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" check stories <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" log add <work unit folder> --stage specify '<text>' --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" lens tally add --session ${CLAUDE_SESSION_ID} --lens interview --accepted <n> --rejected <n> --revised <n> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <work unit> --stage specify --session ${CLAUDE_SESSION_ID} --docs <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Before it writes

1. The argument is the work unit key. Read `.anomaly/<work unit>/decisions.md`; with none, step 4 runs the `gather` port for every fact. [G27]
2. Any `Open:` item in `decisions.md`: stop before it writes anything. Name each item, send the user back to `/anomaly:interview`, and write no `stories.md`, no `log.md` line, no ADR, and run no review. No open question reaches the gate.
3. `worklog start`, then `ports`. Read the glossary file (default `CONTEXT.md`) and the ADRs of every branch with Glob and Read, never from memory. [C20, C21] Make sure `.anomaly/` is in `.git/info/exclude`. [C17]
4. A fact a story needs and `decisions.md` lacks: run the `gather` port (repo code and docs; adapters add tracker and backend lookups). A failed lookup is reported, never guessed. [JC2] Tracker lookups happen here only, none after. [C11] A long source page is summarized with a link; source ACs are kept verbatim or marked `not specified`. [JC4, JC5]
5. A re-run reads the existing `stories.md` and extends it. [US2] A gap is one question to the user, not a round. [TS1]

## Stories

Write `.anomaly/<work unit>/stories.md` in the shape of [formats.md](../../docs/formats.md): Sources with the Gathered date, Why, Rules for all stories (a behaviour that holds everywhere is said once there [US10]), numbered stories, an Out of scope list. [C2, C3]

- One story per capability, in journey order. [TS9, FC6]
- AC ids are continuous from AC-1 across all stories, never renumbered (formats.md). [C5]
- Source criteria first and verbatim; the skill's own ACs after them, one testable sentence each, no Given/When/Then, real error paths and not only the happy path. [C4, US13-17]
- A changed or withdrawn AC follows the amend rule in formats.md. [N8]
- Every Out of scope line names an owner that holds the item: another unit, ticket or ADR, not the deferring `D-n`; if none is known, ask the user who owns it. [N5]
- On the 6 KB warning, suggest a split. [US19]

Example, in a made-up domain:

```
# Seed swap
Sources: swap-rules page, council notes · Gathered: 2026-03-02
Why: members trade seed packets without a spreadsheet.
Rules for all stories: a packet has one owner at a time.

## 1. As a member, I want to list a packet, so that others can ask for it.
- AC-1: A listing shows the plant name and the harvest year. (verbatim swap-rules page)
- AC-2: A listing without a harvest year is refused with the missing field named.

## 2. As a member, I want to ask for a packet, so that the owner can agree.
- AC-3: An owner sees each open request on the packet.
Amended 2026-03-09: a second request replaces the first — one request per member

## Out of scope
- Postal shipping — owner: ADR-0004
```

## Decisions and ADRs

Append `D-n` lines to `decisions.md`, each citing its `Source:` (shape in formats.md). [C6, C7, TS11]

- Every code claim cites `file:line` or `git show --stat`; every claim about a tool cites its source, an ADR or a probe, and says what it enforces.
- `Test seam: …` names the seam (existing, highest, fewest) and a prior-art path. [TS4]
- `Risk: …` and, for each changed rule, the places that repeat it. [N11]
- A prototype snippet that encodes a decision goes in its `D-n`. [TS13]
- A defect found in code is not written as `Open:`. The digest names it with its `file:line`; the user's answer becomes a plain `D-n` with `Source: user, <date>`. [FC12]
- This skill never writes a `T-n` line or a row of `CONTEXT.md`; terms are the interview's.
- For each `D-n` tagged ` ADR?` that the user agrees is an ADR, draft `.anomaly/<work unit>/adr/<NNNN>-<slug>.md` from the repo's ADR template, with the front block. With no `docs/adr/` folder in the repo, raise that with the user before the first draft. [C24] The number must be free on every branch: `git log --all -- docs/adr/<NNNN>*` is empty and no draft in any `.anomaly/*/adr/` holds it. An ADR cites commits on the main branch, not lines of scratch files. [N1, N2]

## The checks and the gate

1. `check stories`. Exit 1 stops the skill before the review: fix each error line. Exit 0 with `warning:` lines carries them into the handoff.
2. `lens tally add` with `--lens interview`, using the counts of the interview's close table (accepted, rejected, revised) from this window; skip it when they are not known, and run it once per window: a re-run in the same window skips it. It runs before the review, so a last-review `lens tally sum` includes it.
3. Run `anomaly:review` in mode `spec` with the work unit folder, in the background; say how long it may take. [N7]
4. A Blocker stops the skill before the digest. List every other finding in the handoff. After a fix, ask `anomaly:review` for a delta round with the work unit folder, and say when this is the session's last review so `lens tally sum` runs.
5. Show a digest of at most 5 lines: stories and ACs, test seams, warnings, defects found in code with their `file:line`, next step. Then wait for approval of `stories.md`. [TS5]

## After the yes

1. `log add`, stage `specify`. The text starts with the id list ended by a semicolon, then the check result: `ACs: AC-1, AC-2; claims checked …`. It must hold every AC id, else `check stories` cannot see that id renumbered. `log.md` lines carry no cost numbers. [G17]
2. `worklog add`, stage `specify`.
3. End with the next-step line, `/anomaly:slice <work unit>`. Never offer `/clear`. [C9, C12]
