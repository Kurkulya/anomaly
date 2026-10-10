"""Commands for operators that do not change a priority."""
from . import bulk, report, store


def cancel_command(args):
    """`cancel <owner id>`: cancel every queued job of one owner."""
    return bulk.cancel_all(args[0])


def show_command(args):
    """`show <job id>`: print who owns a job."""
    job = store.load_job(args[0])
    owner = store.find_owner(job.owner_id) or store.SYSTEM_OWNER
    return report.render_owner(owner)
