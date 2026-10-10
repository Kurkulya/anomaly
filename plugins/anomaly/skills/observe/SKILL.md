---
description: Log what went well and what went wrong in a session as anomalies, a quick note, review-lens stats or a session-kind fix. Use when the user says "retro", "retrospective" or "log this", asks for a note, or wants a session's kind changed.
---

# observe

An **anomaly** is one record in the backlog: a **problem** (friction, waste, a wrong turn) or a
**win** (a step that clearly caught something or saved something). A **sighting** is one session
in which it happened. This skill turns a session into sightings. A script does the writing, the
counting, the index and the commit; you do the judging.

Pick the mode from the user's words:

- **capture** (default; "retro", "retrospective", "run the observe skill"): look back over a session.
- **note** ("log this: ...", "note: ..."): one sighting, no analysis, no questions.
- **lens stats** and **session kind**: small corrections, described near the end.

## The two commands

Run both with the Bash tool. The plugin fills in the paths before you see this text, so do not
change them. Keep the quoting exactly as written: the home value stays in single quotes,
because Claude Code leaves it unfilled in skill text (ADR-0001), and the script then falls back
to the default home. If `python` is not found, try `python3`.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" observe list --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" observe apply --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --file "${CLAUDE_PLUGIN_DATA}/observe-batch-${CLAUDE_SESSION_ID}.json"
```

**`list`** prints one line per anomaly (signature, kind, category, target, scope, status, impact,
times seen, first words of the text), open ones by score, then closed ones. Run it first, in every
mode. This is how you find out which anomalies exist.

If its output has a line that starts with `profile:`, the profile lacks some keys. Repeat that
line once, as it is, and carry on; do not ask the user to fix it now.

**`apply`** records one batch. Write the batch as JSON to the file named in the command (use the
Write tool), then run it. The file name holds the session id, so parallel sessions never share a
file. The Write tool refuses to overwrite a file it has not read, so when the file already exists
(an earlier run in this session), Read it first, then write the new batch. Never feed the batch
through standard input or a heredoc. Every key is optional:

```json
{
  "sightings": [{
    "signature": "slow-check-runs-twice", "text": "what happened in this session, one line",
    "session": "<session id>", "repo": "<repository folder name>",
    "kind": "problem", "category": "automated-checks", "target": "scripts/check.sh",
    "scope": "repo:demo", "impact": 2,
    "summary": "the problem or the win, one short paragraph, one line",
    "fix": "the proposed fix, one line (problems only)"
  }],
  "lenses": [{"session": "<session id>", "lens": "<reviewer name>", "accepted": 3, "rejected": 1}],
  "kind": {"session": "<session id>", "kind": "build"}
}
```

- For a signature that already exists, only `signature`, `text`, `session`, `repo` and `impact`
  matter. The script adds the sighting and keeps the anomaly's own text. For a new one it needs
  `signature`, `kind`, `category`, `scope`, `impact`, `summary`, and `fix` when it is a problem
  (`target` may stay empty). `summary` and `fix` are one line each.
- The current session's id is `${CLAUDE_SESSION_ID}`. If that still reads as an unfilled
  placeholder, ask the user for the session id before building the file name; never invent one.
- `repo`, `session` and every `lens` name are single words (letters, digits and `. _ : -`), no
  spaces. `repo` is the name of the repository folder you are working in.
- The script checks the whole batch before it writes anything. If it prints a line that starts
  with `anomaly:`, fix the batch (the message says what) and run it again. If the same error
  comes back, show it to the user unchanged and stop. If the message names a file under
  `anomalies/`, an existing record is invalid and the batch is not at fault: show the message
  unchanged and stop, do not retry.
- It prints one line per result: `logged:`, `reopened:`, `wontfix:`, `skipped:`, `lens:`, `kind:`,
  then `index:`, up to three `top:` lines (the highest scores) and `commit:`. The index and the
  commit are done for you; never write the index or run git yourself, and never edit an anomaly
  file by hand.
- A session counts once per anomaly and once per lens, so running a batch twice is harmless. A
  later capture or note in the same session about an anomaly that session already logged adds no
  count (the script says `skipped:`); the earlier sighting text stays as it was.

## Writing rules for every sighting and anomaly

Write the process in your own words. Say what happened and what it cost. Never include:

- raw tool output or pasted logs
- credentials or secrets
- URLs that have a query string
- names or email addresses of people

The script catches credentials in `name: value` or `name=value` form, URLs with a query string,
email addresses, pasted program output (stack traces and the like) and long opaque strings; it
also refuses anything longer than one short line. Session ids and commit ids are fine. It cannot
catch people's names or raw output in other shapes, so you must keep those out yourself. When the
script refuses a text, reword it and run again; do not try to get around the check.

## Capture

1. Run `list`.
2. Decide which session to look at. By default it is the current one: use this conversation.
   When the user names another session, start one `anomaly:digest` agent (`digest` model role: model, then effort if set) and ask it to read
   that session's transcript, found as `<id>.jsonl` under the transcripts folder (default
   `~/.claude/projects`, one folder per project), and to return a digest of at most 40 lines:
   the friction points, the things that went well, and every place the user interrupted, rejected
   something, corrected the agent or praised it, each in its own words, with no raw output,
   credentials, URLs with query strings or personal names. Work from that digest. Never read the
   transcript into this window.
3. **Environment pass.** Look for these seven kinds of friction or help:
   - `navigation`: time lost finding where something lives
   - `automated-checks`: a check that a machine could run was missing, slow or noisy
   - `coding-standards`: a rule or convention was missing, unclear, or not followed
   - `steering-files`: an always-loaded instruction file was wrong, bloated, missing or contradictory
   - `tool-economy`: a tool, command or subagent cost more than the job needed
   - `no-ops`: a step ran and changed nothing, or work was repeated for no gain
   - `information-access`: a fact, document or permission was needed and could not be reached
4. **Workflow pass.** Look for these six:
   - `rework`: output was redone
   - `late-catch`: a defect was found later than it could have been
   - `handoff-loss`: context was lost across a clear, a compaction, a subagent or a session
   - `manual-step`: the user did by hand something that could be automated
   - `blocked`: work waited on a person, a tool or another team
   - `pipeline-fit`: a pipeline step was too heavy or too light for the job
5. Both passes record **wins** as well as problems. A win is a step that demonstrably caught or
   saved something. Name it, so that a later cleanup does not remove what works.
6. Weigh the evidence. The strongest evidence is what the user did: interrupting, rejecting an
   action, correcting the agent, or praising something explicitly. Your own impression of how
   things went is only supporting evidence; do not grade your own work kindly. A candidate that
   rests on your impression alone gets impact 1, or is dropped.
7. Sort each candidate into **anomaly**, **memory** or **both**:
   - memory: how the agent should behave next time; it works as soon as it is written
   - anomaly: what the environment must change; it works only after something is built
   - both: write the memory too, and have it state the signature of the anomaly it belongs to
8. Fill in each anomaly candidate:
   - `signature`: lowercase words joined by hyphens, at most five, naming the problem or the win, not the fix
   - `kind`, `category` (one of the thirteen above), `target` (the skill, agent, hook, rule or
     process it is about; may stay empty), `scope` (`global`, `repo:<name>` or `plugin:<name>`)
   - `impact`: 1 wasted tokens or a little time, 2 real lost time or a wrong turn, 3 wrong output
     shipped or work blocked; for a win, how much it saved
   - Match against the `list` output by root cause. The same cause counts as a match however
     differently it is worded. A match uses the existing signature and shows `matches (n seen)`;
     otherwise it is `new`. An existing match that is `fixed` will reopen, and a `wontfix` keeps
     its status; the script tells you both.
9. Show **one table** and ask **one question**. Columns, in this order: signature, kind,
   category, target, scope, impact, `new` or `matches (n seen)`. Mark a "both" row with
   `+ memory` after the signature. A memory-only lesson is a row whose signature cell reads
   `(memory) <short name>`, with `-` in the other cells and `memory only` in the last. Under the
   table add one line for the lens stats (see below) when there are any; they are recorded with
   the answer unless the user declines them, even when the user records no anomaly. Then ask
   once which to record (all, some by number, or none).
   **Nothing is written before the answer**: no anomaly, no memory, no lens line.
10. After the answer, write the batch (the chosen anomalies and, unless declined, the lens stats)
    and run `apply`.
    For the chosen "both" and memory-only rows, write the memory entries the way this session's
    memory rules say; each "both" entry names its signature. A candidate the user dropped is
    dropped.
11. End with: how many were logged, anything `reopened:` or `wontfix:` (say so in plain words),
    the `commit:` line, and the `top:` lines as the three highest scores.

Done when every candidate is recorded, written to memory, or dropped by the user.

## Note

For "log this: ..." or "note: ...".

1. Run `list`.
2. Take the user's line and what this session shows. Infer every field yourself, do not analyse
   further and do not ask anything. Match against the list by root cause as in capture.
3. Write a batch with that one sighting and run `apply`. A match needs `signature`, `text`,
   `session`, `repo` (and `impact` if this one is worse). A new anomaly needs all of: `signature`,
   `kind`, `category`, `scope`, `impact`, `summary`, `text`, `session`, `repo`, and `fix` for a
   problem; `target` may stay empty.
4. Reply in one line: `Logged: <signature> (new)` or `Logged: <signature> (seen n times, score s)`,
   adding `; it was fixed, so it is reopened` or `; it is wontfix, so it keeps that status` when
   the script printed `reopened:` or `wontfix:`. If it printed `skipped:`, say that this session
   already counted.

When you work around an environment problem on your own during a session, offer a note in one
line with a draft signature. Write it only after the user says yes.

## Lens stats

A **lens** is one reviewer, or one review axis, whose findings are counted as accepted or
rejected: an agent, a skill or a review axis, never a person's name. At the end of a capture, for
every reviewer used in the session whose findings the user accepted or rejected, add one entry to
`lenses`: the reviewer's name as it was used, written as one word (join words with hyphens), and
the two counts. Count only what happened in this session; never guess a count. A reviewer with
no decisions gets no entry. The entries are recorded together with the chosen anomalies, after
the user's answer, unless the user declines them. The `review` and `build` skills record their own
lenses through the CLI (`lens tally`), under the fixed names that command holds (`code`, `feature`,
`security`, `plan`, `interview`, `model_pick` and the org reviewers' adapter names).

## Session kind

The kind of a session (`build`, `research`, `config`, `debug` or `unknown`) is guessed from the
numbers. When the user says the guess is wrong, or states what the session was, write a batch
with only `kind` (the current session unless the user names another) and run `apply`. Reply in
one line with the `kind:` line.

## Rules

- Do not read any other retrospective skill, from this plugin or another, at run time. This
  skill is complete as written.
- Do not open transcript files in this window.
- Judge the way of working and the environment, never the product work, and never people.
