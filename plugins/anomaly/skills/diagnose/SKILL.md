---
name: diagnose
description: Acts on a reported bug or a request to diagnose. Finds the root cause with a red-capable command, changes no source, and hands anomaly:build a ready light-path ticket.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
---

# diagnose

Starts on a reported bug or "diagnose"; changes no source. The issue and log sources are read only. Ids in brackets are for the rule trace. Small bug (the error names the file:line, a one-file fix): use the `build` light path, not this skill. [N2]

## The CLI calls

One plain command each, exactly in this form: no chains, inline code, pipe into an interpreter, heredoc or redirection. Free text goes in single quotes; write a ' as ’. No `python`: try `python3`. [as build N12] `<key>` is `<date>-<slug>`. Use the same slug for `worklog start`, `--slug` and `worklog add`; if the stem `ticket adhoc` prints differs, use that stem for `worklog add` (the start time is then lost). [N3] `<checkout>` is the repo of the bug.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog start <key> diagnose --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ports --home '${user_config.home}' --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket adhoc --from <draft file> --slug <slug> --repo <checkout>
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" ticket show <ticket> --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" worklog add --feature <key> --stage diagnose --session ${CLAUDE_SESSION_ID} --home '${user_config.home}' --data "${CLAUDE_PLUGIN_DATA}"
```

## Steps

1. Intake. Input: bug text, a ticket key or a CI log; read a key through the `gather` port. Ask only for what is missing. Redact secrets in shown output, the draft, the ticket and the loop script; read credentials from env vars, never write them into the script; if too little is left, say so and ask. [Q2, J6, D2] Choose the slug, then `worklog start` and `ports`. An adhoc ticket for this bug exists: `ticket show` it, then stop. [J3] Check `.anomaly/` is in `.git/info/exclude`, then record `git status`. [N5]
2. Facts. Read the glossary file (default `CONTEXT.md`) and the ADRs of the area. [D1] Trace the bad value back, compare working code, check recent changes. [S2] Facts only, with file:line. Facts come from `explore` sub-agents; the ranking and root cause stay in the main window. [N9]
3. Loop. Build one command that goes red on the symptom; run it before any hypothesis. Until step 5, no cause, guess or "likely" in chat or files. [D3] It is deterministic, fast, agent-runnable. [D9] Tighten it: faster, sharper; flaky: raise the repro rate. [D6] Try, in order: a failing test, a script against the running app, a log or request replay, a smaller input. [D4] Write the loop script with the Write tool to `.anomaly/adhoc/<key>-repro.<ext>` under the main checkout. In a worktree: stop, ask for the main checkout. Run it as one plain command, as in the CLI rules. [N7] Last resort: the user does the steps and pastes the result. A bug in real data: loop on a copy. A UI bug: record the pane state, then use the `ui_check` port. [N8]
4. Reproduce. Confirm the loop shows the user's symptom, not a nearby one. [D10] Cut the input down one part at a time until each part is needed. [D11] No loop possible: stop, list what was tried, ask for access, a redacted artifact or leave to add probes. [D8]
5. Hypotheses. Write 3-5 ranked, falsifiable ones ("if X, changing Y fixes it"). Show them in chat as a numbered list before the first probe, even if one looks certain. [D12]
6. Probe. One probe per prediction, one variable; use a debugger, not log floods. [D14] Tag each debug log `[DEBUG-xxxx]`. [D15] Performance: take a baseline, then bisect. [D16] Three refuted rounds: stop, report what is ruled out, ask. [N6]
7. Root cause and gate. Cite it as `file:line` or probe output; with neither, mark it "unverified". [N4] Name the fix, its scope (S/M/L) and the risk. L (over 5 files, cross-subsystem or schema work) is the feature path: stop and suggest `interview`. [J7, J8, J10] Name the seam where a test can catch the bug; if none is correct, that is a finding. [D17]
8. Handoff. Remove every probe edit and tagged log line. [D15] `git status` must match the intake record (clean, no new change); no branch, commit or push. [N5]
   - Write the draft with the Write tool to the scratchpad, in the light-path shape of [formats.md](../../docs/formats.md). Its `Repro:` line runs the red loop command (the script's absolute path, if any) for build's test writer. [N1, D18] Its Root cause section holds the cause. [D19]
   - `ticket adhoc --from` with the draft. Fix each named problem and run it again. [N1] It prints the path; run `ticket show` on it.
   - `worklog add`, stage `diagnose`, on every outcome, also when stopped. [N3]
   - Reply with 5 lines: symptom, repro, root cause `file:line`, fix and scope, next step. [N10]
   - Offer `/anomaly:build <adhoc ticket path>`; never start it. [N10]
