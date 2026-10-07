# Stage boundaries

Where each planning stage ends, and what the user is offered next.

- `interview` ends when the user confirms the closing table of decisions. It writes `decisions.md`.
- `specify` ends when `stories.md` passes the spec gate: every claim checked, no open question. It may
  draft ADRs and add decisions.
- `slice` ends when the user approves the ticket list and the tickets gate passes. It writes the
  tickets.
- `build` starts from one ticket; it is not a planning stage.

Each stage ends with one line naming the next skill (shape in `formats.md`).

## Context

- Never offer `/clear` between `interview`, `specify` and `slice`. The next stage needs what the
  last one found, so all three run in one window.
- Offer `/clear` once, after `slice`, because the tickets are self-contained. The model never runs it;
  only the user does.
- Plan in one window up to about 150k tokens of context. Past that zone, finish the stage at hand,
  write its files and tell the user a fresh window is the safer place for the next one.
