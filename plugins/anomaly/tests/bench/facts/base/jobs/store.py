"""Where job records and owners are kept (in memory here)."""
from .model import Owner

JOBS = {}
OWNERS = {'o1': Owner('o1', 'ada'), 'o2': Owner('o2', 'grace')}
SYSTEM_OWNER = Owner('sys', 'system')


def load_job(job_id):
    """The job with this id."""
    return JOBS[job_id]


def find_owner(owner_id):
    """Look up an owner by id."""
    return OWNERS.get(owner_id)


def require_owner(owner_id):
    """Look up an owner by id; an unknown id is an error."""
    owner = OWNERS.get(owner_id)
    if owner is None:
        raise KeyError(owner_id)
    return owner


def save_record(job):
    """Write the job record."""
    JOBS[job.id] = job
    return job
