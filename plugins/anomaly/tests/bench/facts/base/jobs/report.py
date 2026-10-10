"""Text for job summaries."""
from . import directory


def render_owner(owner):
    """The owner's name in capitals."""
    return owner.name.upper()


def owner_table(jobs):
    """Map each job id to the name of its owner."""
    return {job.id: render_owner(directory.require_owner(job.owner_id)) for job in jobs}


def count_by_state(jobs):
    """How many jobs are in each state."""
    counts = {}
    for job in jobs:
        counts[job.state] = counts.get(job.state, 0) + 1
    return counts


def daily_summary(jobs):
    """One line for each job: its id and who owns it."""
    lines = []
    for job in jobs:
        owner = directory.find_owner(job.owner_id)
        lines.append(f'{job.id} {render_owner(owner)}')
    return lines
