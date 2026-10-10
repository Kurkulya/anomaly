# Stack profile: React/TS

Picked when `package.json` lists `react`. The greps come from one real run and were not
re-run for this stack profile. Names in `<angle brackets>` and `# example` lines came from one
repo: replace them with this repo's names before you run them.

- **Layers.** `types/constants/config → api → utils → stores/hooks → components → pages →
  root`.
- **Imports.** Alias `@/pages/...`; relative `../../pages/...`. Run both, then union.
  `import type` counts.
- **Leaks.** Many files read the raw error envelope (`error.response.data.error.details[0]`);
  cache keys are loose strings; requests name a transport instance, not a host; one wire
  quirk (wrapped resource, omitted empty list, page cursor) is copied in many places.
- **State.** Server fact: the query cache only. Edit session: one store with
  `hydrate(serverValue)` and `reset()`; a route-scoped layout resets it on unmount and on id
  change. Session fact (tenant, language): one store. One subtree's view state: a context.
  Ephemeral UI: `useState`. A route handoff: ids in navigation state, not a store field.
- **Side effects.** A util or store returns a decision (`{ kind: "confirm", message }`, a
  dropped count, a diff); a hook near the UI performs it.
- **Platform adapters.** `localStorage`, cookies, `fetch`, `window.location`, the clock: one platform adapter
  each, guarded, with a default.
- **Cohesion.** A page composes one feature hook; a store keeps its reconciliation and returns
  a diff; a big component becomes a state-machine hook, a pure derivation and small parts.

```bash
git ls-files | wc -l
git ls-files 'src/**' | sed -E 's#^src/([^/]+)/.*#\1#' | sort | uniq -c | sort -rn   # base: layers by file count
grep -A40 '"scripts"' package.json ; ls .github/workflows
# 1 lower layer importing a higher one: alias, then relative
git grep -nE "from ['\"]@/(pages|components|hooks|stores)" -- src/utils src/api src/types src/constants
git grep -nE "from ['\"](\.\./)+(pages|components|hooks|stores)/" -- src/utils src/api src/types src/constants
git grep -nE "from ['\"](@/|(\.\./)+)components/(modals|ui)" -- src/hooks                 # hooks importing UI
git grep -nE "from ['\"](@/|(\.\./)+)pages/" -- src/pages | grep -vE "src/pages/([^/]+)/.*pages/\1/"   # page to page
grep -nE "no-restricted-imports|import/no-restricted-paths|boundaries|zones" eslint.config.* vite.config.* .oxlintrc* 2>/dev/null
# 2 raw error envelope readers, spellings, loose keys
git grep -nE "response\??\.data\??\.(error|errors|message|details)" -- src | grep -v "/tests\?/" | wc -l
git grep -noE "response\??\.data\??\.[a-zA-Z?.\[\]0-9]+" -- src | sed 's/.*://' | sort | uniq -c | sort -rn
git grep -nE "queryKey:\s*\[\s*['\"]" -- src | wc -l
git grep -noE "queryKey:\s*\[\s*['\"][^'\"]+" -- src | sed -E "s/.*['\"]//" | sort -u   # roots; singular/plural pairs
git grep -nE '<requestFn>\([^)]*,\s*<instancesObject>\.[a-zA-Z]+' -- src/api | wc -l   # example: instance, not host
git grep -nE '\.(<resource>|<resource>)\s*\?\?|\?\?\s*\[\]|nextPageToken|next_page_token' -- src/api | wc -l   # example: dialect copies
# 3 stores: fields, writes per field, reset callers, a server fact held twice
ls src/stores ; git grep -nE "^\s+[a-zA-Z]+\??:" -- 'src/stores/*.ts' | wc -l
for f in $(git grep -hoE "set\(\{\s*[a-zA-Z]+" -- src/stores | sed -E 's/.*\{\s*//' | sort -u); do echo "$f $(git grep -n "$f" -- 'src/*.ts' 'src/*.tsx' | grep -v /tests/ | wc -l)"; done
git grep -n "reset()" -- 'src/*.tsx' 'src/*.ts' | grep -v "/stores/" | grep -v /tests/
git grep -nE "useQuery|queryFn" -- src/api src/hooks | grep -iE '<fact>' ; git grep -nE '<fact>' -- src/stores
# 4 acting below the UI; raw browser APIs by layer; unguarded parses; try within 5 lines (a hint)
git grep -nE "toast|enqueueSnackbar|openModal|Modals\.|navigate\(" -- src/utils src/stores src/api | grep -v /tests/
for d in src/*/; do echo "$d $(git grep -nE "localStorage\.|sessionStorage\.|Cookies\.(get|set|remove)|\bfetch\(" -- $d | grep -v /tests/ | wc -l)"; done
git grep -nE "JSON\.parse\(localStorage" -- src | grep -v /tests/
git grep -nE -B5 "(local|session)Storage\.(getItem|setItem|removeItem)" -- src | grep -v /tests/ | grep -cE "try\s*\{"
# 5 biggest feature, biggest components, hooks wired, presentational code reaching a store
git ls-files 'src/pages/**' | sed -E 's#^(src/pages/[^/]+)/.*#\1#' | sort | uniq -c | sort -rn | head -5
git ls-files 'src/**/*.tsx' | xargs wc -l | sort -rn | sed -n 2,11p
grep -cE "^\s*(const|let) .* = use[A-Z]" src/pages/<Biggest>/index.tsx
grep -nE "useEffect|useState|useCallback" src/pages/<Biggest>/<BiggestComponent>.tsx | wc -l
git grep -nE "from ['\"](@/|(\.\./)+)stores" -- src/<presentational dirs> src/components/ui
# 6 what CI runs; error sinks; flag age (example); lint level
grep -nE "lint|test|check" .github/workflows/*.yml package.json | head -30
git grep -nE "ENFORCE|STRICT|WARN_ONLY|console\.(error|warn)\(" -- src/<config dirs> | head
git log -1 --format="%ad %h" --date=short -S'<FLAG_NAME> = false' -- src/<config dir>
git grep -nE "console\.(error|warn)" -- 'src/*.tsx' 'src/*.ts' | grep -v /tests/ | wc -l
git grep -nE "Sentry|reporter|report\(" -- src | grep -v /tests/ | wc -l
grep -nE "warn|error" eslint.config.* vite.config.* 2>/dev/null | grep -iE "restricted|boundaries"
```
