"""Filesystem-backed job store.

Each job lives in `settings.jobs_dir / <job_id>/` with a `status.json`
that captures its state, plus the input + intermediate files
alongside. This module owns the lifecycle and serialisation; the
HTTP layer in `app.main` consumes Job objects, never the disk
directly.

For v0.1 the implementation is intentionally a flat directory + JSON
file: no database, no queue, no locks. FastAPI's BackgroundTasks
dispatcher fires processing in the same uvicorn worker so there's no
cross-process coordination to do. When we add LAZ support (v0.2)
and the processing window stretches into multiple minutes we'll
graduate to a proper queue (RQ or arq); the Job interface here is
shaped so that swap stays local.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from app.config import settings


class JobStatus(str, Enum):
    """Lifecycle states a job moves through. Order matters: each
    state transitions to the next one until DONE, or jumps to
    FAILED on any error.
    """

    QUEUED = "queued"
    VALIDATING = "validating"
    PROCESSING = "processing"
    COGGING = "cogging"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """One end-to-end conversion request. Persisted as
    `<jobs_dir>/<job_id>/status.json`.
    """

    job_id: str
    status: JobStatus
    created_at: float
    updated_at: float
    progress_message: str = ""
    #0..100 mapped to the current pipeline phase. Drives the
    #processing progress bar on the frontend. Stays at 100 once the
    #job is done and at the last phase % if the job fails so the
    #bar doesn't visually snap back.
    progress_pct: float = 0.0
    error: str | None = None
    cog_url: str | None = None
    download_filename: str | None = None
    yaml_snippet: str | None = None
    bounds_wgs84: tuple[float, float, float, float] | None = None
    pixel_size_meters: float | None = None
    epsg: int | None = None
    #Unix epoch seconds at which the COG will be deleted from the
    #VPS. The frontend renders a countdown so users know how long
    #they have to grab a fresh copy. None until the COG is published.
    cog_expires_at: float | None = None
    #Either "raster_pair" (DSM + DTM workflow) or "point_cloud"
    #(LAS / LAZ single-file workflow). Set by the POST /jobs handler
    #from which fields the upload includes.
    input_mode: str = ""

    def dir(self) -> Path:
        return settings.jobs_dir / self.job_id

    def to_dict(self) -> dict:
        """JSON-friendly serialisation, status as the string value
        so consumers don't need to know the enum.
        """
        data = asdict(self)
        data["status"] = self.status.value
        if self.bounds_wgs84 is not None:
            data["bounds_wgs84"] = list(self.bounds_wgs84)
        return data

    def save(self) -> None:
        self.updated_at = time.time()
        d = self.dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "status.json.tmp"
        tmp.write_text(json.dumps(self.to_dict()))
        tmp.replace(d / "status.json")

    @classmethod
    def load(cls, job_id: str) -> Job | None:
        path = settings.jobs_dir / job_id / "status.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        data["status"] = JobStatus(data["status"])
        if data.get("bounds_wgs84") is not None:
            data["bounds_wgs84"] = tuple(data["bounds_wgs84"])
        return cls(**data)


def new() -> Job:
    """Allocate a fresh job and persist its initial state."""
    job_id = secrets.token_hex(8)
    now = time.time()
    job = Job(
        job_id=job_id,
        status=JobStatus.QUEUED,
        created_at=now,
        updated_at=now,
        progress_message="Queued",
    )
    job.save()
    return job
