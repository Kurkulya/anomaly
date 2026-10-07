---
# Copy this file to <home>/profile.md and replace the placeholder values.
# Format: `key: value`. Indented lines continue the previous value.
# A line that starts with `#` is a comment.
# A key counts as missing when it is absent, blank or still a <placeholder>; the skills
# still run without it.

# Where work items live and how they are tracked.
tracker: local markdown files under <repo>/.anomaly/<work-unit>/
# The repo-root file that holds the project vocabulary.
glossary_file: CONTEXT.md
# A regular expression that matches one ticket key in a branch name. `measure` uses it
# for the ticket_keys field of every metrics row.
ticket_key: [A-Z][A-Z0-9]+-\d+
# How branches are named.
branch_pattern: <type>/<key>/<slug>
# How commit messages are written.
commit_style: <type>(<key>): <summary>
# Which agent writes code, per stack. One `stack: agent` per indented line, with a space after
# the colon.
implementers:
  stack-a: <agent id>
  stack-b: <agent id>
# The skill or command that opens a merge request.
mr_tool: <skill or command>
# The skill or tool that checks a user interface.
verify_ui: <skill or tool>
# Where requirements come from, and whether the loop may write to it.
issue_source: <tracker name, read-only or read-write>

# Optional: skills that mean "this session was build work". This key is how sessions become
# `build`: the plugin ships no default list, so without it no session counts as build.
# build_skills: skill-a, skill-b

# Optional: the plugin's folder inside its git checkout (for example <checkout>/plugins/anomaly).
# Needed only when the installed plugin is a git-ignored copy and so has no repository of its
# own; `~` is expanded.
# plugin_repo: <path to the plugin folder in its git checkout>

# Optional ports for the pipeline (`ports` prints them). Absent, blank or a <placeholder>:
# the port stays on its core default. `implementers` and `verify_ui` above are ports too.
# Which agent writes acceptance tests, per stack. One `stack: agent` per indented line, with a
# space after the colon.
test_writers:
  stack-a: <agent id>
# Org conventions read after the repo's own docs, per stack. One `stack: path` per indented
# line, with a space after the colon.
conventions:
  stack-a: <path to the conventions doc>
# Reviewers added beside the plugin's own three, separated by commas.
reviewers: <agent id>
# Context skills added beside reading the repo, separated by commas.
gather: <skill>
# The tool the CI step watches and reads logs with.
ci: <ci tool>
# The model per dispatch role. One role per indented line.
models:
  explore: <model>
  implement: <model>
  review: <model>
  deep_analysis: <model>
  browse: <model>
---

Free text after the closing line is ignored.
