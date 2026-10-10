# Ready gate

Read-only: neither the scan nor the docs agent edits a file. [DA5]

1. Run the `docs scan` call of SKILL.md on `<base>...<head>`. [DA3, DD2] Re-run it for a ready MR's later push only when that push changed docs. [N3]
2. Exit 1 (a `[touched]` line): show each line and stop the gate. It goes on when the finding is fixed (a `build` light-path ticket, never an edit here; then step 2 of SKILL.md again, before the push, then scan again) or the user waives it. [AC-51, DA5]
3. Exit 0: show findings in untouched files; they do not stop the gate. Exit 2: an error; stop, print it. A unit's ADR findings are never `[touched]`.
4. A waiver is a finding the user accepts (for example a planted fixture line): one line in Tested, inside the result line. Light path: the body has no Tested section, so show it as one chat line and record it with the `ticket amend` call of SKILL.md. [AC-51]
5. The result line for `--docs-gate`: one plain line: the counts, `clean` when none, `waived: <path>:<line>` per waiver, the agent counts if it ran.
6. `anomaly:docs` (checks 4 and 5) runs only when the user asks. [DA1, DD1, AC-52] Its brief: the main checkout path, the range, the `adr folder:` line `docs scan` prints (resolved, not the raw `ports` value), a limit of 300 words, optionally the `docs scan` output; `model review` and effort. [DA2] Relay the counts and the top 5 findings, `file:line` as reported. [DA4] A High stops the gate like a `[touched]` line; lower findings are listed only. [DD1]
7. CI, after `mr put`: the `ci watch` call of SKILL.md. No `origin`: skip it, say so (it exits 2). 0: go on ("no CI gate" if printed). 3 running: run it again. 5 no pipeline yet: run it again once; still 5: say so, go on. 1, 2, 4: stop, never green. [OM9]
8. Tracker re-check, after CI (read-only, `tracker` port): one line per AC added, removed or changed since the stories' `Gathered:` date; any such line stops the gate until the user answers. No tracker, no stories or unreadable: one line, skipped and why. [OM10, AC-56]
