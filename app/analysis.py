"""The analysis engine: one interface, two implementations.

``MockEngine`` returns the canned ``scgnn.schema`` shape with no heavy stack
(used as the contract-only stub, e.g. on a tiny free host). ``RealEngine`` owns
the process worker pool and runs the genuine ``analyze_source`` under a
wall-clock timeout. ``build_engine`` picks one from settings (``SCGNN_MOCK``).

Both expose the same ``analyze`` coroutine and a ``ModelState`` for ``/health``.
Errors are mapped to a small, structured set the route turns into job statuses:
``ExtractionError`` (the contract could not be compiled/analysed or inference
failed - a routine, client-visible 422-class outcome) and ``AnalysisTimeout``.
"""

from __future__ import annotations

import logging

from . import model_loader
from .model_loader import ModelState
from .settings import Settings
from .worker import AnalysisTimeout, WorkerPool, WorkerPoolError

_log = logging.getLogger("scgnn_api.engine")

__all__ = ["AnalysisTimeout", "ExtractionError", "Engine", "MockEngine", "RealEngine", "build_engine"]


class ExtractionError(RuntimeError):
    """The contract could not be compiled/extracted, or inference failed."""


class Engine:
    state: ModelState

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def analyze(self, source: str, threshold: float) -> dict: ...


class MockEngine(Engine):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.state = ModelState(
            repo_id=settings.repo_id,
            configured_revision=settings.revision,
            device=settings.device,
            hf_token_present=bool(settings.hf_token),
            mock_mode=True,
        )

    async def startup(self) -> None:
        # Resolve the SHA so /health is honest about which commit a real deploy
        # would serve; failure is non-fatal (the mock does not need the bundle).
        try:
            self.state.resolved_sha = model_loader.resolve_revision(
                self._settings.repo_id, self._settings.revision, self._settings.hf_token
            )
            self.state.loaded = True
        except Exception as exc:  # noqa: BLE001
            self.state.loaded = True  # the mock is still "ready" to answer
            self.state.error = f"{type(exc).__name__}: {exc}"
            _log.warning("mock: revision resolution failed: %s", self.state.error)

    async def shutdown(self) -> None:  # nothing to tear down
        return None

    async def analyze(self, source: str, threshold: float) -> dict:
        from .stub_engine import run_mock_analysis

        return await run_mock_analysis(source, threshold)


class RealEngine(Engine):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: WorkerPool | None = None
        self.state = ModelState(
            repo_id=settings.repo_id,
            configured_revision=settings.revision,
            device=settings.device,
            hf_token_present=bool(settings.hf_token),
            mock_mode=False,
        )

    async def startup(self) -> None:
        s = self._settings
        # 1) Resolve the moving ref to an immutable SHA (light, may fail -> degraded).
        try:
            self.state.resolved_sha = model_loader.resolve_revision(s.repo_id, s.revision, s.hf_token)
        except Exception as exc:  # noqa: BLE001 - stay up, report not-ready
            self.state.error = f"revision resolution failed: {type(exc).__name__}: {exc}"
            _log.error(self.state.error)
            return
        # 2) Start the pool, loading the resolved SHA once per worker (heavy).
        try:
            import asyncio

            self._pool = WorkerPool(
                repo_id=s.repo_id,
                revision=self.state.resolved_sha,
                device=s.device,
                max_workers=s.max_workers,
            )
            await asyncio.get_running_loop().run_in_executor(None, self._pool.start)
            self.state.loaded = True
            _log.info("model loaded; serving %s@%s on %d worker(s)",
                      s.repo_id, self.state.resolved_sha, s.max_workers)
        except WorkerPoolError as exc:
            self.state.error = str(exc)
            _log.error("model load failed: %s", exc)

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.shutdown()
            self._pool = None

    async def analyze(self, source: str, threshold: float) -> dict:
        if self._pool is None:
            raise ExtractionError("model is not loaded")
        try:
            return await self._pool.run(source, threshold, timeout=self._settings.analyze_timeout_s)
        except AnalysisTimeout:
            raise
        except RuntimeError as exc:
            # The worker reported an extraction/inference failure as text.
            raise ExtractionError(str(exc)) from exc


def build_engine(settings: Settings) -> Engine:
    return MockEngine(settings) if settings.mock else RealEngine(settings)