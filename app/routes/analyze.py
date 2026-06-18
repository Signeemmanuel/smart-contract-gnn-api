"""The analyse surface.

Two ways in, one job out:

* ``POST /analyze``        - JSON ``{"source": "..."}``
* ``POST /analyze/file``   - multipart ``.sol`` upload

Both validate the input, enqueue a job and return ``202 {job_id, status}``.
``GET /analyze/{job_id}`` polls for the result. The threshold is a fixed server
policy (see /health), not a client field.

Work runs off the event loop through the analysis engine (the process worker
pool in the real engine), under a wall-clock timeout. A bounded number of jobs
may be in the system at once (``SCGNN_QUEUE_MAX``); beyond that the service sheds
load with ``503`` rather than exhausting memory. Engine failures are mapped to
structured job outcomes: extraction/inference failure -> ``failed`` with
``extraction_failed``; timeout -> ``failed`` with ``timeout``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..analysis import AnalysisTimeout, ExtractionError
from ..schema_models import AnalysisResultModel, JobError, JobSubmitResponse, JobView

_log = logging.getLogger("scgnn_api.analyze")

router = APIRouter(tags=["analyze"])

# Keep references to in-flight background tasks so they are not garbage-collected.
_tasks: set[asyncio.Task] = set()


class AnalyzeRequest(BaseModel):
    # The decision threshold is intentionally NOT a client field: it is a fixed
    # server policy (SCGNN_THRESHOLD, the reported 0.5) so every caller gets the
    # evaluated model's verdict. The value in force is reported on /health.
    source: str = Field(min_length=1)


def _require_non_empty(text: str) -> str:
    if not text.strip():
        raise HTTPException(status_code=422, detail="source is empty")
    return text


async def _schedule(request: Request, source: str) -> JobSubmitResponse:
    state = request.app.state
    settings = state.settings

    # Bounded queue: shed load instead of exhausting the host.
    if state.inflight >= settings.queue_max:
        raise HTTPException(status_code=503, detail="server busy; retry shortly")

    job = state.jobs.create()
    state.inflight += 1
    task = asyncio.create_task(_run(state, job.id, source, settings.threshold))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return JobSubmitResponse(job_id=job.id, status="queued")


async def _run(state, job_id: str, source: str, threshold: float) -> None:
    jobs = state.jobs
    jobs.set_running(job_id)
    try:
        result = await state.engine.analyze(source, threshold)
        jobs.set_done(job_id, result)
    except AnalysisTimeout as exc:
        jobs.set_failed(job_id, code="timeout", message=str(exc))
    except ExtractionError as exc:
        jobs.set_failed(job_id, code="extraction_failed", message=str(exc))
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the client
        _log.exception("analysis failed for job %s", job_id)
        jobs.set_failed(job_id, code="analysis_error", message=str(exc))
    finally:
        state.inflight -= 1


@router.post("/analyze", response_model=JobSubmitResponse, status_code=202)
async def analyze_json(request: Request, body: AnalyzeRequest) -> JobSubmitResponse:
    source = _require_non_empty(body.source)
    return await _schedule(request, source)


@router.post("/analyze/file", response_model=JobSubmitResponse, status_code=202)
async def analyze_file(
    request: Request,
    file: UploadFile = File(...),
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
    return await _schedule(request, source)


@router.get("/analyze/{job_id}", response_model=JobView)
async def get_job(request: Request, job_id: str) -> JobView:
    jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")

    result = AnalysisResultModel.from_result_dict(job.result) if job.result else None
    error = JobError(**job.error) if job.error else None
    return JobView(job_id=job.id, status=job.status, result=result, error=error)