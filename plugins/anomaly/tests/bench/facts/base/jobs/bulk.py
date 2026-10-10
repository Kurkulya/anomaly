"""Changes that touch many jobs at once."""
from . import store


def reorder_all(priority):
    """Give every queued job the same priority."""
    for job in list(store.JOBS.values()):
        job.priority = priority
        store.save_record(job)


def cancel_all(owner_id):
    """Cancel every queued job of one owner."""
    for job in list(store.JOBS.values()):
        if job.owner_id == owner_id and job.state == 'queued':
            job.state = 'cancelled'
            store.save_record(job)
