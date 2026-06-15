"""The analyse surface.

Two ways in, one job out:

* ``POST /analyze``        - JSON ``{"source": "...", "threshold"?: number}``
* ``POST /analyze/file``   - multipart ``.sol`` upload (+ optional ``threshold``)

Both validate the input, enqueue a job and return ``202 {job_id, status}``.
``GET /analyze/{job_id}`` polls for the result. Keeping the upload as its own
path keeps the JSON contract clean for the front end and keeps the OpenAPI
schema honest about each content type.

In this increment the work runs as a background task calling the mock engine.
The next increment routes it through the bounded queue and the worker pool with
a wall-clock timeout; the endpoint contract here does not change.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..schema_models import AnalysisResultModel, JobError, JobSubmitResponse, JobView
from ..stub_engine import run_mock_analysis

_log = logging.getLogger("scgnn_api.analyze")

router = APIRouter(tags=["analyze"])

# Keep references to in-flight background tasks so they are not garbage-collected
# mid-run. Replaced by the managed worker pool next increment.
_tasks: set[asyncio.Task] = set()


class AnalyzeRequest(BaseModel):
    source: str = Field(min_length=1)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


def _require_non_empty(text: str) -> str:
    if not text.strip():
        raise HTTPException(status_code=422, detail="source is empty")
    return text


async def _schedule(request: Request, source: str, threshold: float | None) -> JobSubmitResponse:
    settings = request.app.state.settings
    jobs = request.app.state.jobs
    thr = settings.threshold if threshold is None else threshold

    job = jobs.create()
    task = asyncio.create_task(_run(jobs, job.id, source, thr))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return JobSubmitResponse(job_id=job.id, status="queued")


async def _run(jobs, job_id: str, source: str, threshold: float) -> None:
    jobs.set_running(job_id)
    try:
        result = await run_mock_analysis(source, threshold)
        jobs.set_done(job_id, result)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the client
        _log.exception("analysis failed for job %s", job_id)
        jobs.set_failed(job_id, code="analysis_error", message=str(exc))


@router.post("/analyze", response_model=JobSubmitResponse, status_code=202)
async def analyze_json(request: Request, body: AnalyzeRequest) -> JobSubmitResponse:
    source = _require_non_empty(body.source)
    return await _schedule(request, source, body.threshold)


@router.post("/analyze/file", response_model=JobSubmitResponse, status_code=202)
async def analyze_file(
    request: Request,
    file: UploadFile = File(...),
    threshold: float | None = Form(default=None),
) -> JobSubmitResponse:
    settings = request.app.state.settings

    name = (file.filename or "").lower()
    if not name.endswith(".sol"):
        raise HTTPException(status_code=422, detail="upload must be a .sol file")

    # Read at most one byte past the cap so an oversized upload cannot exhaust
    # memory here; reject before any extraction work.
    contents = await file.read(settings.max_upload_bytes + 1)
    if len(contents) == 0:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {settings.max_upload_bytes}-byte limit",
        )

    try:
        source = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="file is not valid UTF-8 text")

    source = _require_non_empty(source)
    if threshold is not None and not 0.0 <= threshold <= 1.0:
        raise HTTPException(status_code=422, detail="threshold must be in [0, 1]")
    return await _schedule(request, source, threshold)


@router.get("/analyze/{job_id}", response_model=JobView)
async def get_job(request: Request, job_id: str) -> JobView:
    jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")

    result = AnalysisResultModel.from_result_dict(job.result) if job.result else None
    error = JobError(**job.error) if job.error else None
    return JobView(job_id=job.id, status=job.status, result=result, error=error)
