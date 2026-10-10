# ADR-0018: A model change is a measured experiment on one agent, never an automatic switch

Status: Proposed · Date: 2026-10-10 · Owner: VK · Revisit-by: 2027-01-10

Decision: each kind of subagent dispatch has its own agent and its own model role (`explore`, `digest`, and per-lens `review_*` roles); a model or effort change for one role is a `calibrate` experiment on the new metric `model-weighted tokens per dispatch <agent>`, with the guard rework sightings, approved by the user; a cheaper model for facts or for a reviewer must first pass a bench. The plugin never switches a model by itself.
Why: `weighted tokens` weighs token types only, so a haiku switch showed no saving; the facts dispatches named a model role but no agent, so their cost could not be told apart; and per-agent quality signals are too thin for an automatic router to trust (ADR-0009).
Revisit: when Claude Code publishes a per-model quota ratio, when API prices change, when the advisor shows up in transcripts, or 2027-01-10.

## Context

The profile's `models` key maps five roles to models (`constants.MODEL_ROLES`), and the model is passed at dispatch time. `measure` records tokens per agent (`tokens_by_agent`, keyed by the transcript's `attributionAgent`) and spawns per agent type (`subagents.by_type`, from `.meta.json`); for a plugin agent both keys are the same string. But:

- `weighted tokens` multiplies token types (`metrics.WEIGHTS`) and not models. A haiku token counts the same as an opus token, so no experiment could show a cheaper model's saving.
- `interview`, `diagnose` and `conduct` dispatch facts lookups on the `explore` model role with no named agent, so the cost lands under whatever agent type ran them; `assess` and `observe` hardcode `sonnet`. Their costs cannot be told apart or tuned.
- A subagent's wrong fact is silent: the main session trusts it, and the error shows later as rework, if at all.

## Decision

- **One agent per kind of dispatch.** `anomaly:digest` (Read, WebFetch) for long sources; for facts one agent, `anomaly:facts`; the facts bench passed haiku, so there is no `anomaly:lookup`. No agent file has a `model` key.
- **One model role per agent**, and optional per-lens reviewer roles that fall back to `review`. A role value is `<model>` or `<model> <effort>`.
- **New metric** `model-weighted tokens per dispatch <agent>`: per session, the agent's weighted tokens with each API call times its model factor, divided by its dispatch count. Factors are API list prices relative to sonnet, kept as one dated constant: haiku 0.05 (0.25 over 100k prompt tokens), sonnet 1, opus 2, fable 5. A model without a factor is skipped and counted, never guessed. Existing metrics keep their meaning (ADR-0013).
- **Experiments change one setting of one role**, the model or the effort. A cheaper reviewer model passes the reviewer bench first; a cheaper facts model passes the facts bench (`bench facts`) first.
- **No automatic switching** (ADR-0002). The advisor is out of scope until it is seen in transcripts.

## Why

ADR-0002 rejected dollar cost because on a seat plan cost is usage-limit pressure plus time. Claude Code publishes no per-model quota ratio, only that Opus "costs several times more per turn than Sonnet, and Sonnet more than Haiku"; API list prices are the only published numbers for that pressure. One agent per use gives each use a metrics key; splitting further would leave too few sessions per key for a verdict. A bench catches a silent quality drop that the rare rework guard would see late or never.

## Alternatives rejected

- An automatic router that picks the cheapest model and calibrates itself: breaks ADR-0002, and per-agent quality signals are too thin.
- Judging a model switch by session `weighted tokens`: blind to the model, and the subagent share drowns in session noise.
- Built-in `Explore` with the role written in the dispatch description: the description is not a metrics key.
- Two facts agents even if haiku passes: halves the data per key and adds a dispatcher choice.

## Accepted risks

- [ ] The plan's real quota ratio may differ from API prices; the metric may overstate haiku savings. Owner: VK · Revisit: 2027-01-10.
- [ ] The transcript format is undocumented; `measure` prints a skipped-entries line as the only alarm. Owner: VK · Revisit: 2027-01-10.
