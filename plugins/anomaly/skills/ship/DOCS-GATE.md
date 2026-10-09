# Docs gate

Read at the ready gate only. Read-only: neither the scan nor the docs agent edits a file. [DA5]

1. Run the `docs scan` call of SKILL.md on `<base>...<head>`. [DA3, DD2] Re-run it for a ready MR's later push only when that push changed docs. [N3]
2. Exit 1 (a `[touched]` line): show each line and stop the gate. It goes on when the finding is fixed (a `build` light-path ticket, never an edit here; then scan again) or the user waives it. [AC-51, DA5]
3. Exit 0: show findings in untouched files; they do not stop the gate. Exit 2: an error; stop, print it. A unit's ADR findings are never `[touched]`.
4. A waiver is a finding the user accepts (for example a planted fixture line): one line in the Tested section, inside the result line.
5. The result line for `--docs-gate`: one plain line, the counts, `clean` when none, `waived: <path>:<line>` for each waiver, the agent counts when it ran. No private names.
6. `anomaly:docs` (checks 4 and 5) runs only when the user asks. [DA1, DD1] Its brief: the main checkout path, the range, the ADR folder from the `adr_folder` line of `ports` as printed (never guessed), a limit of 300 words, optionally the `docs scan` output; model: `model review`. [DA2] Relay the counts and the top 5 findings with `file:line`, as reported. [DA4] A High stops the gate like a `[touched]` line; lower findings are listed only. [DD1]
