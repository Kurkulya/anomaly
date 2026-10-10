---
description: Judge a new link, text or opinion against the recorded evidence of how the user works, and keep the verdict as an idea. Use when the user says "assess", "evaluate this link", "what do you think of", or asks whether something new is worth adopting.
---

# assess

Something new arrives: a link, a pasted text, or an opinion such as "I think reviews are too
slow". Decide whether it deserves a place in this loop, by weighing it against the anomalies,
metrics and rules that are already recorded, and keep the decision as an **idea** in the
home folder. An idea is a proposal from outside, not a deviation, so it is not an anomaly.

Be a critic, not a fan. An input that merely sounds good is not a reason to change anything.

## 1. Check whether it was seen before

Run this with the Bash tool. The plugin fills in the paths before you see this text, so do
not change them. Keep the quoting as written: the home value stays in single quotes, because
Claude Code leaves it unfilled in skill text (ADR-0001), and the script then falls back to the
default home.

How to pass text to the script, so that no quote or `$` in it can break the command:

- A link goes after `--source` in single quotes. If it holds a `'`, write that as `'\''`.
- Any other input (a pasted text, an opinion) and every body goes in a file, never in the
  command line and never in a here-document. Write it with the Write tool to
  `${CLAUDE_PLUGIN_DATA}/assess-source-${CLAUDE_SESSION_ID}.txt` (the input) or
  `${CLAUDE_PLUGIN_DATA}/assess-body-${CLAUDE_SESSION_ID}.txt` (the body), and pass the path
  with `--source-file` or `--body-file`. If the file already exists from an earlier assessment
  in this session, Read it first, then overwrite it.
- The current session's id is `${CLAUDE_SESSION_ID}`. If that still reads as an unfilled
  placeholder, ask the user for the session id before building the file name; never invent one.
- Short single-line values (`--summary`, `--fix`, `--expect`, `--metric`, `--guard`, `--target`)
  go in single quotes with `'` written as `'\''`.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" assess check --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --source '<link>'
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" assess check --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --source-file "${CLAUDE_PLUGIN_DATA}/assess-source-${CLAUDE_SESSION_ID}.txt"
```

Use the first form for a link and the second for anything else.

- If `python` is not found, try `python3`.
- If the output has the line `assess: seen before`, show the earlier record in a few plain
  lines (verdict, date, the reason in the body) and stop. Do not read the page again. Go on
  only if the user asks for a fresh assessment; then record it with the same slug and
  `--replace`.
- If the output has the line `assess: new`, keep the `key:` line (you need it for a text) and
  the list of open anomalies that follows.
- If the first line starts with `profile:`, it names the profile keys that are missing. Repeat
  it once, as it is, and carry on; do not ask the user to fix it now.
- If the command prints an error that starts with `anomaly:`, show it unchanged and stop.

## 2. Read it

- A link: do not fetch it into this window. Send the link straight to one
  `anomaly:digest` agent on the `digest` model role (model, then effort if set) and ask for a
  digest of at most 300 words in its own words: what the thing claims, what it changes, what it costs, what evidence it gives. Work from the digest.
- A text or an opinion: use it as given.

Never keep long passages of the source. You will write about it in your own words.

## 3. Weigh it

Use the open anomalies from step 1. Open the full file of an anomaly only when it looks
related. Answer these four points, briefly and with evidence:

1. **Anomalies it would address**: which open anomalies, and how. Say "none" when none fits;
   do not stretch.
2. **Metrics it would move**: which numbers in the metrics file or the digest, in which
   direction. Name one metric that could get worse (the quality side: rework, corrections,
   review misses).
3. **Conflicts**: with a recorded decision (a `wontfix` or closed anomaly, the
   `## Closed` list in `INDEX.md`, the glossary file named in the profile), with a plugin
   rule (the README, this plugin's skills), or with a win that must not be removed. Say
   "none found" only after you looked.
4. **The strongest case against**: the best honest argument for not adopting it, including
   what it costs in the user's time and tokens. Write it as if you wanted it to win.

## 4. Choose a verdict

- `adopt`: it addresses real recorded anomalies, the case against does not hold, and it can be
  tried as one change to one target with one primary metric and one guard metric. Adopting
  only drafts an experiment for `calibrate` to pick up. It never changes a skill, a setting
  or a file by itself.
- `trial`: it might be good, but a small benchmark must show it first. Say what the benchmark
  is.
- `park`: not now. Give a revisit date and the reason, for example "when slow checks reach
  score 4". A parked idea comes back in the digest when the date passes or a related anomaly
  rises to score 4.
- `reject`: it does not fit. Start the body with a one-line reason.

## 5. Show it, then record it

Show the user the assessment in about ten lines: the four points, the verdict, and for `park`
the date. Ask whether the verdict stands. Write nothing before the user answers; they may
change the verdict.

Then record it. The body is the assessment in your own words, short: write it to the body
file (see step 1) and pass `--body-file`. Related items go in as `--related`, once per item:
an anomaly signature or a target. The script adds each signature's score at assessment time
itself. For `--source`, pass the link, or for a text the value of the `key:` line from step 1.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" assess record --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}" --slug <lowercase-words> --source '<link, or the key value for a text>' --verdict <adopt|trial|park|reject> [--revisit YYYY-MM-DD] [--related '<signature or target>'] --body-file "${CLAUDE_PLUGIN_DATA}/assess-body-${CLAUDE_SESSION_ID}.txt"
```

For `adopt`, add the drafted experiment to the same command:

- A new anomaly: `--signature <lowercase-words> --category <one of the loop's categories>
  --target <skill, agent, hook, rule or file> --summary '<what is wrong today>'
  --fix '<the change to make>'`. Add `--impact 1` to `3` and `--scope` when you know them.
- An open anomaly that has no experiment yet: only `--signature <its signature>`.
- Always: `--expect '<the effect>' --metric '<one metric name>' --guard '<one guard name>'`.
  The metric is exactly one name from the list `calibrate` uses: `weighted tokens`,
  `active minutes`, `interrupts`, `denials`, `weighted tokens without security`,
  `model-weighted tokens per dispatch <agent>` (with one agent name), `sightings since the fix`, or `<category>
  sightings` for one of the loop's categories (when the fix moves no number, use `sightings
  since the fix`). The guard is exactly one of `rework sightings`, `late-catch sightings` or
  `interrupts`: a quality signal that must not get worse, and not the metric. The script
  refuses any other name. Leave out `--check-by`: the draft has no check date until
  `calibrate` applies the fix, and a draft is never due before that.

Rare case: when the lessons you adopt are already built into this plugin, so there is nothing
left to draft, use `--already-applied` instead of the options above and say in the body where
they are built in.

If the script refuses, show its `anomaly:` line unchanged and fix the input; do not work
around it by writing files yourself. A refusal that names a URL with a query string, an email
address, a credential, pasted output or a long opaque string means the text is not in your own
words: reword it and try again. Keep every line of the body under 600 characters.

When `home` is in a git repository, the script commits the files it wrote (the idea, and for
`adopt` the anomaly and `INDEX.md`) and prints one `commit:` line; repeat that line.

Finish with one line: the verdict, and the path of the idea file the script printed. For
`adopt`, add that `calibrate` will pick the experiment up and that nothing else was changed.

## Rules

- Own words only. Do not copy sentences from the source. At most one short quote, at most 15
  words, in quotation marks; the script refuses more.
- The record never holds raw tool output, credentials, links with a query string (the script
  stores only a short digest of one), or names or email addresses of people.
- One idea, one file. Never assess several inputs in one record.
- Never edit `ideas/` or `anomalies/` files by hand, and never change anything an `adopt`
  does not name.
