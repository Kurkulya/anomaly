# Test-writer brief

Loaded at dispatch of the `test_writer` port: a separate agent, never the implementer. Fill each `<…>`. Pass the ticket and `seams.md` only, never the spec or stories file. [N7, AC-86]

- Ticket: <ticket path>. Write the acceptance test from its ACs: <AC ids>. Its dated `Amended` lines are later decisions.
- Seam ledger: <seams.md path>. Call its test helpers before you write one of your own. [I11]
- Extend an existing test of the behaviour first. Add a new test only when none exists, at the cheapest layer that proves it. An e2e test needs a stated reason. [AC-32]
- The test must fail now for the right reason: a missing feature, not an import, syntax or fixture error. Run only the test files you touched; say how many times you ran them.
- If the ticket has a `Repro:` line, its command (the text before ` (red now)`) is the red check: the committed test must fail for the same reason that command fails.
- Write no production code. Do not commit: the main window commits the test alone.
- Edit files only with Edit or Write, never with a shell edit or a heredoc. [X5]
- Send your report as your final message text: each test with `file:line`, why it fails, and the run count. [I13]
