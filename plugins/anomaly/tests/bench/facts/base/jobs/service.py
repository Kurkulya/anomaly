"""Job operations."""
from . import directory, retry, store
from .model import Job


def submit(owner_id, priority=5):
    """Create a job for a known owner."""
    owner = directory.require_owner(owner_id)
    job = Job(f'j{len(store.JOBS) + 1}', owner.id, priority)
    return store.save_record(job)


def set_priority(job_id, priority):
    """Change the priority of one job, kept between 1 and 9."""
    job = store.load_job(job_id)
    job.priority = max(1, min(priority, 9))
    return store.save_record(job)


def fail(job_id):
    """Count a failed attempt; the job goes back to the queue or is marked failed."""
    job = store.load_job(job_id)
    job.attempts += 1
    job.state = 'queued' if retry.should_retry(job) else 'failed'
    return store.save_record(job)
