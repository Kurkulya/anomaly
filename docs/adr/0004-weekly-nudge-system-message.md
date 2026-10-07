# ADR-0004: The weekly nudge prints a JSON systemMessage and marks the week before reading data

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-11-15

## Context

The loop must not depend on the owner's memory, and a quiet backlog must cost no model tokens.

## Decision

A plugin `SessionStart` hook (matcher `startup` only, in `plugins/anomaly/hooks/hooks.json`)
runs `anomaly.py nudge`. At most once per ISO week it prints `{"systemMessage": ...}` when an
open problem has a score of 4 or more or an experiment is due, and nothing otherwise. The week
marker is written before the anomalies are read.

## Why

Plain output from a `SessionStart` hook is added to the model's context, which costs tokens
(aae220f); a `systemMessage` is shown to the user only. Marking the week first means an
unreadable record gives an error once a week, not at every startup (9628f7d).

## Alternatives rejected

- Plain stdout: costs tokens in every session of the week.
- Running on resume and clear as well: noise.
- Marking the week after reading the data: an error at every start.

## Accepted risks

- [ ] The hook runs `python`; a system with only `python3` needs a manual edit of the hooks
  file. Owner: VK · revisit 2026-11-15.
- [ ] The nudge has been confirmed as loaded ("1 hook" after `/reload-plugins`) but not yet
  seen printing in a live new-week session. Owner: VK · revisit 2026-10-18.

## Revisit

If the first live run misbehaves, or Claude Code changes how `SessionStart` output is handled.

## Sources

Commits aae220f, 9628f7d, c2fe731. Design spec AC-32 (kept outside git, in
`.scratch/anomaly-loop/spec.md`).
