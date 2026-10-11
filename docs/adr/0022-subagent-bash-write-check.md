# ADR-0022: A plugin PreToolUse hook refuses shell file writes in subagents

Status: Proposed · Date: 2026-10-11 · Owner: VK · Revisit-by: 2027-01-11

Decision: the plugin adds a second hook beside the ADR-0004 nudge: `PreToolUse` on Bash runs `anomaly.py check subagent-bash`. When the hook input has `agent_id` and the agent is not `anomaly:survey`, the check denies a heredoc, `sed -i`, `tee`, a `>` or `>>` redirection to a file, `curl -o` and `wget -O`. Everything else is allowed.
Why: brief text alone did not hold: in 6 build sessions an implementer or test writer wrote files through the shell although its brief forbade it (anomaly implementer-ignored-no-heredoc-rule).
Revisit: when a subagent needs shell writes the check refuses, or 2027-01-11.

## Context

The build briefs ask implementers and test writers to edit files only with Edit or Write. The rule was broken with heredocs, `sed -i`, `curl -o` and redirects. Claude Code hook input carries `agent_id` for the subagent or in-process teammate the hook fires in, and `agent_type` for a subagent or a main session started with `--agent` (Claude Code hooks docs, common input fields). The `hooks` field of an agent's frontmatter is ignored for plugin subagents (Claude Code docs, sub-agents page, and the location table of the hooks page), so the check must live in the plugin's `hooks.json`. The survey agent's brief allows Bash and file writes with no shell-write rule, and its runtime task saves command output as evidence files (`agents/survey.md` and `skills/tests/reference/agent-briefs.md` on main at d33184f).

## Decision

- Subagent test: `agent_id` present. The main window, also a session started with `--agent`, is never checked.
- Exemption: `agent_type` `anomaly:survey`.
- Denied: any heredoc `<<` or `<<-`, whatever it feeds, `sed -i`, `tee`, `>` or `>>` to a file, `curl -o`, `wget -O`. Allowed: `2>&1`, `>/dev/null`, `2>/dev/null`, a here-string `<<<`, quoted text, inline code with `-c` or `-e`, pipes and chains.
- A deny prints `permissionDecision: deny` with a reason that names Write and Edit, exit 0. Input that is not JSON, or with no command, is allowed (fail open). An unclosed quote ends the scan of the command, and a write before it still counts: `echo x > f 'oops` and a heredoc whose body holds an apostrophe are denied, `echo "a > b` is allowed.
- It applies in every project where the plugin is on.

## Why

A hook enforces what a brief only asks, and it needs no implementer agent of the plugin's own. Keying on `agent_id` keeps the main window free, where the user directs the commands.

## Alternatives rejected

- Only `general-purpose` subagents: misses an implementer adapter of another agent type.
- Also denying inline code and command chains: refuses common read-only pipes such as `git log | head` in every project.
- Hooks in agent frontmatter: ignored for plugin agents.

## Accepted risks

- [ ] In other projects, a subagent's `cmd > out.txt` is refused and it must use Write. Owner: VK · Revisit: 2027-01-11.
- [ ] Python starts on every Bash call of every session with the plugin on, because a matcher cannot test `agent_id`. Owner: VK · Revisit: 2027-01-11.
- [ ] Inline code and chains in subagents stay possible. Owner: VK · Revisit: 2027-01-11.
