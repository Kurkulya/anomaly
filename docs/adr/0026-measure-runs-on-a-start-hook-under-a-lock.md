# ADR-0026: `measure` runs on a start hook and before the conduct report, under a lock in home

Status: Proposed; partly supersedes ADR-0001 (the throwaway metrics.lock lives in home) · Date: 2026-10-12 · Owner: VK · Revisit-by: 2027-01-12

Decision: the plugin adds a third hook: an async `SessionStart` handler with matcher `startup` runs `anomaly.py measure --quiet`, beside the ADR-0004 nudge, and the conduct skill runs `measure --quiet` once before `conduct status`; every run holds a lock file `metrics.lock` in home.
Why: the cost line of `conduct status` read 0 weighted tokens until someone ran `measure`; one run later it read 17,329,129. `conduct status` leaves sessions without a metrics row out of the sum and says nothing (`worklog.read_report`).
Revisit: when the side pane needs fresher numbers than session start gives, when Claude Code changes async hook delivery, or 2027-01-12.

## Context

`measure` was a request-only command: the user, the `anomaly:measure` skill or calibrate step 1 ran it. Plain stdout of a `SessionStart` hook enters the model context (ADR-0004). An async command hook runs in the background; Claude Code passes only the `additionalContext` and `systemMessage` fields of its JSON reply to Claude, on the next turn, and does not enforce its `timeout`; `claude -p` kills an async hook still running at exit (Claude Code hooks docs, Run hooks in the background). `scan` reads the old rows, then writes `metrics.jsonl`, the scan state and the prompt cache one after another, each through a fixed `<name>.tmp` and a rename (`metrics.py` and `files.py` on main). Hook processes and skills get different data folders from Claude Code. Hooks also read a configured home from `CLAUDE_PLUGIN_OPTION_HOME`, while skill text falls back to the default home (ADR-0001), so with the default home, home is the one folder a hook run and a skill run share.

## Decision

- Hook: second handler in the `startup` group of `hooks.json`, `python` with `measure --quiet`, `"async": true`. No `SessionEnd` hook.
- `--quiet`: no stdout on success or on a skip, and no `home: placeholder unfilled` notice. Errors still print `anomaly: <msg>` on stderr with exit 2; an async hook shows them to no one, and a later plain run shows an error that persists.
- Lock: `metrics.lock` in home, created with `O_CREAT|O_EXCL` and holding a token of the run, held from the read of the old rows to the last write. At the end a run removes the lock only if it still holds its own token. Wait 30 s, stale after 10 min, the age taken from the lock file's modification time; a run removes a stale lock (stat, then unlink) and makes its own, once per run. A plain run that skips prints `measure: skipped, another run holds <home>/metrics.lock`.
- Conduct: Report step 13 runs `measure --quiet` just before `conduct status`, and prints nothing about it. The side pane's poll never runs `measure`.

## Why

A start hook costs no model tokens and no wait, because it is async and quiet. The conduct run puts the live session into the wave report. A lock in the default home is the one place both a hook run and a skill run see; waiting is free in an async hook and keeps conduct's numbers fresh when a hook run holds the lock.

## Alternatives rejected

- A `SessionEnd` hook: all `SessionEnd` hooks share a 1.5 s budget that a plugin hook's `timeout` cannot raise, and one incremental run took 1.5 s.
- A unique temporary name per process instead of a lock: it stops two runs writing one `.tmp`, but not one run's state file landing beside another run's `metrics.jsonl`, nor a rewrite from a stale read.
- Trusting the async rule for plain stdout instead of `--quiet`: the docs name the two JSON fields an async hook passes, but do not say outright that its plain text goes nowhere.
- A lock in the data folder: a hook run and a skill run use different data folders.
- Running `measure` on every side-pane poll: it polls every few seconds.

## Accepted risks

- [ ] After a killed run (`claude -p` exit), other runs skip `measure` for up to 10 min. Owner: VK · Revisit: 2027-01-12.
- [ ] A `--full` run longer than 10 min can lose its lock to a second run. Owner: VK · Revisit: 2027-01-12.
- [ ] Two runs that both find the same stale lock (left by a killed run) can both take it over and write together; each removes only a lock that still holds its own token. Owner: VK · Revisit: 2027-01-12.
- [ ] A passing error (on Windows, the rename onto `metrics.jsonl` fails while another process has it open) makes a hook run exit 2 unseen, maybe leaving a `<name>.tmp`; that hook run writes nothing that time, and the next run catches up. Owner: VK · Revisit: 2027-01-12.
- [ ] A conduct run that skips or fails leaves the cost line stale, and nothing says so. Owner: VK · Revisit: 2027-01-12.
- [ ] The hook keeps its own scan state in its data folder, so its first run rereads every transcript. Owner: VK · Revisit: 2026-11-12.
- [ ] With a configured non-default home, the hook writes rows and its lock there, while conduct reads the default home (the ADR-0001 split). Owner: VK · Revisit: 2026-11-15.
- [ ] Python starts at every session start with the plugin on, also in `claude -p` runs that kill it at exit. Owner: VK · Revisit: 2027-01-12.
