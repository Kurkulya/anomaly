# Spec: export

The export spec turns the counts of several runs into a file.

## Acceptance criteria

- AC-1: `tally export FILE...` writes one row of counts for each file.
- AC-2: the totals of a run are printed as CSV rows, one per file, in the order the files were given.
- AC-3: `tally export` refuses to overwrite an existing output file unless `--replace` is given.

## Not in this spec

- Any output format other than CSV.
