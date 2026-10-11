# ADR-0022: Upstream reports go through a new `upstream` port, and a checkout never reports

Status: Proposed · Date: 2026-10-11 · Owner: VK · Revisit-by: 2027-01-11

Decision: an installed-copy user can send the plugin's owner a defect report (a fault, no experiment) or a tuning report (an addenda line whose verdict is `keep` or `unproven`, with its result). A new `upstream` port carries it. The core default writes the GitHub issue text to a file and prints a search link. The `gh` adapter searches, then adds a +1 comment or creates the GitHub issue, each in a second run after the user's yes. A GitHub issue title carries `[anomaly:<skill or agent>] <signature>`, or the path from the plugin root for a plugin-code target. When `plugin_repo` resolves to a checkout, the commands refuse and the fix goes through an MR.
Why: the owner never learns what the plugin gets wrong for other users, because all data stays in their home (ADR-0001). A port keeps `issue_source` read-only (ADR-0007), and the checkout test keeps the owner and fork users on the MR path.
Revisit: at the first real GitHub issue traffic from users, when the +1 match proves wrong more than once, or 2027-01-11.

## Context

The `mr` port already wraps `gh` and `glab` with a core default that prints a body to paste. `issue_source` is a read-only port. The plugin text may name no repository (the neutrality check), and `plugin.json` has no version field. Every user names an anomaly's signature on their own machine, so no experiment ID is shared across users.

## Decision

- Lanes: `upstream defect <signature>` (target, one symptom line, installed version = plugin root folder name) and `upstream tuning <signature>` (line, target, metric before and after, guard, sessions, verdict word).
- Checks: `check_text`, the profile's org markers and the repo-layer names refuse the text, and nothing is redacted (ADR-0003).
- Target repository: the installed copy's marketplace record when its source is GitHub, else the profile key `upstream_repo`, else exit 1 with the file written. The adapter key is `upstream_tool`.
- Match: an exact signature hit is offered as a +1. Otherwise the model proposes a match from the titles, and the user picks +1 or a new GitHub issue.
- Trigger: `calibrate plan` prints one `upstream: tuning|defect <signature>` line per report not yet sent, and the calibrate close offers each one. A comment or create appends `upstream <date> · <number>` to the anomaly, so an offer is never repeated. A checkout gets no offer, and the commands exit 1.
- The new module joins the repo layer's risk patterns, so the security reviewer joins its changes.

## Why

The port pattern gives users without `gh` a paste path, and a second run makes each GitHub write a separate yes. The title key gives an exact match when two users chose the same signature, and the user's confirmation covers the rest. A checkout is the one signal the CLI already has for "works on the plugin source".

## Alternatives rejected

- Print only, with no `gh`: users search and file by hand, and duplicate GitHub issues follow.
- Always use `gh`: no path for users without it.
- A hash of the addendum line as the match key: it finds exact text only.
- An owner-kept catalog of problem IDs: upkeep and a plugin text change for each ID.
- Compare the `gh` login with the repository owner: it needs the network and fails for a directory install.

## Accepted risks

- [ ] The marketplace record is a Claude Code file, so the repository lookup is not agent-neutral. Owner: VK · Revisit: 2027-01-11.
- [ ] A model-proposed match can be wrong, and the user's yes is the only check. Owner: VK · Revisit: 2027-01-11.
- [ ] A fork user with a checkout cannot send a defect report through the CLI and must use a PR. Owner: VK · Revisit: 2027-01-11.
