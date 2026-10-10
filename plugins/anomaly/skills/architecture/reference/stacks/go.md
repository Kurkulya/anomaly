# Stack profile: Go

Picked when the repo has `go.mod`. No Go repo was at hand: the greps below are unverified
(only their git syntax was run). Replace `<module>` (the module path), `<domain>` (paths).

- **Layers.** `domain/models → repository → service → transport (grpc, http)`, then `cmd`.
- **Imports.** One spelling: the full module path (`<module>/internal/x`, in double quotes in the
  source). Modules do not allow relative imports, so there is no second grep; say so in the count.
- **State.** Package-level `var` maps and slices; cached fields on a struct that a DB row
  also owns.
- **Side effects.** `log.Fatal`, `os.Exit`, `panic` below `cmd`: return an error or a value.
- **Platform adapters.** Seams for the clock, the DB, gRPC `metadata` and `os.Getenv` (config).

```bash
git ls-files '*.go' | xargs -n1 dirname | sort | uniq -c | sort -rn      # base: files per package
git ls-files go.mod Makefile '.golangci*' '.github/workflows/*'
# 1 domain importing transport or a higher layer
git grep -nE '"(google.golang.org/grpc|net/http|<module>/(service|transport)|[^"]*/metadata)' -- <domain>
# 2 generated wire types past the transport package
git grep -nE '\bpb\.[A-Z]' -- '*.go' ':(exclude)*_test.go' | grep -v '/transport/'
# 3 package-level mutable state
git grep -nE '^var\s+\w+\s*=\s*(map\[|\[\])' -- '*.go' ':(exclude)*_test.go'
# 4 raw clock and env; acting below cmd
git grep -nE 'time\.Now\(\)|os\.Getenv\(' -- '*.go' ':(exclude)*_test.go' | grep -vE '/(clock|config)/'
git grep -nE 'log\.Fatal|os\.Exit\(|panic\(' -- '*.go' ':(exclude)*_test.go' ':(exclude,glob)**/cmd/**'
# 5 biggest files
git ls-files '*.go' ':(exclude)*_test.go' | xargs wc -l | sort -rn | sed -n 2,11p
# 6 lint level
git grep -nE 'depguard|staticcheck|golangci-lint' -- .golangci* Makefile '.github/workflows/*'
```
