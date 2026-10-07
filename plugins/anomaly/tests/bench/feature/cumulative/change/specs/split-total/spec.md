# Spec: split the total

Move the reading of receipt lines out of `receipt/total.py` into a new `receipt/parse.py`, so a
later spec can read other formats. No behaviour change.

## Acceptance criteria

- AC-1: `receipt total FILE` prints the same bytes as before the split.
- AC-2: `receipt/parse.py` turns the text into `(item, cents)` rows; `receipt/total.py` only adds them up.
- AC-3: The split keeps the printed total and the total of a receipt; characterization checks pin both. When the split ends, each one is kept, rewritten or deleted.

## Not in this spec

- Other receipt formats.
