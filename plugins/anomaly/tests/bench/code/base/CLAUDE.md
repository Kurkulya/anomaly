# shelf

A small catalogue library. Standard library only.

## Rules

- Money is a whole number of cents, held in an `int`. A price is never held in a `float`.
- Every new public function gets a check in `checks/` in the same change.

## Checks

Run `python -m unittest discover -s checks -p "check_*.py"` from the repo root.
