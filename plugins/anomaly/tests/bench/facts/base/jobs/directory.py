"""Who owns the jobs."""
from .model import Owner

OWNERS = {'o1': Owner('o1', 'ada'), 'o2': Owner('o2', 'grace')}
SYSTEM_OWNER = Owner('sys', 'system')


def find_owner(owner_id):
    """Look up an owner by id."""
    return OWNERS.get(owner_id)


def require_owner(owner_id):
    """Look up an owner by id; an unknown id is an error."""
    owner = OWNERS.get(owner_id)
    if owner is None:
        raise KeyError(owner_id)
    return owner
