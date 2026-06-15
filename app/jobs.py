"""In-process job store for the asynchronous analyse pattern.

A deliberately small store: jobs live in a dict in this process. This is the
right simplicity for a single-host demonstration. The stated trade-off is that
jobs are lost on restart and the store does not span replicas; if durability or
horizontal scale is ever needed, this module is the seam to swap for Redis/RQ
without touching the endpoints.

The bounded queue and the worker pool that *executes* jobs arrive in the next
increment; this store only tracks job lifecycle and results.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _touch(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.updated_at = time.time()
        return job

    def set_running(self, job_id: str) -> None:
        job = self._touch(job_id)
        if job is not None:
            job.status = "running"

    def set_done(self, job_id: str, result: dict[str, Any]) -> None:
        job = self._touch(job_id)
        if job is not None:
            job.status = "done"
            job.result = result

    def set_failed(self, job_id: str, code: str, message: str) -> None:
        job = self._touch(job_id)
        if job is not None:
            job.status = "failed"
            job.error = {"code": code, "message": message}
