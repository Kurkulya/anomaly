# UI check

The core default of the `ui_check` port: a walkthrough in the built-in browser; it needs no other checker. [N16, I27]

App facts come from the repo layer: dev server port, window width, theme key, known console error, login redirect. `build` passes you the `app` lines of `ports`. Never guess a fact; a missing one: ask the user.

For `build`, not the agent: build starts the dev server in the ticket's checkout before the dispatch (the start command from the repo's instruction file; none there: ask the user) and stops it after the report, before any worktree removal. The agent never starts or stops it. [P10]

1. Record the pane state first: size, visible or hidden, theme. A hidden pane gives no resize events and no animation-frame ticks. Measure resize and animation-frame values elsewhere, or mark them "not meaningful"; never report one as a finding. [N1, R10]
2. Take each UI acceptance criterion in turn. Ask for DOM proof first: the element, its text or attribute, read from the page. [R10]
3. A value that needs measuring: one JS measure call that returns all the numbers at once, not a call for each number. [R10]
4. Screenshots: ask for a stated scale (for example 0.5) so the files stay small. Save them in the session scratchpad. Never write an image with a shell redirection or a heredoc: take the file the browser tool saved and copy it with `cp`. Write text files with the Write tool. [R10, N12]
5. Console: report new errors; the known console error from the repo layer is not a finding. [R10]
6. A ticket with no visual change: take a before and an after screenshot of each affected screen, in pairs, and write `diff.md` in the same folder: one line for each pair, saying it is the same, with the reason. [R11]
7. Report each criterion as met or not met, with its proof (the DOM text, the number or the screenshot name). A criterion that cannot be judged says so; never call it met. [N16]
