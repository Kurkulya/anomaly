# ADR-0003: Free text is refused, not redacted, before it is stored in home

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2026-12-01

## Context

Anomaly and idea files are committed and may be shared. A review probe showed that `target`
and `scope` skipped the privacy check, and that a repository or session value could add a fake
sighting line (2f8bb2a).

## Decision

`plugins/anomaly/anomaly_loop/privacy.py` refuses, and never edits, text that holds
credentials in `name: value` or `name=value` form, URLs with a query string, email addresses,
pasted program output, or long opaque strings, so the writer rewrites it in their own words.
Repository, session and lens names are single tokens without the sighting separator. Raw
prompts stay only in the prompt cache under the data folder, redacted, pruned after 30 days.
Session ids and commit ids (7-12, 40 or 64 hex characters) pass.

## Why

Silent redaction hides what was stored and can still leave the meaning in place. A refusal
keeps the writer in control, and ordinary wording ("token cost grew") passes.

## Alternatives rejected

- A redaction gate that rewrites text: replaced in 2f8bb2a; it refused normal process wording
  and still let `name: value` credentials through.
- Trusting the skill wording alone.

## Accepted risks

- [ ] Long runs of only letters or only digits pass. Owner: VK · revisit 2026-12-01.
- [ ] 40 and 64 hex strings pass as commit ids. Owner: VK · revisit 2026-12-01.
- [ ] People's names are not detected; the skills tell the writer to keep them out.
  Owner: VK · revisit 2026-12-01.

## Revisit

When a secret or a person's name is found in `home` after a write that passed the check.

## Sources

Commits 2f8bb2a, f2cbc8b, ff57c15, 12c373a, 23c2988, 594c144. Design spec AC-11, AC-19 (kept
outside git, in `.scratch/anomaly-loop/spec.md`).
