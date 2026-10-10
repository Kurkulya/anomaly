# Job queue design notes

## Layout

- `jobs/cli.py` reads a command and calls the service.
- `jobs/service.py` holds the operations on one job.
- `jobs/store.py` keeps the records.

## Retries

A failed job goes back to the queue until it has used `MAX_ATTEMPTS` attempts (3). The check that
enforces this limit is in `jobs/service.py`, line 24.
