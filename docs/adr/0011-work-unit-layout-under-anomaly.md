# ADR-0011: A work unit lives under `.anomaly/<work-unit>/`, and both layouts are read until the switch-over

Status: Accepted; partly superseded by ADR-0012 (the work-unit line is no longer only `{feature, stage, session, date}`) and by ADR-0014 (`worklog report` now reads `work-units.jsonl`, not `measure`) and by ADR-0015 (the `log.md` writer, `anomaly log add`) and by ADR-0016 (diagnose writes its loop script under `.anomaly/adhoc/` with Write) and by ADR-0017 (the work unit's file list gains `research/`, `mr-body.md` and `mr.md`) · Date: 2026-10-06 · Owner: VK · Revisit-by: 2026-11-05

## Context

Until now a feature's files sat in `.scratch/<feature>/`: `spec.md`, `issues/NN-*.md`,
`seams.md`, `digests/`. The rewritten pipeline needs more files per piece of work (the stories,
the decisions, an event log, the briefs) and a place for light-path tickets that have no
feature. The CLI also named `.scratch` in four places: the `ticket adhoc` path, the `tracker` and `issue_source` core
defaults, and the help and docstrings of `ticket` and `seams`.

Two limits shape the move. The `workflow-build` spec itself is built in the old layout and must
finish there (decision G2). A feature must be able to start in an old skill and finish in a new
one, so both layouts have to be readable while the old skills exist.

## Decision

- **The root is `.anomaly/`.** A work unit is a folder `.anomaly/<work-unit>/` with these files:
  `stories.md`, `decisions.md`, `tickets/NN-slug.md`, `log.md`, `seams.md` and `briefs/`. "Wave"
  stays the word for one round of tickets run together.
- **Light-path tickets** have no work unit. `ticket adhoc` writes
  `.anomaly/adhoc/<date>-<slug>.md` (`TICKET_ADHOC_DIR`). Run in a linked git worktree it writes
  under the main checkout, so a repository has one `.anomaly/adhoc/` and not one per worktree.
  Outside git, `--repo <folder>` still works and the file goes under that folder.
- **The core defaults of the `tracker` and `issue_source` ports** name the `.anomaly` layout, and
  the help texts and docstrings of `ticket` and `seams` name it too.
- **Both layouts are read until the switch-over.** Every `ticket` subcommand, `check pre-merge`
  and `seams` give the same result for a ticket in `.scratch/<feature>/issues/` and in
  `.anomaly/<work-unit>/tickets/`, and for a ledger in either place. The new skills read both:
  `build` needs only the ticket and the seam ledger; the cumulative `review` reads `spec.md` when
  it exists, else `stories.md` and `decisions.md`. `workflow-build` keeps the old layout; the new
  layout starts with the next work unit. "Until the switch-over" ends when the old skills are
  deleted (ADR-0008, ADR-0009).
- **Two logs, two jobs.** `log.md` holds events only, for people and agents, and no cost numbers.
  `<home>/work-units.jsonl` (ADR-0001) holds no cost numbers either, only `{feature, stage,
  session, date}` per stage run; cost is found by joining those lines with the session metrics
  (G17). `measure` does not read that file today (`worklog add` only writes it); it is meant to
  read it later. The work-unit JSON field stays `feature`: renaming it would break the lines
  already written.
- **`log.md` lines are written only through a CLI subcommand.** A worktree session refuses a
  Write under the main checkout, so a model cannot append to it directly. The subcommand is not
  built here; it is deferred (see Accepted risks).
- **Supersedes** `.scratch/anomaly-workflow/decisions.md:48` (§ Formats and environment, the
  first line: "Today's `.scratch/<feature>/` layout and line shapes stay") and the layout line of
  the `workflow-build` spec (§ Ticket line shapes: "Today's `.scratch/<feature>/` layout and line
  shapes stay"). The ticket line shapes themselves do not change.
- **`ticket result --merge`** accepts any commit ref (`HEAD`, a branch, a short id) and writes the
  full commit id, resolved through `gitrepo.require_commit` like `check`, `seams` and `ci`.
  `check pre-merge` runs `git update-index --refresh` first, so a file that is dirty by its stat
  only cannot make the merge that follows refuse; it should run in the checkout that will merge,
  and a lock on the index is an error, not a pass.
- **`ticket result` always needs a repository** (`--repo`, or the git top level of the working
  folder), because `--merge` is always resolved through git. A made-up hex `--merge` with
  `--changed-lines` outside git no longer works. This is an intended contract change (AC-99).
- **Each repository that uses the layout git-excludes `.anomaly/`**, because `ticket adhoc`
  writes untracked files into the main checkout. This repository already lists it in
  `.git/info/exclude`.

## Why

A root named for the plugin says the files are kept, not scratch, and one folder per work unit
keeps every file of a piece of work in one place for a person and for an agent. Reading both layouts is cheaper than a migration: the spec that builds the new
layout can finish in the old one, and the same ticket commands work on both, so no skill needs a
second code path in the CLI. Putting the light path at `.anomaly/adhoc/` under the main checkout
keeps those tickets in one place, where a worktree session that cannot write there can still
record state through the CLI. Events and cost are read by different consumers (people and
agents against `measure`); two logs keep a cost number from leaking into a file people edit.

`--merge` takes any ref because there should be one way to resolve a commit, the one `check`,
`seams` and `ci` already use, and `HEAD` was refused although the help named it as the default
(S1). The index refresh is there because a file that was dirty by its stat only, in a CRLF case,
stopped a merge that the check had passed (G33 E3).

## Alternatives rejected

- Keep `.scratch/` and add folders under it: the root would still say "scratch" for work that
  is kept.
- Move `workflow-build` to the new layout too: its tickets are in flight, and the move buys
  nothing the next work unit does not get.
- Rename the work-unit JSON field `feature`: breaks old lines for a name change.
- Put cost numbers in `log.md`: two sources of truth for cost, and one of them editable by hand.

## Accepted risks

- [ ] The `log.md` writer (a CLI subcommand) is not built. Until it exists, `log.md` has no
  writer and a session cannot append events to it. Owner: VK · Revisit: 2026-11-05
  (phase 3 or `conduct`).
- [ ] Two layouts are read until the old skills are deleted, so a ticket path can name either
  and a skill text has to name both. Owner: VK · Revisit: at the switch-over verdict (AC-78), or 2026-11-05.

## Revisit

When the old skills are deleted (drop the `.scratch` reading), or when the `log.md` writer is
built.

## Sources

Decisions G2, G9, G11, G12, G17 and G34 in `.scratch/workflow-build/status-2026-10-06.md` § 6
(git-excluded; G9 names `decisions.md:45` where this ADR and the spec use line 48, the first line
of § Formats and environment); `.scratch/anomaly-workflow/decisions.md` § Formats and
environment; `workflow-build` spec (`.scratch/workflow-build/spec.md`, § Work-unit layout, § Ticket
line shapes; ACs 87 to 90, 98, 99 and 102); ticket 13 (`.scratch/workflow-build/issues/13-work-unit-layout.md`);
the acceptance tests of ticket 13, commit 58bae8b, and the code, commit a427a6f; ADR-0001, ADR-0008, ADR-0009.
