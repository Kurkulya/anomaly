# ADR-0006: The pipeline depends on no third-party skill

Status: Accepted · Date: 2026-10-04 · Owner: VK · Revisit-by: 2027-01-04

## Context

The feature pipeline the plugin replaces (seven skills, from the planning interview to the merge
request) mixes the owner's own skills with a third-party skill set and an org plugin. The
third-party skills were patched from outside: the global config added the `AC-n` prefix, the
`Sources:` header, the `Covers:` and key lines and a claim review on top of their templates. They
also changed under the owner: two of them are slash-only and stayed invisible to the agent, one
was split into two skills, and the phase-boundary rules lived in the
third-party plugin's own file. The workflow audit of 2026-10-04 counts these overlays as a source
of drift (U8).

## Decision

- The pipeline skills (`interview`, `specify`, `slice`, `build`, `conduct`, `review`, `ship`,
  `diagnose`), the reviewer agents and the pipeline docs are written in the owner's own words.
- They depend on no third-party skill in any way: not at run time, not as an optional profile key,
  not as a referenced document. A rule they need is stated in their own text.
- Org skills and agents still take part, but only through a port (ADR-0007).

## Why

A pipeline that breaks when an upstream skill is renamed, split or hidden cannot be measured or
moved to another job. Owning the text also removes the overlay layer: the template and the
parser that reads it agree because one author writes both.

## Alternatives rejected

- Fork the third-party skills: the owner would carry every upstream change by hand.
- Name optional helper skills in profile keys: the same breakage on a rename, only quieter.
- Keep the current mix and patch it from the global config: the drift the audit found.

## Accepted risks

- [ ] Upstream improvements no longer arrive by themselves. Owner: VK · revisit 2027-01-04
  (assess the upstream changes since 2026-10-04 with the `assess` skill).
- [ ] Rules carried over from third-party skills may lose nuance in the rewrite. Owner: VK ·
  revisit at each phase's switch-over (the rule trace review checks every kept rule).

## Revisit

When an upstream release adds something the pipeline lacks, or at the date above.

## Sources

Workflow audit 2026-10-04 (`.scratch/anomaly-workflow/audit-2026-10-04.md`, U8); design
decisions of the same day (`.scratch/anomaly-workflow/decisions.md`, git-excluded).
