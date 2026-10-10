# anomaly

A personal Claude Code plugin with two halves. A **feedback loop** measures, observes and
calibrates how you work with Claude Code: the agent's environment, the workflow, cost and speed,
and the loop itself. A **pipeline** takes a piece of work from an idea to a reviewed, ready merge
request. The vocabulary is in [CONTEXT.md](CONTEXT.md).

The loop keeps one backlog of **anomalies** (things that went wrong, and wins worth keeping) and
runs over it:

1. **measure** turns your session transcripts into numbers, at no model cost.
2. **observe** looks back over a session and records anomalies.
3. **calibrate** is the weekly review: it ranks the backlog, helps you fix a batch of
   problems, and records each fix as an experiment that is checked against the numbers later.

Two more pieces sit around the loop. **assess** judges something new (a link, a text, an
opinion) against the recorded evidence and keeps the verdict as an idea. A once-a-week
**nudge** tells you in the first session of the week when the backlog needs you. The loop never
reads the product work itself, only the transcripts and its own records.

The pipeline runs one **work unit** (a feature, kept in `.anomaly/<work-unit>/`) through its
**stages**:

1. **interview** turns an idea into settled decisions by asking you in rounds.
2. **specify** writes the stories and their acceptance criteria.
3. **slice** cuts them into tickets that each say what they cover and what blocks them.
4. **conduct** runs the tickets in waves through **build**, which takes one ticket from a red
   acceptance test to a reviewed, verified merge into the work unit's integration branch.
5. **ship** opens the one merge request as a draft and takes it to ready.

**review** dispatches the reviewer agents at each gate, and **diagnose** finds a bug's root cause
and leaves a light-path ticket for `build`. Each stage writes a work-unit line, so the loop can
read what each piece of work cost, and each reviewer's accepted and rejected findings, so the loop
can judge the reviewers. Org-specific tools and names come in through **ports** in a profile kept
outside the plugin.

This repo is a local marketplace (`anomaly-local`) that holds one plugin, `anomaly`.
Read this file from top to bottom: install, configure, then the data, then each part of the
loop in the order you meet it, then the pipeline, from tickets to the stage skills.

## Install

Requirements: Python 3.13, standard library only; git 2.31 or later (`ports` names a repository
with `git rev-parse --path-format=absolute`, added in 2.31).

Use the path of this folder (the checkout) on your machine.

```
claude plugin marketplace add <path-to-this-repo>
claude plugin install anomaly@anomaly-local
```

Inside a running session, run `/reload-plugins` (or start a new session). The four skills,
`anomaly:measure`, `anomaly:observe`, `anomaly:calibrate` and `anomaly:assess`, should now be
listed, and the pipeline skills `anomaly:build`, `anomaly:conduct`, `anomaly:review`,
`anomaly:ship` and `anomaly:diagnose` beside them. `/anomaly:interview`, `/anomaly:specify` and
`/anomaly:slice` are slash-only: they are not in that list, and you start them by typing them.

The marketplace points at a folder on disk. Skills are read from that folder when you run
`/reload-plugins`, so editing a skill needs no new version. If a change does not show up after a
reload (a hook, for example), reinstall the plugin from the marketplace. If you move or delete
this checkout, the marketplace breaks until you add it again from the new place.

## Configuration

The plugin declares one `userConfig` value, `home`: the folder for all durable loop data.
Default: `~/.claude/anomaly`. The plugin expands a leading `~` itself, because it is not
known whether Claude Code expands it in a default value
([ADR-0001](docs/adr/0001-durable-data-in-home.md)). Claude Code does not fill the
`${user_config.home}` placeholder in skill text, even when `home` is set (an accepted risk in
ADR-0001); the script then treats it as unset, uses the default and prints one line first:
`home: placeholder unfilled, using <path>`. So a skill command ignores a non-default `home`,
while hooks read it. Check the resolved path
after the first run: `measure` prints the metrics file it wrote.

| Where | What | Location |
|---|---|---|
| home | durable: anomalies, ideas, metrics, lens, session-kind and work-unit lines, profile (see Data layout) | `userConfig.home` |
| data folder | throwaway state: the scan state (`measure-state.json`), the prompt cache (`cache/prompts.jsonl`, redacted, pruned after 30 days), the nudge marker (`nudge-week`), the per-run lens counts (`lens-tally.jsonl`, written by `lens tally add`) with the batch built from them (`lens-batch-<session>.json`, written by `lens tally sum`), the stage start times (`worklog-starts.jsonl`, append-only, written by `worklog start` and `worklog add`), and the per-session files the skills write (`<skill>-<purpose>-<session>.<ext>`: `observe-batch-<session>.json`, `assess-source-<session>.txt`, `assess-body-<session>.txt`) | `${CLAUDE_PLUGIN_DATA}` |

The data folder must not be inside home: throwaway state is never written into `home`, and a
command stops with an error if the data folder is inside home. Keep `home` under version control if you want
history; the commands that write records commit only the files they wrote (see the parts of
the loop).

How the folders are found: `--home` falls back to the environment variable
`CLAUDE_PLUGIN_OPTION_HOME` (set for hooks only), then `~/.claude/anomaly`. `--data` falls
back to `CLAUDE_PLUGIN_DATA` (also set for hooks only, not for Bash commands); with neither,
the command stops with an error. `--projects` (the transcript root) falls back to
`ANOMALY_PROJECTS`, then `~/.claude/projects`. `--user-config` (your Claude Code folder, used by
the digest and calibrate) falls back to `ANOMALY_USER_CONFIG`, then `~/.claude`.

The loop's thresholds and time windows live in one file,
`plugins/anomaly/anomaly_loop/constants.py`. The scanner limits of `metrics.py` and the text
limits of `privacy.py` are kept in those two modules.

## Profile

Environment facts live in `<home>/profile.md`, outside the plugin, so the plugin stays
generic. A template is in [`plugins/anomaly/templates/profile.md`](plugins/anomaly/templates/profile.md).
Without a profile the skills still run and say once which keys are missing. A profile that is
not UTF-8 text is read as empty, and that line says so. Copy the template to
`<home>/profile.md` and replace the placeholder values.

Format: a block between two `---` lines, one `key: value` per line; an indented line
continues the previous value; a line that starts with `#` is a comment. A key that is
absent, blank or still a `<placeholder>` counts as missing.

| Key | Meaning |
|---|---|
| `tracker` | where work items live |
| `glossary_file` | the repo-root file with the project vocabulary |
| `ticket_key` | regular expression for one ticket key; `measure` uses it for `ticket_keys` (default `[A-Z][A-Z0-9]+-\d+`) |
| `branch_pattern` | how branches are named |
| `commit_style` | how commit messages are written |
| `implementers` | the agent that writes code, per stack (one `stack: agent` per indented line, with a space after the colon) |
| `mr_tool` | the MR tool: `glab` or `gh` (the adapter of the `mr` port, see MR) |
| `verify_ui` | the skill or tool that checks a user interface |
| `issue_source` | where requirements come from, and whether they are read-only |
| `build_skills` | optional: skills that mark a session as build work, as a comma or line list. The plugin ships no default list: without this key no session counts as build. The digest and `calibrate` read it (see Session kind) |
| `plugin_repo` | optional: the plugin's folder inside its git checkout, for example `<checkout>/plugins/anomaly` (a leading `~` is expanded). Used only when the installed plugin is a git-ignored copy and so has no repository of its own; a real checkout of the plugin uses its own folder and repository. With neither, the checks that need the plugin repository are skipped and one notice line says so |
| `test_writers` | optional port: the agent that writes acceptance tests, per stack (one `stack: agent` per indented line, with a space after the colon) |
| `conventions` | optional port: an org conventions source per stack, read after the repo's own docs (one `stack: source` per indented line, with a space after the colon) |
| `reviewers` | optional port: reviewers added beside `anomaly:code`, `anomaly:feature` and `anomaly:security`, as a comma or line list |
| `gather` | optional port: context skills added beside reading the repo's code and docs, as a comma or line list |
| `ci` | optional port: the CI tool the CI step watches and reads logs with; the only value today is `glab` (the GitLab CLI), see CI |
| `models` | optional: the model per dispatch role, one `role: model` (or `role: model effort`) per indented line; roles `explore`, `implement`, `implement_wide`, `digest`, `review`, `review_code`, `review_feature`, `review_security`, `deep_analysis` (also written `deep analysis` or `deep-analysis`), `browse`; effort `low`, `medium`, `high`, `xhigh` or `max` |
| `key_line` | optional port: the name of the ticket line that holds the key (core default `Key`) |
| `adr_folder` | optional port: the repo-relative folder ADR drafts are moved to, and where `check stories` looks up `ADR-NNNN` owners (core default `docs/adr/`) |

After changing `ticket_key`, run `measure --full` so old rows are rescanned.

There are nine required keys (`tracker` to `issue_source`) and ten optional ones
(`build_skills` to `adr_folder`). The pipeline reads some of them as ports (see Ports and the
repo layer).

## Ports and the repo layer

The pipeline reads org values only through **ports**, never from its own text
([ADR-0007](docs/adr/0007-one-plugin-ports-and-adapters.md)). Each port has one fixed mode and a
**core default** that works with an empty profile. An **adapter** is a profile value; one that
is absent, blank or still a `<placeholder>` leaves the port on its core default, and the
command never guesses one.

```
python plugins/anomaly/scripts/anomaly.py ports --home <dir> [--repo <dir>]
```

| Port | Mode | Profile key | Core default |
|---|---|---|---|
| `implementer` | replace, per stack | `implementers` | general-purpose agent with the build brief |
| `test_writer` | replace, per stack | `test_writers` | a separate general-purpose dispatch with the test-writer brief, never the implementer |
| `conventions` | extend, per stack | `conventions` | the repo's own docs, only the sections the diff touches |
| `reviewers` | add | `reviewers` | `anomaly:code`, `anomaly:feature`, `anomaly:security` |
| `gather` | add | `gather` | read the repo's code and docs |
| `tracker`, `issue_source` | replace | `tracker`, `issue_source` | local `.anomaly` markdown, read-only |
| `ci` | replace | `ci` | no CI gate |
| `mr` | replace | `mr_tool` | print the MR body to paste |
| `commit`, `branch` | replace | `commit_style`, `branch_pattern` | `type(scope): summary`, `feat/<slug>` |
| `ui_check` | replace | `verify_ui` | built-in browser walkthrough of the ticket's UI ACs; its app facts come from the repo layer |
| `key_line` | replace | `key_line` | `Key`: the name of the ticket line that holds the key |
| `adr_folder` | replace | `adr_folder` | `docs/adr/`: the repo folder ADR drafts are moved to; `check stories` looks up `ADR-NNNN` owners there |

Replace: the adapter takes the core default's place. Add: the adapter's names (separated by
commas or lines, optionally inside one pair of `[ ]`) are listed after the core default's.
Extend: the adapter's source is listed after the repo's own docs. A per-stack port reads one
`stack: value` line per stack, with a space after the colon (so an id such as `pack:agent` is not
read as a stack); a stack named twice keeps its last value. A line without a stack, or a value
written on the key line itself (`implementers: some-agent`), is the adapter of the port's line
without a stack, which stands for every stack not named. A replace port takes one such line: with
two or more, `ports` stops with one `anomaly:` line naming the profile key (other commands use the
first line). An extend port lists every such line after the repo's own docs. The `models` and
`ui_check:` blocks follow the same `name: value` rule.

**Model roles.** `models` maps each role to a model, and optionally an effort: a role value is
`<model>` or `<model> <effort>`, the effort one of `low`, `medium`, `high`, `xhigh` or `max`
(`review: opus high`). Any other shape, such as `sonnet for contained tickets`, stops `ports` with
one `anomaly:` line naming the role. Without the key: `explore` haiku, `implement` sonnet,
`implement_wide` opus, `digest` sonnet, `review` opus, `deep_analysis` opus,
`browse` sonnet. `review_code`, `review_feature` and `review_security` are optional per-lens
roles: one the profile leaves out takes the value of `review` and prints the source of `review`
too (`[profile]` when the profile sets only `review`). A model or effort change is a measured
experiment ([ADR-0018](docs/adr/0018-model-changes-are-measured-experiments.md)). `ports` warns
when `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (the profile's models have no effect) or
`CLAUDE_CODE_EFFORT_LEVEL` (the profile's efforts have no effect) is set.

**Repo layer.** The commands `verify` (the full verify), `e2e`, `install` and `codegen` run from
the repository root. `hook_path` is not a command: it is a folder relative to the repository
root (for example a folder of hook shims), which `build` passes as
`git -c core.hooksPath=<worktree>/<hook_path> commit`. A `hook_path` that is absolute, holds a
space or leaves the root with `..` stops `ports` with one `anomaly:` line naming where it came
from. They come from three tiers; the first tier
that names one wins, and inside a tier the sources are read in the order listed:

1. **Explicit.** In `CLAUDE.md`, then `AGENTS.md`, a line `<label>: `<text>``, optionally a
   list item, the label optionally in bold. Labels: `verify`, `e2e`, `install`, `codegen`, and
   for the hook folder `hook path`, `hook_path`, `hook-path` or `hooks path`, in any case. No
   other text is read. Then a `package.json` script or a `Makefile` target named exactly
   `verify`, `e2e` or `codegen`, as `<manager> run <name>` or `make <name>`.
2. **The override file** `<home>/repos/<repo>.md`.
3. **Guessed**, printed with the source `guessed from <file>`: a `package.json` script or a
   `Makefile` target named `test` (verify), `test:e2e` (e2e) or `generate` (codegen);
   for a `package.json` the manager's frozen install, which keeps the lockfile as it is and runs
   no package scripts: `npm ci --ignore-scripts` for `package-lock.json`, else
   `<manager> install --frozen-lockfile --ignore-scripts` (the Yarn 1 flags for `yarn`); with
   no lockfile there is nothing to freeze, so it is `npm install --ignore-scripts`; the
   `Makefile` target `deps` (install; `install` targets usually install the program itself, so
   they are not read); for a `pubspec.yaml`, `flutter test` / `flutter pub get` when it declares
   `sdk: flutter`, else `dart test` / `dart pub get`, and the `build_runner` command as codegen
   when it names `build_runner`. The package manager follows the lockfile (`yarn.lock`,
   `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `package-lock.json`), else `npm`. An install command the repository
   names itself, or the override file, wins over the guess.

A command no tier names is printed as unresolved. Repository files are read as UTF-8 (a byte
order mark and CRLF lines are fine); a repository file that is not UTF-8, or a `package.json`
that is not JSON, stops `ports` with one `anomaly:` line naming it. Reading the repo layer
writes nothing, in the repository or in home. Precedence: repo layer > profile adapters > core
defaults; the profile holds no commands.

`<repo>` is the last part of the `origin` remote URL without `.git`; without an `origin`, the
folder name of the main checkout (so all worktrees of a repository share one file); outside
git, the folder's own name. The override file, with every key optional:

```
---
verify: <full verify command>
e2e: <area e2e command>
install: <install command>
codegen: <codegen command>
hook_path: <hook folder, relative to the repository root>
base: <base branch>
ui_check:
  port: <app port>
  width: <viewport width>
  theme_key: <theme storage key>
  console_error: <known console error to ignore>
  login_redirect: <path the app redirects to for login>
risk_patterns:
  - <extra risk pattern>
---
```

`base` is the branch `build` cuts the integration branch from. Without it, the base is the
branch `refs/remotes/origin/HEAD` points at (a clone sets it, `git remote set-head origin`
changes it; a fetch does not), else `main`. A blank or placeholder value counts as not set.

`risk_patterns` is a list of fnmatch globs matched against the changed paths (repository-relative,
forward slashes); a trailing `/` matches everything under that folder. The `risk` command adds
them to its core patterns.

**Output.** One line per entry, `<section> <name> = <value> [<source>]`; an unresolved command
has an empty value. Sections in order: `port` (a per-stack adapter as `port <name>.<stack>`),
`repo` (`name`, `override`, `base`), `command`, then `app` and `risk` (only what the override file
sets), then `model`. Sources: `core default`, `profile`, `core default + profile`; the file a
command came from, `override`, `guessed from <file>` or `unresolved`; for the name `origin`,
`checkout` or `folder`; for the override file `found` or `absent`; for the base `override`,
`git` or `core default`. With an empty profile, in a repository with no commands:

```
port implementer = general-purpose agent with the build brief [core default]
port test_writer = a separate general-purpose dispatch with the test-writer brief, never the implementer [core default]
port conventions = the repo's own docs, only the sections the diff touches [core default]
port reviewers = anomaly:code, anomaly:feature, anomaly:security [core default]
port gather = read the repo's code and docs [core default]
port tracker = local .anomaly markdown, read-only [core default]
port issue_source = local .anomaly markdown, read-only [core default]
port ci = no CI gate [core default]
port mr = print the MR body to paste [core default]
port commit = type(scope): summary [core default]
port branch = feat/<slug> [core default]
port ui_check = built-in browser walkthrough of the ticket's UI ACs [core default]
port key_line = Key [core default]
port adr_folder = docs/adr/ [core default]
repo name = demo [checkout]
repo override = <home>/repos/demo.md [absent]
repo base = main [core default]
command verify = [unresolved]
command e2e = [unresolved]
command install = [unresolved]
command codegen = [unresolved]
command hook_path = [unresolved]
model explore = haiku [core default]
model implement = sonnet [core default]
model implement_wide = opus [core default]
model digest = sonnet [core default]
model review = opus [core default]
model review_code = opus [core default]
model review_feature = opus [core default]
model review_security = opus [core default]
model deep_analysis = opus [core default]
model browse = sonnet [core default]
```

## Data layout

Everything under `home`:

| Path | What |
|---|---|
| `anomalies/<signature>.md` | one anomaly per file (format below) |
| `ideas/<slug>.md` | one assessed idea per file (format below) |
| `INDEX.md` | the ranked backlog, generated by `index`; do not edit by hand |
| `metrics.jsonl` | one row per main session: counts, normalized shapes and identifiers only |
| `lenses.jsonl` | one line per reviewer per session: `{session_id, date, lens, accepted, rejected}`, plus `revised` when the review passed it |
| `session-kinds.jsonl` | manual session kinds: `{session_id, kind, set_on}`; the last line for a session counts |
| `work-units.jsonl` | one line per pipeline stage run: `{feature, stage, session, date, ended}`, plus `started`, `doc_bytes`, `ticket` and `mode` when they apply; written by `worklog add` |
| `profile.md` | the profile (see above) |
| `repos/<repo>.md` | optional: the personal override file of one repository (see Ports and the repo layer); never committed to that repository |

### Anomaly file

A frontmatter block, then the text:

```
---
signature: slow-check
kind: problem
category: automated-checks
target: scripts/check.sh
scope: global
impact: 2
occurrences: 3
effort:
status: open
first_seen: 2026-09-01
last_seen: 2026-10-02
fixed_by:
experiment:
  expect: the check finishes in under a minute
  metric: active minutes
  guard: rework sightings
  kind: build
  check_by: 2026-10-25
  result:
---
One paragraph: what went wrong, or what went well.

## Proposed fix
Run the fast suite first.

## Sightings
- 2026-10-02 · <repo> · <session> · what happened, newest first
```

- `signature` is also the file name: lowercase words (letters or digits) joined by hyphens.
- `kind` is `problem` or `win`; a problem has a `## Proposed fix` section.
- `target` is the skill, agent, hook, rule or file the anomaly is about; it may stay blank.
- `impact` is 1 to 3; `occurrences` is the number of sightings.
- `effort` stays blank until `calibrate` sets `S`, `M` or `L`.
- `status` is `open`, `reopened`, `fixed` or `wontfix`.
- `fixed_by` stays blank until the fix lands; `calibrate fix` then writes it as
  `YYYY-MM-DD · <ref>`: the day the change landed, then its commit id or file. The date is
  what an experiment is measured around. An older value without a leading date (just a commit
  id or a note) stays valid, but such a fix has no date to measure from.
- `experiment` is optional. `metric` and `guard` are names from the metric registry (see
  calibrate). `kind` is optional: the session kind (`build`, `research`, `config`, `debug`,
  `unknown`) the change is measured on. `skill` is the new skill of a switch-over (see
  calibrate). `declared_on` is the day `calibrate declare` wrote the
  experiment. `result` is blank until checked, then `keep`, `revert`, `inconclusive` or
  `unproven` (kept, but not proven: see Verdict), and `reason` is the verdict's one-line reason.
  `kind`, `skill`, `declared_on` and `reason` are optional and written only when set, so older
  files keep their shape.
- When a new experiment replaces a finished one, the old one becomes one line under
  `## Earlier experiments` (result, the whole `fixed_by`, metric, guard, expectation, skill, reason),
  newest first, so a reverted attempt stays on record.

Categories: `navigation`, `automated-checks`, `coding-standards`, `steering-files`,
`tool-economy`, `no-ops`, `information-access`, `rework`, `late-catch`, `handoff-loss`,
`manual-step`, `blocked`, `pipeline-fit`.

The score of an anomaly is impact × occurrences. It is worked out each time the backlog is
read and never written into the file, so it cannot go stale. Writing a record with an
unknown category, kind, status, effort or an impact outside 1 to 3 fails.

### Idea file

`assess` keeps one file per judged input, `ideas/<slug>.md`. An idea is not an anomaly.

```
---
slug: faster-checks
source: https://example.com/post
assessed: 2026-10-04
verdict: park
revisit: 2026-12-01
related:
  - slow-check
  - scripts/check.sh
scores_at_assessment:
  slow-check: 3
---
The idea in your own words: what it claims, why it was parked.
```

`verdict` is `adopt`, `trial`, `park` or `reject`. `related` holds anomaly signatures and
targets. `scores_at_assessment` holds the score each related anomaly had when the idea was
assessed; the command fills it in. The body is written in the assessor's own words and holds at
most one short quote (at most 15 words: a block of `> ` lines, or a span of 4 or more
words in straight double, curly double or curly single quotes). A link is stored without its query string (only a
digest of it, see assess).

## The loop

Measure, observe, then calibrate, once a week or whenever you like. The digest is what
calibrate opens with, the nudge reminds you to start it, and assess runs only when you hand it
something new. Each part below says what it does, what it writes and which command the skill
runs.

### measure

`measure` reads the Claude Code transcripts on this machine, counts each API call once, and
upserts one row per main session into `metrics.jsonl`: tokens, active time, friction (interrupts,
denials), tools, skills and the ticket keys found in branch names (from the profile's
`ticket_key`). Nothing goes to a model, and a row holds only counts, normalized shapes and
identifiers, never the text of your work. The scan is incremental; `measure --full` rereads
everything (also needed after `ticket_key` changes). The skill is `anomaly:measure`; run it
first, because the digest and `calibrate` read these rows (`calibrate` runs it for you).

The `subagents` object of a row counts the spawns (`count`, `by_type`, `by_model`,
`stopped_by_user`) and, in `seconds_by_type` and `seconds_by_model`, adds up how long they ran:
a spawn's seconds are the latest minus the earliest timestamp of its `agent-*.jsonl` file, rounded
to a whole second, summed per `agentType` and per `model` (`unknown` when the `.meta.json` has
none). A spawn file with fewer than two timestamps adds 0. Rows scanned before these two keys
existed lack them; `measure --full` adds them, but only for transcripts still on disk.

After `weighted tokens:`, the summary prints one `subagent seconds:` line: the `seconds_by_type`
of all rows added up per agent type, largest first (for example
`subagent seconds: Plan 90, Explore 60, general-purpose 10`). Types with equal totals are ordered
by name. The total covers only rows that carry the key, so run `measure --full` once after the
upgrade to fill the older rows. When no row carries a seconds value, the line is left out.

The next line is `subagent seconds by model:`, the same sum over the `seconds_by_model` of the
rows that carry it, largest first and then by name (for example
`subagent seconds by model: haiku 90, sonnet 60, opus 10`). Rows without that key are skipped, so
old rows still read, and the line is left out when no row carries it.

Whether a session used a skill is answered from `skills_invoked` and `slash_commands`
together (`metrics.skills_used`). That set is for membership checks only: it holds both the
bare and the plugin-qualified name and includes built-in commands. To rank skills, use each
row's `tokens_by_skill`.

### observe

`observe` is the skill that turns a session into anomalies. Say "retro" (or "run the observe
skill") at the end of a session: it looks back over two passes, the agent's environment (seven
categories) and the workflow (six), records wins as well as problems, and treats your
interrupts, rejections, corrections and praise as the strongest evidence. Each candidate is
sorted into anomaly, memory or both (memory is how the agent behaves next time; an anomaly is
what the environment must change; a "both" memory names the anomaly's signature). You get one
table (signature, kind, category, target, scope, impact, `new` or `matches (n seen)`) and one
question; nothing is written before your answer. For a session other than the current one, one
`anomaly:digest` agent on the `digest` model role reads the transcript and returns a digest, so the transcript never enters the
main window. "log this: ..." records one sighting with no questions and a one-line reply.
The skill also records lens stats (one line per reviewer, accepted and rejected) and lets you
correct a session's kind. The `review` skill records its own lenses itself, under the fixed names
that `lens tally add` holds (see lens tally).

The judgement is the skill's; the writing is a script. Two subcommands, used by the skill:

```
python plugins/anomaly/scripts/anomaly.py observe list  --home <dir>
python plugins/anomaly/scripts/anomaly.py observe apply --home <dir> --file <batch.json | ->
```

- `observe list` prints one line per anomaly (open ones by score, then closed ones) so a new
  sighting can be matched by root cause, and the missing-profile line when keys are missing.
- `observe apply` records one batch: `{"sightings": [...], "lenses": [...], "kind": {...}}`,
  every key optional. The whole batch is checked first; nothing is written if any part is
  invalid. A sighting whose signature exists adds one occurrence, sets `last_seen`, puts the
  sighting first, and may raise `impact` (never lowers it); a `fixed` anomaly becomes
  `reopened`, and a `wontfix` one keeps its status and is reported. A new signature creates the
  file. A session counts once per anomaly and once per lens, so repeating a batch changes
  nothing. Lens lines go to `lenses.jsonl` and a kind override to `session-kinds.jsonl`.
- The index is regenerated, and when `home` is inside a git repository only the paths that
  were written (and `INDEX.md`) are committed, as `chore(anomaly): log <what>`; other changes in
  the repository stay as they are. A failed commit leaves the files written and says so.
- Privacy: sightings, summaries, fixes, targets and scopes are one short line each, in the
  writer's own process wording. Repository, session and lens names are single words, so no
  value can add a line to a sighting. The `privacy` module refuses text that holds a credential
  in `name: value` form, a URL with a query string, an email address, pasted program output or
  an opaque string, instead of altering it, so it can be reworded
  ([ADR-0003](docs/adr/0003-privacy-refuses-not-redacts.md)). Opaque means a segment of 20
  or more characters between `/ . - _ =` that mixes letters with digits, a run of 32 or more
  characters made of 3 or more such mixed parts, or a base64-like run (paths, kebab-case names,
  camelCase identifiers and settings like `NAME=value` pass). Session ids and git commit ids (40
  or 64 hex characters, or a short 7 to 12) are allowed; other long hex strings are not. A long
  run of only letters or only digits passes (a known gap). People's names are not
  detected; the skill tells the writer to keep them out.
- The 13 categories split into `ENVIRONMENT_CATEGORIES` (7) and `WORKFLOW_CATEGORIES` (6) in
  `constants.py`.

### The digest: trends

`digest` opens with direction. Five sections come first, all computed from files, at no
model cost:

- **Trends**: for each session kind, the median of weighted tokens, active minutes and
  denials, and the mean of interrupts, over the last 14 days, next to the same number for the
  14 days before. The header says which is which: `(median, n = sessions; interrupts: mean)`.
  Interrupts are a mean because they are 0 in nearly every session, so their median never
  moves. Every value shows its sample size (`n=`), because a value from two sessions is a hint,
  not a result ([ADR-0002](docs/adr/0002-every-fix-is-an-experiment.md)). A line with at least
  `VERDICT_MIN_SAMPLES` (5) sessions in both windows ends with a percentage and a verdict word.
  The percentage is `(from 0)` when the earlier value is zero and the later one is not, and
  there is none when both are zero. The word is `→ real change` or `→ within noise`, by the same
  rule as the verdict of an experiment (see Verdict: two-way test at 10%, a change of 15% or
  more, 5 sessions per window; [ADR-0009](docs/adr/0009-verdicts-use-a-permutation-test.md)).
  With fewer than 5 sessions in either window a line shows no percentage and no word. A session
  belongs to the window of the day it started on, in the same clock as today's date; both ends
  of a window count. Each kind is a bold label.
- **Top skills**: the three skills with the most weighted tokens in the last 14 days, ranked
  by each row's `tokens_by_skill`, with the number of sessions they appeared in.
- **Experiments due**: experiments whose fix has landed and that are ready to be judged
  (the rule is in the calibrate section; the nudge uses the same rule). A line that is due for
  a reason other than its check date says why.
- **Experiment results**: one line that counts the current experiments by result:
  `keep N · unproven N · revert N · inconclusive N · pending N` (`pending` is an experiment
  with no result yet). `unproven` is its own count and is never added to `keep`. An earlier
  experiment kept under `## Earlier experiments` is not counted.
- **Tried and reverted**: experiments with the result `revert`: anomaly, target, metric,
  check date, the first line of the proposed fix and the verdict's reason; then one `earlier:`
  line for each reverted attempt kept under `## Earlier experiments`. It is information only
  and never blocks a new proposal.

A section with nothing to show is left out, except Experiment results, which always shows.

**Session kind** is never stored in a metrics row; it is worked out when it is read, so it
also works for older rows. The order is: an entry for the session
in `session-kinds.jsonl` (the last line wins); else a build skill used in the session
(`build`); else a first working folder inside the Claude Code user folder (`config`); else
`unknown`. The build skills are the ones named by the profile key `build_skills`; the plugin
ships no default list, so without that key no session counts as build. A skill counts as
used when it was invoked or typed as a slash command, with
or without its plugin name. The rules live in one place, `trends.py`; other code asks it for a
kind and does not repeat them.

### The digest: flags

The digest sections that say what needs attention. The thresholds are in `constants.py`;
the numbers below are the default values.

**Needs rework.** The targets named by anomalies are checked. A target is flagged when it has
3 or more commits in the last 28 days in its git repository, or 3 or more open or reopened
problems. Where a target's repository is found:

- a path (with a separator, starting with `~`, or absolute) is the repository that holds it; a
  relative path is looked up under the user config folder, then the plugin folder, then the root
  of the plugin's checkout (so `plugins/anomaly/skills/measure/SKILL.md` works too); a bare
  file name that exists under the user config or plugin folder is treated as a path;
- `plugin:skill` is a skill of that plugin (the plugin name is matched in any case); a bare
  `skill` is a skill of this plugin or, if there is none, of the user config folder. The commits
  counted are those that touched the skill's folder. A plugin skill uses the plugin's repository (the checkout, or the profile's
  `plugin_repo` for an installed copy); a user skill uses the user config repository;
- anything else (free text, another plugin's skill) has no repository, and only its open
  problems are counted. When the plugin's repository cannot be found, the digest says so once
  and skips the plugin-skill checks.

A target created or rewritten in the last 14 days is not flagged for its commits. "Rewritten" is
read from the commit days alone: a run of activity is a series of commits no more than 28 days
apart, and a target is new or rewritten when its newest run began less than 14 days ago. A new
target starts a run, and so does an old one that comes back after a quiet spell; steady patching
stays one long run and is flagged. A target with no git history gets no grace. The grace covers
only the commit count: 3 or more open or reopened problems always flag the target.

**Repeated actions.** A normalized prompt, a command shape, a tool trigram or a slash command
seen 3 or more times in 2 or more sessions in the last 14 days. Prompts come from the prompt
cache in the data folder (without a data folder they are skipped, and when the section has other
lines it says so), the rest from the metrics rows. Command shapes are ranked by the number of
sessions they appear in, and shapes that only read (`sed -n`, `grep`, `cat`, `head`, `tail`, `ls`,
`git log`, `git show`, `git diff`, `git status`) or only set a shell variable (`S=<str>`) are
skipped. Prompts that start with `<` (harness or command markup) are skipped too; `measure` no
longer caches them, but older cache lines may still hold them. Slash commands count only when they
are a skill: a `plugin:skill` name, or a bare name of a skill of this plugin or of the user config
folder; other bare names are built-in commands. A prompt is printed cut to 80 characters. Each line
names the lightest form that fits and why: a script for a command, a hook or lint rule for a
tool sequence, a pointer in a steering file for a short prompt or a slash command, a skill for a
long prompt. An agent is never proposed here. Trigrams of one tool
repeated three times are left out, and so are rows scanned before the `tool_trigrams` field
existed (older rows lack it; `measure --full` adds it for transcripts still on disk).

**Stale, near-duplicates, lenses.** Open problems seen once and last seen more than 60 days ago
are offered as `wontfix`; wins and anomalies seen more than once are never offered. Two open
anomalies of the same kind are near-duplicates when they share a target and category and their
summaries or proposed fixes share at least 30% of their words, or when their signatures share at least 60% of their words; records that are linked this way are printed
as one group, 5 groups at most. Each review lens
shows accepted findings over all findings, summed over `lenses.jsonl`.

**Unused plugin skills.** A skill of this plugin with no use in the last 56 days is proposed for
removal. Its start is the first commit of its folder in the plugin repository, so nothing
qualifies in a skill's first 56 days. Use is the plugin-qualified name (`anomaly:measure`) in the
session's skills or slash commands, or the bare name (`measure`, as typed) unless the user config
folder has a skill of that name. Nothing is judged unless the
measured sessions cover the whole 56 days. A skill with a win of 2 or more sightings is listed as
protected instead of proposed. Hook runs are not in transcripts and are not counted.

### The weekly nudge

```
python plugins/anomaly/scripts/anomaly.py nudge --home <dir> --data <dir> [--user-config <dir>] [--plugin-root <dir>]
```

`plugins/anomaly/hooks/hooks.json` runs this at the start of a new session (the `startup` source only, not
resume or clear). In the first session of an ISO week it prints one line when an open problem
has a score of 4 or more, or an experiment is due; otherwise nothing. The week is marked in
`nudge-week` in the data folder the first time it runs, even when there was nothing to say.
It uses no model: the line is a JSON `systemMessage`, which is shown to you and not added to
the model's context (plain output from a start hook would be). The hook gets `home` and the data
folder from `CLAUDE_PLUGIN_OPTION_HOME` and `CLAUDE_PLUGIN_DATA`, which Claude Code sets for hook
processes, and starts `python` from the `PATH` without a shell. On a system where the command is
only `python3`, change `command` in `plugins/anomaly/hooks/hooks.json`.

### calibrate

`calibrate` is the weekly review. Say "calibrate" or "review the backlog" (or follow the
nudge). The skill is `anomaly:calibrate`; it runs only when asked. It runs `measure`, shows the
digest, tidies the backlog, lets you pick one batch of problems to fix, and records every fix
as an experiment. A script does the ranking, the recording and the arithmetic:

```
python plugins/anomaly/scripts/anomaly.py calibrate plan    --home <dir>
python plugins/anomaly/scripts/anomaly.py calibrate effort  --home <dir> --set <signature>=S|M|L [--set ...]
python plugins/anomaly/scripts/anomaly.py calibrate declare --home <dir> --signature <s> --expect '<effect>' --metric '<name>' --guard '<name>' [--kind <kind>] [--skill <new skill>] [--check-by <date>] [--effort S|M|L] [--approved]
python plugins/anomaly/scripts/anomaly.py calibrate fix     --home <dir> --signature <s> --ref <commit or file> [--date <date>]
python plugins/anomaly/scripts/anomaly.py calibrate verify  --home <dir> --signature <s>
python plugins/anomaly/scripts/anomaly.py calibrate decide  --home <dir> --signature <s> --result keep|revert
python plugins/anomaly/scripts/anomaly.py calibrate close   --home <dir> --signature <s> [--signature ...]
python plugins/anomaly/scripts/anomaly.py calibrate merge   --home <dir> --into <stays> --from <folded in>
```

Every action also takes the `--data`, `--user-config` and `--plugin-root` options of `digest`.
Every action that writes regenerates `INDEX.md` and, when `home` is in a git repository,
commits only the files it wrote, with `chore(anomaly): calibrate <what>`.

**Plan.** First the housekeeping, each list from the digest section that owns it:
near-duplicates (merge), stale anomalies (close), experiments due (verify) and unused plugin
skills (removal). Then the open and reopened problems in batches: a `repo:` or `plugin:` scope
is one batch; any other scope (`global` and the like) is split by target (`target: <target>`),
and problems without a target share one `untargeted` batch. The batches are ranked by the summed
score of the problems that can be fixed now; inside a batch the order is score, then the lower
effort (`S`, `M`, `L`, then not set). The plan ends with the metric names, the allowed guards and
the number of sessions per kind in the last 28 days. Marks on a problem:

- `waits`: a problem in a workflow category (`rework`, `late-catch`, `handoff-loss`,
  `manual-step`, `blocked`, `pipeline-fit`) is fixed only with score 4 or more, or impact 3.
  Below that it is listed but adds nothing to its group's score, and `declare` refuses it.
- `tried before`: an experiment on this anomaly or on the same target was reverted earlier.
- `protected`: a win with 2 or more sightings is about this target; it is not proposed for
  removal unless you override that explicitly.
- `experiment drafted`: an adopted idea left a draft experiment; `declare` completes it and keeps
  the drafted values you do not replace.

**Declare, then change, then record.** `declare` writes the experiment before the change: the
expected effect, exactly one primary metric, exactly one guard, the session kind, `declared_on`
(today) and, only when given, `check_by`. The guard must be a quality signal: `rework sightings`,
`late-catch sightings` or `interrupts`. `declare` refuses a second `--metric` or `--guard`, a
missing guard, any other guard, an unknown metric name, a guard equal to the metric, a win, a
closed anomaly, and an anomaly whose experiment is still running. It says how many sessions of
the chosen kind ran in the last 28 days, and warns below 20, the number an experiment waits for
(then leave the kind out). When the metric or the guard counts sightings and the backlog does
not yet cover the 28 days before today, it names the first fix day that can be judged on them
and suggests the `interrupts` guard; it says nothing of the kind when the metric is
`sightings since the fix`, which needs no baseline. A finished
experiment is moved to `## Earlier experiments` and the new one takes its place. A target that is
part of this plugin (`anomaly:<skill>` in any case, or a path inside the plugin folder or its
checkout) needs `--approved`: the loop proposes changes to itself and applies them only after
your explicit yes. After the change, `fix` writes `fixed_by` as `YYYY-MM-DD · <ref>` and sets the
status to `fixed`. It refuses an experiment that `declare` did not write, and a `--date` before
`declared_on`. A blank `check_by` becomes the fix day + 21 days.

**A switch-over** replaces an old build skill with a new one
([ADR-0013](docs/adr/0013-switch-over-compares-skills.md)). Declare it with `--kind build --skill
<new skill>`; the profile's `build_skills` must name the new skill beside the old one, and both
stay there until the old skill is deleted (`declare` refuses `--skill` without `--kind build` or
when `build_skills` does not name it). The skill, not the date, then splits the sessions: before
is every build session that did not run the new skill, from 28 days before the fix day to today,
so the old skill's sessions that run beside the new one count; after is every build session since
the fix that ran the new skill and nothing else a `build_skills` name matches. A **fall-back**, a
session that ran the new skill beside another build skill, is in neither side; `verify` prints how
many as `- fall-backs: N (in neither side)`. A session that ran the new skill before the fix day
(a dogfood run) and the fix day itself are in neither side too. A sighting counts only for a
session on its side: a sighting of a session that was not measured, or that is on neither side,
counts on neither. Record the switch-over's `fix` with `--date` the day after the last dogfood
session and `--ref` the merge into `main`, before the first real-ticket session. `declare`, `fix`
and `verify` each say which sessions are compared. In the experiment lines (Experiments due, Tried
and reverted) a switch-over shows its progress, `n/20 <skill> sessions, m fall-backs`, in place
of its check date. Once its check date has passed without 20 new-skill sessions, it is listed
under Experiments due with `stalled: due only after 20 new-skill sessions`, so a switch-over that
stalls still shows; it is still not due.

**Metric registry.** A metric or a guard is one of these names (case and outer spaces do not
matter). Fewer is better for all of them.

| Name | Read as |
|---|---|
| `weighted tokens`, `active minutes`, `denials` | the trend metrics of one session, compared as medians over the sessions |
| `interrupts` | the trend metric of one session, compared as the mean per session: it is 0 in nearly every session, so its median would never move |
| `weighted tokens without security` | a session's weighted tokens less those of the core security reviewer (`anomaly:security` in the row's `tokens_by_agent`; a row without that entry keeps its whole weighted tokens), compared as medians. For a switch-over, which adds the security reviewer as new coverage ([ADR-0013](docs/adr/0013-switch-over-compares-skills.md)). Not a digest trend; read like weighted tokens, with active minutes beside it |
| `sightings since the fix` | the anomaly's own sightings. As the primary metric (a rare-event metric, for a fix that moves no number) it is judged by whether the anomaly came back, not as a rate (see Verdict) |
| `<category> sightings`, for example `rework sightings` or `late-catch sightings` | sightings of problems in that category, per session |

User corrections and review misses reach the backlog through `observe` as rework and late-catch
sightings, so those two are the usual guards. Sightings are rare, so a sighting metric is read as
a rate (sightings over sessions) and tested as the mean of the sightings of each measured
session, not as a median. A sighting from a session that was not measured still counts in the
shown rate but not in the test; the reading says how many were left out of the test. With a
`kind`, only sessions of that kind count, and a sighting from a measured session of another kind
is left out of both. A window that starts before the backlog's first sighting reads as unknown,
not as zero: the backlog did not exist then. So a fix can be judged on a sighting metric only 28
days after the backlog's first sighting; before that, an experiment that would otherwise be
inconclusive says the backlog does not cover the baseline (a worse metric, guard or time still
reverts). The one exception is a `sightings since the fix` primary: it needs no baseline, so a
backlog that does not cover the 28 days before the fix never makes it inconclusive.

**Due.** An experiment is due when its fix has landed (`fixed_by` is set), it has no result, and
either its `check_by` date has come or 20 sessions of its kind started after the fix day (this
needs a `kind` and a dated `fixed_by`; with only 5 sessions after the fix, even a real -50% is
almost never seen). A switch-over is due only after 20 sessions on its after side, sessions that
ran the new skill and no other build skill; its check date alone never makes it due. An
`inconclusive` experiment is due again when its moved
check date comes, for your decision. A draft without a fix is never due. The digest, the nudge
and `calibrate verify` all use this one rule (`trends.experiment_due`).

**Verdict.** `verify` compares the 28 days before the fix day with the days after it, up to
today (a switch-over splits by skill instead, see above). The fix day itself is in neither
window, because a date cannot say whether a session came before the change or after it ([ADR-0002](docs/adr/0002-every-fix-is-an-experiment.md)). Your
sessions vary a lot by themselves, so a fixed bar such as 15% would call many moves that are
only chance. `verify` asks instead how often chance alone would give such a change
([ADR-0009](docs/adr/0009-verdicts-use-a-permutation-test.md)):

- **Chance alone.** `verify` pools the sessions from before and after the fix, splits them at
  random again with the real group sizes, and counts how often a split changes at least as much
  as the real one. The share is printed as "N% of random splits change this much" (rounded up).
  Every split is counted when there are 10,000 or fewer; otherwise 10,000 random splits are
  drawn with a fixed seed, so the same data always gives the same answer, and the real split is
  counted too, `(hits + 1) / (10,000 + 1)`, so chance alone is never 0. Each window is read as
  the median of its sessions, or the mean for `interrupts` and for sighting rates.
- **Real change or within noise.** The metric, and active minutes when the metric is weighted
  tokens (with or without security), show a **real change** only when chance alone is 10% or less
  (in either direction), the change is 15% or more, and each side has at least 5 sessions. From an earlier value of 0, any
  rise meets the 15% and the line says `from 0`. Anything else is **within noise**, and that also
  covers a change under 15% even when chance alone is 10% or less. With fewer than 5 sessions on
  a side, the line shows only the values and sample sizes.
- **The guard is tested one way**, for "did it get worse?". It is `worse` only when chance alone
  for a rise at least as large is 10% or less, the rise is 15% or more, and each side has at
  least 5 sessions. A fall is never `worse`, so a guard is never `better`, only `worse` or
  `same`. A sighting guard that would be `worse` but has fewer than 2 of its sightings since the
  fix is `thin`: it cannot count as worse, though a worse primary metric still reverts, and it
  stops a `keep`.

When goals conflict, quality comes first, then your time, then tokens:

1. the guard got worse: `revert`;
2. the metric is weighted tokens (with or without security) and active minutes got worse: `revert`;
3. the metric got worse: `revert`;
4. the metric made a real change for the better, the guard held (`same`) and, when the metric is
   weighted tokens (with or without security), active minutes held too (better or the same): `keep`;
5. anything else: `inconclusive`. The check date moves out 21 days, once. When it comes again
   and the numbers still cannot say, you decide with `decide`.

**A rare-event primary.** When the metric is `sightings since the fix`, an anomaly has only a few
sightings, and no count of one or two can prove that a fix worked. So `verify` uses no test and
no baseline. A worse guard still comes first and gives `revert`. Otherwise one or more sightings
of the anomaly after the fix day (a sighting from a measured session of another kind is left
out) give `revert`, with the reason that it came back. If there are none, the result is
`unproven`: kept, but not proven, because chance alone would also explain the quiet. Only a worse guard blocks this; a guard that
cannot be judged yet (the backlog is too young, or too few sessions or sightings) is named in the
reason. `unproven` is written like `keep`: the anomaly stays fixed, the experiment is not due
again, and a later sighting reopens the anomaly as it does for any fixed one.

Every reason ends with the rule that produced it, `permutation test, ADR-0009` or
`rare-event rule, ADR-0009`, so a result written under the older 15% rule can be told apart.

`verify` prints the metric and the guard (and active minutes when the metric is weighted tokens,
with or without security), each as
`<metric> (<role>): <before> (n=<n>) before, <after> (n=<n>) since, <change>; <N>% of random
splits change this much → real change` (or `within noise`). The change is `+N%` or `-N%`,
`from 0`, or left out from 0 to 0. It adds a note only when chance alone is 10% or less but the
tested sessions moved the other way than the shown change (sightings left out of the test made the
shown change), and how many sightings were left out of the test. A rare-event primary
shows its values, sample sizes and `sightings since the fix: N` on its reading line, with no
chance alone and no verdict word. For any other metric, after the readings it prints a separate
line with the anomaly's sightings since the fix; then it writes the result with its reason. When
the anomaly has sightings on the fix day, it says how many and that the verdict does not count
them (they are in neither window), and when one of them is what reopened the anomaly, it says
that too. On a guard line, `→ real change`
means the one-way test passed (the guard is worse), even when the result is `inconclusive`
because a sighting guard is `thin`. `revert` reopens the anomaly. `decide` is accepted once the
moved check date of an inconclusive result has come, or when an experiment is due but its metric
or fix date cannot be measured (older records).

**Housekeeping writes.** `effort` sets the effort of several anomalies in one step. `close` marks
anomalies `wontfix`. `merge` adds the sightings of one anomaly to another (occurrences added up,
the higher impact, the newer last-seen date) and marks the folded one `wontfix` with a
`## Merged` note that names where it went.

### assess

`assess` judges something new (a link, a pasted text, or an opinion such as "I think reviews
are too slow") against what the loop has recorded, and keeps the verdict as an idea. Say
"assess <link>", "evaluate this link" or "what do you think of ...". The skill is
`anomaly:assess`; it runs only when asked.

What the skill does:

1. Checks whether the input was assessed before. A link is compared after cleaning it up
   (scheme, `www.`, user name, trailing slash and a plain `#anchor` are dropped; tracking
   parameters `utm_*`, `fbclid`, `gclid` and `ref` are ignored; any other query, and a routing
   fragment `#/...` or `#!...`, are kept only as a short digest, so two videos or two items on
   one site stay two keys); a text is compared by its lower-case words. A repeat shows the
   earlier idea and stops.
2. Reads it. A long page is read by one `anomaly:digest` agent on the `digest` model role that returns a short digest.
3. Weighs it: the open anomalies it would address, the metrics it would move, what it
   conflicts with (recorded decisions, plugin rules, wins), and the strongest case against.
4. Proposes a verdict and, after the user's answer, records it:
   - `adopt`: writes an anomaly with a drafted experiment (`expect`, one `metric`, one `guard`;
     `check_by` stays blank, so the draft is never due before the fix is made) for `calibrate`
     to pick up, or adds the draft to an open anomaly that has none. It changes nothing else.
   - `trial`: a small benchmark must show it first.
   - `park`: with a `revisit` date.
   - `reject`: with a one-line reason.

An idea is one file, `ideas/<slug>.md` in `home` (format: see Idea file above).

Digest section `## Parked ideas`: parked ideas whose `revisit` date has come (on that day or
later), and parked ideas with a related problem that is open or reopened and now has score 4
or more (`NUDGE_MIN_SCORE`) while it was below 4 when the idea was assessed.

Commands (the skill runs them; they are also usable by hand):

```
python plugins/anomaly/scripts/anomaly.py assess check  --home <dir> (--source <link | text | -> | --source-file <file>)
python plugins/anomaly/scripts/anomaly.py assess record --home <dir> --slug <slug> (--source <link | text | key | -> | --source-file <file>)
    --verdict <adopt|trial|park|reject> [--revisit <date>] [--related <signature or target>]...
    (--body <text | -> | --body-file <file>) [--replace]
    [--signature <s> --category <c> --target <t> --scope <s> --impact <1-3> --summary <text> --fix <text>]
    [--expect <text> --metric <text> --guard <text> [--check-by <date>]]  [--already-applied]
```

- `check` prints `assess: seen before` and the earlier idea, or `assess: new`, the key to use
  for the record, and the open anomalies by score. Like `observe list`, it prints the
  missing-profile line first.
- Text options have a `-file` twin that reads a UTF-8 file (the skill uses it so that quotes in
  the text cannot break the command line); give one of the two. `-` reads standard input.
- `record` refuses an input whose key is already used by an idea with another slug, and refuses
  an existing slug unless `--replace`. With `adopt`, give a complete experiment draft and either
  describe a new anomaly (`--category`, `--summary`, `--fix`; a signature that already exists is
  refused; `--impact` must be 1 to 3) or name an open anomaly that has no experiment (nothing else is changed).
  `--metric` and `--guard` are checked as `calibrate declare` checks them: registered metric
  names, the guard one of the quality guards and not the metric. `--already-applied` is the one way to
  adopt without a draft: for lessons that are already built into the plugin. Nothing is
  written unless everything is valid. All text it stores goes through the privacy checks of
  `privacy.py`: a URL with a query string, an email address, a credential, pasted
  output or a long opaque string is refused, and so is a body line over 600 characters or an
  option that is not one line. A new anomaly's first sighting has no repository (`unknown`)
  and the idea's slug in the session place. When `home` is in a git repository, only the
  files written (the idea, and for `adopt` the anomaly and `INDEX.md`) are committed, with
  `chore(anomaly): assess <slug> (<verdict>)`; the command prints one `commit:` line.

## Tickets

The `ticket` commands read and edit the ticket files of a work unit
(`.anomaly/<work-unit>/tickets/NN-<slug>.md`, or one file in `.anomaly/adhoc/`; see ADR-0011).
They are the only writer of ticket lines, so a session that cannot write under the main checkout can still record
state. They need no home and no profile, and a ticket is always named by its file path.

```
python plugins/anomaly/scripts/anomaly.py ticket show       <ticket>
python plugins/anomaly/scripts/anomaly.py ticket gate       <ticket>
python plugins/anomaly/scripts/anomaly.py ticket set-status <ticket> <status>
python plugins/anomaly/scripts/anomaly.py ticket result     <ticket> --branch <branch> [--merge <ref>] [--open <items>] [--ac AC-n ...] [--suites <n>] [--type-checks <n>] [--reviewer-passes <n>] [--high <n>] [--fix-rounds <n>] [--changed-lines <n>] [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py ticket reviewed   <ticket> <sha> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py ticket verified   <ticket> <sha> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py ticket red        <ticket> <sha> <test path> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py ticket red        <ticket> --changed <reason>
python plugins/anomaly/scripts/anomaly.py ticket adhoc      <task text> | --from <draft> [--slug <slug>] [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py ticket amend      <file> [--after AC-n|D-n] '<text>'
```

- A state line is plain (`Status: done`) or bold (`**Status:** done`); both are read, `Blocked
  by:` included. An edit changes only the lines it names, in the shape each line already has;
  every other byte stays, line endings and a missing final newline included. A line that is not
  there yet is added as a plain line after the nearest line that comes before it in the order
  `Status`, `Metrics`, `Reviewed`, `Verified`, `Red`, `Red-changed`, `Result`. Lines inside a
  fenced code block (three backticks or tildes) are examples and are never read or changed. A
  byte order mark at the start of a file does not hide the first line, and stays on write. Every
  action that writes a state line refuses a file with no `Status:` line: it is not a ticket (a wrong path).
- `ticket show` prints the state lines that exist (`Status`, `Blocked by`, `Covers`, the key line
  (under the name it has in the ticket), `Tests`, `Repro`, `Base` (the integration branch, which
  `build` reads here), `Reviewed`, `Verified`, `Red`, `Red-changed`) and a `warning:` line when
  the ticket has no `Blocked by:` line or its value is not only two-digit ticket numbers (see
  `ticket gate`).
- `ticket gate` exits 1 for a ticket that waits (`ticket.waits`, the rule `frontier` uses): only a
  `ready-for-agent` ticket starts, an `in-progress` one (a resume) passes, and any other status waits,
  whatever its blockers are. It prints `<status>, waits for a person` for `ready-for-human`,
  `needs-info` and `wontfix`, and `status <x> is not ready-for-agent` for any other (a typo, no `Status:` line).
  It looks up each blocker as `<NN>-*.md` beside the ticket and exits 0 only when
  all have `Status: done`. Otherwise it prints one `blocked by <NN>: <status> (<file>)` line for
  each blocker that is not done (a missing file counts as not done) and exits 1. `None` and
  titles in parentheses are not blockers. A ticket with no `Blocked by:` line gets the same
  `warning:` line and passes. A `Blocked by:` value that is not `None` and holds no two-digit
  ticket number, or holds a number outside the parentheses that is not two digits (`101`,
  `1, 3`, `02, 101`, `soon`, blank), prints a `warning:` line and exits 1; `ticket show` prints
  the same warning. Exit 2 is kept for real errors (a missing file, a bad option, a ticket path
  of `-`, which is refused because it would read standard input).
- `ticket set-status` rewrites `Status:`. For `in-progress` it also writes
  `Metrics: started <date time>` from the clock; a ticket that already has a start time keeps it
  (a resumed ticket).
- `ticket result` closes a merged ticket: it ticks the ACs it names with `--ac` (default: those
  on `Covers:`), writes `Status: done`, `Result: <branch> · <merge sha> · Open: <items>` and
  `Metrics: started <t> · merged <t> · full suites <n> · type-checks <n> · reviewer passes <n> ·
  High <n> · fix rounds <n> · changed lines <n>`. It computes what it can: the start time is the
  one `set-status` wrote, the merge time is now, the merge sha is the full id of `HEAD` of the
  repository unless `--merge` names it (any commit ref, such as `HEAD`, a branch or a short id,
  resolved through git in `--repo` or the working folder's repository and written as the full
  id; a name that is no commit is refused), and the changed lines are the lines added plus
  deleted by that merge against its first parent. The counts only the caller knows (`--suites`,
  `--type-checks`, `--reviewer-passes`, `--high`, `--fix-rounds`) are left out of `Metrics:` unless
  given (a count that is not passed is not written as 0; one passed as `0` is written), and the
  open items are `none`. A ticket with no start time (no `Metrics: started` line) gets
  `started unknown`, not the merge time, and the command prints `warning: no start time` on
  standard output and still exits 0. `ticket set-status ... in-progress` on a ticket closed with
  `started unknown` replaces only that part and keeps the counts. Nothing is written when an AC named with `--ac` has no
  checkbox line. A ticket closed before these fields existed (every count, no `fix rounds`) still
  reads as before.
- `ticket reviewed` and `ticket verified` add or replace one `Reviewed: <sha>` or
  `Verified: <sha>` line. A ticket without them reads as before. The sha must name a commit in
  `--repo` (else the working folder), else the command exits 2 and the ticket stays as it was; a
  short id is written as the full 40-character one.
- `ticket red` records the red step: `Red: <sha> · <test path>` (a second call replaces it). The
  sha follows the same rule as for `ticket reviewed` (a commit of `--repo`, written in full).
  A later change to that test file needs `ticket red <ticket> --changed <reason>`, which adds
  one more `Red-changed: <reason>` line (earlier reasons stay; it takes no `--repo`). A reason
  covers only the edits after the red commit it was written for, so the first `Red:` line (a note
  written for "no `Red:` line" ends when the red commit arrives) and a different sha remove the
  earlier `Red-changed:` lines; the same sha again (a short id and a full id of one commit are the
  same, in either order) keeps them.
- `ticket adhoc` writes `.anomaly/adhoc/<date>-<slug>.md` under the top folder of the main
  checkout of the repository that holds `--repo` (else the working folder); a `--repo` that is a
  subfolder still gives the top folder, and a folder outside git is used as it is. Run in a linked
  worktree, it writes under the main checkout's `.anomaly/adhoc/`, not the worktree's. Git-exclude
  `.anomaly/` in each repository that uses it. The date is today's; the slug comes from the task
  (lowercase words, at most 40 characters) unless `--slug` gives it (also at most 40, so the file
  name without `.md` stays a valid work-unit key for `worklog add`). The file holds the task,
  `Covers: AC-1`, `Blocked by: None`, `Status: ready-for-agent` and one AC; it has no key line.
  The AC-1 line holds the whole task text; only the title line is cut short.
  The task is put on one line, so its text cannot add a state line. It prints the path and never
  overwrites a file. Every other `ticket` action takes this file like any other ticket.
  `--from <draft>` replaces the task text (the two are exclusive): the draft is a light-path ticket
  a skill wrote (title, `Covers:`, `Blocked by: none`, `Status: ready-for-agent`, `Tests:`,
  `Repro: <command>`, an AC, a `## Hypotheses` section of 3 to 5 numbered lines that each say
  `confirmed` or `refuted` and `probe`). A draft with a line or the section missing, or one that names a blocker,
  is refused with each problem named and nothing is written; a valid one is written unchanged, a
  key line kept and none added. A `Repro:` that holds `;`, `&&`, `||`, `|`, `>` or `<` gets a
  `warning:` on stderr (it should be one plain command) and is still written. The slug comes from
  the title unless `--slug` gives it.
- `ticket amend` writes one dated `Amended <YYYY-MM-DD>: <text>` line, so a change to a ticket or a
  planning file needs no hand edit. The date is today's, from the CLI clock. Without `--after` the
  line goes at the end of the file (a ticket, or any markdown file). With `--after AC-n` (in
  `stories.md`) or `--after D-n` (in `decisions.md`) it goes right below that list item, and below
  the `Amended` lines already under it, so the dated lines stay in order; it is indented like those
  lines, else by two spaces under a `D-n` and not at all under an `AC-n`. An id matches whole
  (`AC-1` is not the line of `AC-10`), and the first match outside a fenced code block is used. The
  text must be one line and pass the privacy check (no email address, credential, URL with a query,
  pasted program output or long opaque identifier). It has no length limit, because real `Amended`
  lines are long. An id that is not in the file, an id that is no `AC-n` or `D-n`, or a text that
  fails a check is an error (exit 2) and the file is left byte for byte as it was. This action does
  not need a `Status:` line.

## Frontier

`frontier` reads the tickets of one work unit and says which of them can start now. It needs no home
and no profile; the work unit is named by its folder.

```
python plugins/anomaly/scripts/anomaly.py frontier <work unit folder>
```

- It reads the numbered ticket files (`NN-*.md`) of `tickets/` and decides "every blocker is done"
  with the rule `ticket gate` uses (`ticket.unfinished_blockers` and `ticket.is_blocked`), so a
  blocker that is not `done` and an unreadable `Blocked by:` value (for example `TBD`) make a ticket
  blocked in both commands. A blocker with no ticket file is also not
  done, but `frontier` reports it as an error (see below).
- A **startable** ticket has `Status: ready-for-agent` (an allow list: nothing else starts) and
  every blocker `done`. It is one
  line, `<ticket>: <status>`, in ticket order. An `in-progress` ticket is one line too, `<ticket>: in
  progress`; it is neither startable nor blocked, so a ticket that waits for it is not printed while
  another ticket is startable. A `Blocked by:` of `none` or `None` is no blocker.
- A ticket that is not `done`, not `in-progress` and not `ready-for-agent` **waits**, whatever its
  blockers are (`ticket.waits`, the rule `ticket gate` uses). It always gets one line:
  `<ticket>: <status>, waits for a person` for `ready-for-human`, `needs-info` and `wontfix`, and
  `<ticket>: status <x> is not ready-for-agent` for any other status (a typo, no `Status:` line). It is
  neither startable nor blocked. A unit whose open tickets all wait prints those lines and exits 0
  with nothing startable. `conduct status` counts such a ticket as open.
- With no startable ticket, `frontier` prints each in-progress ticket and each blocked ticket with
  its unfinished blockers (`<ticket>: blocked by <NN> (<status>)`). It exits 1 only when nothing is
  in progress and at least one open ticket is blocked; while a ticket is in progress it exits 0, so
  `conduct` can offer to resume it. With every ticket `done` it prints one line that says the unit
  is finished and exits 0. A work unit with no ticket file is an error (exit 2).
- A ticket that is not `done` and has no `Blocked by:` line, or names a blocker number with no
  ticket file, is an error: one `anomaly:` line names each such ticket, nothing else is printed, and
  the exit code is 2.
- After the ticket lines, one `warning:` line names each AC of the unit's AC file that no ticket's
  `Covers:` names. The file is `stories.md` (ADR-0011); the AC lines are read as `check stories`
  reads them (`- AC-n:`), and the uncovered ACs are found by the same function as in `check slice`.
  A unit with no `stories.md` gets one `warning:` line, not an error.

## Wave report

`conduct status` prints the **wave report**: where a work unit stands after a wave of tickets, in
five lines. It reads the tickets of the unit like `frontier` and the cost like `worklog report`, and
writes nothing.

```
python plugins/anomaly/scripts/anomaly.py conduct status <work unit folder> [--home <dir>]
```

```
done: 1
failed: 1 (02-bravo)
open: 2 (03-charlie, 04-delta)
next: 03-charlie
cost: weighted tokens 3,000, weighted tokens per merged ticket 1,000, minutes per merged ticket 40.0
```

- The lines come in this order, and the label opens each line. The three counts split the tickets:
  `done` is the tickets with `Status: done`; `failed` is the tickets that are `in-progress` with no
  `Result:` line (a run that stopped without a merge); `open` is every other ticket, which means
  startable, blocked, and `in-progress` with a `Result:` line. `failed` and `open` give the ticket
  names after the count. An empty group says `0` and no names.
- `next` is the startable tickets, as `frontier` finds them (the `start` entries of
  `frontier.classify`), in ticket order, and `none` when nothing can start. It names tickets only:
  the `warning:` lines and the finished line of `frontier` are not part of it.
- `cost` is the cost line of `worklog report` for the unit, built by the one function both commands
  call (`worklog.cost_line`). The work-unit key is the name of the folder, as in `worklog add`,
  and `--home` is read as in `worklog report`. A unit with no work-unit line is an error of
  `worklog report`, so it is one here too. Its merged tickets come from the `build` lines of the
  work log, not from `Status:`, so `done` and the merged tickets of the cost line can differ.
- When `--home` is an unfilled placeholder, the CLI prints one `home:` notice line before the five
  lines (the same notice every command prints). Read the lines by their label, not by position.
- The rule for tickets is `frontier`'s: a ticket that is not `done` and has no `Blocked by:` line,
  or names a blocker with no ticket file, is an error. One `anomaly:` line names each such ticket,
  nothing else is printed, and the exit code is 2.

## MR body

`mr body` writes the body of a merge request to a file, from the files of the work, so the `ship` skill
never writes it by hand (bodies go through files, ADR-0007). It writes the file and prints its path; it
does not create or update the MR.

```
python plugins/anomaly/scripts/anomaly.py mr body <work unit folder | ad-hoc ticket> [--draft] [--docs-gate '<text>'] [--repo <dir>] [--home <dir>]
```

- The file starts with `Title: <type>(<key>): <summary>` and a blank line, then the body in markdown
  with `## <Section>` headings. A work unit folder gives `<folder>/mr-body.md`; an ad-hoc ticket gives
  the sibling file `.anomaly/adhoc/<date>-<slug>.mr-body.md`. A ticket file outside `.anomaly/adhoc/`
  (for example a ticket of a unit) is refused, so a unit never gets a body file beside its tickets.
- **Title.** `<type>` is, for a work unit and an ad-hoc ticket alike, the part of the current
  branch name before the first `/` when that is an Angular type (`fix/widget` gives `fix`), else
  `feat`. The branch is read from the repository of `--repo`, so `mr body` needs a git repository for
  both kinds of target. `<key>` of a unit is the key line (the line the `key_line` port names;
  `ticket.load(path, ports.key_line(home))`) that every keyed ticket shares; when the keyed tickets
  have different keys it is the unit folder name. A key of `no-ticket` counts as no key, and a unit
  with no key at all gets `no-ticket`. `<summary>` is the first heading of
  the AC file or the title of the ad-hoc ticket. The summary is cut at a word so the whole title is
  under 70 characters; a summary with no word left after the cut is an error. The AC file is
  `stories.md` (ADR-0011), as in `frontier`.
- **Work unit sections.** Each is left out when it has no facts, and they come in this order. Only the
  tickets with `Status: done` count as merged.
  - Why: the `Why:` line of the AC file, its first letter a capital (the rest as written).
  - What changed: one line per merged ticket, from its title (the merge subjects hold only
    `merge <NN-slug>`, so they add nothing).
  - Acceptance criteria: `n of m covered`, where m is the AC lines of the AC file and n those that a
    merged ticket's `Covers:` names (`check.uncovered_acs`, the rule `frontier` uses); the missing ids
    follow as `missing: AC-4`.
  - Still open: the `Open:` text of each merged ticket's `Result:` line, except `none`, with the ticket
    number.
  - Breaking changes: the `- Breaking:` lines of `decisions.md` and the numbered form
    `- D-n: Breaking: ...` (see `docs/formats.md`); for the numbered form the fact stops before its
    `Why:` or `Source:`.
  - Tested: the `full suites`, `type-checks`, `reviewer passes` and `High` counts of the merged tickets'
    `Metrics:` lines, summed (`ticket.metric_counts` reads them); `Docs gate: <text>` when
    `--docs-gate '<text>'` is given (one line, checked for private content); and `no CI ran` when the
    `ci` port is on its core default.
  - How to review: one line that names the merged tickets, in order, to review one merge commit at a
    time. No commit id is printed. It is left out when no ticket is merged.
- `--draft` writes a two-line body: the Why, then `Work in progress`. With no Why, the draft is the one
  line `Work in progress`. It works for an ad-hoc ticket too.
- **Ad-hoc ticket.** The light-path body has two sections: Why (the ticket's
  `What to build:`, with the same capital first letter) and What changed (the subjects of the commits
  on the current branch of `--repo` that are not on the repo base, oldest first, merge commits left
  out). The repo base is the one `ports` prints (`repo base`). `--docs-gate` is
  refused, since the body has no Tested section.
- The body holds no commit id, no table row and no attribution line: a hex word (the id shapes of
  `privacy.COMMIT_ID`) that has a digit and a letter a-f loses that word, a `|` becomes `/`, and a
  fact that starts with `Co-Authored-By:` or `Generated with` is dropped. A body over 2.5 KB (2560 bytes, not counting the Title line) prints one `warning:` line on
  standard error and is still written.
- Facts come only from the ticket files, the AC file, `decisions.md` and, for an ad-hoc ticket,
  commit subjects; the diff is never read.
- **Privacy.** The `Title:` line (section `title`) and every body line go through `privacy.privacy_problems` (a URL with a query string,
  an email address, a credential, pasted program output, a long opaque identifier). A problem is
  an error (exit 2) that names the section it is in, and no file is written. `mr put` runs the same
  check on the title and body of the file before any tool call, since the file can be edited by hand.

## MR

The **MR** of a work unit (a pull request on GitHub) is opened and kept by the CLI, so no skill writes a
tool call by hand. `mr put`, `ready` and `show` work on the MR; `mr reviewed` and `mr verified` record
the gate lines.

```
python plugins/anomaly/scripts/anomaly.py mr put      <work unit folder | ad-hoc ticket> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr ready    <work unit folder | ad-hoc ticket> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr show     <work unit folder | ad-hoc ticket> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr reviewed <work unit folder> <ref> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr verified <work unit folder> <ref> [--repo <dir>] [--home <dir>]
```

- **Adapter.** The `mr` port (profile key `mr_tool`) names the tool: `glab` or `gh`
  (`constants.MR_ADAPTERS`). Any other value is one `anomaly:` line naming the accepted ones, before any
  call. The tool runs for the project of the `origin` remote, which must be on the tool's host: `gh`
  works with `github.com` only and `glab` with `gitlab.com` only. Any other host, a self-hosted one
  too, is an error that names the host; the host is never guessed. `gh` also refuses an origin
  project that is not exactly `owner/name` (a group path such as `a/b/c` is a GitLab shape), before
  any call. `gh` is called only through
  `anomaly_loop/gh.py` and `glab` through `anomaly_loop/glab.py`, with argument lists and no shell.
  The body reaches `gh` on its standard input (`--body-file -` for `gh pr create`, `-F body=@-` for the
  REST call `gh api -X PATCH repos/<project>/pulls/<number>` that replaces a body, since `gh pr edit`
  fails on gh 2.46 with the deprecated Projects classic query) and `glab api` as one argument; a write
  is tried once, and a failed call prints the tool's message (exit 2).
  TODO(VK, revisit 2026-12-01): verify mr put, ready and show against a live gitlab.com project
- **put.** Reads the title from the first `Title:` line of the body file (`mr-body.md`, or the sibling
  `<name>.mr-body.md` of an ad-hoc ticket) and the body from the lines after the blank line that follows
  it; a missing file says to run `mr body` first. With no `MR:` line in the MR file it opens a draft MR
  from the current branch to the repo base (`ports` prints it as `repo base`) and writes the link as
  the `MR:` line. With an `MR:` line it replaces the body of that MR; the title and the draft state stay.
  It prints the link. It refuses the body file when its title or a line has a privacy problem (see MR body).
- **The MR link check.** Before `put` replaces a body and before `ready` acts, the CLI views the MR
  that the origin project has under the number of the `MR:` link. It refuses (exit 2, no change)
  when that MR has another link than the line, which is the case for a link of another project, or
  when its source branch is not the current branch. `view_mr` of both adapters returns the source
  branch (`gh`: `headRefName`, `glab`: `source_branch`). `show` only views.
- **Core default.** With the `mr` port on its core default, or a repository with no `origin`, `put`
  prints the title and the body (and a `note:` line on standard error) and calls nothing. `ready` and
  `show` are errors then, since there is no tool to call.
- **ready, show.** Act on the MR of the `MR:` line; without one they say to run `mr put` first. `ready`
  takes the draft state off. `show` prints the link, then `state: open|closed|merged|locked` (`locked`
  is glab's), with `, draft` when it is a draft.
- **The MR file.** `mr.md` in a work unit folder, or `<name>.mr.md` beside an ad-hoc ticket, holds the
  lines `MR: <link>`, `Reviewed: <sha>` and `Verified: <sha>`, in this order. Only the CLI writes it:
  `put` sets the first line, `reviewed` and `verified` set the other two, and each action keeps the
  others. `<ref>` is a commit id, branch or tag; the file holds the full commit id, and a ref that
  names no commit is an error that writes nothing.
- **Targets.** A folder target must be a work unit folder: a folder in `.anomaly/`, not
  `.anomaly/adhoc/`; any other folder is refused. `reviewed` and `verified` take a work unit folder
  only: an ad-hoc ticket keeps its own `Reviewed:` and `Verified:` lines (`ticket reviewed`,
  `ticket verified`), so its `<name>.mr.md` holds only the `MR:` line, and the two actions refuse it
  and name those commands.

## Benchmark

Each reviewer agent has one small seeded-defect fixture under `plugins/anomaly/tests/bench/`
(`code/`, `feature/`, `security/`, and `docs/` for the docs agent). A reviewer change is judged by running the agent on the
fixture by hand and scoring what it printed with `bench score`; it needs no home and no profile.

```
python plugins/anomaly/scripts/anomaly.py bench score <defects.json> <findings> [<findings> [<findings>]]
```

A fixture folder holds `base/` (the repository before the change), `change/` (the files the
change adds or replaces; lay it over `base/` for the reviewed state) and `defects.json`. The
feature fixture has a second set in `rules/` (a ledger `brief.md`, a `SKILL.md` and its own
`defects.json`) for rules mode, and a third in `cumulative/` (its own `base/`, `change/` and
`defects.json`: a small refactor spec with two characterization checks) for cumulative mode.
`bench score` has no mode, so each set is scored by its own call. To run an agent, copy
`base/` into a new temporary git repository and commit it, copy `change/` over it and commit
again, and review that last commit.
Line numbers in `defects.json` are those of the reviewed state. No fixture file is named
`test*.py`, so `python -m unittest discover` never runs them. The security fixture plants no
credential, key, token or password value.

`defects.json` is a JSON object with `fixture` (a name), `defects` and `decoys`. A defect has an
`id`, a `min_severity` (`Blocker`, `High` or `Medium`) and `places`
(`{"file": <path>, "lines": [first, last]}`), a `rule` id, or both. It may have `category` (an
OWASP Top 10 2021 label such as `A03`, or a list of labels when more than one is right; the
security fixture) and `unverified: true` (found only
by a finding marked unverified; the feature fixture's F-D8). A decoy is correct code that looks
wrong: an `id` and `places` or a `rule`. Planted defects: code 10 (3 decoys; D9, a new check
that repeats an existing one, and D10, a check deleted with no cover, plant the test rules),
feature 8 (3 decoys), 5 in rules mode (2 decoys) and 1 in cumulative mode (F-D9, a
characterization check that mocks internals; 1 decoy), security 10 (3 decoys), docs 2 (1 decoy, an ADR claim the code still holds).

Each findings file is the text of one run. A finding is one line in the shape every reviewer agent prints:

```
- [<Blocker|High|Medium|Low|Nit>] <path>:<line> — <problem> — fix: <fix> — <observed|unverified>
```

The dashes are em dashes (U+2014), and the line splits at the last ` — fix: `. Text after the
state word (`— unverified (not run)`, with no em dash in it) is ignored; the agents still end the
line with the state word. Other lines (headings, "fine" lines, tables, a bullet such as
`- [Done] ...` or `- [README](...)`) are ignored. A line that starts like a finding (a bullet,
`*`, `+`, `1.` or `- **`, then a severity word in brackets, in any case) but has another shape
stops the command with its file and line number, so a broken line cannot count as a miss. A file of `-` is read from standard input.

- A finding matches a defect when its path is the planted file (a longer path that ends with it
  also fits; backslashes and a leading `./` are normalized) and its line is within the planted
  range plus or minus 3, or when its problem or fix text quotes the defect's `rule` id as a whole
  word (rules mode).
- A defect is **found** when a Medium or higher finding matches it (for an `unverified` defect,
  one marked unverified), and found **at min severity** when such a finding is at least the
  defect's `min_severity`. **Missed** is every other defect.
- A Blocker or High that matches no planted defect is a **false High**; a hit on a decoy counts
  and is named in the run's output.
- **Category right** (only when defects carry a `category`) counts the found defects whose
  matching finding names one of the defect's labels. The label is the first one in the finding's
  problem text, written `A03`, `OWASP-A03`, `A03:2021` or `A03-Injection` (a one-digit form
  needs the prefix or the suffix: `OWASP-A3`, `A3:2021`; a bare `A1` is no label), or the public
  category name alone (`Injection`, `Broken Access Control`, ...), whichever stands first.
- Give one to three findings files, one for each run. The output has one line for each run, then
  the median of each number over the runs (the mean of the two for two runs). Pass bars are
  not printed; they belong to the agent's own acceptance criteria (see Reviewer agents).

### Facts bench

`plugins/anomaly/tests/bench/facts/` is a fixture for a reader agent, not a reviewer: a small
repository under `base/` (a job queue in `jobs/`, and `docs/design.md` with a stale claim) and
`facts.json`. The agent answers three questions by reading `base/` only, and the questions need
judgment, not a search: a 3-file call chain (which function in each file carries a command from
the entry point to the write), a moved claim (the design notes cite a place that no longer holds
the check; where is it now) and the callers of one function that can pass `None` (some look the
same but cannot).

```
python plugins/anomaly/scripts/anomaly.py bench facts <facts.json> <answers> [<answers> [<answers>]]
```

`facts.json` is a JSON object with `fixture` (a name), `questions` (`id`, `kind` of `call-chain`,
`moved-claim` or `none-callers`, and the `ask` text), `facts` and `decoys`. An expected fact has an
`id`, the `question` it answers and `places`, written as in `defects.json`, with the file as
`base/` has it. A decoy has the same keys and is a plausible wrong answer, such as the place the
stale claim cites. The fixture holds 3 questions, 6 expected facts and 5 decoys.

Each answers file is the text of one run. An answer is one line, with an em dash (U+2014) after the
place:

```
- <path>:<line> — <fact>
```

The path is bare and the line is one number (no backticks, no range, no bold), and a line names
only a place that is an answer: a place the reader rejects, or quotes as context, goes in prose.
Every other line is prose and is ignored; empty text, or text of blanks only, is refused. A bullet
that holds a `<path>:<digits>` place and an em dash but has another shape (a backticked path, a
line range, bold) is refused, with the file and line number, as `bench score` refuses a broken
finding line. The finding-line parser is not used. An answer matches an item by the same rule as a finding matches a
defect: the planted file and a line within the planted range plus or minus 3. An expected fact is
**found** when an answer matches it; a decoy is **hit** when an answer matches it, and each hit is
named. The output has one line for each run (the facts found, the facts missed and the decoys hit,
each with its ids), then the median over the runs of the found and decoy-hit counts. Give one to
three answers files.

Pass bar for the `explore` role: three runs on haiku and three on sonnet. Haiku passes when its
median found count is at least sonnet's and no haiku run hits a decoy. Then `explore` defaults to
haiku; else `anomaly:lookup` (a find-and-quote agent) is added and `explore` stays sonnet. Before
the medians are compared, check that each run produced answer lines: a run whose answers all
failed to parse also shows found 0. The bar is not printed by the command.

Scores, 2026-10-10 (3 runs each, every run produced 7 to 9 answer lines):

| Model | Found, per run | Median found | Decoys hit, per run | Median hit |
|---|---|---|---|---|
| haiku | 4, 5, 5 of 6 | 5 | 0, 0, 0 | 0 |
| sonnet | 5, 6, 5 of 6 | 5 | 2, 0, 0 | 0 |

Haiku passes, so `explore` defaults to haiku and no `anomaly:lookup` agent exists. The two sonnet
decoy hits were X4 and X5, from one run that put rejected call sites in answer lines. The runs were
general-purpose subagents that carried the `agents/facts.md` brief text, with only the Read tool
(no Grep or Glob in that session), each on its own copy of `base/`; F6 (the caller in a module no
other file imports) was found only by the one run that guessed its file name.

## The build skill

`anomaly:build` takes one ticket from a red acceptance test to a reviewed, verified commit merged
`--no-ff` into the integration branch, and closes the ticket through the CLI. The model may call
it, but it acts only on an explicit request from you or from `conduct`. Its text is
`plugins/anomaly/skills/build/SKILL.md` (8 KB or less); four docs are loaded only when used: the
implementer brief `BRIEFS.md` and the test-writer brief `TEST-WRITER.md` at dispatch (3 KB and 2 KB
or less), the worktree commit recipe `WORKTREE.md` (2 KB or less) inside a worktree, and the UI
walkthrough `UI-CHECK.md` (3 KB or less) only when the UI step of the verify runs (`Tests:`
says UI, or a UI ticket with no `Tests:` line); `build` starts the dev server before that
walkthrough and stops it after, and the walkthrough agent never does. Its only pre-approved tool is the CLI. It reads only the ticket and `seams.md`,
never the spec or stories file.

- **Start.** Resolve "build 01" or a path, `worklog start`, `ports` (unresolved `command verify`:
  stop and ask), `ticket gate`, stop and ask on an under-specified ticket, `ticket set-status
  in-progress`. The integration branch is the ticket's `Base:` line, else the `branch` port with
  the work-unit key as slug, created once from the `repo base` branch (see Ports and the repo
  layer). The ticket branch starts at the integration tip; no commit on base or integration branch.
- **Resume.** After a stop, run the same `build`. If the ticket's merge subject `merge <NN-slug>`
  is already in the first-parent log of the integration branch, `build` goes straight to the close
  with that merge; an existing ticket branch is reused, not created again.
- **Light path.** A free-text task needs no ticket file: `ticket adhoc` writes one under
  `.anomaly/adhoc/`, and its file name without `.md` is the work-unit key. `build` branches from the
  current head with the `branch` port, then follows the same red step and invariants, with one
  `anomaly:review` in combined mode, one verify and a `--no-ff` merge back into the starting
  branch. It writes no seam ledger lines. If the `branch` or `commit` port needs a `<key>`, it asks
  you for it and never guesses.
- **Red first.** The `test_writer` port, never the implementer, writes the acceptance test,
  extending an existing test first. The skill runs it, confirms it fails for the right reason,
  commits it alone and records it with `ticket red`.
- **Implement.** The `implementer` port gets the filled brief; follow-ups go to the same agent.
- **Shared close**, in this order: `anomaly:review` (ticket mode), one full verify (`ticket
  verified`), the CI check (`ci log` on the integration tip), the merge (`check pre-merge`, then
  `git merge --no-ff` with the subject `chore(<scope>): merge <NN-slug>`; when the lockfile
  changed, it names each new dependency to you before it runs the install), and the close
  (`seams prune`, `seams add`, `ticket result`, `worklog add`). `conduct`'s parallel path enters
  here with a branch. Every commit and merge message goes through a scratchpad file and `-F`.
  `build` never pushes.
- Rules whose experiments are still running say "pending verdict", with no date: the
  review-before-verify order, the isolated re-run of failures in untouched files, the seam
  ledger steps and codegen after a tip merge.

## The review skill

`anomaly:review` reviews one diff in a named mode by dispatching the reviewer agents (next
section), and gives their findings back per axis: one heading per agent, as each agent reported
them, never merged or re-ranked. The `build` and `conduct` skills call it, and you may too. Its
text is `plugins/anomaly/skills/review/SKILL.md` (8 KB or less); the per-agent brief it fills,
`BRIEFS.md` (3 KB or less), is loaded at dispatch; its last section is for the main window after
each round. Its only pre-approved tool is the CLI.

The modes, in one line each (the full dispatch table is in
[SKILL.md](plugins/anomaly/skills/review/SKILL.md)):

- **ticket**: one ticket's diff, code and feature reviewers, security when `risk` matches.
- **delta**: after a fix round, only the reviewer whose Blocker or High was fixed. After a
  conflict merge of the integration tip into the ticket branch, one round of `anomaly:code` on
  `<old tip>..<new tip>`, with the conflicted files named. Each delta or conflict-merge round runs
  `worklog start` before its dispatch, so its `worklog add --mode delta` line has a start time.
- **cumulative**: the whole branch before the MR, all three reviewers.
- **combined**: a docs-only diff or the light path, one code reviewer with the feature checklist.
- **rules**: a rewritten skill checked against its rule ledger by the feature reviewer.
- **`spec`** and **`tickets`** (the plan gate): the end of `specify` and `slice`. No range, no
  diff, no `risk`; the caller passes the work-unit folder and `anomaly:plan` checks it, counted
  under lens `plan`. A Blocker stops the calling skill; Warnings and Nits go in its handoff. A
  fix gets a delta round from the same agent, on the lines changed since its report.

- It stops before any dispatch when the range does not resolve or the diff is empty. A docs-only
  diff (no source, config, script or test file) uses combined mode.
- The agents come from the `reviewers` port: an org reviewer gets the same range, its own heading
  and its own lens. Org conventions sections for the touched areas go to `anomaly:code` only. The
  model and effort are those of the agent's lens model role (see Reviewer agents). The first round goes out in one message, in the background.
- Cumulative mode reads `stories.md` + `decisions.md` as the spec, passes every
  `.anomaly/*/seams.md` ledger, and asks for a keep, rewrite or delete verdict per
  characterization test file.
- A mutation probe that a reviewer proposes (one plain command) is shown to you first and run by
  the skill only after you say yes, on a scratchpad copy, never in the worktree; the agents stay
  read-only.
- Only when no Blocker or High is open does `ticket reviewed` write `Reviewed: <head sha>`. Each
  round leaves its work-unit line with `worklog add --mode`. Each reviewer, when it is done (after its
  last delta round, or after its first round when it had no Blocker or High), stores its counts over all its rounds with `lens tally add`, `--revised`
  always passed; after the session's last review, `lens tally sum` and one `observe apply` put
  each lens into home once.
- A rule trace: in ticket or combined mode, when the ticket's `Tests:` line names
  `rule trace <brief path> <SKILL.md path>`, the skill also runs a rules-mode pass on that pair. Its
  High findings go back to the caller, and every delta round on that ticket runs the rules pass
  again on the fixed SKILL.md (rules mode has no diff range) while it has an open High.

## Reviewer agents

The plugin ships five read-only reviewer agents in `plugins/anomaly/agents/`: the three code-review ones, `anomaly:plan`, the planning
gate's, and `anomaly:docs`, the docs check (below the table). Only the `review` skill dispatches the first four, and it passes the model and effort of its lens model role (`review_code` for `anomaly:code`, `review_feature` for `anomaly:feature`, `review_security` for `anomaly:security`, `review` for `anomaly:plan` and org reviewers): no agent file pins
one. Each has the tools Read, Grep, Glob and Bash (no Edit, no Write), a description of 250
characters or fewer and a file of 6 KB or less. Two more read-only agents (seven in all) are
readers, not reviewers: `anomaly:facts` and `anomaly:digest`. They have no Bash and no Write, pin
no model either, and keep the same size and description limits.

| Agent | Checks | Modes |
|---|---|---|
| `anomaly:code` | defects against the repo's written rules and sound design: correctness, resources, performance, contracts, tests, second copies of ledger-owned seams, design smells, new dependencies, suppressed linter or type errors | ticket, delta, cumulative, combined (adds the feature checklist, read at run time from `agents/feature.md`) |
| `anomaly:feature` | the diff does what its ticket or spec asks and no more: the AC coverage table, scope, visible changes, docs drift, deferral targets, claims against their sources, known items; in cumulative mode a keep, rewrite or delete verdict per characterization test file | ticket, delta, cumulative, rules (loads `skills/review/rules-mode.md`, 2 KB or less, in that mode only) |
| `anomaly:security` | exploitable weaknesses and missing controls by OWASP Top 10 2021 category; secrets and database safety in every run | ticket and combined when `risk` matches; delta only when its own High was fixed; always in cumulative |
| `anomaly:plan` | a planning artifact before work starts: in `spec` mode every code or tool claim against its `file:line`, commit or probe, every AC testable, every out-of-scope line owned, no open question left; in `tickets` mode ordering, invented paths, hidden dependencies between parallel tickets, sizing, `Restates:` overlap, AC coverage and a `Tests:` level for every AC | `spec` (loads `skills/review/plan-spec.md`), `tickets` (loads `skills/review/plan-tickets.md`), each 3 KB or less, in that mode only |
| `anomaly:docs` | check 4 of the docs audit: commits in the range whose message holds a decision word that no ADR records; check 5: ADR claims (files, functions, flags, behaviours) the code no longer matches | one mode over a range; dispatched by `ship` only when the user asks |
| `anomaly:facts` | questions about a repository that need inference across lines (a call chain, whether a claim still holds, which callers can pass a value); tools Read, Grep and Glob; model role `explore`; answers in `- <path>:<line> — <fact>` lines (see Facts bench) | one mode: the questions the dispatcher passes |
| `anomaly:digest` | a transcript or a long page (a local file or a link) as a digest in its own words; tools Read and WebFetch; model role `digest` | one mode: the source and the word limit the dispatcher passes |

`anomaly:docs` is not a lens of the `review` skill and is not in the `reviewers` port, so `lens tally`
does not accept the lens `docs` unless an org adds the agent to its own `reviewers` line. It never repeats
checks 1 to 3 (overdue ADR revisit dates, unkeyed deferrals, dead paths in `CLAUDE.md`): `docs scan`
owns them, and the agent may be passed that output. It reads ADRs from the ADR folder
the caller passes, already resolved through the CLI (so the folder fallback of `docs scan` has one
owner), and from the `adr/` of each unit folder. For a commit finding, `<path>:<line>` is the first changed line of the main file the commit
touched; for an ADR claim, the ADR line that holds the claim. The `docs/` fixture has no diff to
review: its `commits.md` gives the two commit messages to use when you build the repository (first
`base/`, then `change/`), and the agent reviews the whole history.

Each of the first five agents prints one finding per line in the shape above, with the fix always after ` — fix: `
and nothing after the closing `observed` or `unverified`; then a `fine: <class> — ...` line for
each clean class or category. It asks no questions. It never runs tests, builds or other repo
code, so a test outcome is unverified unless a cited CI log shows it; the only runs are the ones
its brief names (`anomaly:code` on a scratch copy of real data, `anomaly:feature`'s
base-versus-tip byte diff for a no-behaviour-change ticket). A file read at the branch tip is
observed for what it holds, and a claim about a CI job or the running app is observed only from a cited log; anything else is
unverified and ranked Medium at most. The test rules belong to `anomaly:code`: a duplicate test
is Medium, a deleted test with no cover is a Blocker, a behaviour change with no test is Medium.
A disputed cover is settled by a mutation probe that the agent proposes and `review` runs on a
scratchpad copy after you say yes. Security problem text starts with the two-digit label (`A03 Injection: ...`),
and a found secret value is never printed. Most rules in an agent file carry their ledger id in
brackets (`[C1]`, `[T2]`) for the rule trace; a rule whose verdict is still open says "pending
verdict". The rules-mode and plan-mode docs sit beside the `review` skill, not under `agents/`,
because Claude Code loads every Markdown file under `agents/` as an agent.

Pass bars, set by the workflow-build spec in the local work folder: the median of three hand
runs through `bench score`, with at most 1 false High per run.

| Agent | Fixture | Bar |
|---|---|---|
| `anomaly:code` | `code/` | found ≥ 8 of 10 |
| `anomaly:feature` | `feature/` (ticket mode) | found ≥ 6 of 8; F-D8 counts only when marked unverified |
| `anomaly:feature` | `feature/rules/` | all 5 found |
| `anomaly:feature` | `feature/cumulative/` (its own run) | 1 of 1 |
| `anomaly:security` | `security/` | found ≥ 8 of 10 |

## The pre-merge check and the seam ledger

`check pre-merge` makes three rules of the pipeline checks instead of requests, from the ticket
file and git. `check pre-push` holds a push to the review and the verify of the head.
`check stories` checks the shapes of a work unit's `stories.md` and `decisions.md`;
`check slice` checks that its tickets can be run.
`seams prune` and `seams add` keep the seam ledger true after a merge. None of them
needs a home or a profile; `check stories` and `check slice` read the `key_line` and `adr_folder`
ports from the profile in `--home` when there is one.

```
python plugins/anomaly/scripts/anomaly.py check pre-merge <ticket> [--head <rev>] [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py check pre-push  <work-unit folder | ad-hoc ticket> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py check stories     <work-unit folder> [--home <dir>]
python plugins/anomaly/scripts/anomaly.py check slice       <work-unit folder> [--home <dir>]
python plugins/anomaly/scripts/anomaly.py seams prune     <ledger> [--merge <rev>] [--repo <dir>] [--dry-run]
python plugins/anomaly/scripts/anomaly.py seams add       <ledger> --name <name> --owner <owner file> --replaces <old way> --ticket <NN>
```

- `check pre-merge` exits 0 only when `Reviewed:` and `Verified:` both name the head being
  merged (`--head`, a commit id or a branch; default `HEAD` of `--repo`) and the acceptance test
  is unchanged since its red commit. Every failed rule is one line on stdout, named by its ticket
  line: `Reviewed:` or `Verified:` (no line, not a commit id, not a commit of this repository, or
  not the head), `Red:` (no `Red:` line, so the test cannot be checked) and `Test:` (the test file at the head
  differs from the file at the `Red:` commit, or is gone). The exit code is 1, as for
  `ticket gate`; an error (a missing ticket, a head that is not a commit) is one `anomaly:` line
  and exit 2. Nothing is written except the index's file stats: `git update-index --refresh`
  runs first, so a file that is dirty by its stat only (a line-ending change, a touched file)
  cannot make the merge that follows refuse; run it in the checkout that will merge. A lock on
  the index is an error (`anomaly:` line, exit 2). It takes an adhoc ticket like any other.
- Commit ids in the ticket are normalised with git first, so a 7 to 12 digit id equals the full
  one. The test file is read from git at both commits, never from the working folder.
- A `Red-changed:` line (`ticket red <ticket> --changed <reason>`) excuses a change to the test
  file since the `Red:` commit, and also a missing `Red:` line (a docs-only ticket has no
  acceptance test); the check then passes with a `note:` line that repeats the reason. The
  ticket keeps no order between its lines, so `ticket red` removes the earlier `Red-changed:`
  lines when it records the first `Red:` line or a different sha: each reason covers only the
  edits after the red commit it was written for. A `Red-changed:` line never excuses a wrong `Reviewed:` or `Verified:`. A test path
  written with backslashes is read with forward slashes.
- `check pre-push` exits 0 only when `Reviewed:` and `Verified:` both name the current head of
  `--repo`. A work-unit folder keeps the two lines in its `mr.md` (`mr reviewed`, `mr verified`);
  an ad-hoc ticket keeps them in the ticket itself (`ticket reviewed`, `ticket verified`). Every
  failed line is one line on stdout, named by its label (`Reviewed:` or `Verified:`: no line, not a
  commit id, not a commit of this repository, or not the head, so a head that moved after the
  review names both lines), and the exit code is 1. A missing or unreadable `mr.md`, or a target
  that is neither a work-unit folder nor an ad-hoc ticket, is one `anomaly:` line and exit 2.
  Nothing is written, and the red commit and the test file are not checked (`check pre-merge`
  does that).
- `check stories` reads `stories.md`, `decisions.md` and `log.md` of a work-unit folder against the
  shapes in `plugins/anomaly/docs/formats.md`. Errors, each a line `<file>:<line>: ...` with the
  allowed shape: a duplicate `AC-<n>` id; an AC id that an earlier `specify:` line of `log.md` named
  (its text starts `ACs: AC-1, AC-2, …;`) and `stories.md` no longer holds (the error is
  `log.md:<line>` of the first `specify:` line that named it; a `specify:` line without that
  shape is an error too); a `- D-<n>:` line in `decisions.md` with no `Source:` (`T-n` lines need
  none); a line under `## Out of scope` with no `— owner:`; an owner that names a `D-n` outside
  brackets; an owner (on an Out of scope line or a `- D-<n>:` line) that is not in the checkout
  and carries no `TODO(<owner>, revisit YYYY-MM-DD)` key (the date must be a real one). The owner
  exists when it names a unit folder under `.anomaly/` other than the checked one
  (a bare name or a path; a unit is never the owner of its own item, also by its bare name),
  `ticket NN` (`tickets/NN-*.md` of the unit) or ``ticket NN of `<unit>` `` (that unit's
  `tickets/`; the form "in `<unit>`" fails), the path of a ticket file or an ADR file, or `ADR-NNNN`
  (in the folder the `adr_folder` port names, core `docs/adr/`, read from the profile in `--home`, or in the
  `adr/` of a unit folder; an `adr_folder` that is absolute, has `..`, is `.` or is a URL falls back to
  `docs/adr/`); only the checkout
  counts, so an ADR on another branch fails, and any other file (a README, a skill) is no owner. A
  path with a root or a drive is no owner. A person or a skill needs the key. A work-unit folder
  that is not `<root>/.anomaly/<unit>` gets one layout error and no
  owner lookup. Only the first `— owner:` starts the owner; it ends at the first `. Why:` or
  `. Source:`; a plain `owner:` elsewhere is ignored. Warnings, never a failure: `stories.md` over
  6 KB, `decisions.md` over 8 KB, printed as `warning:` lines. Exit 1 on any error, 0 otherwise (a
  clean run prints `stories check passed for <folder>`); a folder that is not there is one
  `anomaly:` line and exit 2.
  A missing `stories.md` is an error line; a missing `decisions.md` or `log.md` is read as empty.
  Nothing is written.
- `check slice` reads `stories.md` and `tickets/NN-slug.md` of a work-unit folder, so a ticket set
  that `build` cannot run is caught by code before the plan gate. Errors, each a line
  `<file>:<line>: ...` with the allowed shape or values: an `- AC-<n>:` line of `stories.md` in no
  ticket's `Covers:` (`Covers: none` is allowed); a ticket with no `Status:`, `Blocked by:`,
  `Covers:`, `Tests:` or key line, or one with an empty value (the key line is the line the
  `key_line` port names, core `Key:`, read from the profile in `--home`; it accepts any word for
  now, see ADR-0017, Revisit); a `Status:`
  that is not a triage word or run state of `formats.md`, or `ready-for-human` without
  `(<why>)`; a blocker with no `NN-*.md` file or in a cycle; a path with a line number
  (`check.py:42`) outside fenced code blocks and copied `- D-n:` lines (a host:port after `://`
  or `@` is not one; a bare one such as `example.com:8080` is; a path right after `@`, such as
  `@check.py:42`, or in a URL path right after the host (no port), such as
  `https://host/x/check.py:42`, is skipped too). Warning: a ticket over 5 KB. Exit codes and the
  `warning:` prefix as for `check stories` (a clean run prints `slice check passed for <folder>`).
  Nothing is written.
- `seams prune` reads the merge (`--merge`, default `HEAD`) as its changes against its first
  parent, and compares them with the ledger lines (`- <name> · <owner> · <rest>`). The owner is
  one or more owner paths, each followed by its names in parentheses; a non-file part after a path
  is one more name of it. Each path is judged alone and matches a changed file when it is that
  path or the end of it; a bare name that matches several changed files, none with exactly that
  path, is printed as `ambiguous:` and the line is left alone, even if another path was renamed.
  A deleted path removes the line; a renamed one gives that path (only) its new path; a changed
  one that no longer mentions a name listed for it (a heuristic) removes the line, as its claim is
  probably stale. Each change is printed as `deleted:`, `renamed:` or `reshaped:` with the old line
  (git does not track the ledger); `--dry-run` only prints. Other lines and every other byte stay.
- `seams add` appends one line, `- <name> · <owner file> · replaces <old way> (ticket NN)`, with
  `NN` two digits. A field cannot hold ` · ` or a line break. The same line is added only once. The
  ledger file may be new when its folder exists.
- `seams prune` and `seams add` are pending the calibrate verdict of experiment
  `seam-ledger-goes-stale` (rule I34); the help text says "pending verdict".

## CI

`ci watch` and `ci log` read the CI pipeline of a commit through the `ci` port (see Ports and
the repo layer). They need the profile only for that port, and they never write anything.

```
python plugins/anomaly/scripts/anomaly.py ci watch <commit|ref> [--pipeline] [--project <group/project>] [--repo <dir>] [--max-min <n>]
python plugins/anomaly/scripts/anomaly.py ci log   <commit|ref> [--pipeline] [--project <group/project>] [--repo <dir>]
```

- With no `ci` adapter (absent, blank or a placeholder) both print `no CI gate` and exit 0,
  before anything else runs. A value that is not an accepted adapter (`glab`) is one `anomaly:`
  line and exit 2: the adapter is never guessed.
- The CI tool (`glab api`) is called through one wrapper, `anomaly_loop/glab.py`, with
  argument lists and never a shell string; its JSON is read in Python. A commit or ref is
  resolved with git in `--repo` (default: the current folder), even when it is only digits;
  its pipeline is the newest merge request pipeline for that commit, else the newest pipeline.
  With `--pipeline` the target is a pipeline number instead, and no git is needed when
  `--project` is given. The project is `--project`, else read from the `origin` remote when that
  is a `gitlab.com` one (the remote is never printed).
- Both commands print `pipeline <id>` and one line per job (name, status, `(allow_failure)` when
  set, duration). `ci watch` polls every 30 seconds while a job is active, for about `--max-min`
  minutes (default 8, under the 10-minute foreground limit; pass more for a background run). The
  limit counts polls, not the clock, so the time of the tool calls comes on top: it is not a hard
  bound. `ci watch` reports job statuses only. `ci log` looks once, never waits, and prints the
  failure lines of each failed job (at most 40 per job, without colour codes or runner
  timestamps); it is the only way to read a CI log. When one job's log cannot be read, `ci log`
  prints one `note:` line for that job and keeps the exit code the jobs give.
- Accepted risk: `ci log` prints the failure lines as the job wrote them, with nothing redacted,
  so a job that prints a secret shows it to the session. The prompt redaction of `measure` does
  not fit: it masks mixed-case paths and everything after the words token or password, which is
  what a failure line names. Keep secrets out of job logs (masked CI variables). Owner: VK ·
  revisit 2026-12-01.
- Accepted risk: an `install`, `verify` or `codegen` command the repository documents itself
  (`CLAUDE.md`, `AGENTS.md`, a `package.json` script, a `Makefile` target) still wins over the
  frozen guess (VK D3), and it is read from the checkout, which the reviewed branch can change:
  a branch can rewrite the command `build` then runs. Owner: VK · revisit 2026-12-01.
- A job that is not active and is not allowed to fail must have succeeded or been skipped. A
  failed, canceled or blocked (manual) job without `allow_failure` makes the pipeline red. A
  blocking manual job with no job working (`pending`, `running`, `preparing` or
  `waiting_for_resource`) holds the pipeline for a person, while the jobs of later stages wait as
  `created`: that is red (exit 1) at once, not "still running", and a watch does not wait for it.
  With a job working beside it the pipeline is still running (exit 3).
- A call that fails with a network error is tried up to 3 times (5 s, then 10 s apart) before
  it counts as failed. A failure that is not the network, an answer that is not JSON or not a
  job list (a job needs `id`, `name` and `status`), and a pipeline with no jobs are errors,
  never a green pipeline.
- Exit codes, the same for both commands and listed in `ci watch --help`:

| Code | Meaning |
|---|---|
| 0 | every blocking job succeeded or was skipped (a job with `allow_failure` never blocks), or no CI gate |
| 1 | a blocking job did not succeed: it failed, was canceled, or is manual and holds the pipeline |
| 2 | an error, as one `anomaly:` line: unknown adapter, a failure that is not the network, an answer in an unknown shape, a bad option or ref |
| 3 | a job is still running (`ci watch`: still so at about the time limit; `ci log`: whenever a job is still running): run it again |
| 4 | the CI tool did not answer after the retries (a dead watch): one `anomaly:` line, never 0 |
| 5 | no pipeline for the commit yet: nothing to gate, so not an error; a plain message on standard output (no `anomaly:` prefix), push and run it again |

## Risk areas, lens tally and work units

Four small commands serve the review and build skills: `risk`, `lens tally`, `worklog` and `log add`
(which writes a work unit's `log.md`, and also serves specify and slice). None of them needs a
profile; `lens tally add` reads the profile's `reviewers` only to learn the org lens names.

### risk

```
python plugins/anomaly/scripts/anomaly.py risk <range> [--repo <dir>]
```

`risk` tells the review whether security joins: it names the **risk areas** a range of changes
touches and the files that touch them. It reads the range with git and writes nothing.

- The range is `A..B` or `A...B` (commit ids, branches, tags; `HEAD~1..HEAD`). An end that is no
  commit, or text that is no range, is one `anomaly:` line and exit 2. `--repo` defaults to the git
  top level of the working folder.
- Output: `risk areas: <area>, <area>` and then one `<area>: <path>` line for each file in each
  area (a file that fits two areas is listed under both), or the one line `no risk area matched`.
  The exit code is 0 either way, so read the output, not the code.
- Core areas, as globs in `constants.RISK_AREAS`, matched in lower case against the changed paths
  (renamed files by either path, deleted files too). Only paths are matched, never the lines of
  the diff, so a risky change in a file with a neutral name is not seen.

| Area | Paths |
|---|---|
| `auth` | `auth`, `login`, `logout`, `session`, `token`, `password`, `permission`, `role`, `oauth`, `jwt`, `cookie`, `csrf` anywhere in the path |
| `input parsing and execution` | `parse`, `deserializ`, `pickle`, `upload`, `multipart`, `subprocess`, `shell`, `exec`, `migrat` anywhere in the path, and `*.sql` files (SQL and migrations: statements that run against a database) |
| `secrets or config` | `.env*`, `*config*`, `*settings*`, `*secret*`, `*credential*`, CI files (`.gitlab-ci.yml`, `.github/workflows/`, `.circleci/`, `Jenkinsfile`), `Dockerfile*`, key and certificate files (`*.pem`, `*.key`, `*.crt`, `*.p12`, `*.pfx`) |
| `dependencies` | `package.json`, every lockfile the repo layer knows (`yarn.lock`, `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `package-lock.json`), `*.lock`, `pubspec.*`, `go.mod`, `go.sum`, `pyproject.toml`, `requirements*.txt` |
| `network calls` | `fetch`, `axios`, `http`, `urllib`, `requests`, `socket`, `grpc` anywhere in the path |

- In every row a bare word stands for the glob `*word*`, and `*` also matches `/` (this is
  `fnmatch`, not a shell glob). So `auth` matches `author.py` and any folder name on the way
  (`src/auth/x.py`, `docs/authors/x.md`), and `*.sql` matches `db/a/b.sql`. The core areas lean
  towards joining the security review; a miss costs more than an extra match.
- The repo layer adds an area named `repo layer`: the `risk_patterns` of the personal override
  file `<home>/repos/<repo>.md` (a `- <glob>` line each; see Ports and the repo layer). A glob
  matches a path when it matches the whole repository-relative path or its file name, in the case
  written; `*` crosses `/` here too, so `src/*.sql` also matches `src/a/b.sql`. A glob that ends
  in `/` means everything under that folder from the repository root (`migrations/`). The
  override file is read through the repo layer, never parsed again here.

### lens tally

```
python plugins/anomaly/scripts/anomaly.py lens tally add --session <id> --lens <name> --accepted <n> --rejected <n> [--revised <n>] --data <dir>
python plugins/anomaly/scripts/anomaly.py lens tally sum --session <id> --data <dir>
```

`observe apply` keeps one line per lens per session in `lenses.jsonl`, but a review can run
several times in a session (a delta round after a fix, a second ticket). The review skill stores
each reviewer's counts over its rounds with `lens tally add`, once when that reviewer is done,
and, after the session's last review, sums them with
`lens tally sum` and runs one `observe apply --file <path>`, so home gets each lens once.

- `lens tally add` appends `{session, lens, accepted, rejected}` to `lens-tally.jsonl` in the data
  folder and prints `tally: <lens> accepted <n>, rejected <n>`. The tally is throwaway state and
  is never written into home. The session and lens are single words (letters, digits and
  `. _ : -`; [ADR-0003](docs/adr/0003-privacy-refuses-not-redacts.md)), and the session holds no
  `:` either, because it becomes part of the batch file name (Windows reads `a:b` as a stream of
  the file `a`); both commands refuse it before anything is written. The counts are whole
  numbers of 0 or more, and `accepted` and `rejected` are both required.
- The lens names are fixed: `code`, `feature`, `security` (the core reviewers `anomaly:code`,
  `anomaly:feature`, `anomaly:security`), `plan` (the plan-gate reviewer `anomaly:plan`),
  `interview` (the interview's recommendations) and each org reviewer's adapter name from the
  `reviewers` port (see Ports and the repo layer). Any other name is one `anomaly:` line that lists
  the allowed names, exit 2, and nothing is written.
- `--revised <n>` counts the accepted findings whose fix differed from the one the reviewer
  proposed, so it is at most `--accepted` (more is one `anomaly:` line naming both counts, exit
  2). The tally line, the batch line and the home line gain `revised` only when it is passed;
  lines with two counts stay as they are and still read. `sum` gives a lens `revised` when at
  least one of its runs had it, a run without it counting 0. Accept rates in the digest stay
  accepted / (accepted + rejected) and ignore `revised`.
- The call is not idempotent: a run that is added twice (a retried call) is counted twice, so the
  review skill adds each reviewer's counts once, when that reviewer is done. The file only grows and nothing prunes it; the lines of old sessions are
  harmless, and the file may be deleted when no session is waiting for its sum.
- `lens tally sum` adds up the runs of one session per lens (in the order the lenses first
  appeared) and writes `{"lenses": [{"session", "lens", "accepted", "rejected"}, ...]}`, the lens
  entries of an `observe apply` batch, to `lens-batch-<session>.json` in the data folder. It prints
  that path and nothing else. A session with no stored runs is an error, so a mistyped session id
  is not mistaken for an empty review. The tally is never rewritten: summing again gives the same
  batch, and `observe apply` skips a lens it already logged for the session.

### worklog

```
python plugins/anomaly/scripts/anomaly.py worklog start <key> <stage> [--home <dir>] --data <dir> [--ticket <NN>]
python plugins/anomaly/scripts/anomaly.py worklog add --home <dir> --feature <key> --stage <stage> --session <id> [--data <dir>] [--docs <folder>] [--ticket <NN>] [--mode <mode>]
python plugins/anomaly/scripts/anomaly.py worklog report <work unit> [--home <dir>]
```

Every pipeline skill run (`build`, `review`, the later stages) leaves one line, so the cost of one
**work unit** can be read per stage.

- `worklog add` appends `{feature, stage, session, date, ended}` to `work-units.jsonl` in home. The
  feature is the work-unit key: the work-unit folder name, or the ad-hoc ticket's file name without
  `.md` on the light path. The date is today's, and `ended` is the time now (`YYYY-MM-DD HH:MM`,
  the form of a ticket's `Metrics:` line). Feature, stage and session are single words, checked
  like every identifier the loop stores ([ADR-0003](docs/adr/0003-privacy-refuses-not-redacts.md)), so a value
  cannot add a line or a separator. Earlier lines are never rewritten; a run that is repeated adds
  its line again, because the file records runs.
- It prints `work unit: <feature> <stage>` and one `commit:` line. When `home` is inside a git
  repository only `work-units.jsonl` is committed, as
  `chore(anomaly): log work unit <feature> <stage>`; other changes in the repository stay as they
  are, and a failed commit leaves the line written and says so.
- `worklog start <key> <stage>` stamps the start of a stage from the CLI clock; the model never
  passes a time. It appends one `{feature, stage, [ticket,] started}` line to `worklog-starts.jsonl`
  in the data folder (`--data` or `CLAUDE_PLUGIN_DATA`; throwaway, never home) and prints
  `start: <key> <stage> <time>`. Key and stage are checked like `add`'s. `worklog add` reads that
  time into `started` and appends a `consumed` line to the same file before it writes the
  work-unit line (the file is never rewritten), so one start measures one `add`: two starts in a row
  keep the later one, and an `add` after that with no new `start` has no start time. A start that
  no `add` ever read (an abandoned one) is still read by the next `add` for the same key, stage and
  ticket, however long ago it was made. With no start record (or no data folder) the line is
  still written without `started`, and the command prints `warning: no start time` on standard
  output and exits 0. A data folder inside home is refused by `add` as well as by `start`, and no
  line is written.
- A start and an `add` belong together when their key, stage and ticket are equal: `start --ticket
  <NN>` is read only by an `add` with the same `--ticket`, and a start without one only by an `add`
  without one. So parallel tickets of one feature each read their own start.
- `--docs <folder>` adds `doc_bytes`: the byte total of the `.md` files in that folder and every
  sub-folder, summed by the CLI. Files are matched by their name suffix (so `.MD` counts on
  Windows, where names ignore case), and symbolic links are skipped. A path that is not a folder is
  refused and nothing is written.
- `--ticket <NN>` (two digits) on stage `build` or `review` adds `ticket`. `--mode <mode>`
  (`ticket`, `delta`, `cumulative`, `combined` or `rules`) on stage `review` adds `mode`, so one
  review line is one review round. Another stage refuses the flag, and so does a value outside
  those forms.
- The new fields only add. A line written before them (`feature`, `stage`, `session`, `date`)
  stays as it is, and no field is renamed. The reasons are in
  [ADR-0012](docs/adr/0012-work-unit-lines-carry-times-and-rounds.md).
- `worklog report <work unit>` prints what one work unit cost. It reads `work-units.jsonl` and
  `metrics.jsonl` in home, joins them by session id, and writes nothing: no file and no commit.
  The first line gives the unit and how many merged tickets and sessions it has (counts, not
  names). Then comes one line per work-unit line, grouped by ticket: the stage, the start and end
  times with the minutes between them, the review mode and the doc bytes when the line has them; a
  `review` line is one review round, numbered within its ticket. A **merged ticket** is a ticket
  number on a `build` line, which `anomaly:build` writes after the merge (`ended` is on every line,
  so it does not mark a merge). A unit with no ticket number on any line (an ad-hoc unit) counts
  its `build` line as its one merged ticket and prints that line as `adhoc build`. A ticket's
  minutes are `ended` minus `started` of its `build` lines; a `build` line without a start adds no
  minutes, and the report counts those lines. Each session counts once, however many tickets or
  stages it holds, and the report counts the sessions that hold more than one ticket. The last line
  is `cost:`: the weighted tokens of the unit's sessions, then the weighted tokens and the minutes
  per merged ticket, which are the unit total divided by the merged tickets. There is no per-ticket
  token number, because one session holds many tickets. A unit with no merged ticket prints no
  per-ticket numbers. A session with no row in `metrics.jsonl` is left out of the sum and counted,
  with a hint to run `measure`. A unit with no lines stops the command with an `anomaly:` line that
  names the units that exist.

### log

```
python plugins/anomaly/scripts/anomaly.py log add <folder> --stage <stage> [--] '<text>'
```

`log add` is the one writer of a work unit's `log.md` (the line shape is in
[docs/formats.md](plugins/anomaly/docs/formats.md)). It appends one line `<YYYY-MM-DD HH:MM> <stage>:
<text>` to `<folder>/log.md` and writes nothing else. The time is the CLI clock, in the same format
as `worklog start`; the model passes none. The file is made when it is missing and is only appended
to, so its earlier bytes stay as they are; the new line takes the file's line ending, and a last line
without one gets it first. The folder must exist (the command never creates it) but may be anywhere,
inside `.anomaly/` or not. A folder that does not exist, a stage that is not one word
(letters, digits and `.` `_` `-`; a `:` is refused because it would end the stage in the line), and
text that is empty or has a line break, and a `log.md` that is a symlink stop the command with an
`anomaly:` line and no write. Put `--` before a text that starts with `-`. Cost numbers do not belong
in `log.md`; the command does not check this.

## Command line

The skills run these; they are also usable by hand. Every command takes `--home <dir>`, and
the ones that keep state take `--data <dir>` (see Configuration for the fallbacks).

```
python plugins/anomaly/scripts/anomaly.py measure   --home <dir> --data <dir> [--projects <dir>] [--full]
python plugins/anomaly/scripts/anomaly.py index     --home <dir>
python plugins/anomaly/scripts/anomaly.py digest    --home <dir> [--data <dir>] [--user-config <dir>] [--plugin-root <dir>]
python plugins/anomaly/scripts/anomaly.py observe   list|apply ...
python plugins/anomaly/scripts/anomaly.py assess    check|record ...
python plugins/anomaly/scripts/anomaly.py calibrate plan|effort|declare|fix|verify|decide|close|merge ...
python plugins/anomaly/scripts/anomaly.py nudge     --home <dir> --data <dir> [--user-config <dir>] [--plugin-root <dir>]
python plugins/anomaly/scripts/anomaly.py ticket    show|gate|set-status|result|reviewed|verified|red|adhoc|amend ...
python plugins/anomaly/scripts/anomaly.py ports     --home <dir> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py bench     score <defects.json> <findings>...
python plugins/anomaly/scripts/anomaly.py bench     facts <facts.json> <answers>...
python plugins/anomaly/scripts/anomaly.py check     pre-merge|pre-push|stories|slice ...
python plugins/anomaly/scripts/anomaly.py seams     prune|add ...
python plugins/anomaly/scripts/anomaly.py ci        watch|log <target> [--project <group/project>] [--repo <dir>] ...
python plugins/anomaly/scripts/anomaly.py risk      <range> [--repo <dir>]
python plugins/anomaly/scripts/anomaly.py lens      tally add|sum ...
python plugins/anomaly/scripts/anomaly.py worklog   start|add|report ...
python plugins/anomaly/scripts/anomaly.py log       add <folder> --stage <stage> '<text>'
python plugins/anomaly/scripts/anomaly.py frontier  <work unit folder>
python plugins/anomaly/scripts/anomaly.py conduct   status <work unit folder> [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr        body <work unit folder | ad-hoc ticket> [--draft] [--docs-gate '<text>'] [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr        put|ready|show <work unit folder | ad-hoc ticket> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py mr        reviewed|verified <work unit folder> <ref> [--repo <dir>] [--home <dir>]
python plugins/anomaly/scripts/anomaly.py docs      scan <range> [--repo <dir>] [--home <dir>]
```

- `measure` scans transcripts into `metrics.jsonl` (see measure).
- `index` rewrites `INDEX.md` from `anomalies/`: open and reopened anomalies in one table,
  highest score first (ties: most recent `last_seen` first), then fixed and wontfix ones in a
  separate list. The commands that write records do this for you.
- `digest` prints the review summary for `calibrate`: one block per section, and a section with
  nothing to show is left out, except Experiment results, which always shows. The backlog
  section (counts and the top three anomalies by score) belongs to the index; the others are
  described under The digest. The data folder is optional here, and a section that needs it
  says so.
- `observe`, `assess` and `calibrate` take an action; their options are in their sections.
- `nudge` is run by a hook (see The weekly nudge).
- `ticket` takes an action; its options are in Tickets.
- `ports` prints the adapter of every port, the repo-layer commands and the model roles for the
  repository that holds `--repo` (default: the current folder), and a `warning:` line on stderr for
  each of `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` and `CLAUDE_CODE_EFFORT_LEVEL` that is set; see Ports
  and the repo layer.
- `bench` takes the action `score` or `facts`; their inputs and scoring rules are in Benchmark.
- `check` and `seams` take an action; their options are in The pre-merge check and the seam
  ledger.
- `ci` takes an action (`watch` or `log`); its options and exit codes are in CI.
- `risk` prints the risk areas and files of a range; see Risk areas, lens tally and work units.
- `lens` takes `tally add` or `tally sum`; its options are in the same section.
- `worklog` takes `start`, `add` or `report`; `add` appends one work-unit line to home and `report`
  prints what one work unit cost; the options are in the same section.
- `log` takes the action `add`, which appends one line to a work unit's `log.md`; see the same section.
- `frontier` takes a work-unit folder and prints the tickets that can start now; see Frontier.
- `conduct` takes the action `status`, which prints the five-line wave report of a work unit; see Wave report.
- `mr` takes the actions `body` (writes the MR body of a work unit or an ad-hoc ticket to a file), `put`, `ready`, `show`, `reviewed` and `verified`; see MR body and MR.
- `docs` takes the action `scan`, which prints the overdue ADRs, the deferral notes without an owner and date, and the dead paths of `CLAUDE.md` files; see Docs scan.

Errors, including a usage error such as an unknown command or a missing option, print as one
line starting with `anomaly:` and exit with status 2.

## Docs scan

```
python plugins/anomaly/scripts/anomaly.py docs scan <range> [--repo <dir>] [--home <dir>]
```

`docs scan` runs the three checks of the docs audit that need no judgment: it reports the ADRs
whose revisit date has passed, the deferral notes without an owner and a revisit date, and the
paths in `CLAUDE.md` files that no longer exist. The other two checks (a commit that decided
something no ADR records, and an ADR claim the code has moved away from) are the docs agent's, not
this command's. It reads the working folder and writes nothing. The range is `A..B`
or `A...B` (a range that does not resolve is an error, exit 2); it only decides which findings
are marked, not what is scanned. Today is the command's clock.

The first line is `adr folder: <folder>`, the ADR folder the scan reads, resolved by
`check.adr_folder_path` (for example `adr folder: docs/adr`). A port value that names no folder of
the repo (a URL, `..`) reads as `docs/adr`, and the line shows it. The docs agent gets this line,
not the raw `ports` value.

Each finding is one line, `<path>:<line>: <kind>: <detail>`, with the path relative to the
repository, in the order of path and line. A finding in a file the range changes ends with
` [touched]`. The last line counts the findings, or says there are none. The exit code is 1 when
any finding is marked `[touched]` and 0 otherwise; whether that blocks anything is the caller's
decision.

- `adr-overdue`: the date is the `Revisit-by:` field of the ADR's status line; an ADR with no such
  field uses its `Revisit:` front-block line (a line that starts with `Revisit:` above the first
  `## ` heading) when that line holds a date. A date before today is overdue; the day itself is
  not. An ADR whose status starts with `Superseded` is left out. The ADRs are the `NNNN-*.md`
  files in the folder of the `adr_folder` port (read from the profile in `--home`; a value outside
  the repo gives `docs/adr`, as in `check stories`) and in the `adr/` of every work-unit folder.
- `todo-unkeyed`: in any tracked text file, the word `TODO` that is not followed at once by the
  key `(<owner>, revisit YYYY-MM-DD)`. A key whose date is not a real date counts as no key. The
  word counts only where a deferral is written: as the first word of a comment (after `#`, `//`,
  `--`, `/*` or `<!--`, spaces allowed), the first word of a line (after leading spaces or `> `
  quote marks) or the first word of a list item (`- `, `* `, `1. `, also with a `[ ]` or `[x]` box).
  A mention in the middle of code or of a sentence,
  and the word followed by `(<` (the key shape written out), are not reported. One finding for
  each line.
- `todo-overdue`: a keyed deferral whose revisit date is before today. It is read wherever the
  key with a real date stands in the line, in a comment or not.
- `dead-path`: in a tracked file named `CLAUDE.md`, in any folder, a path claim that is live when
  it is at or under `.anomaly/` (the folder of local work units: a clone has none, so it is never
  reported), or exists beside that file or at the repository root, or when git ignores it (a folder that git
  ignores, such as a local work-unit folder, exists in one checkout only, so it is live whether or
  not it is on disk), or when a tracked file or folder equals it or ends with `/<claim>` (whole path parts only, so `scripts/tool.py` is
  live for `tools/scripts/tool.py` and a bare `SKILL.md` is live when any tracked `SKILL.md`
  exists). It is dead only when none of these holds. A claim is a backticked word that has no
  space, glob, placeholder or colon character (a trailing `:12` or `:12-20` line cite is cut off
  first) and either holds a `/` or is a bare file name ending in `.md`, `.py`, `.json`, `.toml`,
  `.yml`, `.yaml`, `.sh` or `.txt`; or the target of a markdown link that is relative (a URL, an
  anchor and a `#fragment` are skipped). A claim that climbs out of the repo (`..`; refused by
  `check.relative_parts`) cannot be checked against it and is skipped. Fenced code blocks are not read. A git ref such as
  `origin/main` also looks like a claim: this is a known limit.

The scan covers the files git tracks (`git ls-files`, read at the working folder, so an
uncommitted edit counts); files that are not UTF-8 text and symbolic links are skipped. Work-unit
ADRs are read from the working folder even when git ignores them.

## Planning formats

The planning skills share their file shapes (`stories.md`, `decisions.md`, tickets, `log.md`, triage
words, the next-step offer, the ADR front block) in `docs/formats.md`. Where each planning stage ends,
and when `/clear` may be offered, is in `docs/boundaries.md`.

## The interview skill

`/anomaly:interview` is slash-only (`disable-model-invocation: true`): the model never starts it. It
turns an idea into settled decisions and terms by asking the user in rounds.

- It runs the `gather` port, then lists what is already settled (ADRs and `D-n` lines) before round 1.
- Each round asks at most 8 questions, hard-to-reverse first. Every question has `Assumes:` and
  `Recommend:`; low-risk items with an obvious answer go in one defaults block.
- After each round it writes `D-n` lines (with a `Source:`) and `T-n` lines (settled terms) to
  `.anomaly/<work unit>/decisions.md`. It edits no other file and makes no commit.
- It closes with a table of the decisions and one confirm question, writes an `interview` work-unit
  line (`worklog add --stage interview`) and offers `/anomaly:specify`.
- The close table shows the counts of its recommendations accepted, rejected and revised.
  `/anomaly:specify` records them with `lens tally add --lens interview`.
- No question or option offers to reopen a settled ADR or `D-n`, even when the idea asks for it; only
  the user reopens it. A part of the idea in conflict with one is named under "Settled already" (in
  round 1, or in the round where it shows) and written, without a question and in every round, as an
  out-of-scope `D-n` owned by that ADR or by the other unit that holds that `D-n`; it never asks for
  the owner, and when that `D-n` is in this unit it writes none. A gap the user settles as out of
  scope is a `D-n` whose decision names an owner after `— owner:` (another unit, ticket or ADR,
  never a `D-n`; it must exist or carry `TODO(<owner>, revisit YYYY-MM-DD)`, never a placeholder;
  when none is known, it asks, then recommends the key; only if the user declines does it write an
  `Open:` line and say that `/anomaly:specify` will stop on it). `Open:` holds only unanswered
  items, because it stops `/anomaly:specify`.

## The specify skill

`/anomaly:specify <work unit>` is slash-only (`disable-model-invocation: true`). It turns the
interview's `decisions.md` into the `stories.md` the owner reads.

- It stops before it writes anything when `decisions.md` still holds `Open:` items, and sends the
  user back to `/anomaly:interview`.
- It writes `.anomaly/<work unit>/stories.md` (Sources with the Gathered date, Why, rules for all
  stories, numbered stories with continuous `AC-n`, verbatim source criteria tagged, an Out of scope
  list with owners) and appends `D-n` lines, each with a `Source:`. It writes no `T-n` line and no
  `CONTEXT.md` row. When no owner is known and the user declines the `TODO` key, the line keeps an
  empty owner, `check stories` fails on it and specify stops before the gate.
- Agreed ADRs are drafted in `.anomaly/<work unit>/adr/` with a number free on every branch.
- It runs `check stories`, then `anomaly:review` in `spec` mode, then shows a digest of at most 5
  lines and waits for approval. A Blocker stops it before the digest.
- It adds one `specify` line to `log.md` (the AC ids, ended by `;`), a `specify` work-unit line, and
  offers `/anomaly:slice`.

## The slice skill

`/anomaly:slice <work unit>` is slash-only (`disable-model-invocation: true`). It cuts `stories.md`
and `decisions.md` into the self-contained tickets `anomaly:build` runs.

- It shows a numbered list (title, blocked by, covers, tests) and writes nothing until the user
  approves it.
- It writes `.anomaly/<work unit>/tickets/NN-slug.md` in the formats doc shape, with the ACs and
  `D-n` lines each ticket needs copied verbatim and no line numbers. Each `T-n` term line and ADR
  draft lands in the first ticket that needs it, named in `Touches:`.
- It runs `check slice`, then `anomaly:review` in `tickets` mode. A Blocker stops it before it
  offers the next build step.
- It adds one `slice` line to `log.md` per gate result, a `slice` work-unit line, and offers
  `/anomaly:build <work unit> <NN>` for the first ticket with no open blocker, then `/clear` once.

## The diagnose skill

`anomaly:diagnose` is model-invocable: it starts on a reported bug or a request to diagnose. It
finds the root cause and changes no source.

- It runs a red-capable command before any hypothesis, and cites the root cause as `file:line` or
  probe output, else marks it "unverified".
- It removes every probe edit and leaves `git status` clean: no branch, commit or push. The loop
  script stays under the git-excluded `.anomaly/adhoc/` as `<key>-repro.<ext>`, so build can run it.
  The ticket stem can differ from the `<key>` in the script name: `Repro:` holds the script's
  absolute path, so build still runs it.
- It writes a light-path draft (the shape is in the formats doc) to the session scratchpad and
  passes it to `ticket adhoc --from`, which checks it. Its 3 to 5 ranked hypotheses are a
  `Hypotheses` section of the draft, each with its probe result (`confirmed` or `refuted`), not a chat list.
- It adds one `diagnose` work-unit line, replies with a 5-line digest, and offers
  `/anomaly:build <adhoc ticket path>`.

## The ship skill

`anomaly:ship` is model-invocable but acts only on an explicit request from you or from `conduct`.
It takes the MR of one work unit, or of a light-path ticket, from a clean tree to ready. Its text is
`plugins/anomaly/skills/ship/SKILL.md` (5 KB or less); the docs gate `DOCS-GATE.md` (2 KB or less)
is read only at the ready gate. Its only pre-approved tool is the CLI.

- **Draft.** `check pre-push`, `mr body --draft`, one plain `git push`, `mr put`.
- **Ready.** The docs gate (`docs scan` on the range; a `[touched]` finding stops the gate until it is
  fixed or waived in the Tested section, or on the light path in one chat line and a `ticket amend`;
  `anomaly:docs` runs only when you ask), `mr body`, the push, `mr put`, `ci watch`, the tracker AC
  re-check against the stories' `Gathered:` date, and `mr ready`.
- **Pushes.** Before every push `check pre-push` must pass; on a stale head `ship` runs a delta review
  and one verify first, and records the head only when no Blocker or High is open and the verify is
  green. At a draft's first push there is no `mr.md` yet, so the check exits 2 and `ship` goes on. It
  never pushes to the base branch, never forces, and does not retry a refused push. With no
  `origin` it skips the push and `ci watch`; on the `mr` core default or with no `origin`, it skips
  `mr ready` and `mr show`.
- **End.** One line each offering `/anomaly:observe` and `/clear`, and one `ship` work-unit line.

## The conduct skill

`anomaly:conduct` drives every ticket of one work unit through `anomaly:build` on one integration
branch, then takes the one MR to the ready gate. It is model-invocable but acts only on an explicit
request from you. Its text is `plugins/anomaly/skills/conduct/SKILL.md` (8 KB or less); the
kickoff text `KICKOFF.md` (1 KB or less) is read only in chip mode, and the parallel text
`PARALLEL.md` (3 KB or less) only after you pick a parallel wave. Its only pre-approved tool is
the CLI.

- **Start.** `worklog start`, `ports`, then `frontier` (its warnings are shown; blockers stop the
  run; an `in-progress` ticket is resumed only after you confirm that no other session runs it; when
  only tickets that wait for a person are left, `conduct` names them and goes to the finish, so they
  run after the MR exists).
  The integration worktree is made once with `git worktree add`; the main checkout stays on the base
  branch. With no `origin` there is no push, MR or CI step and no question about it: the `ports`
  lines decide.
- **Plan.** Before each wave, one `anomaly:facts` agent on the `explore` model role checks the wave's code claims and
  returns only the false or moved ones; each becomes a `ticket amend` line, and a claim that changes
  the scope goes to you first. The wave plan is one line per ticket with its `Touches:` paths. A
  ticket whose gate is closed waits. Research notes go to `research/NN-slug.md` in the unit folder,
  and a `ticket amend` line puts their path on the ticket, so `build` passes it on.
- **Run.** `anomaly:build` once per ticket, in `frontier` order. With an `origin`, one plain
  `git push` after each merge (never forced, never to the base branch); the first push calls
  `anomaly:ship` for the draft MR; a `ci` port that is not on its core default starts `ci watch` in
  the background.
- **Report.** `log add` events (a `wave <n>` line at the start of each wave, then merge, push and
  stop; no cost numbers), then `conduct status` first: only when it answers "no lines for work unit"
  (exit 2) does `conduct` write `worklog add` and run it again. The end-of-run `worklog add` still
  runs once for the run (at the finish, or at the first stop that has none yet). Then the five lines
  of the wave report. With an MR, one more
  line gives its size as a number.
- **Parallel pick.** A wave of two or more tickets with disjoint `Touches:` paths is the only wave
  that asks you a question: parallel or sequential. Any other wave is sequential and starts without
  one. After a parallel pick, `PARALLEL.md` marks each ticket `par` or `seq` (disjoint touches, no
  shared `seams.md` owner, medium or larger, at most one UI check), builds a prep branch for a
  shared helper (a `ticket adhoc` unit on `build`'s light path), and makes one plain worktree per
  ticket with `command install` run once in it; a branch or worktree left by a stopped wave is
  reused. `conduct` itself runs the red step: it starts the build worklog of each ticket
  (`worklog start <key> build --ticket <NN>`, so the later `worklog add` has a start time), sets it
  in progress, then sends one message with one `test_writer` dispatch per ticket, commits each red
  test and runs `ticket red`. One more message sends one
  `implementer` agent per ticket with absolute paths; the agents only implement. Then, one branch
  at a time, `conduct` removes the agent's worktree, switches its own worktree to the ticket
  branch and runs the close of `anomaly:build` (review, verify, CI check, merge) there, so the
  verify runs on the ticket's own code. The push, CI watch and report follow as in a sequential
  wave.
- **Go on or stop.** A sequential wave with no open decision and a tip that is not red goes straight
  on. It stops for a parallel pick, a scope change, a red tip and the ready gate. Past 200k tokens
  of context it stops after the report and offers a fresh session: in the desktop app a chip with the
  kickoff text, in a plain CLI session the printed text.
- **Finish.** `anomaly:review` in cumulative mode over the whole branch (skipped for a one-ticket
  unit), one fix branch that also takes every open Low and Nit finding whose fix needs no decision,
  one full verify and the `ui_check` port, `mr reviewed` and `mr verified` on the tip, then
  `anomaly:ship` for the ready gate.

## Development

Run the tests from the plugin folder:

```
cd plugins/anomaly
python -m unittest discover
```

`tests/test_neutral.py` keeps the plugin free of environment facts: it fails when an identifier
from your `profile.md` (an agent id, a tool or a dashed skill name) appears in a plugin file, or
when a link names a host other than a reserved example host, and it runs every subcommand
against a home with no profile. Without a profile the identifier check is skipped.

`tests/test_pipeline_files.py` and `tests/test_cli.py` hold the static checks over the text of the
pipeline (every skill except the four loop skills, its extra docs, the agent files and the files
under `docs/`). They pass while those files do not exist. Once they do:

- A skill's description and an agent's description are 250 characters or fewer; a pipeline skill's
  `SKILL.md` is 8 KB or less and an agent file is 6 KB or less.
- The `allowed-tools` of `build` and `review` is the one CLI pattern, defined once as
  `CLI_PATTERN` in `anomaly_loop/constants.py`, and every call of the CLI in their text uses that
  exact command and is never chained.
- No pipeline text holds a command shape that a deny rule of your Claude Code settings matches.
  The rules are read when the test runs, from the user settings (`~/.claude/settings.json`, and
  `settings.local.json` beside it if present) and the managed settings file of the platform
  (`C:\Program Files\ClaudeCode\managed-settings.json`,
  `/Library/Application Support/ClaudeCode/managed-settings.json`,
  `/etc/claude-code/managed-settings.json`; the last two are documented but unverified, not
  tried), and the test is skipped when none can be read. Project settings files are not read. A
  failure names the rule and the `file:line`, never the text.
- No pipeline text runs inline code (`node -e`, `sh -c`, `bash -c`), pipes output into an
  interpreter or writes a file with a shell heredoc.
- No plugin file edits a settings file or prints an allow rule: the plugin never changes your
  permissions.
- This `README.md` names every command group of `--help` and every `<group> <action>` pair of
  `<group> --help`.
- No doc of `build` or `review` other than `SKILL.md`, nor any file under `docs/`, holds a `${…}`
  placeholder: in a skill
  folder Claude Code fills `${CLAUDE_PLUGIN_ROOT}`-style placeholders only in `SKILL.md`
  (`${user_config.*}` not even there, ADR-0001).

Line endings are LF everywhere (see `.gitattributes`).

Design decisions and their reasons are recorded as ADRs in `docs/adr/`:
[0001](docs/adr/0001-durable-data-in-home.md) durable data in home,
[0002](docs/adr/0002-every-fix-is-an-experiment.md) every fix is an experiment,
[0003](docs/adr/0003-privacy-refuses-not-redacts.md) privacy refuses instead of redacting,
[0004](docs/adr/0004-weekly-nudge-system-message.md) the weekly nudge,
[0005](docs/adr/0005-no-default-build-skills.md) no default build-skill list,
[0006](docs/adr/0006-no-third-party-skill-dependency.md) no third-party skill dependency,
[0007](docs/adr/0007-one-plugin-ports-and-adapters.md) one plugin with ports and adapters,
[0008](docs/adr/0008-rewrite-judged-per-switch-over.md) a rewrite is judged at its switch-over,
[0009](docs/adr/0009-verdicts-use-a-permutation-test.md) verdicts use a permutation test,
[0010](docs/adr/0010-static-guard-rails-read-live-deny-rules.md) static guard rails read the live deny rules.
