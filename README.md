# anomaly

A Claude Code plugin that helps you work better with Claude Code. It has two halves:

- **Feedback loop.** It measures your sessions, records what went wrong and what went well, and
  runs a weekly review. Every fix is an experiment, checked against the numbers later.
- **Pipeline.** It takes one piece of work from an idea to a reviewed merge request that is
  ready to merge: interview, specify, slice, build, ship.

Python standard library only, no install step. The loop reads only your session transcripts and
its own records, never your product code.

## Install

Requirements: Python 3.13 and git 2.31 or later.

```
claude plugin marketplace add <path-to-this-repo>
claude plugin install anomaly@anomaly-local
```

Then run `/reload-plugins` in a session, or start a new session.

To update:

```
claude plugin marketplace update anomaly-local
claude plugin update anomaly@anomaly-local
```

Then start a new session and confirm the installed commit: `claude plugin list` shows it as the
`Version` of `anomaly@anomaly-local`.

## What's inside

### Feedback loop

| Skill | What it does |
|---|---|
| `anomaly:measure` | Turns your session transcripts into numbers: tokens, active time, friction, tools. No model cost. |
| `anomaly:observe` | Looks back over a session and records **anomalies**: things that went wrong, and wins worth keeping. |
| `anomaly:calibrate` | The weekly review. Ranks the backlog, fixes one batch, records each fix as an experiment. |
| `anomaly:assess` | Judges a new link, text or opinion against the recorded evidence, and keeps the verdict as an idea. |

Three hooks run without a model. The **weekly nudge** tells you in the first session of the week
when the backlog needs you. The **measure run** refreshes the metrics in the background at the
start of each new session. The **subagent Bash check** stops a subagent from writing files
through the shell.

### Pipeline

One **work unit** (a feature, kept in `.anomaly/<work-unit>/`) goes through these stages:

| Stage | Skill | What it does |
|---|---|---|
| 1 | `/anomaly:interview` | Turns an idea into settled decisions by asking you in rounds. |
| 2 | `/anomaly:specify` | Writes the stories and their acceptance criteria. |
| 3 | `/anomaly:slice` | Cuts the stories into tickets. Each ticket says what it covers and what blocks it. |
| 4 | `anomaly:conduct` | Runs the tickets in waves through `build`, on one integration branch. |
| 4 | `anomaly:build` | Takes one ticket from a red acceptance test to a reviewed, verified merge. |
| 5 | `anomaly:ship` | Opens the merge request as a draft and takes it to ready. |

Two skills help at every stage. `anomaly:review` sends the diff or the plan to the reviewer
agents (code, feature, security, plan) and returns their findings. `anomaly:diagnose` finds a
bug's root cause and leaves a ready ticket for `build`.

You start the first three stages by typing them; they are not in the skill list. `build`,
`conduct` and `ship` act only when you ask for them.

### Audits

| Skill | What it does |
|---|---|
| `anomaly:architecture` | Audits a repo in 7 areas against 6 principles, with a score and a lock for each area. |
| `anomaly:research` | Compares options or vendors in a decision matrix. Every claim has a source and a label. |
| `anomaly:tests` | Finds tests you can cut, on any stack. Each cut is proven by a deliberate break. Changes no code. |

## Quick start

**Feedback loop**

1. Work as usual for a few sessions.
2. Say "measure" to get fresh numbers.
3. At the end of a session, say "retro". `observe` records the anomalies.
4. Once a week, say "calibrate". The nudge reminds you.

**Pipeline**

1. Type `/anomaly:interview` and describe the idea.
2. Type `/anomaly:specify`, then `/anomaly:slice`.
3. Ask Claude to conduct the work unit. Each ticket gets built and reviewed.
4. Ask Claude to ship it.

## Configuration

- **`home`**: the folder for durable data (anomalies, metrics, your profile). It is the plugin's
  only setting. Default: `~/.claude/anomaly`. Put it under git if you want history.
- **Profile**: `<home>/profile.md` holds the facts about your environment: tracker, ticket key,
  branch pattern, merge request tool, models. Copy
  [the template](plugins/anomaly/templates/profile.md) and fill it in. Without a profile the
  skills still run and say which keys are missing.

The plugin itself holds no environment facts. Your own tools and names come in only through the
profile.

## Documentation

- [docs/reference.md](docs/reference.md): the full reference, with every skill, command, file
  format and rule.
- [CONTEXT.md](CONTEXT.md): the glossary.
- [docs/adr/](docs/adr/): why each decision was made.
- [plugins/anomaly/docs/formats.md](plugins/anomaly/docs/formats.md): the shapes of stories,
  tickets and the other planning files.

## Development

```
cd plugins/anomaly
python -m unittest discover
```
