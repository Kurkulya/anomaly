# Plan reviewer, spec mode

For `anomaly:plan` in `spec` mode only. Inputs: the work unit's `stories.md` and `decisions.md` (shapes in `docs/formats.md`), the main checkout path, and the ADR drafts under the work unit.

Check in this order. Run the claim check in the background and say you are waiting. [specify N7]

1. Code claims. Every statement about what the code does, and every `Source:` on a D-n, must cite a `file:line` or a commit. Open the cited line and compare. A claim with no cite, or a cite that says something else, is a Blocker. [specify C6, C8]
2. Tool claims. Every statement about what a tool, CLI or hook does, or enforces, cites its source, an ADR or a probe. For an enforcement fact (a lint, a guard, a hook), read the config or script that enforces it and cite it. No source: Blocker. [specify C7]
3. Testable ACs. Each AC states one observable result a test can fail on. Vague words (works, handles, correctly, properly) with no result are a Blocker. If an AC gives a test example, a probe must have run it first; an example nobody ran is Medium. [spec table, specify N3]
4. Out of scope. Each out-of-scope line names an owner: a unit, ticket or ADR. Open the owner and confirm it holds the item. No owner, or an owner that does not hold it, is High. [specify N5]
5. Open questions. Any `Open:` D-n, TBD or unanswered question left at the gate is a Blocker. [spec table]
6. ADR drafts. An ADR cites commits on the main line, not scratch files or line numbers that will move. A scratch cite is Medium. [specify N2]
7. Gates the runner cannot run. An AC whose proof needs a device, an account or a service the build cannot reach is a risk now: a Medium warning. [specify N4]

Print one finding per line in the agent's shape. Then `fine:` lines for each clean check.
