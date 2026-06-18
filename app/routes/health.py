"""Liveness and readiness: reports whether the model loaded, which exact commit
SHA the configured revision resolved to, the decision threshold in force, and
whether the service is running the mock or the real engine. Never discloses the
token value, only whether one is present.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schema_models import HealthView

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthView)
async def health(request: Request) -> HealthView:
    s = request.app.state.engine.state
    settings = request.app.state.settings
    return HealthView(
        status="ok",
        model_loaded=s.loaded,
        mock_mode=s.mock_mode,
        device=s.device,
        repo_id=s.repo_id,
        configured_revision=s.configured_revision,
        resolved_sha=s.resolved_sha,
        threshold=settings.threshold,
        hf_token_present=s.hf_token_present,
        error=s.error,
    )