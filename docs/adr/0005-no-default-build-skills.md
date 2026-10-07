# ADR-0005: The plugin ships no default build-skill list

Status: Accepted · Date: 2026-10-04 · Owner: VK

## Context

A session's kind is `build` when it used one of the build skills. The plugin shipped the
default list `('implement', 'orchestrate-tickets')`, which are the owner's own user skill
names. The plugin must hold no values that belong to one person's or one organisation's setup
(ADR-0001: environment facts live in the profile).

## Decision

`constants.BUILD_SKILLS` is empty. The profile key `build_skills` names the build skills; with
no such key, no session counts as `build` (only an override, `config` or `unknown`). The
owner's profile sets `build_skills: implement, orchestrate-tickets`, so their digest and
calibrate results do not change.

## Why

Any default list would encode one workflow's skill names into a plugin meant to work in other
setups. A missing key gives a visible result (no build sessions) instead of a silently wrong
one.

## Alternatives rejected

- Keep the two names as a "generic" default: they are the owner's skills, not a convention.
- A guessed default from common skill names: still a guess about one setup.

## Accepted risks

None open.

## Revisit

If the plugin is shared and new users find the empty default confusing.

## Sources

Commit 241c66d; docs audit 2026-10-04; owner's decision in the session that wrote ADR-0001 to
ADR-0004. Refines ADR-0001 (does not supersede it).
