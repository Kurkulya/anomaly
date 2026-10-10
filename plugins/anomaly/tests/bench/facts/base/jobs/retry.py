"""When a failed job may run again."""

MAX_ATTEMPTS = 3


def should_retry(job):
    """True while the job has attempts left."""
    return job.attempts < MAX_ATTEMPTS
