# ADR-0002: A title is at most 80 characters

Status: Accepted · Date: 2026-03-02 · Owner: maintainer

## Context

Titles are shown in a one-line list, so a long title breaks the layout.

## Decision

- `append_note` in `notes/store.py` refuses a title longer than 80 characters with a `ValueError`.

## Why

The limit is checked where the note is written, so no long title can reach the file.
