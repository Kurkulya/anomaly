# ADR-0025: `progress` prints a versioned, local JSON report of one work unit for outside UIs

Status: Proposed · Date: 2026-10-12 · Owner: VK · Revisit-by: 2027-01-12

Decision: a new CLI command, `progress --json [--unit <name>] [--repo <checkout>]`, prints one JSON object with a work unit's last ended stage, wave, tickets, `mr.md` gate and cost. It reads local files only and always exits 0 with JSON, except for bad arguments. The object starts with `"schema": 1`. Changes only add fields. A rename or a removal raises the number, and the reference says so. A UI that draws a unit, such as a side pane in a separate plugin, calls this one command and parses no other output.
Why: a UI in another language and repo needs one stable contract. Today the same facts are spread over 5 text printers (`conduct status`, `frontier`, `ticket show`, `mr show`, `worklog report`). The plugin stays one standard-library Python CLI (ADR-0007), so the parsing lives here, under the unit tests, and not in the UI.
Revisit: when a second outside consumer needs a field that breaks schema 1, when the pane needs the MR draft or ready state, or 2027-01-12.

## Context

The side pane is a TypeScript hooks module that runs inside Claude Code and polls every few seconds. ADR-0007 keeps it out of the plugin, so it ships from its own repository on its own schedule. Until now the CLI printed JSON only for hooks (`nudge`, `check subagent-bash`) and for `pkg-facts --json`. None of the status commands print JSON, and `conduct status` stops with exit 2 when a unit has no work-unit line.

## Decision

- One command, one object. It reuses the existing readers (`frontier.classify`, `worklog.read_report`, `mr.read_state`, `ticket.metric_counts`) and one new data function in `conduct.py` that the `conduct status` text also uses, so the two reports cannot drift. `worklog.read_report` stays the one reader of `work-units.jsonl` (ADR-0014).
- Local only. It makes no `gh` or `glab` call and writes no file.
- Always JSON. No unit gives `"unit": null`. A bad ticket file becomes a `warnings` entry while the other tickets still show. Inside `conduct`, `frontier` and `ticket gate` still stop on that ticket.
- Unit pick: a ticket's `Base:` line or the `branch` port pattern matching the current branch, else the unfinished unit with the newest `log.md` line. `--unit` pins one. A worktree reads the main checkout's `.anomaly/` (ADR-0011).
- Versioned. `schema` is the first key. A test pins the field lists, and `docs/reference.md` lists every field with the change rule.

## Why

A single object costs one process per refresh and gives one contract to test. The schema number lets an outside UI say "update the pane" instead of drawing wrong data when the CLI moves ahead of it.

## Alternatives rejected

- `--json` on each of the 5 existing commands: 4-5 processes per refresh, and 5 contracts to keep in step.
- The UI parses the files itself: a second copy of the ticket, log and work-unit parsing, in a second language, outside the unit tests (ADR-0007).
- The MR draft or ready state through `mr show`: a network call and a `gh` login inside a UI refresh. The pane shows the local `mr.md` link and the `Reviewed:` and `Verified:` lines instead.
- No version field: a renamed field would break the pane without a sign.
