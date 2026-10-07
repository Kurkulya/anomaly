# ADR-0015: The plan gate and the rule trace run in `review`; terms and logs reach files through tickets and the CLI

Status: Accepted · Date: 2026-10-07 · Owner: VK · Revisit-by: 2026-11-05

Decision: `anomaly:review` gains the modes `spec` and `tickets`, which dispatch a new read-only agent `anomaly:plan`, and its ticket mode adds a rules-mode pass when the ticket's `Tests:` line names `rule trace <brief> <SKILL.md>`. `interview` writes settled terms as `T-n` lines in `decisions.md`; `slice` moves them, and ADR drafts, into the first ticket that needs them. `log.md` is written only by `anomaly log add`.
Why: one dispatcher of reviewers keeps lens counts and rounds in one place; `build` has 9 bytes of budget left; a glossary edit outside a ticket leaves an uncommitted file in the main checkout.
Revisit: when `conduct` (phase 2) drives tickets, or 2026-11-05.

## Context

Phase 3 (`workflow-plan`) adds `interview`, `specify`, `slice` and `diagnose`. Its tickets are built with `anomaly:build`, which calls `review` only in ticket or combined mode (`build/SKILL.md`, Shared close). The rewrite method needs a rule trace per skill, and the plan reviewer was planned as one agent with two modes (`anomaly:plan`). ADR-0011 left the `log.md` writer unbuilt (Accepted risks).

## Decision

- `REVIEW_MODES` gains `spec` and `tickets`. Like `rules`, they have no diff and no `risk` run. They dispatch `anomaly:plan` with its mode text, count lens `plan` through `lens tally`, and write a `review` work-unit line with the mode. A Blocker stops the calling skill.
- Ticket mode reads `Tests:` (`ticket show`). A `rule trace <brief> <SKILL.md>` item adds a rules-mode pass on that pair; after a High fix the pass runs again, since rules mode has no range.
- `T-n:` lines (term, meaning, words to avoid) live in `decisions.md` until a ticket writes the `CONTEXT.md` row. ADR drafts live in `.anomaly/<work unit>/adr/` until a ticket moves them.
- `anomaly log add <work-unit folder> --stage <stage> '<text>'` is the one writer of `log.md`.

## Why

`review` already owns lens accounting and rounds; a second dispatcher in `specify` and `slice` would copy it. `build` SKILL.md is 8,183 B of its 8,192 B budget, so the rule-trace trigger cannot live there. A worktree session cannot write under the main checkout, and a glossary row written there by hand stays uncommitted across every `git switch` of a build.

## Alternatives rejected

- `specify` and `slice` dispatch `anomaly:plan` directly: lens and round logic written twice.
- The rule-trace step in `build`: over budget, and it changes the skill under switch-over judgement.
- `interview` edits `CONTEXT.md` at once and `specify` commits it: a commit outside `build`, on no defined branch in a team repo.

## Accepted risks

- [ ] A rules-mode High fix has no delta range, so its second pass re-reads the whole SKILL.md. Owner: VK · Revisit: 2026-11-05.
- [ ] The committed glossary lags the interview until the first ticket that needs a term merges. Owner: VK · Revisit: 2026-11-05.

## Revisit

When `conduct` exists, or 2026-11-05.

## Sources

Commits of the `workflow-plan` tickets: 01 (rule-trace pass), merge 4ab329f (d40b9f9, 774b7de); 03 (`log add`), merge 61113bf (e99f479, c65bcd1); 06 (plan agent), merge 7ec3e76 (55c69b5, 5d276ef); 07 (review modes), red commit 3c9d3bd and this ticket's merge. Also ADR-0011; `plugins/anomaly/tests/test_cli.py` (`SKILL_MAX_BYTES`); `plugins/anomaly/anomaly_loop/constants.py` (`REVIEW_MODES`).
