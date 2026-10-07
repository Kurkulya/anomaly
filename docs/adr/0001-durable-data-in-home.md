# ADR-0001: Durable data lives in a `home` folder outside the plugin

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-11-15 · Amended 2026-10-07: third accepted risk, Revisit trigger and Sources line (dogfood-fixes 04, VK)

## Context

The plugin must be replaceable, publishable and uninstallable without losing the backlog or
the metrics baseline; Claude Code deletes transcripts after 30 days, so the metrics rows are
the only lasting record. Environment facts (tracker, glossary file, implementer agents, MR
tool) differ from one job to the next.

## Decision

- All durable data (anomalies, ideas, metrics, lens and session-kind lines, profile) lives
  under `userConfig.home` (default `~/.claude/anomaly`). Throwaway state (scan state, nudge
  marker, prompt cache, per-session files) lives under `${CLAUDE_PLUGIN_DATA}`, and the data
  folder may never be inside home.
- Environment facts live in `<home>/profile.md`, never in the plugin: 9 required keys plus the
  optional `build_skills` and `plugin_repo`.
- The plugin expands a leading `~` itself and treats an unfilled `${user_config.home}`
  placeholder as unset.
- Commands that write records commit only the paths they wrote, and only when home is inside a
  git repository.

## Why

The data survives an uninstall and stays under the owner's version control. Losing the data
folder costs nothing. A profile outside the plugin means a new environment is one file, not a
fork of the skills.

## Alternatives rejected

- Data inside `${CLAUDE_PLUGIN_DATA}`: deleted on uninstall.
- Organisation values in the skills: breaks reuse and review.
- Committing with `git add -A`: sweeps in other sessions' unrelated changes in the user config
  repository.

## Accepted risks

- [ ] Claude Code may or may not expand `~` in a userConfig default; the plugin does it itself.
  Owner: VK · revisit 2026-11-15 (verify, then drop the workaround or keep it).
- [ ] The default home depends on the user config repository's git allowlist including the home
  path, which lives outside this repository. Owner: VK · revisit 2026-11-15.
- [ ] Claude Code does not fill `${user_config.home}` in skill text (observed 2026-10-07 in
  session `56db0ddc`), so the unset rule above is what runs: skill commands use the default home,
  and a configured non-default home is ignored (the option variable is set for hooks only; not
  probed with a non-default home). The only sign is the CLI's `home: placeholder
  unfilled, using <path>` line, which does not say that a configured value was lost. Hooks still
  read the configured home (`CLAUDE_PLUGIN_OPTION_HOME`), so the nudge and the skills can see
  different backlogs. Owner: VK · revisit 2026-11-15 (check whether a Claude Code release fills
  user config in skill text; if not, decide whether that line is enough).

## Revisit

When Claude Code documents `~` expansion for userConfig values, when it fills
`${user_config.*}` in skill text, or if the plugin is published.

## Sources

Commits 55b186c, 15b1764 (unfilled placeholder), cc2f4b8, 30efa52 (commit only named paths),
b1e17f3, 0802f72 (`plugin_repo`), 704eab5 (retro-log retired). Design spec AC-2, AC-5, AC-9a
(the spec is kept outside git, in `.scratch/anomaly-loop/spec.md`). The unfilled
`${user_config.home}` risk: dogfood session 56db0ddc, `.scratch/workflow-build/digests/dogfood.md`
(kept outside git).
