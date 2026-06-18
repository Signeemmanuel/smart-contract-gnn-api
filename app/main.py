"""FastAPI application factory and start-up wiring.

``lifespan`` builds the analysis engine (mock or real, per ``SCGNN_MOCK``),
starts it (resolving the revision and, for the real engine, loading the model
into the worker pool), and holds the engine, settings and job store on
``app.state``. The engine is shut down cleanly on exit. CORS is added only when
origins are configured.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .analysis import build_engine
from .jobs import JobStore
from .routes import analyze, flaws, health
from .settings import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.jobs = JobStore()
    app.state.inflight = 0  # queued+running jobs, bounded by settings.queue_max

    engine = build_engine(settings)
    await engine.startup()
    app.state.engine = engine
    try:
        yield
    finally:
        await engine.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="scgnn-api",
        version="0.2.0",
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


app = create_app(title="smart-contract-gnn-api")