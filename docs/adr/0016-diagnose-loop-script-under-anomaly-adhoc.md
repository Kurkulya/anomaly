# ADR-0016: diagnose keeps its loop script under `.anomaly/adhoc/` with Write, the one file there the CLI does not write

Status: Proposed; partly supersedes ADR-0011 (a worktree session records adhoc state only through the CLI) · Date: 2026-10-08 · Owner: · Revisit-by: 2026-11-05

Decision: `diagnose` writes `<main checkout>/.anomaly/adhoc/<key>-repro.<ext>` with the Write tool; the ticket's `Repro:` line runs it by absolute path. It is the only file under `.anomaly/adhoc/` that the CLI does not write, and the one exception to the `build` rule that every `.scratch` or `.anomaly` edit goes through the CLI. In a linked worktree, diagnose stops and asks for the main checkout.
Why: a later `build` session must run the script, and the diagnose session scratchpad does not outlive the session.
Revisit: 2026-11-05.

## Context

ADR-0011 puts light-path tickets in `.anomaly/adhoc/` under the main checkout, written by `ticket adhoc`, so that a worktree session, which refuses a Write under the main checkout, can still record state through the CLI. `build` goes further: every `.scratch` or `.anomaly` edit it makes goes through the CLI (rule N12). A loop script is code, not a record, so no CLI action fits it. `interview`, `specify` and `slice` write their work-unit files under `.anomaly/<work unit>/` with Write; this ADR does not change them.

The diagnose eval found two gaps in the `Repro:` hand-over: the line pointed at a script in the diagnose session scratchpad, which no later session could run, and its `(red now)` suffix kept it from running as written.

## Decision

- `build/SKILL.md` names the exception on its CLI-only line (N12). Diagnose step 3 says where the script goes and stops in a worktree. Diagnose step 1 ensures `.anomaly/` is in `.git/info/exclude` (ADR-0011) before it records `git status`, so the new file keeps the hand-over check clean.
- The `Repro:` shape is `Repro: <command>`, runnable as written and red at hand-over (`plugins/anomaly/docs/formats.md`); the old `(red now)` suffix is gone. The line may also run a failing test when diagnose made no script.
- `ticket adhoc --from` warns on stderr, and still writes the ticket, when `Repro:` holds `;`, `&&`, `||`, `|`, `>` or `<` (`check.draft_warnings`), because the test writer runs it as written.
- The diagnose redact rule also covers the loop script; credentials come from env vars and are never written into the script.
- The ticket stem can differ from the `<key>` in the script name; the absolute path in `Repro:` still finds the script.
- **Partly supersedes ADR-0011**, the Why sentence that puts the light path under the main checkout, "where a worktree session that cannot write there can still record state through the CLI": `.anomaly/adhoc/` now also holds a file written with Write, so diagnose must run in the main checkout. The rest of ADR-0011 stands.

## Why

The script must outlive the diagnose session, stay out of git (`git status` is clean at hand-over) and sit where any later session on the repository can run it. `.anomaly/adhoc/` under the main checkout gives all three, and the ticket that runs the script already lives there.

## Alternatives rejected

- The session scratchpad: lost before `build` runs.
- A CLI action that copies the script (`ticket adhoc --repro-file`): new code and tests for a file the CLI never reads.
- The script inside the ticket as a fenced block: the `Repro:` command would not run as written.

## Accepted risks

- [ ] No CLI check scans the script for secrets; only the skill's redact rule applies. Owner: · Revisit: 2026-11-05.

## Revisit

2026-11-05, or when a CLI action starts to read the script.

## Sources

Commits of the durable-repro ticket: merge 61b9a58 (red commit 817f3f4; f792ce3, 5bc6e36, 4fccb1b). Commits of the eval-fixes cumulative-review fix: merge 00c3f9c (red commit 6921f61; 7900f05, d471ee2, 31ed7cb, 6710680). Also ADR-0011; `plugins/anomaly/skills/build/SKILL.md` (N12); `plugins/anomaly/skills/diagnose/SKILL.md` (steps 1, 3 and 8); `plugins/anomaly/anomaly_loop/check.py` (`draft_warnings`).
