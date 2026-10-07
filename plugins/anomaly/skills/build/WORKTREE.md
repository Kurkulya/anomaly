# Worktree commits

Loaded only inside a worktree. Pass this recipe to the implementer too; the message-file, `--no-verify` and hook pre-run rules are in BRIEFS.md. [P13, P15, N4]

1. Commit with the worktree's own hooks: `git -c core.hooksPath=<worktree>/<hook_path> commit -F <msg file>`, `<hook_path>` from the `command hook_path` line. An empty or foreign hooks path skips the hooks, the same as `--no-verify`: when the repo has hooks and the line is empty, stop and ask. [P13]
2. Check each commit before the next `git add`: `git log -1 --format=%s`. A hook rejection leaves its files staged: run `git reset -q`, fix the cause, stage again. [P15]
3. To stage part of a file, write the hunks to a patch file with the Write tool, run `git apply --cached <patch file>`, then check `git diff --cached`. [N4]
4. `.scratch` and `.anomaly` live in the main checkout: pass the CLI absolute paths. [O8]
