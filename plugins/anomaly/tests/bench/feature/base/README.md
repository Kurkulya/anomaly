# tally

A small command that counts the lines or the words of a text file.

## Use

```
tally count FILE
tally count FILE --by-word
```

`tally count FILE` prints the number of lines in FILE as a bare number.
`--by-word` counts words instead of lines and prints the number the same way.

## Checks

Run `python -m unittest discover -s checks -p "check_*.py"` from the repo root.
