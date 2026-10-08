# ADR-0010: Static guard rails read the live deny rules, and `ui_check` joins the ports

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-12-01

## Context

ADR-0007 decided that the pipeline complies with the org deny list by design, and that a CLI test
scans every pipeline skill's text for command shapes the deny list matches. Its accepted-risk
line assumes a fixed copy of the patterns: the test "knows only the deny list as of 2026-10-04".
The `workflow-build` spec settles a better default, so that line is outdated.

The same spec adds one port the ADR-0007 table does not name. The build brief (rule N16) found
that the profile key `verify_ui` held an org UI checker but no port existed for it, so `build`
had nowhere to call it without an org check in the skill text.

## Decision

- **The deny-shape test reads the deny rules at test time.** It reads `permissions.deny` from the
  user settings file (`~/.claude/settings.json`, or in the folder named by `CLAUDE_CONFIG_DIR`;
  a `settings.local.json` beside it is read if present, though the settings documentation names
  only `settings.json` at user scope) and from the managed settings file of the platform, plus its
  `managed-settings.d/*.json` drop-ins (named on the managed settings page). It skips when no
  file is readable, or none holds a rule. Nothing is copied into the plugin.
- **Managed settings paths**, as the Claude Code documentation on managed settings gives them
  (read 2026-10-04): Windows `C:\Program Files\ClaudeCode\managed-settings.json` (also read on
  this machine; the file starts with a byte order mark, so it is read as `utf-8-sig`); macOS
  `/Library/Application Support/ClaudeCode/managed-settings.json` and Linux or WSL
  `/etc/claude-code/managed-settings.json` (documented, not tried: unverified on those two). The
  legacy Windows path `C:\ProgramData\ClaudeCode` is not read by Claude Code and not by the test.
- **What the test checks.** Over every pipeline skill (any skill except `measure`, `observe`,
  `calibrate`, `assess`), its extra docs and the agent files: no `Bash(...)` deny rule matches a
  line, an inline span or a part of a chain (`&&`, `||`, `;`, `|`) of the text; no inline code
  (`node -e`, `sh -c`, `bash -c` and the like), no pipe into an interpreter, no shell heredoc.
  A finding prints the rule and `file:line`, never the matched text.
- **The CLI pattern is one constant.** `CLI_PATTERN` in `anomaly_loop/constants.py` is
  `Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)`, the quoted form the loop skills
  already use. The `allowed-tools` of `build` and `review` holds exactly that one entry, and every
  call of the CLI in their text uses that exact command, never chained. The plugin edits no
  settings file and prints no allow rule.
- **Supersedes** the accepted-risk line of ADR-0007 that reads "The deny-shape test knows only the
  deny list as of 2026-10-04; a new org rule needs a new pattern". The risk is now the one named
  below. ADR-0007 itself stays as written.
- **New port `ui_check`** (mode replace), added under ADR-0007's rule that a new org need becomes
  a new port through a spec. Core default: the built-in browser walkthrough of the ticket's UI
  acceptance criteria, with its app facts (port, width, theme key, known console error, login
  redirect) read from the repo layer. Org adapter: the profile's UI checker, today the value of
  `verify_ui`. Used in phase 1 by `build`. The profile key name that feeds the port is set by the
  ticket that builds `ports`.

## Why

A fixed copy of the deny list goes stale the day an org rule changes, and it would put org
facts into the plugin, which ADR-0001 forbids. Reading the rules the machine really enforces
tests the true list with no upkeep. Deny rules caused 52% of the 684 build-session refusals
(denials classification, 2026-10-04), so this is the check that pays most. A skill text that is
checked against the rules cannot teach the agent a shape that is refused.

`ui_check` follows the same reasoning as the other ports: an org UI checker is an adapter, the
walkthrough is the core default, and the skill text carries no org check.

## Alternatives rejected

- Keep a fixed copy of the deny patterns in the plugin: stale at the next rule change, and an org
  fact inside the core.
- A CLI subcommand that reads the settings at run time: the plugin must not touch settings, and a
  run-time check would only fail after the text shipped.
- Match each line against each rule as Claude Code does, with its own matcher: its matching of
  compound commands is not documented as an interface, so a copy would drift. The test uses a
  simple reading and errs towards flagging.

## Accepted risks

- [ ] The test sees only the deny rules readable on the machine that runs it. Rules delivered by
  an MDM policy, the registry or server-managed settings are not files, and a machine with no
  readable file skips the test. Owner: VK · revisit 2026-12-01.
- [ ] The macOS and Linux managed settings paths come from the documentation and were not tried.
  Owner: VK · revisit when the tests first run on one of those systems, or 2026-12-01.
- [ ] The text scan is a heuristic, not Claude Code's matcher: a shape that is only mentioned in
  prose can be flagged, and an unusual spelling of a denied command can slip through. Owner: VK ·
  revisit 2026-12-01.
- [ ] Deny rules in a project's `.claude/settings.json` or `.claude/settings.local.json` are not
  read: the test has no project to read from, and the pipeline runs in many. Owner: VK · revisit
  2026-12-01.

## Revisit

When Claude Code documents a way to read the effective permission rules, or when a refusal shows
a denied shape that the test did not find.

## Sources

`workflow-build` spec (`.scratch/workflow-build/spec.md`, § Permissions, Testing Decisions,
Ports, Risks; ACs 23, 26, 63 to 65, 67, 80 to 82; git-excluded); ADR-0007 and its accepted-risk
line; denial classification 2026-10-04 (`.scratch/anomaly-workflow/denials-2026-10-04.md`); build
brief rule N16 (`.scratch/workflow-build/briefs/build.md`); Claude Code documentation on managed
settings (the file paths per platform, the `managed-settings.d` drop-ins and the legacy Windows
path) and on settings (the user-scope file), read 2026-10-04; managed settings file on this
machine, observed 2026-10-04.

Amended 2026-10-08: the scan also covers the plugin's docs/ folder (planning formats and boundaries).
