# anomaly

A Claude Code plugin marketplace with one plugin, `plugins/anomaly/`: skills, agents, hooks and a
Python CLI (`scripts/anomaly.py` → `anomaly_loop/`). The README is the full reference.

## Commands

```
cd plugins/anomaly
python -m unittest discover
```

Standard library only; no install step.

## Where things live

- `plugins/anomaly/anomaly_loop/` — CLI code; `tests/` — unittest suite and bench fixtures.
- `docs/adr/` — the why of each decision. `CONTEXT.md` — glossary.
- `.anomaly/` — work units (stories, tickets, briefs). Git-excluded (ADR-0011):
  they exist only in the local checkout, never in a clone.

## Rules

- **Tracked text holds no org facts**: no employer, product, repository or colleague names, no
  local paths. `tests/test_neutral.py` guards plugin files.
- **Edit cited files last.** Docs cite other files by `file:line`. Never insert lines above a
  cited line; append, or re-check every cite below the insert.
- **Fix cheap Lows before the merge.** At a ticket's close, fix the cheap Low and Nit review
  findings in the same change; ask only about items that need a decision.
- **Show every case in a display choice.** When asking how output should look, show the exact
  line for every code path the choice touches, not one example.
- **Read shared links in full** before reporting on them; say so if only a summary was seen.
- **Before calling a skill missing**, find its `SKILL.md` on disk; slash-only skills are not in
  the skill list.
- **Windows paths in scripts**: write backslash paths with an editor tool or a raw string, never
  through `sed` or a plain Python literal. Write files with `newline='\n'`.
