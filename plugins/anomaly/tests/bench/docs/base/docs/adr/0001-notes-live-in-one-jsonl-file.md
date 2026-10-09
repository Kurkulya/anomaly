# ADR-0001: Notes live in one JSON-lines file

Status: Accepted · Date: 2026-03-02 · Owner: maintainer

## Context

The keeper has one user and a few hundred notes. A database would be more machinery than the data needs.

## Decision

- Every note is one line of `notes.jsonl`, written by `append_note` in `notes/store.py`.
- `list_notes` in `notes/store.py` returns the notes newest first.
- Nothing else writes the file.

## Why

One plain file is easy to back up, to read by eye and to repair by hand.
