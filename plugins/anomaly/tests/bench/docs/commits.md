# Commits of the docs fixture

Build a temporary git repository with two commits, in this order, with these messages. The first
holds `base/`; the second holds `change/` laid over it. Do not copy this file into the repository.
The agent reviews the whole history. Pass `docs/adr` as the ADR folder.

## 1. base

```
docs(notes): add the notes store and its two ADRs
```

## 2. change

```
refactor(notes): replace the per-call file read with an in-memory cache

A second read of the same file now costs nothing.
```
