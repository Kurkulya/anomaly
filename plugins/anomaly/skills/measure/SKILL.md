---
description: Refresh the per-session metrics file (tokens, active time, friction, tools) from Claude Code transcripts, at no model cost. Use when the user asks for metrics or fresh numbers on their sessions, or before old transcripts are deleted.
---

# measure

Turn the transcripts on this machine into one row of numbers per session, stored in the
`metrics.jsonl` file in the loop's home folder. Nothing is sent to a model: a script reads the
files and counts.

## Run it

Run this one command with the Bash tool. The plugin fills in the three paths before you see
this text, so do not change them. Keep the quoting exactly as written: the home value stays in
single quotes, because Claude Code leaves it unfilled in skill text (ADR-0001), and the script
then falls back to the default home.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" measure --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

- If `python` is not found, try `python3`.
- The scan is incremental: only transcripts that changed since the last run are read again.
- Add `--full` to the command when the user asks for a complete re-read, after the
  `ticket_key` value in the profile has changed (old rows keep the keys they were scanned with),
  or once after an upgrade that adds row keys (for example `seconds_by_type`).

## Report back

The script prints a few lines. Pass them on in plain words:

- how many sessions were read and how many were skipped
- how many rows the file holds, the date range they cover, and the total weighted tokens
- the `subagent seconds:` line and the `subagent seconds by model:` line, when the script prints them, as they are
- the path of the metrics file

If the output has a line that starts with `profile:`, it names the profile keys that are
missing. Repeat that line once, as it is, and say that the measurement itself was not affected.
Do not ask the user to fix it now.

If the command prints an error that starts with `anomaly:`, show it unchanged and stop. The
usual cause is a missing data folder; never work around it by choosing a folder yourself.

## Rules

- Do not open transcript files yourself and do not quote anything from them. The script
  already keeps only counts, normalized shapes and identifiers.
- Do not edit `metrics.jsonl` by hand.
