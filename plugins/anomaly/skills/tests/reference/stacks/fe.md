# Stack profile: FE (Vitest, Playwright)

Picked when `package.json` lists vitest or playwright. Use the repo's own script names.
`<pm>` is its package manager. Greps are candidates only (`grep-recipes.md`).

- **Find tests.** Unit: `git ls-files '*.test.ts' '*.test.tsx'`. E2e: read `testDir` and
  `testMatch` in `playwright.config.*` first; without `testDir` it is the config's folder.
- **Run one file.** `<pm> exec vitest run <file>`; e2e: `<pm> exec playwright test <file>`
  (`npx` with npm).
- **Time one file.** The Duration line of `vitest run <file>`; all files:
  `--reporter=json --outputFile=<evidence>/vitest.json`. A per-file `duration` may hold
  test bodies only: check on the target's version. E2e:
  `PLAYWRIGHT_JSON_OUTPUT_NAME=<evidence>/pw.json <pm> exec playwright test --reporter=json`.
- **Empty assertion.** Presence checks only; a check of what the user sees
  (`toBeVisible()`) is real.
- **E2e test.** A `test(` in the e2e folder; the reason tag (`@reason-<slug>`) may sit on
  the next line, so read the test before you call it untagged.
- **Break code.** In the copy, edit the code under test by hand: flip a comparison,
  return an early value, drop a branch. Run the cover with `<pm> exec vitest run
  <cover file>` (`npx vitest run` with npm), or the repo's script.
- **Install freshness.** `node_modules/vitest/package.json` against the lockfile entry.
- **Scope example** (an example only): components + maps · pages + forms · other `src/`
  logic + API + Playwright · runtime.

## Recipes

```bash
git ls-files '*.test.ts' '*.test.tsx' '*.test.js' | cut -d/ -f1-2 | sort | uniq -c | sort -rn
git grep -cE "^[[:space:]]*(it|test)(\.(each|only|skip|todo|fails|concurrent))?[ (\`]" -- '*.test.ts' '*.test.tsx' | awk -F: '{s+=$2} END {print s}'

# EMPTY-ASSERTION
git grep -nE "toBeDefined\(\)|toBeInstanceOf\(Function\)|not\.toBeUndefined\(\)" -- '*.test.ts*' | head -50
git grep -L "expect" -- '*.test.ts' '*.test.tsx' | head    # assertions may hide in a helper

# INTERNALS (Mui...- is one UI kit's class prefix: use the repo's kit)
git ls-files '*.snap'
git grep -nE "toMatch(Inline)?Snapshot|asFragment\(\)|container\.innerHTML|toHaveClass\(|toHaveStyle\(|getComputedStyle|Mui[A-Z][A-Za-z]+-" -- '*.test.ts*' | head -50
git grep -cF "vi.mock(" -- '*.test.ts*' | sort -t: -k2 -rn | head -20    # a relative path to the API module is the boundary

# DUPLICATE: take a route, i18n key or function name from one test, look in the other layers
git grep -n '<route | i18n key | function>' -- '*.test.ts*' '<e2e dir>/*.spec.ts' | head

# Playwright
git grep -nE "^[[:space:]]*test(\.(only|fixme|skip|fail))?\(" -- '<e2e dir>/*.spec.ts' | head -80
git grep -nE "@reason-[a-z-]+" -- '<e2e dir>' | head -80    # compare slugs with the repo's list
npx playwright test --list | tail -3    # runtime count, runs no test; with npm, else <pm> exec
git grep -nE "toHaveScreenshot|toMatchSnapshot|snapshotPathTemplate" -- '<e2e dir>' 'playwright.config.*' | head
```

A screenshot test whose baselines exist for one OS only compares nothing on the CI OS:
check `ls` of the snapshot folder against the CI image.
