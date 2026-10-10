"""Messages sent when a job changes state."""
from . import report, store


def build_message(job):
    """One line to send to the owner of a job."""
    owner = store.OWNERS.get(job.owner_id)
    text = report.render_owner(owner)
    return f'{text}: job {job.id} is {job.state}'
