"""Where job records are kept (in memory here)."""

JOBS = {}


def load_job(job_id):
    """The job with this id."""
    return JOBS[job_id]


def list_jobs():
    """Every job, in the order they were added."""
    return list(JOBS.values())


def save_record(job):
    """Write the job record."""
    JOBS[job.id] = job
    return job
