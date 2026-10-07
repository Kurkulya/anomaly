# receipt

Adds up the prices in a receipt file and prints the total.

## Use

```
receipt total FILE
```

Each line of FILE is `<item>,<price in cents>`; blank lines are skipped. The command prints
`total: <cents>`.

## Checks

Run `python -m unittest discover -s checks -p "check_*.py"` from the repo root.
