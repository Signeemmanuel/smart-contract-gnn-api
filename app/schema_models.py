"""Pydantic wire models for the HTTP surface.

These mirror the canonical structures in ``scgnn.schema`` (the single source of
truth shared with the front end) purely so FastAPI can document and validate the
wire format. The result payload is passed through unchanged in shape; we never
redefine the contract here.

Two deliberate choices:

* ``lines`` is preserved in the order ``scgnn`` returns it. That order is the
  localisation result (most-influential first), not a numeric sort, so nothing
  here re-sorts it.
* ``degraded`` is an *optional* top-level flag, defaulting to ``False`` and
  absent from the current ``scgnn`` output. Repo 1 will thread a ``degraded:
  true`` flag through ``analyze_source`` when a contract's CFG fell back to the
  one-node placeholder (a Slither crash). ``from_result_dict`` reads it if
  present, so the field flows through automatically the moment the updated
  ``scgnn`` tag lands, with no change here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FlawModel(BaseModel):
    type: str
    confidence: float = Field(ge=0.0, le=1.0)
    lines: list[int] = Field(default_factory=list)


class AnalysisResultModel(BaseModel):
    source: str
    flaws: list[FlawModel] = Field(default_factory=list)
    degraded: bool = False  # forward-compatible passthrough (repo-1 Option A)

    @classmethod
    def from_result_dict(cls, d: dict[str, Any]) -> "AnalysisResultModel":
        return cls(
            source=d["source"],
            flaws=[FlawModel(**f) for f in d.get("flaws", [])],
            degraded=bool(d.get("degraded", False)),
        )


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobError(BaseModel):
    code: str
    message: str


class JobView(BaseModel):
    job_id: str
    status: JobStatus
    result: AnalysisResultModel | None = None
    error: JobError | None = None


class FlawMeta(BaseModel):
    type: str
    name: str
    dasp: int


class HealthView(BaseModel):
    status: str
    model_loaded: bool
    mock_mode: bool
    device: str
    repo_id: str
    configured_revision: str
    resolved_sha: str | None = None
    hf_token_present: bool
    error: str | None = None
