# ADR-0007: One plugin, one CLI, and thin ports for everything org-specific

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-11-15

## Context

The pipeline must work in the owner's personal repos and in their work repos, where org agents,
conventions, a tracker, a CI host and an MR tool apply. Personal repos already run on defaults:
this repo is Python, and the profile maps implementers only for other stacks. A first design with
configurable combine modes, a list of invariants no adapter could remove and a semantic conflict
check was red-teamed the same day: prompts cannot enforce an interface, and the extra wiring text
in every skill would rebuild the bloat the rewrite removes.

## Decision

- **One plugin, one CLI.** The loop and the pipeline live in the `anomaly` plugin; all helpers are
  subcommands of the one stdlib Python CLI (the Node helpers are ported).
- **Ports with one fixed mode each:** `implementer` and `test_writer` per stack (replace),
  `conventions` per stack (extend), `reviewers` (add), `gather` (add), `tracker` / `issue_source`,
  `ci`, `mr`, `commit` / `branch` (replace). Each port has a core default that works with an empty
  profile. A new org need becomes a new port through a spec, never an org check inside a skill.
- **The CLI does the injection:** one subcommand resolves the profile into ports and prints one
  line of the resolved adapters; skills read that line and carry no wiring text. A missing adapter
  is reported, never guessed. Adapters are values in `profile.md`.
- **Repo layer:** commands are read from what the repo already documents; a personal file
  `<home>/repos/<repo>.md` fills the gaps. Nothing is committed to team repos.
- **Precedence:** org policy (managed instructions) > repo layer > profile adapters > core defaults.
- **Invariants:** enforced by the CLI and `conduct` from ticket files and git (review recorded
  before merge, one full verify per ticket, the acceptance test unchanged since its red commit
  unless noted, issue source read-only, state in files and git); briefed only: test first.
  No semantic conflict detection; a noticed conflict is logged with `observe`.
- **Permissions: comply by design.** The CLI does all parsing itself (a subcommand calls an org
  tool and reads its output in Python; nothing is piped into an inline interpreter). The pipeline
  runs no inline code (`node -e`, `sh -c`, `bash -c`), passes MR titles and bodies through files,
  and writes files with the Write tool, not shell heredocs. A CLI test scans every pipeline
  skill's text for command shapes that match the deny list (enforced). Each skill declares
  `allowed-tools` for the CLI pattern and runs that exact command string, never chained. The
  plugin never edits settings and adds no user allow rule.

## Why

Two real consumers (personal repos on defaults, work repos on org adapters) make injection worth
its cost. Fixed modes leave nothing to misconfigure; injection in the CLI keeps the skills short;
splitting invariants into enforced and briefed makes every promise checkable. On permissions,
the 2026-10-04 classification of 684 build-session refusals found 52% matched an org deny rule
(mostly inline `node -e`, including the old pipeline's own script calls and glab output piped
into it), 40% were org hooks, and at most 6% lacked an allow rule. Those rules and hooks are org
policy, so the pipeline must not trip them; more allow rules would have removed about 0.3%.
Plugin settings files cannot ship permission rules anyway (only `agent` and
`subagentStatusLine` are honoured), and a skill's `allowed-tools` grant lasts one turn.

## Alternatives rejected

- Two plugins (loop and pipeline): they cannot share Python code; publishing is out of scope.
- Profile-only config with a `repos:` map: repo facts change with the repo and are documented there.
- The wide design with configurable modes and semantic conflict checks (red-teamed, see Context).
- Node helpers beside the Python CLI: two languages, two test styles, two privacy paths.

## Accepted risks

- [ ] Org hooks (secret scan, destructive-command check) also block legitimate pipeline steps;
  the pipeline cannot change them. Owner: VK · revisit through calibrate (open anomalies
  `secret-scan-blocks-page-cursor-props`, `destructive-hook-matches-heredoc-text`).
- [ ] The deny-shape test knows only the deny list as of 2026-10-04; a new org rule needs a new
  pattern. Owner: VK · revisit 2026-12-01.
- [ ] That managed instructions load first in every session is observed, not documented.
  Owner: VK · revisit 2026-11-15.
- [ ] An org agent in a replace port follows its own instructions; the core can only brief it
  and check the result. Owner: VK · revisit at the `workflow-build` switch-over.

## Revisit

When a third environment appears, or when Claude Code documents plugin-shipped permissions.

## Sources

Design decisions 2026-10-04 (`.scratch/anomaly-workflow/decisions.md`, git-excluded) and the
red-team pass recorded there; docs check of plugin settings and skill `allowed-tools` the same
day; denial classification (`.scratch/anomaly-workflow/denials-2026-10-04.md`); workflow audit 2026-10-04 (U1, U9, § 8). Builds on ADR-0001 (environment facts in the profile).
