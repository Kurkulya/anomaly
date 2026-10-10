# Area outline: the questions and the count lists

The 7 areas of a run. The greps for areas 1–6 are in the stack profile
(`stacks/<stack>.md`), one block per area. The area shape and the area score rubric are in
`SKILL.md`. Names in `<angle brackets>` and lines marked `# example` came from one repo:
replace them with this repo's names before you run them.

Base facts, once (the stack profile adds files per layer, scripts and the CI file):

```bash
git ls-files | wc -l
git log --oneline | wc -l ; git log -1 --format=%ad --date=short
```

## Area 1 — Layers and dependency direction (principle 1)

**Questions.** What is the layer order, written down? Which imports point up? Do
type-only imports point up? Is the order enforced by lint, and at which level?

**Count and report:** violations by source layer, type-only included.

## Area 2 — Module depth (principle 2)

**Questions.** For each boundary (API seam, store, platform adapter): what does it hide, and what
leaks? How many callers walk the internals?

**Count and report:** raw-shape readers and their spellings, loose keys and their roots,
transport-instance names, wire-quirk copies.

## Area 3 — State ownership (principle 3)

**Questions.** For each state field: which kind is it (server fact, edit session, session
fact, view state, handoff)? Who writes it, how many writers? Who resets it? Is any field
never written, or never read?

**Count and report:** facts with two owners, writers per fact, dead fields, stores with
zero reset callers.

## Area 4 — Side effects and platform adapters (principles 4 and 5)

**Questions.** Which utilities and stores act (message, dialog, navigate) instead of
returning a decision? How many raw platform-API call sites exist, by layer, and how many
are guarded?

The guarded-call grep only hints. Confirm by reading each raw call site; over about 15
sites, delegate the read to `anomaly:facts` (`explore` role: model, effort if set) with the list.

**Count and report:** acting sites by layer, raw storage/network sites by layer,
guarded vs unguarded.

## Area 5 — Cohesion in the biggest feature (principle 6)

**Questions.** Which feature is biggest (files, lines, state holders)? Run the change-locality
test: for one realistic change, how many files open? How many parts does its top unit
wire? How many jobs does the biggest component have?

**Count and report:** parts per top unit, lines and jobs of the biggest component, store
imports from presentational code, the diff or logic a top unit holds that its store should.

## Area 6 — Guards on the five-rung ladder

**Questions.** For each rule the repo says it has: which rung (blocks CI / pre-commit /
warns / documented / tribal)? Does lint block CI **from inside this repo**, or only via a
shared template? Where do production errors go? Is any flag "temporarily" off?

**Count and report:** a table of guards with rung and the one step that moves each up.

## Area 7 — Decision records

**Questions.** Where do the whys live: ADRs, CLAUDE.md prose, commit bodies, comments,
nobody? How many ADRs vs how many "why" paragraphs? Then run the five docs checks.

**Base counts.**

```bash
git ls-files 'docs/adr/*' | wc -l
grep -cE "because|measured|instead of|trade-off|deliberate|rejected" CLAUDE.md   # whys in the shape file
git log --format=%h -- CLAUDE.md | wc -l                                         # how often it is rewritten
```

**The five docs checks.**

1. **Revisit dates passed.** Each dated revisit before today is overdue.
   ```bash
   git grep -noE "[Rr]evisit[^0-9]{0,12}[0-9]{4}-[0-9]{2}-[0-9]{2}" -- docs/adr CLAUDE.md <source dir>
   ```
2. **Deferrals with no owner or date.**
   ```bash
   git grep -nE "TODO|FIXME|HACK|follow-up" -- <source files> | grep -v /tests/ | grep -vE "TODO\([^)]*revisit 20[0-9]{2}-[0-9]{2}-[0-9]{2}\)" | wc -l
   ```
3. **Dead paths in CLAUDE.md.** List the paths it names, then run `git ls-files <path>`
   on each; an empty result is a dead path.
   ```bash
   grep -oE '`[A-Za-z0-9_.-]+/[A-Za-z0-9_./*-]+`' CLAUDE.md | tr -d '`' | sort -u
   ```
4. **Decisions in commits with no ADR.** For each hit, grep `docs/adr/` for its hash or
   subject; no match means the why lives only in the commit.
   ```bash
   git log --no-merges --format="%h %ad %s" --date=short -i --grep="instead of" --grep="rejected" --grep="deliberate" --grep="measured" | head -15
   ```
5. **ADR claims the code drifted from.** For each ADR, take the checkable claims in its
   Decision (a file exists, a value, a count, an import is absent) and re-run the check.
   With more than about 5 ADRs, delegate to `anomaly:facts` (`explore` role: model, effort if set) with the ADR paths and
   a ≤900-word cap. It has no git: pass it the `git ls-files` path list, and re-count with git
   every number it returns.

**Count and report:** ADR count, "why" paragraphs in CLAUDE.md, rewrite count, overdue
revisit dates, unkeyed deferrals with age, dead paths, commit decisions with no ADR,
drifted ADR claims.
