"""Plain records for the job queue."""
from dataclasses import dataclass


@dataclass
class Owner:
    id: str
    name: str


@dataclass
class Job:
    id: str
    owner_id: str
    priority: int = 5
    attempts: int = 0
    state: str = 'queued'
