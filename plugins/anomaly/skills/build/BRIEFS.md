# Implementer brief

Loaded at dispatch of the `implementer` port. Fill each `<…>`; leave out a line that does not apply. Pass the ticket and `seams.md` only, never the spec or stories file. [AC-86, K2]

- Ticket: <ticket path>. Its dated `Amended` lines are later decisions. Branch: <ticket branch> in <checkout>.
- The failing acceptance test: <test path>. Do not edit it; if it looks wrong, stop and say why. [N7]
- Seam ledger: <seams.md path>. Call its owners, test helpers included, before you write a helper of your own. [I11]
- Red-Green-Refactor. No scope creep. Give `file:line` for each change.
- Run only the tests you touched or added; never the full suite or e2e: the main window runs them once. Do not pre-run what the commit hook runs. Report how many times you ran tests and type-checks. [I12]
- When the ticket reads or writes real files: one probe on a copy of real data; report what it showed. [N2]
- Run final gates in the foreground. Never end your turn with a background command still running. [N3]
- Before you write what a tool checks or enforces, read its config or script and cite it. [X4]
- Edit files only with Edit or Write, never with a shell edit or a heredoc. Each command is one plain command: no chains, no inline code, no pipe into an interpreter. [X5, N12]
- Commits: <commit port format>, atomic, no AI trailers. Write the message to <scratchpad>/msg-<NN>-<n>.txt with the Write tool, then commit with `-F <file>`. Never `--no-verify`. Never push. [I28, P14, P16]
- Inside a worktree: <the WORKTREE.md recipe>.
- Codegen: after a merge that touched its inputs, run <the `command codegen` line> (pending verdict, I38).
- Merge conflict at close: merge <integration tip> into your branch, run your touched tests, report the new tip. [P8]
- Send your report as your final message text, also after each follow-up. [I13]
