---
name: interview
description: Slash-only skill, started as /anomaly:interview. Turns an idea into settled, cited decisions and terms by asking the user rounds of questions, then offers the specify stage.
disable-model-invocation: true
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# interview

Started by the user as `/anomaly:interview`; the model never starts it. [GM1, GW1, CD3] Ids in brackets are for the rule trace. Line shapes are in [formats.md](../../docs/formats.md), stage end and `/clear` in [boundaries.md](../../docs/boundaries.md); repeat neither.

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <work unit> interview --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <work unit> --stage interview --session ${CLAUDE_SESSION_ID} --docs <work unit folder> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Before round 1

1. Take the idea: the user's text, or a key read through the `issue_source` port (read-only). Ask the work unit name before round 1 (or take it from the idea's key); create `.anomaly/<work unit>/` at the first `D-n`, not before. [A10, DM3]
2. `worklog start`, then `ports`. Run the `gather` port (repo code and docs; adapters add tracker, backend and org ADR lookups, named `Server:tool`). [CM5, CM8, G27]
3. Scan what is already settled: the ADRs, both layouts' `decisions.md`, the glossary file from the profile's `glossary_file` (default `CONTEXT.md`) and the backlog. Look with Glob and Read in the checkout (tracked ADRs and the git-excluded `decisions.md` files), never recall. Read the repo layer's own domain doc; it wins on a clash. [A1, CM4, CM9, CX1, DM2]
4. Open round 1 with "Settled already": one line per ADR or `D-n`. Even when the idea asks for it, no question or option offers to reopen a settled ADR or `D-n`; only the user reopens it. A part in conflict with one is named under Settled already as a `D-n` out of scope owned by that ADR or the other unit with that `D-n`, written without a question in every round; it never asks for an owner; when that `D-n` is in this unit, write none. [A1]

## A round

Markdown, no emoji: bold labels, one blank line between blocks, options as a list. Ask the whole frontier at once: at most 8 numbered questions, hard-to-reverse first (blast radius high, medium, low). [GR2, GR3, A8, CD1, CD2]

```
**Settled already:** <D-n / ADR-n, one line each>          (round 1; later, a new conflict)

**Facts pending:** <lookup> → blocks Q<n>

**Taking these defaults unless you object:**
1. …
2. …

**Q<n> — <title>** (blast radius: high | medium | low)
<body>
- a) …
- b) …

**Assumes:** <premise> (<source>)

**Recommend:** <answer>. **Risk:** <one line>. **Conflicts:** <D-n / ADR-n / none>
```

- Every question has `Assumes:` with its source and `Recommend:` with a real flaw in `Risk:`. A tool or library limit says whether a documented way around exists. [A2, CM12]
- Low-risk items with an obvious answer go in the one defaults block, not as questions. [A9]
- Facts are the skill's job: dispatch a sub-agent on the `models` role `explore`, never ask the user what a lookup can find. [GR5, K2]
- A running lookup blocks only the questions downstream of it; the rest go on, and the round lists "Facts pending". [GR6, A3]
- The user says how the code works: check the code, and show any clash. [DM7]
- A decision is the user's: put it with options and wait. A question on an open answer waits for the next round, whose frontier is recomputed from the answers. [GR7, GR4, GR1]
- Ask about names when a new file, folder or term appears, and test a term with an edge case. A clash with the glossary: say so at once. [A7, DM4, DM5, DM6, CM11]

## After each round

Write the settled items to `.anomaly/<work unit>/decisions.md`; no other file changes. No source edits, no `stories.md`, no spec, no ADR files, and no commit. [A4, CM10, CM6]

- `D-n` lines, each with a `Source:`; tag ` ADR?` when the decision is hard to reverse, surprising and a real trade-off. `specify` writes ADRs. [DM10, G4]
- `T-n` lines for settled terms: one canonical term, others under Avoid, a meaning in 1-2 sentences, project-specific words only, no implementation detail. Write each when it settles, without asking, never into the glossary file. [GF1, GF2, GF3, GF4, DM8, DM9, DM1]
- The shape of `D-n`, `T-n`, `Open:` and ` ADR?` lines, number reuse and amendments are in [formats.md](../../docs/formats.md). Unanswered items stay out.
- A gap the user settles as out of scope is a normal `D-n` with its `Source:` and an owner after `— owner:`, never `Open:`. The owner is another unit, ticket or ADR, never a `D-n` (a bracketed `(D-n)` citation after the owner is allowed). It must exist in the checkout or carry `TODO(<owner>, revisit YYYY-MM-DD)`; a person or a skill needs the key. Never write a placeholder owner. If none is known, ask who owns it; if the user has none, recommend the TODO key with an owner and a date first; only if the user declines, keep the item as an `Open:` line and say specify will stop on it. `Open:` is only for the unanswered: it blocks specify.

## The close

Done when the frontier is empty and nothing is assumed silently. [GR8, CM1]

1. Show a table, one line per `D-n` and `T-n`, with the counts of recommendations accepted, rejected and revised, shown here only. [A5, A6]
2. Ask one confirm question with AskUserQuestion, the only use of it; text everywhere else. Act on nothing before the yes. [GR9, K3, CM11]
3. On "stop", keep an `Open:` list of the unanswered items only in `decisions.md`.
4. `worklog add`, stage `interview`; leave out `--docs` when the work unit folder does not exist.
5. Offer `/anomaly:specify <work unit>` as the next-step line; the stage end and the `/clear` rule are in [boundaries.md](../../docs/boundaries.md). [CM3, CM2]
