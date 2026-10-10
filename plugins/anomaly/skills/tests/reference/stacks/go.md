# Stack profile: Go (go test)

Picked when the repo has `go.mod` and `*_test.go` files. Go was not installed here, so
every command below is from memory of the standard `go test` tool: unverified. Check
`go help test` and `go help testflag` before the first run.

- **Find tests.** `*_test.go` files next to the code they test. `go test -list '.*' ./...`
  lists test names without running them (unverified).
- **Run one file.** `go test` runs a package, not a file. Run the package, or filter by
  name: `go test -run '^TestName$' ./path/to/pkg` (unverified). To keep to one file, read
  the test names in it and join them in the `-run` regex.
- **Time one file.** `go test -v ./path/to/pkg` prints `--- PASS: TestName (0.00s)` per
  test and `ok <pkg> <seconds>` per package (unverified). `-count=1` skips the test cache,
  which would give a fake time. `-json` gives machine-readable output.
- **Empty assertion.** A test function with no `t.Error`, `t.Errorf`, `t.Fatal`,
  `t.Fatalf`, `t.Fail`, and no assert call (`assert.`, `require.`, if the repo uses testify).
- **E2e test.** A build tag at the top of the file (`//go:build integration` or `e2e`),
  or a skip under `testing.Short()`. Read `go test` flags in CI to see which run.
- **Break code.** In the copy, edit the code under test by hand. Run the cover with
  `go test -count=1 -run '^TestName$' ./path/to/pkg`.
- **Install freshness.** `go.mod` against `go.sum` and the vendor folder, if any. Do not
  run `go mod download` in the repo.

## Recipes

```bash
git ls-files '*_test.go' | xargs -n1 dirname | sort | uniq -c | sort -rn
git grep -cE "^func Test[A-Z_]" -- '*_test.go' | awk -F: '{s+=$2} END {print s}'

# EMPTY-ASSERTION: test files with no failure call
git grep -L -E "t\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\(|assert\.|require\." -- '*_test.go' | head

# E2E: build-tagged and short-skipped tests
git grep -nE "^//go:build|testing\.Short\(\)" -- '*_test.go' | head -50
```
