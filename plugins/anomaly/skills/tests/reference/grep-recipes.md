# Grep recipes — finding candidates

A grep finds candidates. It never decides a class. The agent reads each candidate test
before it writes a row. Use `git grep` (tracked files only), cap output with `| head -50`
or `-c`, and write the command next to every count (tag it [C]).

The recipes for one stack (counts, EMPTY-ASSERTION, INTERNALS, DUPLICATE, e2e) are in its
stack profile, `reference/stacks/<stack>.md`. This file holds the shared ones.

The patterns are portable ERE: `grep -E`, `[[:space:]]`, no `\s`, `\b` or `\|`. Folder
names in the recipes (`.husky`, `.vite-hooks`) are examples; use the folders `facts` found.

**At the tip sha.** The recipes search the working tree. They are valid only when
`git rev-parse HEAD` equals the Phase 0 sha and `git status --porcelain
--untracked-files=no` matches `evidence/status-0-tracked.txt` (untracked test outputs do
not count). If not:

- add the sha: `git grep -n <pattern> <sha> -- <paths>`. Hits then start with `<sha>:`,
  so every field shifts by one. Pipe through `sed 's/^<sha>://'` before any
  `awk -F:` total or `sort -t: -k2`;
- use `git ls-tree -r --name-only <sha>` instead of `git ls-files` (it reads the index,
  not the sha);
- read files with `git show <sha>:<path>`.

Static counts count an `.each` table once. Say "static" next to such counts; runtime
counts come from the reporter (`timing.md`).

## Shared

```bash
# The repo's reason list. None found -> the topic map's fallback applies; say so.
# '*.md' on purpose: the list may live outside docs/adr (a README, CONTEXT.md, a test doc).
git grep -nliE "reason list|browser-only|device-only|@reason-|reason-[a-z]" -- '*.md' | head
# Characterization candidates: tests added in refactor commits, or tests that say so.
# <test globs> come from the stack profile.
git log --diff-filter=A -i --grep=refactor --grep=characteri --format='--%h %s' --name-only -- <test globs> | head -60
git grep -niE "characteri[sz]|pins? (the )?current behaviou?r|before (the )?refactor" -- <test globs> | head
# Is that refactor finished? Read its ticket in .anomaly/*/tickets/*.md (git-excluded, so
# use Glob and Read, not git grep): Status: done means finished. Or read the later commits:
git log --format='%h %ad %s' --date=short -- <refactored source file> | head
# Tooling tests: tests outside product code.
git ls-files | grep -E "(^|/)(scripts|tool|tooling|mocks?|fixtures)/" | grep -E '<test file pattern>' | head -50
# Does that tool gate CI or ship? No hit in CI, hooks or build config -> dev-only.
git grep -n '<tool or script name>' -- .github .gitlab-ci.yml .husky .vite-hooks lefthook.yml package.json 'vite.config.*' pubspec.yaml
```
