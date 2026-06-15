"""FastAPI application factory and start-up wiring.

``lifespan`` resolves the configured revision once at start-up (see
``model_loader``) and holds the resulting state, the settings and the job store
on ``app.state``. CORS is added only when origins are configured, so the service
does not silently allow all origins.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import model_loader
from .jobs import JobStore
from .routes import analyze, flaws, health
from .settings import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.model_state = model_loader.load(settings)
    app.state.jobs = JobStore()
    yield
    # No teardown in the stub; the worker pool added next increment closes here.


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="scgnn-api",
        version="0.1.0",
        summary="HTTP service wrapping the SC-GNN smart-contract flaw detector.",
        lifespan=lifespan,
    )

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(flaws.router)
    app.include_router(analyze.router)
    return app


app = create_app()
