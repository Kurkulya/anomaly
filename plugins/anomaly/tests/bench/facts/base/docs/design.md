# Job queue design notes

## Layout

- `jobs/cli.py` reads a command and calls the service.
- `jobs/service.py` holds the operations on one job.
- `jobs/store.py` keeps the records.

## Retries

A failed job goes back to the queue until it has used its third attempt; after that it is marked
failed. The check that makes this decision is in `jobs/service.py`, line 8.
