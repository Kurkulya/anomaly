# ADR-0017: The key line and the ADR folder come from ports; a work unit gains `research/`, `mr-body.md` and `mr.md`

Status: Accepted · Date: 2026-10-09 · Owner: VK · Revisit-by: 2026-12-01

Decision: two new `REPLACE` ports, `key_line` (core default `Key`) and `adr_folder` (core default `docs/adr/`), name the ticket key line and the folder ADRs are moved into; the CLI still reads a `Jira:` key line until the switch-over. A work unit folder gains `research/NN-slug.md` (conduct's research notes), `mr-body.md` (written only by `mr body`) and `mr.md` (`Reviewed:`, `Verified:` and `MR:` lines of the unit's MR, written only by the CLI); `check pre-push` reads `mr.md`.
Why: a vendor name in core text and a fixed ADR folder are org facts, which belong in the profile (ADR-0001, ADR-0007); the MR head of a work unit had no file that records its review and verify, so the "review before push" invariant could not be enforced from files and git.
Revisit: when a tracker needs more than a line name (a key format or a link), when an org keeps its ADRs outside the repo, or 2026-12-01.

## Context

The ticket key line is the literal `Jira:` in the ticket parser, `check slice` and `formats.md`, which says it holds a key "until the tracker port (phase 2, D-11) names the key line". ADR drafts move into a fixed `docs/adr/`, which `check stories` also searches. Every port value is one free-text line, so a line name cannot be read out of the `tracker` text.

ADR-0011 lists the files of a work unit: `stories.md`, `decisions.md`, `tickets/`, `log.md`, `seams.md`, `briefs/`. Phase 2 adds `conduct` and `ship`, which need a place for research notes, the MR body file, and a record of the MR head's review and verify. A ticket's `Reviewed:` and `Verified:` lines name the ticket tip, not the integration tip that the MR shows.

## Decision

- `constants.PORTS` gains `key_line` (profile key `key_line`, core default `Key`) and `adr_folder` (profile key `adr_folder`, core default `docs/adr/`). `ports` prints both.
- The ticket parser, `ticket show` and `check slice` read the key from the `key_line` line; a ticket with only `Jira:` is read the same way until the switch-over, like the two layouts of ADR-0011.
- `check stories` resolves `ADR-NNNN` and the ADR number search in the `adr_folder` folder and in the `adr/` of every unit folder.
- A work unit folder may hold `research/NN-slug.md`, `mr-body.md` and `mr.md`. `mr-body.md` is written only by `mr body`; `mr.md` only by `mr put`, `mr reviewed` and `mr verified`. An ad-hoc ticket keeps its MR files as siblings in `.anomaly/adhoc/`: `<stem>.mr-body.md` and `<stem>.mr.md`, where `<stem>` is the ticket file name without `.md`.
- `check pre-push` passes a unit only when `Reviewed:` and `Verified:` in `mr.md` name the current head; for a light-path ticket it reads the ticket's own lines.
- Partly supersedes ADR-0011 (the work unit's file list).

## Why

A port keeps the org fact in the profile and leaves one owner for the line name. Two separate ports, not a parsed `tracker` value, keep every port value one line. Reading the old `Jira:` line costs one fallback and spares a migration of every closed ticket. A file in the unit, written by the CLI, keeps the MR state with the other state in files and git, and a worktree session can still write it through the CLI.

## Alternatives rejected

- Keep `Jira:` as the core line and let an adapter rename it: a vendor name stays in core text.
- Parse the key-line name out of the `tracker` port text: the first structured value in a free-text port.
- Record the MR head's review and verify on home work-unit lines: the gate would depend on home, outside the repo and git.
- Check only that every merged ticket was reviewed: a commit after the ready gate passes unchecked.

## Accepted risks

- [x] Two key-line names are read until the switch-over, so a ticket text may hold either. Owner: VK · Revisit: at the switch-over, or 2026-12-01. Closed 2026-10-09: see Consequences.
- [ ] An org that keeps its ADRs outside the repo (a wiki) gets the core folder; reading such ADRs stays with the `gather` port. Owner: VK · Revisit: 2026-12-01.

## Revisit

When a tracker needs more than a line name, when an org keeps its ADRs outside the repo, or 2026-12-01.

## Sources

ADR-0001, ADR-0007, ADR-0011; main at 914b3b8 (`plugins/anomaly/anomaly_loop/constants.py` `PORTS`, `ticket.py` `HEADER_KEYS`, `check.py` `ADR_GLOBS`, `docs/formats.md` § Ticket).

## Consequences

- The merged-ticket rule that ADR-0014 names as `worklog.run_report` now lives in `worklog.read_report`, which `conduct status` shares with `worklog report`.
- 2026-10-09: no switch-over ran (ADR-0008, Consequences), so the `Jira:` line is no longer read in place of
  the key line: the key is read only from the line the `key_line` port names. An org whose tickets keep a
  `Jira:` line sets `key_line: Jira` in its profile.
