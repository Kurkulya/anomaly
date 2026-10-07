# Spec: tally

## Acceptance criteria

- AC-1: `tally count FILE` prints the number of lines in FILE.
- AC-2: `tally count FILE --words` prints the number of words in FILE.
- AC-3: `tally count FILE --skip-blank` leaves blank lines out of the line count.
- AC-4: `tally count FILE --json` prints `{"lines": <n>}`.
- AC-5: `tally count -` reads the text from standard input.
- AC-6: a FILE that does not exist ends the command with one `tally: <message>` line and exit code 2.

## Not in this spec

- Counting characters.
- Several files in one call.
