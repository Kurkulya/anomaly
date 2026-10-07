# Next

Updated: 2026-10-07

## Where we stopped

Work unit `workflow-plan` (phase 3: the plugin's own interview, specify, slice and diagnose
skills) is planned and not started: 14 tickets, 12 `ready-for-agent`, 2 `ready-for-human`.
Earlier work units are done.

The plan lives in the local checkout only (`.anomaly/workflow-plan/`, git-excluded). A clone,
such as a cloud session, does not have it.

## Next

1. Tickets 01 (review rule-trace pass), 02 (formats and boundaries) and 03 (`log add`) have no
   blockers and can start now, in any order.
2. Then 12 (needs 02), 04 (needs 02, 03), 06 (needs 01, 02).
3. 11 and 14 are `ready-for-human`: they need the plugin reinstalled and a fresh local session.

## Cloud sessions (Claude Code on the web)

- The plugin is **not loaded** in a cloud session: plugins, also ones the repository declares, are
  not installed there. The `anomaly:*` skills and agents cannot run.
- User-level files (`~/.claude`) and the work units do not exist there; this file and
  `CLAUDE.md` are the context. Use a cloud session for work that needs only the code: run the
  suite, fix, refactor, docs.
- Python 3 is installed; the suite needs no packages.
