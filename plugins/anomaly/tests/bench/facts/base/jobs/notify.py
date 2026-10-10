"""Messages sent when a job changes state."""
from . import directory, report


def build_message(job):
    """One line to send to the owner of a job."""
    owner = directory.OWNERS.get(job.owner_id)
    text = report.render_owner(owner)
    return f'{text}: job {job.id} is {job.state}'
