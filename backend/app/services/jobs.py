from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanJob:
    job_id: str
    status: str = "pending"  # pending|running|done|error
    library_id: int | None = None
    scanned: int = 0
    created: int = 0
    scraped: int = 0
    errors: list[str] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "library_id": self.library_id,
            "scanned": self.scanned,
            "created": self.created,
            "scraped": self.scraped,
            "errors": self.errors[-50:],
            "message": self.message,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ScanJob] = {}
        self._lock = threading.Lock()

    def create(self, library_id: int | None = None) -> ScanJob:
        job = ScanJob(job_id=uuid.uuid4().hex[:12], library_id=library_id, status="pending")
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            return self._jobs.get(job_id)


job_store = JobStore()
